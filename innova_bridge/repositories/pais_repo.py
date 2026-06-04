"""
innova_bridge/repositories/pais_repo.py

Persistencia do PAI no Supabase (tabela public.pais), com a MESMA governanca
do persistence.py local: status_rule + supersede + versionamento.

ADITIVO: NAO substitui a persistencia local em pais_gerados/. E um destino a
mais (o worker grava nos dois). Usa o pool asyncpg de innova_bridge/db/client.py.

Regras honradas (espelham agents/agente1/persistence.py):
  - status_rule: rationale.low_confidence_areas vazio -> 'active'; senao -> 'needs_review'.
  - 1 PAI vigente por (student_id, family_id): ao gravar, faz SUPERSEDE de TODOS
    os anteriores com status in (active, needs_review).
  - version = ultima + 1 (por aluno+familia).

As funcoes recebem uma `conn` asyncpg (devem rodar DENTRO de uma transacao do
chamador) — assim o worker grava PAI + log + carimbo da secao de forma atomica.
`persist_pai()` e um atalho conveniente que abre a propria transacao.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg


# ============================================================================
# Status rule (espelha persistence.aplicar_status_rule)
# ============================================================================

def status_from_pai(content: dict) -> str:
    """low_confidence_areas vazio -> 'active'; senao -> 'needs_review'."""
    low = (content.get("rationale") or {}).get("low_confidence_areas") or []
    return "active" if not low else "needs_review"


# ============================================================================
# Helpers transacionais (recebem conn — rodam dentro da tx do chamador)
# ============================================================================

async def next_version(conn: asyncpg.Connection, student_id: str, family_id: int) -> int:
    """Proxima versao incremental para (aluno, familia)."""
    atual = await conn.fetchval(
        "SELECT COALESCE(MAX(version), 0) FROM public.pais "
        "WHERE student_id = $1 AND family_id = $2",
        student_id, family_id,
    )
    return int(atual or 0) + 1


async def supersede_vigentes(conn: asyncpg.Connection, student_id: str, family_id: int) -> int:
    """Marca como 'superseded' todos os PAIs vigentes (active + needs_review)
    do (aluno, familia). Retorna quantos foram afetados."""
    res = await conn.execute(
        "UPDATE public.pais SET status = 'superseded', updated_at = now() "
        "WHERE student_id = $1 AND family_id = $2 "
        "AND status IN ('active', 'needs_review')",
        student_id, family_id,
    )
    try:
        return int(str(res).split()[-1])
    except (ValueError, IndexError):
        return 0


async def insert_pai(
    conn: asyncpg.Connection,
    *,
    school_id: str,
    student_id: str,
    family_id: int,
    section_id: Optional[str],
    content: dict,
    generated_by_agent: str,
    version: int,
    status: str,
    applies_to_subjects: Optional[list[str]] = None,
    created_via: Optional[str] = None,
) -> str:
    """Insere uma linha nova em public.pais e devolve o id (uuid str).

    created_via = origem da criacao ('web_form' | 'python_manual' | 'worker_auto')
    — visivel nos dois lados (frontend + Streamlit).
    """
    pai_id = await conn.fetchval(
        """
        INSERT INTO public.pais
            (school_id, family_id, student_id, section_id,
             applies_to_subjects, version, status, content, generated_by_agent, created_via)
        VALUES ($1, $2, $3, $4, $5::text[], $6, $7::pai_status, $8::jsonb, $9, $10)
        RETURNING id
        """,
        school_id, family_id, student_id, section_id,
        list(applies_to_subjects or []), version, status,
        json.dumps(content, ensure_ascii=False), generated_by_agent, created_via,
    )
    return str(pai_id)


# ============================================================================
# API publica conveniente (abre a propria transacao)
# ============================================================================

async def persist_pai(
    pool: asyncpg.Pool,
    *,
    school_id: str,
    student_id: str,
    family_id: int,
    section_id: Optional[str],
    content: dict,
    generated_by_agent: str,
    applies_to_subjects: Optional[list[str]] = None,
    status_override: Optional[str] = None,
) -> dict[str, Any]:
    """Grava um PAI novo no Supabase com supersede + status_rule + versao,
    tudo numa transacao. Retorna {pai_id, version, status, superseded}.

    Use o worker para gravar PAI + log + carimbo atomicos; este atalho serve
    para escrita standalone / testes.
    """
    status = status_override or status_from_pai(content)
    async with pool.acquire() as conn:
        async with conn.transaction():
            superseded = await supersede_vigentes(conn, student_id, family_id)
            version = await next_version(conn, student_id, family_id)
            pai_id = await insert_pai(
                conn,
                school_id=school_id,
                student_id=student_id,
                family_id=family_id,
                section_id=section_id,
                content=content,
                generated_by_agent=generated_by_agent,
                version=version,
                status=status,
                applies_to_subjects=applies_to_subjects,
            )
    return {"pai_id": pai_id, "version": version, "status": status, "superseded": superseded}


# ============================================================================
# Leitura (fonte única): o Streamlit lê a MESMA tabela pais que o frontend
# ============================================================================

def listar_pais_ativos_supabase(code_or_uuid: str) -> list[dict]:
    """Lista os PAIs vigentes (active/needs_review) de um aluno DIRETO do Supabase,
    aceitando o `code` (ex.: 'U4') OU o uuid. Garante que o Streamlit veja
    EXATAMENTE os mesmos PAIs que o frontend (fonte única = tabela pais).
    Sincrono (run_async) pro Streamlit. Retorna [] em erro.
    """
    from innova_bridge.db.client import get_pool, run_async

    async def _go():
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT p.content, p.family_id, p.version, p.status::text AS status,
                   p.created_via, p.generated_by_agent, d.name AS familia
            FROM public.pais p
            JOIN public.students s ON s.id = p.student_id
            JOIN public.discipline_families d ON d.id = p.family_id
            WHERE (s.code = $1 OR s.id::text = $1)
              AND p.status IN ('active', 'needs_review')
            ORDER BY p.family_id, p.version DESC
            """,
            str(code_or_uuid),
        )
        out: list[dict] = []
        for r in rows:
            c = r["content"]
            if isinstance(c, (str, bytes, bytearray)):
                try:
                    c = json.loads(c)
                except (ValueError, TypeError):
                    c = {}
            out.append({
                "content": c,
                "family_id": r["family_id"],
                "familia": r["familia"],
                "version": r["version"],
                "status": r["status"],
                "created_via": r["created_via"],
                "generated_by_agent": r["generated_by_agent"],
            })
        return out

    try:
        return run_async(_go())
    except Exception:
        return []


__all__ = [
    "status_from_pai",
    "next_version",
    "supersede_vigentes",
    "insert_pai",
    "persist_pai",
    "listar_pais_ativos_supabase",
]
