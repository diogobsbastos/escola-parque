"""
pagina_home.py — Painel Inicial (Visao Geral) do Backend Central.

Resumo conciso de tudo: colegios, logins por papel, alunos, turmas, sedes,
PAIs ativos e custo de LLM do mes. Le o Postgres `innova` (VPS) via
innova_bridge. Roteador publico: render_pagina_home() (chamado pelo app.py).
"""
from __future__ import annotations

import streamlit as st

try:
    from innova_bridge.db import run_async, get_pool
    _DB_OK, _DB_ERR = True, ""
except Exception as e:  # pragma: no cover
    _DB_OK, _DB_ERR = False, f"{type(e).__name__}: {e}"

_CSS = """
<style>
.hm-card { border:1px solid #ececec; border-radius:14px; padding:18px 20px; background:#fff; }
.hm-card .v { font-size:2.0em; font-weight:800; line-height:1; color:#222; }
.hm-card .l { color:#777; font-size:0.76em; text-transform:uppercase; letter-spacing:0.5px; margin-top:8px; }
.hm-role { display:flex; justify-content:space-between; align-items:center; padding:8px 2px; border-bottom:1px solid #f1f1f1; font-size:0.95em; }
.hm-pill { display:inline-block; background:#eef3fb; color:#1f4e79; border-radius:10px; padding:1px 11px; font-weight:700; font-size:0.85em; }
</style>
"""

ROLE_LABEL = {
    "super_admin": "Plataforma (super_admin)", "admin": "Diretores / Adm do Colégio",
    "coordinator": "Coordenação", "teacher": "Professores", "aee": "Apoio (AEE)",
    "student": "Alunos (login)", "guardian": "Responsáveis",
}


async def _carregar(pool):
    g = {}
    g["colegios"] = await pool.fetchval("SELECT count(*) FROM schools")
    g["alunos"] = await pool.fetchval("SELECT count(*) FROM students WHERE archived_at IS NULL")
    g["turmas"] = await pool.fetchval("SELECT count(*) FROM classes")
    g["sedes"] = await pool.fetchval("SELECT count(*) FROM campuses")
    g["logins"] = await pool.fetchval("SELECT count(*) FROM users")
    g["pais_ativos"] = await pool.fetchval("SELECT count(*) FROM pais WHERE status='active'")
    g["por_papel"] = await pool.fetch("SELECT role::text AS role, count(*) AS n FROM users GROUP BY role")
    try:
        g["custo_mes"] = await pool.fetchval(
            "SELECT COALESCE(SUM(cost_brl),0) FROM agent_run_logs WHERE created_at >= date_trunc('month', now())"
        )
    except Exception:
        g["custo_mes"] = 0
    try:
        hb = await pool.fetchrow(
            "SELECT value->>'host' AS host, "
            "EXTRACT(EPOCH FROM (now() - (value->>'ts')::timestamptz)) AS idade "
            "FROM system_settings WHERE key='python_worker_heartbeat'"
        )
        g["online"] = bool(hb and hb["idade"] is not None and float(hb["idade"]) < 60)
        g["host"] = hb["host"] if hb else None
    except Exception:
        g["online"], g["host"] = None, None
    return g


def _card(col, valor, label):
    col.markdown(
        f"<div class='hm-card'><div class='v'>{valor}</div><div class='l'>{label}</div></div>",
        unsafe_allow_html=True,
    )


def render_pagina_home():
    st.markdown("# 🏠 Painel Inicial")
    st.caption("Visão geral, concisa, de toda a plataforma — colégios, pessoas, turmas e produção pedagógica.")

    if not _DB_OK:
        st.error(f"Sem conexão com o banco (innova_bridge): {_DB_ERR}")
        return
    try:
        pool = run_async(get_pool())
        g = run_async(_carregar(pool))
    except Exception as e:
        st.error(f"Falha ao ler o banco: {type(e).__name__} — {e}")
        return

    st.markdown(_CSS, unsafe_allow_html=True)
    papel = {r["role"]: r["n"] for r in g["por_papel"]}

    if g["online"]:
        st.success("🧠 Backend Central **Online**" + (f" · {g['host']}" if g["host"] else ""), icon="✅")
    elif g["online"] is False:
        st.warning("🧠 Backend Central **Offline** (worker parado).", icon="⚠️")

    st.markdown("### Números da plataforma")
    r1 = st.columns(4)
    _card(r1[0], g["colegios"], "Colégios")
    _card(r1[1], g["sedes"], "Sedes")
    _card(r1[2], g["turmas"], "Turmas")
    _card(r1[3], g["alunos"], "Alunos")

    st.markdown("<br>", unsafe_allow_html=True)
    r2 = st.columns(4)
    _card(r2[0], g["logins"], "Logins")
    _card(r2[1], papel.get("teacher", 0), "Professores")
    _card(r2[2], g["pais_ativos"], "PAIs ativos")
    _card(r2[3], f"R$ {float(g['custo_mes']):.2f}", "Custo LLM (mês)")

    st.markdown("### Logins por papel")
    c = st.columns(2)
    with c[0]:
        for role in ["super_admin", "admin", "coordinator", "teacher"]:
            st.markdown(
                f"<div class='hm-role'><span>{ROLE_LABEL.get(role, role)}</span>"
                f"<span class='hm-pill'>{papel.get(role, 0)}</span></div>",
                unsafe_allow_html=True,
            )
    with c[1]:
        for role in ["aee", "student", "guardian"]:
            st.markdown(
                f"<div class='hm-role'><span>{ROLE_LABEL.get(role, role)}</span>"
                f"<span class='hm-pill'>{papel.get(role, 0)}</span></div>",
                unsafe_allow_html=True,
            )

    st.divider()
    st.caption("Atalhos na barra lateral: **🏫 Colégios** (gestão por colégio, turmas e associações), **Área de Alunos**, **Professores**.")
