"""
innova_bridge/repositories/agent_configs_repo.py

Leitura/escrita da config de execucao por agente no Supabase (public.agent_configs).
FONTE DA VERDADE do default consumido pelo WORKER (e, no fim, pelo frontend).

Sincrono (run_async) pra uso direto no Streamlit: o painel de Agentes grava aqui,
o worker (innova_bridge/workers/agente1_worker.py) le daqui.

agent_name e o enum do banco: 'profile_builder' | 'adapter' | 'validator'.
"""
from __future__ import annotations

from typing import Optional

from innova_bridge.db.client import get_pool, run_async


VALID_ENGINES = ("native", "hybrid", "llm")
VALID_AGENTS = ("profile_builder", "adapter", "validator")


async def _read(agent_name: str) -> Optional[dict]:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT agent_name::text AS agent_name, engine, model, strict_no_fallback, "
        "       temperature, max_tokens, updated_at "
        "FROM public.agent_configs WHERE agent_name = $1::agent_name",
        agent_name,
    )
    return dict(row) if row else None


async def _upsert(agent_name, engine, model, strict, temperature, max_tokens, updated_by) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO public.agent_configs
            (agent_name, engine, model, strict_no_fallback, temperature, max_tokens,
             updated_by_user_id, updated_at)
        VALUES ($1::agent_name, $2, $3, $4, $5, $6, $7, now())
        ON CONFLICT (agent_name) DO UPDATE SET
            engine             = EXCLUDED.engine,
            model              = EXCLUDED.model,
            strict_no_fallback = EXCLUDED.strict_no_fallback,
            temperature        = EXCLUDED.temperature,
            max_tokens         = EXCLUDED.max_tokens,
            updated_by_user_id = EXCLUDED.updated_by_user_id,
            updated_at         = now()
        """,
        agent_name, engine, model, strict, temperature, max_tokens, updated_by,
    )


def read_config(agent_name: str) -> Optional[dict]:
    """Le a config do agente (ou None). Nunca levanta — devolve None em erro
    (o painel cai pros defaults)."""
    try:
        return run_async(_read(agent_name))
    except Exception:
        return None


def save_config(
    agent_name: str,
    *,
    engine: str,
    model: Optional[str],
    strict_no_fallback: bool,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    updated_by_user_id: Optional[str] = None,
) -> tuple[bool, str]:
    """Grava (upsert) a config do agente no Supabase. Retorna (ok, msg)."""
    if agent_name not in VALID_AGENTS:
        return False, f"agent_name invalido: {agent_name!r}"
    if engine not in VALID_ENGINES:
        return False, f"engine invalido: {engine!r}"
    try:
        run_async(_upsert(agent_name, engine, model, bool(strict_no_fallback),
                          temperature, max_tokens, updated_by_user_id))
        return True, "Default salvo no banco (agent_configs) — worker e frontend ja consomem."
    except Exception as e:
        return False, f"Falha ao salvar: {type(e).__name__}: {e}"


__all__ = ["read_config", "save_config", "VALID_ENGINES", "VALID_AGENTS"]
