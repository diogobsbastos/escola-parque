"""
innova_bridge/repositories/teachers_repo.py
Adapter: professores do Supabase BR -> formato esperado por pagina_professores.

DESCOBERTA ARQUITETURAL:
  O Supabase BR JA TEM o conceito de professor:
  - `users` (role='teacher' default) = identidade do professor
  - `class_teacher_subjects` = vinculo professor x turma x materia

  Logo, NAO criamos tabela nova. Lemos diretamente de users WHERE role='teacher'
  e enriquecemos com counts de class_teacher_subjects.

CONTRATO (espelho de backend_professores.buscar_lista_professores):
  listar_professores_supabase()
      DataFrame com colunas:
          id (uuid), apelido, email, materia, turmas, ativo, cadastro

  obter_detalhes_professor_supabase(uuid_ou_email)
      dict com identidade completa + lista de turmas + lista de materias.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from innova_bridge.db import run_async, get_pool


# ============================================================================
# Helpers
# ============================================================================

def _formatar_data_br(dt) -> str:
    if dt is None:
        return "-"
    try:
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(dt)[:10]


def _format_turmas(turmas: list[str]) -> str:
    """['1601', '1602'] -> '1601, 1602'."""
    if not turmas:
        return "-"
    return ", ".join(sorted(set([t for t in turmas if t])))


# ============================================================================
# Queries assincronas
# ============================================================================

async def _q_listar_professores(pool, school_id: Optional[str] = None) -> list[dict]:
    """SELECT users WHERE role='teacher' enriquecido com counts de turmas/materias."""
    sql = """
        SELECT
            u.id::text                                  AS uuid,
            u.email                                     AS email,
            u.full_name                                 AS full_name,
            u.role                                      AS role,
            u.active                                    AS active,
            u.created_at                                AS created_at,
            COALESCE(turmas_cnt, 0)                     AS n_turmas,
            COALESCE(materias_cnt, 0)                   AS n_materias,
            COALESCE(turmas_list, '{}')::text[]         AS turmas_list,
            COALESCE(materias_list, '{}')::text[]       AS materias_list
        FROM public.users u
        LEFT JOIN LATERAL (
            SELECT
                COUNT(DISTINCT cts.class_id)            AS turmas_cnt,
                COUNT(DISTINCT cts.subject_id)          AS materias_cnt,
                ARRAY_AGG(DISTINCT c.name) FILTER (WHERE c.name IS NOT NULL)
                                                        AS turmas_list,
                ARRAY_AGG(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL)
                                                        AS materias_list
            FROM public.class_teacher_subjects cts
            LEFT JOIN public.classes c  ON c.id  = cts.class_id
            LEFT JOIN public.subjects s ON s.id  = cts.subject_id
            WHERE cts.user_id = u.id
        ) cnts ON true
        WHERE u.role = 'teacher'
    """
    params = []
    if school_id:
        sql += " AND u.school_id = $1"
        params.append(school_id)
    sql += " ORDER BY u.full_name"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def _q_obter_detalhes_professor(pool, uuid_ou_email: str,
                                       school_id: Optional[str] = None) -> Optional[dict]:
    """Busca um professor pelo uuid OU email. Retorna dict ou None."""
    # Detecta se eh uuid (tem hifens) ou email
    if "@" in uuid_ou_email:
        where = "u.email = $1"
    else:
        where = "u.id = $1::uuid"

    sql = f"""
        SELECT
            u.id::text                                  AS uuid,
            u.email                                     AS email,
            u.full_name                                 AS full_name,
            u.role                                      AS role,
            u.active                                    AS active,
            u.created_at                                AS created_at,
            COALESCE(
                ARRAY_AGG(DISTINCT c.name) FILTER (WHERE c.name IS NOT NULL),
                '{{}}'
            )::text[]                                   AS turmas_list,
            COALESCE(
                ARRAY_AGG(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL),
                '{{}}'
            )::text[]                                   AS materias_list
        FROM public.users u
        LEFT JOIN public.class_teacher_subjects cts ON cts.user_id = u.id
        LEFT JOIN public.classes c  ON c.id  = cts.class_id
        LEFT JOIN public.subjects s ON s.id  = cts.subject_id
        WHERE u.role = 'teacher' AND {where}
        GROUP BY u.id
        LIMIT 1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, uuid_ou_email)
    return dict(row) if row else None


# ============================================================================
# API publica
# ============================================================================

