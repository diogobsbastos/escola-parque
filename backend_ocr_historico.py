"""
backend_ocr_historico.py — Camada de persistência de histórico de OCR.

Responsabilidade: gravar e ler da tabela `ocr_resultados` no PostgreSQL local.
Segue o mesmo padrão do backend_molde.py: asyncpg + run_async via innova_bridge.

Regras:
  - NUNCA remove ou sobrescreve linhas (histórico imutável).
  - Falha silenciosa: todas as funções públicas capturam exceções e retornam
    valores neutros (None / False) — o disco continua como backup.
  - NÃO importa nem modifica backend_molde.py, backend_formularios.py nem
    innova_bridge/db/client.py.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

# ── BD: asyncpg via innova_bridge (mesmo padrão de backend_molde.py) ──────
try:
    from innova_bridge.db.client import run_async, get_pool
    _BD_IMPORT_OK = True
except ImportError:
    _BD_IMPORT_OK = False


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS INTERNOS
# ═══════════════════════════════════════════════════════════════════════════

def _bd_disponivel() -> bool:
    if not _BD_IMPORT_OK:
        return False
    try:
        pool = run_async(get_pool())
        return pool is not None
    except Exception:
        return False


async def _async_inserir(pool, professor_id: str, molde: Optional[str],
                          dados: Dict[str, Any]) -> int:
    """INSERT na tabela ocr_resultados. Retorna o id gerado."""
    dados_str = json.dumps(dados, ensure_ascii=False)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO public.ocr_resultados (professor_id, molde, dados_json)
            VALUES ($1, $2, $3::jsonb)
            RETURNING id
            """,
            professor_id, molde, dados_str,
        )
        return row["id"]


async def _async_ler_mais_recente(pool, professor_id: str) -> Optional[Dict[str, Any]]:
    """Lê o registro mais recente de ocr_resultados para professor_id."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, professor_id, molde, dados_json, score, criado_em
            FROM   public.ocr_resultados
            WHERE  professor_id = $1
            ORDER  BY criado_em DESC
            LIMIT  1
            """,
            professor_id,
        )
        if row is None:
            return None
        val = row["dados_json"]
        if isinstance(val, str):
            dados = json.loads(val)
        else:
            dados = dict(val)
        return {
            "id":           row["id"],
            "professor_id": row["professor_id"],
            "molde":        row["molde"],
            "dados_json":   dados,
            "score":        row["score"],
            "criado_em":    row["criado_em"].isoformat() if row["criado_em"] else None,
        }


# ═══════════════════════════════════════════════════════════════════════════
# API PÚBLICA
# ═══════════════════════════════════════════════════════════════════════════

def inserir_resultado(professor_id: str,
                       dados: Dict[str, Any],
                       molde: Optional[str] = None) -> bool:
    """Grava um resultado de OCR na tabela ocr_resultados.

    Args:
        professor_id: chave do cache (mesmo valor usado em ocr_cache_<id>.json).
        dados:        payload completo que vai/foi gravado no arquivo JSON.
        molde:        nome do molde usado (extraído de dados['_meta']['molde_usado']
                      se não passado explicitamente).

    Retorna True em sucesso, False em qualquer falha (nunca lança exceção).
    """
    if not _bd_disponivel():
        return False
    try:
        # Extrai molde dos metadados embutidos se não foi fornecido
        if molde is None:
            molde = (dados.get("_meta") or {}).get("molde_usado")
        pool = run_async(get_pool())
        run_async(_async_inserir(pool, str(professor_id), molde, dados))
        return True
    except Exception:
        return False


def ler_mais_recente(professor_id: str) -> Optional[Dict[str, Any]]:
    """Lê o resultado mais recente do BD para professor_id.

    Retorna dict com {id, professor_id, molde, dados_json, score, criado_em}
    ou None se não houver registro ou em caso de falha.
    """
    if not _bd_disponivel():
        return None
    try:
        pool = run_async(get_pool())
        return run_async(_async_ler_mais_recente(pool, str(professor_id)))
    except Exception:
        return None
