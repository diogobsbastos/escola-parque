"""
innova_bridge/repositories/students_repo.py
Adapter: alunos do Supabase BR -> formato esperado por pagina_alunos.

CONTRATO:
  listar_alunos_supabase()
      Devolve DataFrame com colunas:
          id, apelido, serie, turma, ppos, quest, cadastro
      Mesmo formato que backend_alunos.buscar_lista_alunos().

  obter_detalhes_aluno_supabase(student_code_ou_uuid)
      Devolve dict com:
          id, apelido, id_anon, serie, turma  (+ campos extras do Supabase)
      Mesmo formato que backend_alunos.obter_detalhes_aluno().

MAPEAMENTO DE CAMPOS (Supabase -> SQLite):
  students.code         -> id        (string "U1", "U2"...)
  students.full_name    -> apelido
  classes.grade_level   -> serie     (ex: "6_ano_ef" -> "6o ano")
  classes.name          -> turma     (ex: "1601")
  count(pais)           -> ppos
  count(questionnaires) -> quest
  students.created_at   -> cadastro  (DD/MM/YYYY)

CACHE:
  As leituras sao cacheadas com TTL curto (5s) via st.cache_data
  pra nao bombardear o Supabase a cada rerun do Streamlit.
"""

from __future__ import annotations

import time
from typing import Optional

import pandas as pd
import streamlit as st

from innova_bridge.db import run_async, get_pool


# ============================================================================
# Helpers internos
# ============================================================================

def _grade_level_humanizado(gl: str) -> str:
    """Converte grade_level do schema -> string amigavel.

    Ex.: '6_ano_ef' -> '6o ano EF', '7_ano_ef' -> '7o ano EF',
         '1_ano_em' -> '1o ano EM'.
    Se nao reconhecer, devolve o original.
    """
    if not gl:
        return "-"
    mapa = {
        "1_ano_ef": "1o ano EF", "2_ano_ef": "2o ano EF", "3_ano_ef": "3o ano EF",
        "4_ano_ef": "4o ano EF", "5_ano_ef": "5o ano EF", "6_ano_ef": "6o ano EF",
        "7_ano_ef": "7o ano EF", "8_ano_ef": "8o ano EF", "9_ano_ef": "9o ano EF",
        "1_ano_em": "1o ano EM", "2_ano_em": "2o ano EM", "3_ano_em": "3o ano EM",
    }
    return mapa.get(gl, gl)


def _formatar_data_br(dt) -> str:
    """Converte datetime/date -> 'DD/MM/AAAA'. Aceita None."""
    if dt is None:
        return "-"
    try:
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(dt)[:10]


# ============================================================================
# Queries assincronas (rodam via run_async)
# ============================================================================

async def _q_listar_alunos(pool, school_id: Optional[str] = None) -> list[dict]:
    """SELECT alunos com join nas counts de PAIs e questionarios.

    Inclui filtro opcional por school_id (defesa em profundidade — RLS
    tambem filtra, mas o handoff recomenda sempre passar explicito).
    """
    sql = """
        SELECT
            s.id::text             AS uuid,
            s.code                 AS code,
            s.full_name            AS full_name,
            s.created_at           AS created_at,
            s.archived_at          AS archived_at,
            c.name                 AS class_name,
            c.grade_level          AS grade_level,
            COALESCE(pais_cnt, 0)  AS ppos,
            COALESCE(quest_cnt, 0) AS quest
        FROM public.students s
        LEFT JOIN public.student_classes sc ON sc.student_id = s.id
        LEFT JOIN public.classes c          ON c.id          = sc.class_id
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS pais_cnt
            FROM public.pais p
            WHERE p.student_id = s.id
        ) px ON true
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS quest_cnt
            FROM public.questionnaires q
            WHERE q.student_id = s.id
        ) qx ON true
        WHERE s.archived_at IS NULL
    """
    params = []
    if school_id:
        sql += " AND s.school_id = $1"
        params.append(school_id)
    sql += " ORDER BY s.code"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def _q_obter_detalhes(pool, code: str, school_id: Optional[str] = None) -> Optional[dict]:
    """Busca um aluno pelo code (ex: 'U1'). Retorna dict ou None."""
    sql = """
        SELECT
            s.id::text             AS uuid,
            s.code                 AS code,
            s.full_name            AS full_name,
            s.birth_date           AS birth_date,
            s.created_at           AS created_at,
            c.name                 AS class_name,
            c.grade_level          AS grade_level,
            COALESCE(pais_cnt, 0)  AS ppos,
            COALESCE(quest_cnt, 0) AS quest
        FROM public.students s
        LEFT JOIN public.student_classes sc ON sc.student_id = s.id
        LEFT JOIN public.classes c          ON c.id          = sc.class_id
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS pais_cnt
            FROM public.pais p
            WHERE p.student_id = s.id
        ) px ON true
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS quest_cnt
            FROM public.questionnaires q
            WHERE q.student_id = s.id
        ) qx ON true
        WHERE s.code = $1
    """
    params = [code]
    if school_id:
        sql += " AND s.school_id = $2"
        params.append(school_id)
    sql += " LIMIT 1"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
    return dict(row) if row else None


