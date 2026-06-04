"""
innova_bridge/db - Cliente asyncpg + queries basicas.

O modulo client expoe:
  - run_async(coro): roda coroutine em event loop singleton (Streamlit-safe)
  - get_pool(): retorna pool asyncpg (cached, lazy)
  - close_pool(): fecha pool (cleanup)

O modulo queries_basicas expoe queries de leitura para validacao da conexao.
"""

from .client import run_async, get_pool, close_pool
from . import queries_basicas

__all__ = ["run_async", "get_pool", "close_pool", "queries_basicas"]
