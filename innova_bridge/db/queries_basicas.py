"""
innova_bridge/db/queries_basicas.py - Queries de validacao de conexao.

Sao queries de LEITURA pura, usadas pra provar que o pipeline
Python -> asyncpg -> Supabase BR esta funcional. F1 nao escreve nada.

Lista das 22 tabelas vem do SUPABASE_SCHEMA.md (Migracao BD/.../docs/).
"""

from __future__ import annotations

import time
from typing import Optional

import asyncpg

# As 22 tabelas + 1 cache, conforme SUPABASE_SCHEMA.md
# Ordenadas por dominio logico (Tenant -> Pedagogia -> Questionarios -> Provas -> Audit -> Config)
TABELAS_SCHEMA = (
    # Tenant & Identidade
    "schools",
    "users",
    "classes",
    "students",
    "student_classes",
    # Taxonomia Pedagogica
    "discipline_families",
    "subjects",
    "class_teacher_subjects",
    # Questionarios & PAIs
    "questionnaires",
    "questionnaire_sections",
    "questionnaire_field_responses",
    "questionnaire_tokens",
    "pais",
    "pai_reviews",
    # Provas & Adaptacoes
    "exams",
    "adapted_exams",
    "validations",
    # Observabilidade & Auditoria
    "agent_run_logs",
    "audit_log",
    # Pricing, Cache & Config
    "model_pricing",
    "agent_prompts",
    "adaptation_components_cache",
    "provider_keys",
    "system_settings",
)


# ============================================================================
# Queries individuais
# ============================================================================

async def selecionar_um(pool: asyncpg.Pool) -> tuple[int, int]:
    """SELECT 1 -- prova viva mais simples. Retorna (valor, latencia_ms)."""
    t0 = time.perf_counter()
    async with pool.acquire() as conn:
        valor = await conn.fetchval("SELECT 1")
    ms = int((time.perf_counter() - t0) * 1000)
    return valor, ms


async def obter_versao_pg(pool: asyncpg.Pool) -> tuple[str, int]:
    """SELECT version() -- mostra o build do PostgreSQL. Retorna (texto, ms)."""
    t0 = time.perf_counter()
    async with pool.acquire() as conn:
        v = await conn.fetchval("SELECT version()")
    ms = int((time.perf_counter() - t0) * 1000)
    return str(v), ms


async def contar_tabela(pool: asyncpg.Pool, tabela: str) -> tuple[Optional[int], int, Optional[str]]:
    """SELECT count(*) FROM public.<tabela> -- com whitelist contra SQL injection.

    Retorna (count, latencia_ms, erro_ou_None).
    Se tabela nao estiver na whitelist, devolve (None, 0, 'tabela nao permitida').
    Se a query falhar (RLS, tabela inexistente), devolve (None, ms, msg_erro).
    """
    if tabela not in TABELAS_SCHEMA:
        return None, 0, f"Tabela '{tabela}' nao esta na whitelist do schema."

    t0 = time.perf_counter()
    try:
        async with pool.acquire() as conn:
            c = await conn.fetchval(f"SELECT count(*) FROM public.{tabela}")
        ms = int((time.perf_counter() - t0) * 1000)
        return int(c), ms, None
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return None, ms, f"{type(e).__name__}: {str(e)[:100]}"


async def inventario_completo(pool: asyncpg.Pool) -> list[dict]:
    """Conta linhas de TODAS as 22 tabelas. Retorna lista de dicts:
        [{ tabela, count, ms, erro }]
    """
    resultado = []
    for tabela in TABELAS_SCHEMA:
        c, ms, erro = await contar_tabela(pool, tabela)
        resultado.append({
            "tabela": tabela,
            "count": c,
            "ms": ms,
            "erro": erro,
        })
    return resultado


async def listar_schools(pool: asyncpg.Pool, limit: int = 5) -> tuple[list[dict], int]:
    """SELECT id, name, slug FROM schools (a raiz da multi-tenancy)."""
    t0 = time.perf_counter()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, name, slug, created_at FROM public.schools ORDER BY created_at LIMIT $1",
            limit,
        )
    ms = int((time.perf_counter() - t0) * 1000)
    return [dict(r) for r in rows], ms


async def listar_students(pool: asyncpg.Pool, limit: int = 10) -> tuple[list[dict], int]:
    """SELECT id, code, full_name FROM students (pra ver o U1 do seed)."""
    t0 = time.perf_counter()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id::text, code, full_name, birth_date, archived_at, created_at
               FROM public.students
               WHERE archived_at IS NULL
               ORDER BY created_at
               LIMIT $1""",
            limit,
        )
    ms = int((time.perf_counter() - t0) * 1000)
    return [dict(r) for r in rows], ms