@st.cache_data(ttl=5, show_spinner=False)
def listar_professores_supabase() -> pd.DataFrame:
    """Devolve DataFrame no mesmo formato que backend_professores.buscar_lista_professores().

    Colunas (ordem fixa):
        id (uuid), apelido, email, materia, turmas, ativo, cadastro
    """
    try:
        pool = run_async(get_pool())
        rows = run_async(_q_listar_professores(pool, school_id=None))
    except Exception as e:
        st.warning(f"Falha ao consultar Supabase (teachers): {e}")
        return pd.DataFrame(columns=["id", "apelido", "email", "materia", "turmas", "ativo", "cadastro"])

    if not rows:
        return pd.DataFrame(columns=["id", "apelido", "email", "materia", "turmas", "ativo", "cadastro"])

    df = pd.DataFrame([
        {
            "id":       r["uuid"],
            "apelido":  r["full_name"] or "-",
            "email":    r["email"] or "-",
            "materia":  _format_turmas(r.get("materias_list") or []),
            "turmas":   _format_turmas(r.get("turmas_list") or []),
            "ativo":    bool(r["active"]),
            "cadastro": _formatar_data_br(r["created_at"]),
        }
        for r in rows
    ])
    return df


def obter_detalhes_professor_supabase(uuid_ou_email: str) -> Optional[dict]:
    """Detalhes completos pra prontuario. None se nao encontrar."""
    try:
        pool = run_async(get_pool())
        return run_async(_q_obter_detalhes_professor(pool, uuid_ou_email, school_id=None))
    except Exception as e:
        st.warning(f"Falha ao buscar professor: {e}")
        return None


# ============================================================================
# Mutacao: UPDATE em public.users
# ============================================================================

async def _q_atualizar_professor(pool, uuid_str: str,
                                  full_name: Optional[str] = None,
                                  active: Optional[bool] = None) -> bool:
    """UPDATE public.users SET ... WHERE id = $1::uuid AND role='teacher'.

    CUIDADO: a coluna `email` NAO eh editavel via Streamlit pq esta vinculada
    a auth.users (gerenciado pelo Supabase Auth). Pra trocar email use o painel
    Auth do Supabase ou o React Innova V2 com permissoes apropriadas.

    Retorna True se a linha foi atualizada, False senao.
    """
    sets = []
    params = []
    idx = 2  # $1 e o uuid

    if full_name is not None:
        sets.append(f"full_name = ${idx}")
        params.append(full_name)
        idx += 1
    if active is not None:
        sets.append(f"active = ${idx}")
        params.append(active)
        idx += 1
    if not sets:
        return False

    sets.append("updated_at = now()")
    sql = f"""
        UPDATE public.users
           SET {", ".join(sets)}
         WHERE id = $1::uuid
           AND role = 'teacher'
    """
    async with pool.acquire() as conn:
        result = await conn.execute(sql, uuid_str, *params)
    # asyncpg devolve 'UPDATE N' como string
    try:
        rows = int(result.split()[-1])
    except Exception:
        rows = 0
    return rows > 0


def atualizar_professor_supabase(uuid_str: str,
                                  full_name: Optional[str] = None,
                                  active: Optional[bool] = None) -> bool:
    """API publica de UPDATE. Limpa o cache apos a operacao."""
    try:
        pool = run_async(get_pool())
        ok = run_async(_q_atualizar_professor(pool, uuid_str, full_name, active))
        if ok:
            invalidar_cache()
        return ok
    except Exception as e:
        st.warning(f"Falha ao atualizar professor: {e}")
        return False


# ============================================================================
# Listar escolas (pro dropdown de cadastro)
# ============================================================================

