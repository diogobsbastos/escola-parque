"""
innova_bridge/api/routers/moldes.py — Endpoints de moldes de gabarito (máscaras OMR).

Reutiliza o motor OpenCV encapsulado em `backend_molde` (root do projeto) para:
  - listar moldes salvos (Postgres com fallback disco)
  - carregar um molde pelo nome
  - detectar candidatos a marcação (bolhas/caixas) em um PDF enviado pelo cliente

Endpoints:
  GET  /api/v1/moldes                Lista todos os nomes de moldes disponíveis.
  GET  /api/v1/moldes/{nome}         Retorna o dict completo de um molde.
  POST /api/v1/moldes/detectar       Recebe PDF, roda detecção OpenCV, retorna candidatos + imagens base64.
"""
from __future__ import annotations

import base64
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

# Importação defensiva do OpenCV — pode não estar instalado no ambiente mínimo
try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

import backend_molde as bm
from innova_bridge.api.deps import usuario_autenticado

router = APIRouter(prefix="/moldes", tags=["moldes"])

# ────────────────────────────────────────────────────────────────
# Modelos Pydantic
# ────────────────────────────────────────────────────────────────


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


# ────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────


@router.get("", response_model=ListaMoldesResponse)
async def listar_moldes(
    _user: Dict = Depends(usuario_autenticado),
):
    """Lista todos os moldes disponíveis. Qualquer usuário autenticado."""
    nomes = bm.listar_moldes()
    return ListaMoldesResponse(moldes=nomes)


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


@router.post("/detectar", response_model=DetectarResponse)
async def detectar_candidatos(
    pdf: UploadFile = File(...),
    _user: Dict = Depends(usuario_autenticado),
):
    """
    Recebe um PDF e roda a detecção OpenCV de candidatos a marcação.

    Retorna por página: imagem PNG em base64 + lista de candidatos com
    posição (x, y, w, h) e métricas de qualidade (score, stddev).

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

        resultado = bm.detectar_candidatos_para_molde(tmp_path)

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
