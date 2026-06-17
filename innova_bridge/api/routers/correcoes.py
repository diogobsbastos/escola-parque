"""
innova_bridge/api/routers/correcoes.py — Endpoints de Correção (OCR).

Roda o motor de OCR encapsulado em `backend_ocr` e persiste o resultado
na tabela `ocr_resultados` do Postgres (banco innova).

Endpoints:
  POST /api/v1/correcoes          Envia PDF + molde, roda OCR, grava e retorna resultado.
  GET  /api/v1/correcoes          Lista resultados (sem dados_json pesado).
  GET  /api/v1/correcoes/{cid}    Retorna 1 resultado completo por id.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

# Importação defensiva do backend_ocr
try:
    import backend_ocr as _bocr
    _BOCR_OK = True
    _BOCR_ERRO = ""
except Exception as _e:
    _BOCR_OK = False
    _BOCR_ERRO = str(_e)

# Importação defensiva do backend_molde (para garantir_pasta_moldes)
try:
    import backend_molde as _bm
    _BM_OK = True
except Exception:
    _BM_OK = False

from innova_bridge.api.deps import usuario_autenticado
from innova_bridge.db.client import get_pool

router = APIRouter(prefix="/correcoes", tags=["correcoes"])


# ───────────────────────────────────────────────
# Helpers internos
# ───────────────────────────────────────────────

def _calcular_score(dados: Dict[str, Any]) -> int:
    """Conta quantas respostas têm marcado=True em todas as seções."""
    total = 0
    for secao in dados.values():
        if isinstance(secao, list):
            for item in secao:
                if isinstance(item, dict) and item.get("marcado") is True:
                    total += 1
    return total


def _garantir_pasta() -> str:
    """Retorna a pasta de moldes (usada para arquivo temp)."""
    if _BM_OK:
        return _bm.garantir_pasta_moldes()
    # Fallback: /tmp
    return "/tmp"


# ───────────────────────────────────────────────
# POST /correcoes — rodar OCR e gravar resultado
# ───────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def criar_correcao(
    pdf: UploadFile = File(...),
    molde: str = Form(...),
    _user: Dict = Depends(usuario_autenticado),
):
    """
    Recebe um PDF e o nome de um molde, roda o OCR e grava em ocr_resultados.

    Retorna: id inserido, molde, score (qtd marcado=True), dados e telemetria.
    """
    if not _BOCR_OK:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"backend_ocr não está disponível neste ambiente: {_BOCR_ERRO}",
        )

    # Salvar PDF em arquivo temporário
    pasta = _garantir_pasta()
    tmp_nome = f"_tmp_correcao_{uuid.uuid4().hex}.pdf"
    tmp_path = os.path.join(pasta, tmp_nome)

    try:
        conteudo = await pdf.read()
        with open(tmp_path, "wb") as f:
            f.write(conteudo)

        # Rodar OCR
        resultado = _bocr.analisar_com_treinamento(tmp_path, molde)

        if "erro" in resultado:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=resultado["erro"],
            )

        dados = resultado.get("dados", {})
        telemetria = resultado.get("telemetria")
        score = _calcular_score(dados)

        # Serializar para JSON (asyncpg exige string para ::jsonb)
        resultado_json_str = json.dumps(resultado, ensure_ascii=False)

        professor_id = str(_user.get("id") or "")

        # Gravar no banco
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO ocr_resultados
                    (professor_id, molde, dados_json, score, criado_em)
                VALUES
                    ($1, $2, $3::jsonb, $4, now())
                RETURNING id
                """,
                professor_id,
                molde,
                resultado_json_str,
                score,
            )

        inserted_id = row["id"]

        return {
            "id": inserted_id,
            "molde": molde,
            "score": score,
            "dados": dados,
            "telemetria": telemetria,
        }

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# ───────────────────────────────────────────────
# GET /correcoes — listar resultados (sem dados_json)
# ───────────────────────────────────────────────

@router.get("")
async def listar_correcoes(
    molde: Optional[str] = None,
    professor_id: Optional[str] = None,
    limit: int = 50,
    _user: Dict = Depends(usuario_autenticado),
) -> List[Dict[str, Any]]:
    """
    Lista ocr_resultados (sem dados_json), mais recentes primeiro.

    Filtros opcionais: molde, professor_id. Limite padrão: 50.
    """
    conditions = []
    params: List[Any] = []

    if molde:
        params.append(molde)
        conditions.append(f"molde = ${len(params)}")

    if professor_id:
        params.append(professor_id)
        conditions.append(f"professor_id = ${len(params)}")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    params.append(limit)
    limit_clause = f"LIMIT ${len(params)}"

    sql = f"""
        SELECT id, professor_id, molde, score, criado_em
        FROM ocr_resultados
        {where_clause}
        ORDER BY criado_em DESC
        {limit_clause}
    """

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return [
        {
            "id": r["id"],
            "professor_id": r["professor_id"],
            "molde": r["molde"],
            "score": r["score"],
            "criado_em": r["criado_em"].isoformat() if r["criado_em"] else None,
        }
        for r in rows
    ]


# ───────────────────────────────────────────────
# GET /correcoes/{cid} — resultado completo por id
# ───────────────────────────────────────────────

@router.get("/{cid}")
async def obter_correcao(
    cid: int,
    _user: Dict = Depends(usuario_autenticado),
) -> Dict[str, Any]:
    """Retorna 1 resultado completo (com dados_json) pelo id, ou 404."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, professor_id, molde, dados_json, score, criado_em
            FROM ocr_resultados
            WHERE id = $1
            """,
            cid,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Correção id={cid} não encontrada.",
        )

    dados_json = row["dados_json"]
    # asyncpg retorna jsonb como string ou dict dependendo do driver/versão
    if isinstance(dados_json, str):
        try:
            dados_json = json.loads(dados_json)
        except Exception:
            pass

    return {
        "id": row["id"],
        "professor_id": row["professor_id"],
        "molde": row["molde"],
        "dados_json": dados_json,
        "score": row["score"],
        "criado_em": row["criado_em"].isoformat() if row["criado_em"] else None,
    }