async def _q_listar_escolas(pool) -> list[dict]:
    sql = """
        SELECT id::text AS uuid, name
        FROM public.schools
        ORDER BY name
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
    return [dict(r) for r in rows]


def listar_escolas_supabase() -> list[dict]:
    """Retorna lista de escolas [{uuid, name}, ...] do Supabase BR."""
    try:
        pool = run_async(get_pool())
        return run_async(_q_listar_escolas(pool))
    except Exception as e:
        st.warning(f"Falha ao listar escolas: {e}")
        return []


# ============================================================================
# Cadastro via Supabase Auth Admin API
# ============================================================================

def criar_professor_supabase(email: str, password: str, full_name: str,
                              school_id: str) -> tuple[bool, str]:
    """Cria novo professor via /auth/v1/admin/users (Auth Admin API).

    O trigger `on_auth_user_created` insere automaticamente em public.users
    com role='teacher' (default) e school_id lido do raw_user_meta_data.

    Returns:
        (ok, mensagem)
    """
    import requests
    from innova_bridge.config import get_bd_ativo

    try:
        bd = get_bd_ativo()
    except Exception as e:
        return False, f"BD ativo nao acessivel: {e}"

    supabase_url = bd.get("supabase_url", "").rstrip("/")
    service_role = bd.get("service_role", "")
    if not supabase_url:
        return False, "supabase_url ausente no BD ativo."
    if not service_role:
        return False, "service_role ausente no BD ativo. Edite o BD no carrossel."

    endpoint = f"{supabase_url}/auth/v1/admin/users"
    headers = {
        "Authorization": f"Bearer {service_role}",
        "apikey": service_role,
        "Content-Type": "application/json",
    }
    payload = {
        "email": email.strip(),
        "password": password,
        "email_confirm": True,  # ja confirma email (sem precisar de link)
        "user_metadata": {
            "school_id": school_id,
            "full_name": full_name.strip(),
            "role": "teacher",
        },
        # Tambem manda no app_metadata pra trigger ter prioridade
        "app_metadata": {
            "school_id": school_id,
            "role": "teacher",
        },
    }

    try:
        r = requests.post(endpoint, json=payload, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        return False, f"Erro de rede: {e}"

    if r.status_code in (200, 201):
        invalidar_cache()
        try:
            user_data = r.json()
            uuid_novo = user_data.get("id", "?")
            return True, f"Professor criado. UUID: {uuid_novo[:8]}..."
        except Exception:
            return True, "Professor criado."

    # Erros
    try:
        msg = r.json().get("msg") or r.json().get("error_description") or r.text
    except Exception:
        msg = r.text[:200]
    return False, f"HTTP {r.status_code}: {msg}"


def resetar_senha_professor(email: str, redirect_to: str = "") -> tuple[bool, str]:
    """Dispara email de reset de senha via /auth/v1/recover.

    ATENCAO - DESIGN DECISION:
    Esta funcao NAO eh usada pela UI Streamlit por decisao arquitetural:
    o fluxo de "esqueci minha senha / primeiro acesso" eh responsabilidade
    EXCLUSIVA do frontend (React Innova V2), onde o proprio professor
    digita seu email e solicita o reset. O backend admin so cria o
    professor com senha demo.

    Mantida aqui como REFERENCIA pro frontend implementar a mesma chamada,
    e como helper opcional pra scripts de manutencao (ex: reset em massa).

    Args:
        email: email do professor cadastrado no auth.users
        redirect_to: URL pra onde redirecionar apos reset (opcional).
                     Default = pagina do Innova V2 lida do BD ativo, se houver.

    Returns:
        (ok, mensagem)
    """
    import requests
    from innova_bridge.config import get_bd_ativo

    try:
        bd = get_bd_ativo()
    except Exception as e:
        return False, f"BD ativo nao acessivel: {e}"

    supabase_url = bd.get("supabase_url", "").rstrip("/")
    anon_key = bd.get("anon_key", "") or bd.get("service_role", "")
    if not supabase_url:
        return False, "supabase_url ausente."
    if not anon_key:
        return False, "anon_key ausente no BD ativo."

    endpoint = f"{supabase_url}/auth/v1/recover"
    headers = {
        "apikey": anon_key,
        "Content-Type": "application/json",
    }
    payload = {"email": email.strip()}
    if redirect_to:
        payload["redirect_to"] = redirect_to

    try:
        r = requests.post(endpoint, json=payload, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        return False, f"Erro de rede: {e}"

    # Supabase devolve 200 mesmo se email nao existe (pra nao vazar existencia)
    if r.status_code in (200, 201):
        return True, f"Email de reset enviado para {email}."

    try:
        msg = r.json().get("msg") or r.json().get("error_description") or r.text
    except Exception:
        msg = r.text[:200]
    return False, f"HTTP {r.status_code}: {msg}"


def gerar_senha_temporaria(tamanho: int = 12) -> str:
    """Gera senha temporaria forte (letras + numeros + 1 simbolo)."""
    import secrets
    import string
    alfabeto = string.ascii_letters + string.digits
    senha = "".join(secrets.choice(alfabeto) for _ in range(tamanho - 1))
    senha += secrets.choice("!@#$%")
    return senha


def invalidar_cache() -> None:
    listar_professores_supabase.clear()
