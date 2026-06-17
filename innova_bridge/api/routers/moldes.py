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

Endpoint de análise de tabela:
  POST /api/v1/moldes/analisar-tabela        Detecta grid de quadrados numa região tabular e faz OCR de cabeçalhos/perguntas.
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


def _mediana(valores: List[float]) -> float:
    """Calcula a mediana de uma lista de floats. Retorna 0.0 se vazia."""
    if not valores:
        return 0.0
    s = sorted(valores)
    n = len(s)
    meio = n // 2
    if n % 2 == 1:
        return float(s[meio])
    return float(s[meio - 1] + s[meio]) / 2.0


def _ocr_regiao_px(page: Any, x0: int, y0: int, x1: int, y1: int, dpi: int) -> str:
    """Extrai e normaliza texto de uma região em pixels (PyMuPDF). Requer _FITZ_OK."""
    f_conv = 72.0 / dpi
    rect = fitz.Rect(x0 * f_conv, y0 * f_conv, x1 * f_conv, y1 * f_conv)
    texto = page.get_text("text", clip=rect) or ""
    return " ".join(texto.split())


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


@router.post("/analisar-tabela")
async def analisar_tabela(
    pdf: UploadFile = File(...),
    pagina: int = Form(0),
    x: int = Form(...),
    y: int = Form(...),
    w: int = Form(...),
    h: int = Form(...),
    dpi: int = Form(200),
    threshold: float = Form(0.75),
    _user: Dict = Depends(usuario_autenticado),
):
    """
    Analisa uma região retangular de um PDF que contém uma TABELA de checkboxes.

    Detecta o grid de quadrados (linhas = perguntas, colunas = opções), agrupa-os
    em linhas e colunas e extrai via OCR (PyMuPDF) o texto de cabeçalho de cada
    coluna e o rótulo (pergunta) de cada linha.

    Parâmetros (multipart/form):
      - pdf        : arquivo PDF
      - pagina     : índice 0-based da página (padrão 0)
      - x, y, w, h : região em pixels no DPI de referência que envolve a tabela
      - dpi        : DPI de referência (padrão 200)
      - threshold  : limiar de correlação para detecção de quadrados (padrão 0.75)

    Retorna estrutura com n_linhas, n_colunas, colunas (com texto OCR do cabeçalho),
    linhas (com texto OCR da pergunta e lista de quadrados) e lista plana de todos
    os quadrados com seus índices (linha, coluna).
    """
    if not _FITZ_OK:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PyMuPDF (fitz) não está disponível: {_FITZ_ERRO}. Instale com: pip install pymupdf",
        )

    pasta_moldes = bm.garantir_pasta_moldes()
    tmp_nome = f"_tmp_tabela_{uuid.uuid4().hex}.pdf"
    tmp_path = os.path.join(pasta_moldes, tmp_nome)

    try:
        conteudo = await pdf.read()
        with open(tmp_path, "wb") as f:
            f.write(conteudo)

        try:
            # ── 1. Detectar quadrados via backend_molde ──────────────────────────
            res = bm.detectar_candidatos_para_molde(tmp_path, x_max_pct=0.98, threshold=threshold)
            if "erro" in res:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=res["erro"],
                )

            cands = res.get("candidatos", [])

            # Filtra apenas candidatos da página e cujo centro caia dentro da região
            x_fim = x + w
            y_fim = y + h
            filtrados = []
            for c in cands:
                if c.get("pag", 0) != pagina:
                    continue
                cx = c["x"] + c["w"] / 2.0
                cy = c["y"] + c["h"] / 2.0
                if x <= cx <= x_fim and y <= cy <= y_fim:
                    filtrados.append(c)

            # Estrutura vazia se não encontrou nenhum quadrado
            if not filtrados:
                return {
                    "pagina": pagina,
                    "n_linhas": 0,
                    "n_colunas": 0,
                    "colunas": [],
                    "linhas": [],
                    "quadrados": [],
                }

            # ── 2. Agrupar em LINHAS ─────────────────────────────────────────────
            med_h = _mediana([float(c["h"]) for c in filtrados])
            tol_linha = 0.6 * med_h if med_h > 0 else 8.0

            # Ordenar por centro-y
            filtrados_ordenados = sorted(filtrados, key=lambda c: c["y"] + c["h"] / 2.0)

            grupos_linhas: List[List[Dict]] = []
            for c in filtrados_ordenados:
                cy = c["y"] + c["h"] / 2.0
                alocado = False
                for grupo in grupos_linhas:
                    cy_ref = grupo[0]["y"] + grupo[0]["h"] / 2.0
                    if abs(cy - cy_ref) < tol_linha:
                        grupo.append(c)
                        alocado = True
                        break
                if not alocado:
                    grupos_linhas.append([c])

            # Ordenar linhas de cima para baixo; dentro de cada linha ordenar por x
            grupos_linhas.sort(key=lambda g: g[0]["y"] + g[0]["h"] / 2.0)
            for g in grupos_linhas:
                g.sort(key=lambda c: c["x"])

            # ── 3. Agrupar em COLUNAS ────────────────────────────────────────────
            med_w = _mediana([float(c["w"]) for c in filtrados])
            tol_col = 0.6 * med_w if med_w > 0 else 8.0

            # Coletar todos os centros-x para agrupar
            todos_cx = [c["x"] + c["w"] / 2.0 for c in filtrados]
            todos_cx_sorted = sorted(set(todos_cx))

            grupos_cols_cx: List[float] = []
            for cx_val in sorted([c["x"] + c["w"] / 2.0 for c in filtrados]):
                alocado = False
                for i, ref_cx in enumerate(grupos_cols_cx):
                    if abs(cx_val - ref_cx) < tol_col:
                        # Atualiza referência como média
                        grupos_cols_cx[i] = (ref_cx + cx_val) / 2.0
                        alocado = True
                        break
                if not alocado:
                    grupos_cols_cx.append(cx_val)

            grupos_cols_cx.sort()  # da esquerda para a direita

            def _col_idx(c: Dict) -> int:
                cx_val = c["x"] + c["w"] / 2.0
                melhor = 0
                melhor_dist = abs(cx_val - grupos_cols_cx[0])
                for i, ref_cx in enumerate(grupos_cols_cx):
                    dist = abs(cx_val - ref_cx)
                    if dist < melhor_dist:
                        melhor_dist = dist
                        melhor = i
                return melhor

            # ── 4. Montar lista plana com (linha_idx, coluna_idx) ────────────────
            quadrados_planos: List[Dict[str, Any]] = []
            for linha_idx, grupo in enumerate(grupos_linhas):
                for c in grupo:
                    col_idx = _col_idx(c)
                    quadrados_planos.append({
                        "x": c["x"],
                        "y": c["y"],
                        "w": c["w"],
                        "h": c["h"],
                        "linha": linha_idx,
                        "coluna": col_idx,
                    })

            n_linhas = len(grupos_linhas)
            n_colunas = len(grupos_cols_cx)

            # ── 5. OCR via PyMuPDF ───────────────────────────────────────────────
            doc = fitz.open(tmp_path)
            try:
                page = doc[pagina]

                # Topo da 1ª linha de quadrados (menor y entre todos os quadrados)
                y_topo_quadrados = min(c["y"] for c in filtrados)
                # Esquerda da 1ª coluna de quadrados (menor x)
                x_esq_quadrados = min(c["x"] for c in filtrados)

                # Cabeçalho de cada coluna j
                colunas_out: List[Dict[str, Any]] = []
                for j, ref_cx in enumerate(grupos_cols_cx):
                    # x-range: todos os quadrados desta coluna
                    cands_col = [c for c in filtrados if abs((c["x"] + c["w"] / 2.0) - ref_cx) < tol_col]
                    if cands_col:
                        col_x0 = max(0, min(c["x"] for c in cands_col) - 4)
                        col_x1 = max(c["x"] + c["w"] for c in cands_col) + 4
                        col_w = col_x1 - col_x0
                    else:
                        col_x0 = int(ref_cx) - 10
                        col_x1 = int(ref_cx) + 10
                        col_w = 20

                    # y-range do cabeçalho: do topo da região até 2px acima do topo dos quadrados
                    cab_y0 = y
                    cab_y1 = max(y, y_topo_quadrados - 2)

                    texto_cab = ""
                    if cab_y1 > cab_y0:
                        texto_cab = _ocr_regiao_px(page, col_x0, cab_y0, col_x1, cab_y1, dpi)

                    colunas_out.append({
                        "indice": j,
                        "texto": texto_cab,
                        "x": col_x0,
                        "w": col_w,
                    })

                # Rótulo (pergunta) de cada linha i
                linhas_out: List[Dict[str, Any]] = []
                for i, grupo in enumerate(grupos_linhas):
                    # y-range: quadrados desta linha com padding
                    lin_y0 = max(0, min(c["y"] for c in grupo) - 4)
                    lin_y1 = max(c["y"] + c["h"] for c in grupo) + 4
                    lin_h = lin_y1 - lin_y0

                    # x-range do rótulo: da borda esquerda da região até 2px antes do 1º quadrado
                    rot_x0 = x
                    rot_x1 = max(x, x_esq_quadrados - 2)

                    texto_rot = ""
                    if rot_x1 > rot_x0:
                        texto_rot = _ocr_regiao_px(page, rot_x0, lin_y0, rot_x1, lin_y1, dpi)

                    # Quadrados desta linha
                    quads_linha = [
                        q for q in quadrados_planos if q["linha"] == i
                    ]

                    linhas_out.append({
                        "indice": i,
                        "pergunta": texto_rot,
                        "y": lin_y0,
                        "h": lin_h,
                        "quadrados": quads_linha,
                    })

            finally:
                doc.close()

            # ── 6. Resposta ──────────────────────────────────────────────────────
            return {
                "pagina": pagina,
                "n_linhas": n_linhas,
                "n_colunas": n_colunas,
                "colunas": colunas_out,
                "linhas": linhas_out,
                "quadrados": quadrados_planos,
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )

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
