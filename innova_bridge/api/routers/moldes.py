"""
innova_bridge/api/routers/moldes.py — Endpoints de moldes de gabarito (máscaras OMR).

Reutiliza o motor OpenCV encapsulado em `backend_molde` (root do projeto) para:
  - listar moldes salvos (Postgres com fallback disco)
  - carregar um molde pelo nome
  - detectar candidatos a marcação (bolhas/caixas) em um PDF enviado pelo cliente

Endpoints existentes:
  GET  /api/v1/moldes                Lista todos os nomes de moldes disponíveis.
  GET  /api/v1/moldes/{nome}         Retorna o dict completo de um molde.
  POST /api/v1/moldes/detectar       Recebe PDF, roda detecção OpenCV, retorna candidatos + imagens base64.
  POST /api/v1/moldes/ocr-regiao     Extrai texto de uma região de um PDF digital via PyMuPDF.

Endpoints novos (Sessões Dinâmicas — exam_templates):
  POST /api/v1/moldes/templates              Salva novo template no formato 3.0-Sessões.
  GET  /api/v1/moldes/templates              Lista templates (sem definition).
  GET  /api/v1/moldes/templates/{tid}        Retorna template completo por id.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

# Importação defensiva do OpenCV — pode não estar instalado no ambiente mínimo
try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

# Importação defensiva do PyMuPDF — usado para OCR de PDFs digitais
try:
    import fitz  # PyMuPDF
    _FITZ_OK = True
    _FITZ_ERRO = ""
except Exception as e:
    _FITZ_OK = False
    _FITZ_ERRO = str(e)

import backend_molde as bm
from innova_bridge.api.deps import usuario_autenticado
from innova_bridge.db import get_pool

router = APIRouter(prefix="/moldes", tags=["moldes"])

# ───────────────────────────────────────────────
# Modelos Pydantic — originais
# ───────────────────────────────────────────────


class ListaMoldesResponse(BaseModel):
    moldes: List[str]


class PaginaImagem(BaseModel):
    numero: int
    largura_px: int
    altura_px: int
    imagem_base64: str  # "data:image/png;base64,..."


class CandidatoMolde(BaseModel):
    pag: int
    x: int
    y: int
    w: int
    h: int
    score: float
    stddev: float


class DetectarResponse(BaseModel):
    qtd_paginas: int
    qtd_candidatos: int
    candidatos: List[Dict[str, Any]]
    paginas: List[PaginaImagem]


# ───────────────────────────────────────────────
# Modelos Pydantic — templates Sessões Dinâmicas
# ──────────────────────────────────────────────

_KINDS_VALIDOS = ("agente1_intake", "exam_correction")


class TemplateIn(BaseModel):
    name: str
    kind: str = "agente1_intake"
    definition: Dict[str, Any]
    template_layout: Optional[str] = None
    dpi_referencia: int = 200
    school_id: Optional[str] = None


# ───────────────────────────────────────────────
# Helpers internos
# ───────────────────────────────────────────────

def _parse_uuid_or_none(valor: Optional[str]) -> Optional[str]:
    """Retorna a string se for UUID válido, senão None."""
    if not valor:
        return None
    try:
        uuid.UUID(str(valor))
        return str(valor)
    except (ValueError, AttributeError):
        return None


# ───────────────────────────────────────────────
# Endpoints — templates Sessões Dinâmicas
# (declarados ANTES de /{nome} para evitar captura pelo catch-all)
# ───────────────────────────────────────────────


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def criar_template(
    body: TemplateIn,
    _user: Dict = Depends(usuario_autenticado),
):
    """
    Salva um novo template no formato 3.0-Sessões na tabela exam_templates.

    Retorna o id gerado e a quantidade de sessões detectada no definition.
    """
    if body.kind not in _KINDS_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"kind inválido: '{body.kind}'. Valores permitidos: {list(_KINDS_VALIDOS)}",
        )

    qtd_sessoes = len(body.definition.get("sessions", []))
    definition_json = json.dumps(body.definition)

    # created_by: usar id do usuário somente se for UUID válido
    created_by = _parse_uuid_or_none(_user.get("id"))
    school_id = _parse_uuid_or_none(body.school_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO exam_templates
                (name, kind, definition, template_layout, dpi_referencia,
                 qtd_sessoes, school_id, created_by, updated_at)
            VALUES
                ($1, $2, $3::jsonb, $4, $5,
                 $6, $7::uuid, $8::uuid, now())
            RETURNING id
            """,
            body.name,
            body.kind,
            definition_json,
            body.template_layout,
            body.dpi_referencia,
            qtd_sessoes,
            school_id,
            created_by,
        )

    return {"id": row["id"], "qtd_sessoes": qtd_sessoes}