# ============================================================================
# API publica — espelho do backend_alunos
# ============================================================================

@st.cache_data(ttl=5, show_spinner=False)
def listar_alunos_supabase() -> pd.DataFrame:
    """Devolve DataFrame no mesmo formato de backend_alunos.buscar_lista_alunos().

    Colunas (ordem fixa):
        id, apelido, serie, turma, ppos, quest, cadastro

    Onde:
      id      = students.code (string tipo "U1")
      apelido = students.full_name
      serie   = grade_level humanizado
      turma   = classes.name
      ppos    = count de PAIs do aluno
      quest   = count de questionnaires do aluno
      cadastro = data formatada DD/MM/YYYY
    """
    pool = run_async(get_pool())
    rows = run_async(_q_listar_alunos(pool, school_id=None))

    if not rows:
        # Devolve DataFrame vazio mas com schema correto (evita .empty quebrar)
        return pd.DataFrame(columns=["id", "apelido", "serie", "turma", "ppos", "quest", "cadastro"])

    df = pd.DataFrame([
        {
            "id":       r["code"] or "-",
            "apelido":  r["full_name"] or "-",
            "serie":    _grade_level_humanizado(r["grade_level"]),
            "turma":    r["class_name"] or "-",
            "ppos":     int(r["ppos"] or 0),
            "quest":    int(r["quest"] or 0),
            "cadastro": _formatar_data_br(r["created_at"]),
        }
        for r in rows
    ])
    return df


@st.cache_data(ttl=5, show_spinner=False)
def obter_detalhes_aluno_supabase(student_code: str) -> Optional[dict]:
    """Devolve dict no mesmo formato de backend_alunos.obter_detalhes_aluno().

    Campos garantidos: id, apelido, id_anon, serie, turma.
    Campos extras (vindos do Supabase): uuid, ppos, quest, birth_date, cadastro.
    """
    pool = run_async(get_pool())
    row = run_async(_q_obter_detalhes(pool, student_code, school_id=None))
    if not row:
        return None

    return {
        # ── Contrato 100% espelhado de backend_alunos.obter_detalhes_aluno ──
        "id":             row["code"],
        "apelido":        row["full_name"],
        "id_anon":        row["code"],  # no Innova V2 o code JA e anonimizado (U1, U2...)
        "serie":          _grade_level_humanizado(row["grade_level"]),
        "turma":          row["class_name"] or "-",
        "ppos_ativos":    int(row["ppos"] or 0),
        "questionarios":  int(row["quest"] or 0),
        # ── Campos EXTRAS especificos do Supabase (UI pode usar opcionalmente) ──
        "uuid":           row["uuid"],
        "birth_date":     row["birth_date"],
        "cadastro":       _formatar_data_br(row["created_at"]),
    }


def invalidar_cache() -> None:
    """Limpa o cache TTL — util apos clicar 'Recarregar'."""
    listar_alunos_supabase.clear()
    obter_detalhes_aluno_supabase.clear()
