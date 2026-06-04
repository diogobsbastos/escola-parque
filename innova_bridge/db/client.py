"""
innova_bridge/db/client.py - Pool asyncpg com Streamlit-safe event loop.

ARQUITETURA:
  - asyncpg.create_pool() e coroutine. Streamlit roda sincronicamente.
  - Solucao: event loop dedicado, criado uma vez (cached), reusado em
    todas chamadas via run_until_complete().
  - statement_cache_size=0 OBRIGATORIO no Transaction Pooler (porta 6543)
    para evitar erro "prepared statement does not exist".

USO:
    from innova_bridge.db import run_async, get_pool, queries_basicas

    pool = run_async(get_pool())
    versao = run_async(queries_basicas.obter_versao_pg(pool))
"""

from __future__ import annotations

import asyncio
from typing import Optional

import asyncpg

from innova_bridge.config import get_database_url

# ============================================================================
# Event loop singleton (Streamlit-safe)
# ============================================================================

_loop: Optional[asyncio.AbstractEventLoop] = None
_pool: Optional[asyncpg.Pool] = None


def _get_loop() -> asyncio.AbstractEventLoop:
    """Retorna um event loop dedicado, criando se preciso.

    Streamlit nao tem event loop ativo por default. Cada thread do
    Streamlit precisa do seu loop. asyncio.get_event_loop() pode
    falhar em algumas versoes recentes do Python.
    """
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


def run_async(coro):
    """Roda uma coroutine no event loop singleton. Bloqueante.

    Use em codigo sincrono do Streamlit pra chamar funcoes async do asyncpg.
    """
    loop = _get_loop()
    return loop.run_until_complete(coro)


# ============================================================================
# Pool asyncpg
# ============================================================================

async def get_pool() -> asyncpg.Pool:
    """Retorna o pool asyncpg singleton, criando se preciso.

    Configuracao CRITICA:
      statement_cache_size=0  -> obrigatorio em Transaction Pooler 6543
                                  (sem isso da erro depois de poucas queries)
      min_size=1, max_size=5  -> conservador (Streamlit local, sem concorrencia
                                  pesada). Pra producao Web ajustar pra cima.
      command_timeout=30      -> mata query que demora > 30s
    """
    global _pool
    if _pool is None or _pool._closed:
        database_url = get_database_url()
        _pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=5,
            statement_cache_size=0,
            command_timeout=30,
        )
    return _pool


async def close_pool() -> None:
    """Fecha o pool (cleanup). Idempotente."""
    global _pool
    if _pool is not None and not _pool._closed:
        await _pool.close()
    _pool = None


def reset_pool_sync() -> None:
    """Forca recriacao do pool (uso: trocou de BD ativo via UI)."""
    global _pool
    if _pool is not None:
        try:
            run_async(close_pool())
        except Exception:
            pass
    _pool = None