@router.get("/templates")
async def listar_templates(
    _user: Dict = Depends(usuario_autenticado),
):
    """
    Lista templates cadastrados (sem o campo definition para economizar tráfego).

    Retorna id, name, kind, qtd_sessoes, is_active, template_layout, created_at,
    ordenados do mais recente ao mais antigo.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, kind, qtd_sessoes, is_active, template_layout, created_at
            FROM exam_templates
            ORDER BY created_at DESC
            """
        )

    templates = [dict(row) for row in rows]
    # Converter created_at para string ISO se necessário
    for t in templates:
        if t.get("created_at") is not None:
            t["created_at"] = t["created_at"].isoformat()

    return {"templates": templates}


@router.get("/templates/{tid}")
async def obter_template(
    tid: int,
    _user: Dict = Depends(usuario_autenticado),
):
    """
    Retorna o template completo (incluindo definition) pelo id numérico.

    Retorna 404 se não encontrado.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, kind, definition, template_layout, dpi_referencia,
                   qtd_sessoes, is_active, school_id, created_by, created_at, updated_at
            FROM exam_templates
            WHERE id = $1
            """,
            tid,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template id={tid} não encontrado.",
        )

    result = dict(row)
    # Converter timestamps para string ISO
    for campo in ("created_at", "updated_at"):
        if result.get(campo) is not None:
            result[campo] = result[campo].isoformat()
    # Converter UUIDs para string
    for campo in ("school_id", "created_by"):
        if result.get(campo) is not None:
            result[campo] = str(result[campo])
    # definition já vem como dict pelo asyncpg (jsonb → dict automático)

    return result


# ───────────────────────────────────────────────
# Endpoints — originais
# ───────────────────────────────────────────────


@router.get("", response_model=ListaMoldesResponse)
async def listar_moldes(
    _user: Dict = Depends(usuario_autenticado),
):
    """Lista todos os moldes disponíveis. Qualquer usuário autenticado."""
    nomes = bm.listar_moldes()
    return ListaMoldesResponse(moldes=nomes)


