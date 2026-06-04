"""
innova_bridge/repositories/agent_run_logs_repo.py

Leitura do log de execucoes LLM (public.agent_run_logs) pras telas de custo.
FONTE COMPARTILHADA com o frontend — a mesma tabela que o worker grava e que a
pagina de logs do Next.js le. "Um vidro so".

Sincrono (run_async) pra uso direto no Streamlit.
Mapeia 'request_source' pra um rotulo de ORIGEM (Frontend / Backend).
"""
from __future__ import annotations

from typing import Optional

from innova_bridge.db.client import get_pool, run_async


# request_source -> rotulo amigavel de ORIGEM da requisicao.
ORIGEM_LABEL = {
    "web_form": "Frontend (web)",
    "python_manual": "Backend (manual)",
    "worker_auto": "Backend (worker)",
}


async def _listar(limit: int):
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT created_at, request_source, model, agent_name::text AS agent_name,
               input_tokens, output_tokens, cached_input_tokens,
               cost_brl, cost_usd_raw, latency_ms, status::text AS status
        FROM public.agent_run_logs
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


def listar_runs(limit: int = 500) -> Optional[list[dict]]:
    """Devolve as execucoes ja MAPEADAS pras colunas da tela de custos (Streamlit),
    mais recente primeiro. Retorna None em erro (a tela cai no fallback local)."""
    try:
        raw = run_async(_listar(limit))
    except Exception:
        return None

    out: list[dict] = []
    for r in raw:
        src = r.get("request_source") or ""
        created = r.get("created_at")
        out.append({
            "timestamp": created.strftime("%Y-%m-%d %H:%M:%S") if created else "",
            "origem": ORIGEM_LABEL.get(src, src or "—"),
            "modelo": r.get("model") or "",
            "processo": r.get("agent_name") or "",
            "tokens_in": int(r.get("input_tokens") or 0),
            "tokens_out": int(r.get("output_tokens") or 0),
            "tokens_cache": int(r.get("cached_input_tokens") or 0),
            "custo_brl": float(r.get("cost_brl") or 0),
            "tempo_execucao": round(float(r.get("latency_ms") or 0) / 1000.0, 2),
            "status": r.get("status") or "",
        })
    return out


__all__ = ["listar_runs", "ORIGEM_LABEL"]
