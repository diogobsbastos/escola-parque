"""
innova_bridge/workers/autostart.py

Sobe o WORKER (Backend Central) AUTOMATICAMENTE junto com o Streamlit — sem
ligar na mão. Idempotente: só dispara se NÃO houver worker vivo (checa o
heartbeat no Supabase), evitando duplicados em reruns/reinícios do Streamlit.

Uso no app.py (uma vez, no topo), idealmente memoizado pra rodar 1x por
processo do servidor:

    import streamlit as st
    @st.cache_resource
    def _autostart_backend_central():
        from innova_bridge.workers.autostart import ensure_worker_running
        return ensure_worker_running()
    _autostart_backend_central()
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Raiz do projeto (.../ESCOLA_PARQUE) — pra rodar `python -m innova_bridge...`
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _worker_vivo() -> bool:
    """True se já existe um worker com heartbeat fresco (< 60s) no Supabase.
    Defensivo: qualquer falha (sem rede/sem BD) -> False (deixa subir)."""
    try:
        from innova_bridge.db.client import get_pool, run_async

        async def _go():
            pool = await get_pool()
            row = await pool.fetchrow(
                "SELECT EXTRACT(EPOCH FROM (now() - (value->>'ts')::timestamptz)) AS idade "
                "FROM public.system_settings WHERE key = 'python_worker_heartbeat'"
            )
            if not row or row["idade"] is None:
                return False
            return float(row["idade"]) < 60.0

        return bool(run_async(_go()))
    except Exception:
        return False


def ensure_worker_running(interval: float = 10.0) -> dict:
    """Dispara o worker em background se ninguém estiver vivo. Idempotente.

    Retorna {"started": bool, "reason": str}.
    """
    if _worker_vivo():
        return {"started": False, "reason": "ja_havia_worker_vivo"}

    try:
        popen_kwargs: dict = {
            "cwd": str(_PROJECT_ROOT),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            # DETACHED_PROCESS (0x08) | CREATE_NO_WINDOW (0x08000000):
            # roda solto, sem abrir janela de console.
            popen_kwargs["creationflags"] = 0x00000008 | 0x08000000
        else:
            popen_kwargs["start_new_session"] = True

        subprocess.Popen(
            [sys.executable, "-m", "innova_bridge.workers.agente1_worker",
             "--interval", str(interval)],
            **popen_kwargs,
        )
        return {"started": True, "reason": "spawned"}
    except Exception as e:  # noqa: BLE001
        return {"started": False, "reason": f"falha: {type(e).__name__}: {e}"}


__all__ = ["ensure_worker_running"]