@router.post("/detectar", response_model=DetectarResponse)
async def detectar_candidatos(
    pdf: UploadFile = File(...),
    hibrido: bool = Form(False),
    threshold: float = Form(0.60),
    _user: Dict = Depends(usuario_autenticado),
):
    """
    Recebe um PDF e roda a detecção OpenCV de candidatos a marcação.

    Retorna por página: imagem PNG em base64 + lista de candidatos com
    posição (x, y, w, h) e métricas de qualidade (score, stddev).

    hibrido: quando True, busca caixas em toda a largura da página (x_max_pct=0.98)
             em vez dos 20% da esquerda (comportamento padrão).
    threshold: limiar mínimo de correlação para aceitar um match (0.0–1.0).
               Default 0.60. Valores mais altos reduzem falsos-positivos de letras.

    # TODO: mover para threadpool se necessário (funções de backend são síncronas).
    """
    if not _CV2_OK:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OpenCV (cv2) não está instalado neste ambiente. Instale com: pip install opencv-python-headless",
        )

    # Validar que o arquivo é um PDF
    eh_pdf = (
        (pdf.content_type or "").lower() == "application/pdf"
        or (pdf.filename or "").lower().endswith(".pdf")
    )
    if not eh_pdf:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo enviado não é um PDF. Envie um arquivo .pdf.",
        )

    pasta_moldes = bm.garantir_pasta_moldes()
    tmp_nome = f"_tmp_detectar_{uuid.uuid4().hex}.pdf"
    tmp_path = os.path.join(pasta_moldes, tmp_nome)

    try:
        conteudo = await pdf.read()
        with open(tmp_path, "wb") as f:
            f.write(conteudo)

        if hibrido:
            resultado = bm.detectar_candidatos_para_molde(tmp_path, x_max_pct=0.98, threshold=threshold)
        else:
            resultado = bm.detectar_candidatos_para_molde(tmp_path, threshold=threshold)

        if "erro" in resultado:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=resultado["erro"],
            )

        # Serializar imagens numpy → PNG → base64
        paginas_out: List[PaginaImagem] = []
        paginas_imagens: Dict = resultado.get("paginas_imagens", {})
        for num_pag, img_bgr in sorted(paginas_imagens.items(), key=lambda kv: kv[0]):
            altura_px, largura_px = img_bgr.shape[:2]
            ok, buf = cv2.imencode(".png", img_bgr)
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Falha ao codificar imagem da página {num_pag} em PNG.",
                )
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            paginas_out.append(
                PaginaImagem(
                    numero=int(num_pag),
                    largura_px=largura_px,
                    altura_px=altura_px,
                    imagem_base64=f"data:image/png;base64,{b64}",
                )
            )

        return DetectarResponse(
            qtd_paginas=resultado.get("qtd_paginas", len(paginas_out)),
            qtd_candidatos=resultado.get("qtd_candidatos", len(resultado.get("candidatos", []))),
            candidatos=resultado.get("candidatos", []),
            paginas=paginas_out,
        )

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@router.post("/ocr-regiao")
async def ocr_regiao(
    pdf: UploadFile = File(...),
    pagina: int = Form(0),
    x: int = Form(...),
    y: int = Form(...),
    w: int = Form(...),
    h: int = Form(...),
    dpi: int = Form(200),
    _user: Dict = Depends(usuario_autenticado),
):
    """
    Extrai o texto de uma REGIÃO de um PDF digital (texto selecionável) via PyMuPDF.

    Parâmetros (multipart/form):
      - pdf      : arquivo PDF
      - pagina   : índice 0-based da página (padrão 0)
      - x, y, w, h : região em pixels no DPI de referência
      - dpi      : DPI de referência usado na detecção (padrão 200)

    Retorna {"texto": "...", "vazio": bool, "fonte": "pymupdf", "pagina": int}.
    Requer PyMuPDF (fitz). Para PDFs escaneados (sem texto selecionável) o texto
    retornado será vazio — use o endpoint de OCR por imagem nesses casos.
    """
    if not _FITZ_OK:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PyMuPDF (fitz) não está disponível: {_FITZ_ERRO}. Instale com: pip install pymupdf",
        )

    pasta_moldes = bm.garantir_pasta_moldes()
    tmp_nome = f"_tmp_ocrregiao_{uuid.uuid4().hex}.pdf"
    tmp_path = os.path.join(pasta_moldes, tmp_nome)

    try:
        conteudo = await pdf.read()
        with open(tmp_path, "wb") as f:
            f.write(conteudo)

        doc = fitz.open(tmp_path)
        try:
            if not (0 <= pagina < doc.page_count):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Página {pagina} fora do intervalo válido (0–{doc.page_count - 1}).",
                )

            page = doc[pagina]

            # Converte região de pixels@dpi para pontos do PDF (1 pt = 1/72 pol)
            f_conv = 72.0 / dpi
            rect = fitz.Rect(x * f_conv, y * f_conv, (x + w) * f_conv, (y + h) * f_conv)

            texto = page.get_text("text", clip=rect)
            texto = (texto or "").strip()
            # Normaliza quebras de linha internas → espaço simples
            texto = " ".join(texto.split())
        finally:
            doc.close()

        return {
            "texto": texto,
            "vazio": len(texto) == 0,
            "fonte": "pymupdf",
            "pagina": pagina,
        }

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@router.get("/{nome}", response_model=Dict[str, Any])
async def obter_molde(
    nome: str,
    _user: Dict = Depends(usuario_autenticado),
):
    """Retorna o dict completo de um molde pelo nome. Qualquer usuário autenticado."""
    molde = bm.carregar_molde(nome)
    if molde is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Molde '{nome}' não encontrado.",
        )
    return molde
