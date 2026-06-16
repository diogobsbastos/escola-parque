"""
pagina_colegios.py - Gestao por Colegio (F2) com a TEIA relacional.

Cada colegio e um AMBIENTE PROPRIO de gestao. Dentro dele, tudo amarrado:
  Colegio -> Sede (Unidade) -> Turma -> Alunos
  Professor <-> Materia <-> Turma <-> Colegio   (via class_teacher_subjects)

Filtros por Sede/Turma nas abas de Professores e Alunos. Visual estilizado
(tabelas HTML/CSS, lista -> detalhe com abas), igual a pagina de Professores.
Leitura ao vivo do Postgres innova (VPS) via innova_bridge.

Roteador publico: render_pagina_colegios()  (chamado pelo app.py).
Read-first: \"+ Novo Colegio\" ja grava; o CRUD com login (professor/aluno/
diretor via GoTrue Admin API) entra na proxima etapa (#9).
"""
from __future__ import annotations

from collections import defaultdict

import streamlit as st

try:
    from innova_bridge.db import run_async, get_pool
    _DB_OK, _DB_ERR = True, ""
except Exception as e:  # pragma: no cover
    _DB_OK, _DB_ERR = False, f"{type(e).__name__}: {e}"


# ============================================================================
# Estilo (prefixo .col-)
# ============================================================================
_CSS = """
<style>
.col-header { font-weight:700; font-size:0.78em; color:#555; text-transform:uppercase;
  letter-spacing:0.5px; border-bottom:2px solid #999; padding:4px 4px 8px; }
.col-cell { padding:9px 4px; font-size:0.92em; border-bottom:1px solid #ececec;
  min-height:40px; display:flex; align-items:center; flex-wrap:wrap; gap:4px; }
.col-cell-alt { background:#fafafa; }
.col-name { font-weight:600; }
.col-mono { font-family:"Courier New",monospace; font-size:0.8em; color:#8a8a8a; }
.col-badge { display:inline-block; padding:2px 9px; border-radius:11px; font-size:0.78em; font-weight:600; }
.col-b-super { background:#efe7fb; color:#5b2a9e; }
.col-b-admin { background:#fdeede; color:#9a5b07; }
.col-b-coord { background:#e7f0fb; color:#1f4e79; }
.col-b-teacher { background:#e8f5e9; color:#1e7e34; }
.col-b-aee { background:#fdeef3; color:#a13b69; }
.col-b-student { background:#eef3fb; color:#33507a; }
.col-b-guardian { background:#f1f1f1; color:#666; }
.col-b-on { background:#e8f5e9; color:#1e7e34; }
.col-b-off { background:#f5f5f5; color:#999; }
.col-b-mat { background:#eef3fb; color:#1f4e79; }
.col-b-turma { background:#f0ecfb; color:#5b3aa0; }
.col-b-reg { background:#fff3e0; color:#9a5b07; }
.col-kpi { border:1px solid #eee; border-radius:12px; padding:14px 16px; background:#fff; text-align:center; }
.col-kpi b { font-size:1.6em; }
.col-kpi span { color:#777; font-size:0.78em; text-transform:uppercase; letter-spacing:0.4px; }
.col-muted { color:#aaa; }
</style>
"""

_ROLE_BADGE = {
    "super_admin": ("col-b-super", "Plataforma"),
    "admin": ("col-b-admin", "Diretor / Adm"),
    "coordinator": ("col-b-coord", "Coordenacao"),
    "teacher": ("col-b-teacher", "Professor"),
    "aee": ("col-b-aee", "Apoio (AEE)"),
    "student": ("col-b-student", "Aluno"),
    "guardian": ("col-b-guardian", "Responsavel"),
}


def _badge_papel(role):
    cls, lbl = _ROLE_BADGE.get(role, ("col-b-guardian", role))
    return f"<span class='col-badge {cls}'>{lbl}</span>"


def _badge_ativo(ativo):
    return ("<span class='col-badge col-b-on'>ATIVO</span>" if ativo
            else "<span class='col-badge col-b-off'>INATIVO</span>")


def _badges(items, cls):
    if not items:
        return "<span class='col-muted'>-</span>"
    return " ".join(f"<span class='col-badge {cls}'>{x}</span>" for x in items)


def _tabela(rows, colunas, vazio="Nada por aqui ainda."):
    if not rows:
        st.caption(vazio)
        return
    larguras = [c[2] for c in colunas]
    with st.container(border=True):
        hcols = st.columns(larguras)
        for col, (label, _, _) in zip(hcols, colunas):
            col.markdown(f"<div class='col-header'>{label}</div>", unsafe_allow_html=True)
        for i, row in enumerate(rows):
            cells = st.columns(larguras)
            klass = "col-cell" + (" col-cell-alt" if i % 2 else "")
            for cell, (_, fn, _) in zip(cells, colunas):
                cell.markdown(f"<div class='{klass}'>{fn(row)}</div>", unsafe_allow_html=True)


# ============================================================================
# Dados (com a teia relacional)
# ============================================================================
async def _carregar(pool):
    schools = await pool.fetch("SELECT id, name, slug FROM schools ORDER BY name")
    users = await pool.fetch(
        "SELECT id, school_id, role::text AS role, email, full_name, active FROM users ORDER BY full_name"
    )
    students = await pool.fetch(
        "SELECT id, school_id, code, full_name FROM students WHERE archived_at IS NULL ORDER BY full_name"
    )
    campuses = await pool.fetch(
        "SELECT id, school_id, name, city, state, is_active FROM campuses ORDER BY name"
    )
    classes = await pool.fetch(
        "SELECT id, school_id, name, grade_level, year, campus_id FROM classes ORDER BY name"
    )
    cts = await pool.fetch(
        "SELECT cts.user_id, cts.class_id, cts.is_homeroom, "
        "       s.name AS subject, c.name AS turma, c.campus_id, c.school_id "
        "FROM class_teacher_subjects cts "
        "JOIN subjects s ON s.id = cts.subject_id "
        "JOIN classes c ON c.id = cts.class_id"
    )
    scl = await pool.fetch(
        "SELECT sc.student_id, c.id AS class_id, c.name AS turma, c.campus_id, c.school_id "
        "FROM student_classes sc JOIN classes c ON c.id = sc.class_id"
    )
    return schools, users, students, campuses, classes, cts, scl


async def _criar_colegio(pool, name, slug):
    return await pool.execute("INSERT INTO schools (name, slug) VALUES ($1, $2)", name, slug)


def _idx(rows, key="school_id"):
    d = defaultdict(list)
    for r in rows:
        d[r[key]].append(r)
    return d


# ============================================================================
# Modal: novo colegio
# ============================================================================
@st.dialog("Novo Colegio")
def _modal_novo_colegio(pool):
    st.caption("Cria um novo colegio (tenant). Depois voce cadastra sedes, diretoria, professores, turmas e alunos dentro dele.")
    nome = st.text_input("Nome do colegio *", placeholder="Ex.: Colegio Inovacao")
    slug = st.text_input("Slug (identificador) *", placeholder="colegio-inovacao",
                         help="Curto, sem espacos/acentos. Usado internamente.")
    if st.button("Criar colegio", type="primary", use_container_width=True):
        n, s = nome.strip(), slug.strip().lower().replace(" ", "-")
        if not n or not s:
            st.error("Nome e slug sao obrigatorios.")
            return
        try:
            run_async(_criar_colegio(pool, n, s))
            st.success(f"Colegio '{n}' criado.")
            st.balloons()
            st.rerun()
        except Exception as e:
            st.error(f"Falha ao criar: {type(e).__name__} - {e}")


# ============================================================================
# Lista de colegios
# ============================================================================
def _render_lista(schools, u_idx, st_idx, cp_idx, cl_idx, pool):
    col_t, col_btn = st.columns([4, 1.2])
    with col_t:
        st.title("\U0001F3EB Colegios")
        st.caption("Cada colegio e um ambiente proprio de gestao. Clique em **Gerir** para entrar e administrar toda a infra dele.")
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("+ Novo Colegio", type="primary", use_container_width=True):
            _modal_novo_colegio(pool)

    st.markdown(_CSS, unsafe_allow_html=True)

    def cnt(sid, papel):
        return sum(1 for u in u_idx.get(sid, []) if u["role"] == papel)

    colunas = [
        ("Colegio", lambda s: f"<span class='col-name'>{s['name']}</span> <span class='col-mono'>{s['slug']}</span>", 2.4),
        ("Diretoria", lambda s: str(cnt(s["id"], "admin") + cnt(s["id"], "coordinator")), 0.9),
        ("Profs", lambda s: str(cnt(s["id"], "teacher")), 0.7),
        ("AEE", lambda s: str(cnt(s["id"], "aee")), 0.6),
        ("Alunos", lambda s: str(len(st_idx.get(s["id"], []))), 0.8),
        ("Turmas", lambda s: str(len(cl_idx.get(s["id"], []))), 0.8),
        ("Sedes", lambda s: str(len(cp_idx.get(s["id"], []))), 0.7),
        ("", None, 0.9),
    ]
    larguras = [c[2] for c in colunas]
    with st.container(border=True):
        hcols = st.columns(larguras)
        for col, (label, _, _) in zip(hcols, colunas):
            col.markdown(f"<div class='col-header'>{label}</div>", unsafe_allow_html=True)
        for i, s in enumerate(schools):
            cells = st.columns(larguras)
            klass = "col-cell" + (" col-cell-alt" if i % 2 else "")
            for cell, (_, fn, _) in zip(cells[:-1], colunas[:-1]):
                cell.markdown(f"<div class='{klass}'>{fn(s)}</div>", unsafe_allow_html=True)
            with cells[-1]:
                if st.button("Gerir →", key=f"gerir_{s['id']}", use_container_width=True):
                    st.session_state["colegio_em_gestao"] = str(s["id"])
                    st.rerun()


# ============================================================================
# Ambiente do colegio (detalhe com abas + filtros + teia)
# ============================================================================
def _render_gestao(school, us, sts, cps, cls, cts, scl):
    sid = school["id"]
    col_back, col_tit = st.columns([1, 5])
    with col_back:
        if st.button("← Voltar", use_container_width=True):
            st.session_state["colegio_em_gestao"] = None
            st.rerun()
    with col_tit:
        st.markdown(f"### \U0001F3EB {school['name']} <span class='col-mono'>{school['slug']}</span>", unsafe_allow_html=True)

    st.markdown(_CSS, unsafe_allow_html=True)

    campus_name = {c["id"]: c["name"] for c in cps}
    by_role = defaultdict(list)
    for u in us:
        by_role[u["role"]].append(u)

    prof_mat, prof_turmas, prof_reg, prof_campi = defaultdict(set), defaultdict(set), defaultdict(bool), defaultdict(set)
    for r in cts:
        if r["school_id"] != sid:
            continue
        prof_mat[r["user_id"]].add(r["subject"])
        prof_turmas[r["user_id"]].add(r["turma"])
        if r["is_homeroom"]:
            prof_reg[r["user_id"]] = True
        if r["campus_id"]:
            prof_campi[r["user_id"]].add(r["campus_id"])

    stu_turmas, stu_campi = defaultdict(set), defaultdict(set)
    for r in scl:
        if r["school_id"] != sid:
            continue
        stu_turmas[r["student_id"]].add(r["turma"])
        if r["campus_id"]:
            stu_campi[r["student_id"]].add(r["campus_id"])

    k = st.columns(5)
    for col, (lbl, val) in zip(k, [
        ("Diretoria", len(by_role.get("admin", [])) + len(by_role.get("coordinator", []))),
        ("Professores", len(by_role.get("teacher", []))),
        ("Apoio (AEE)", len(by_role.get("aee", []))),
        ("Alunos", len(sts)),
        ("Turmas", len(cls)),
    ]):
        col.markdown(f"<div class='col-kpi'><b>{val}</b><br><span>{lbl}</span></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    fc1, fc2, _ = st.columns([2, 2, 4])
    sede_opts = ["Todas as unidades"] + [c["name"] for c in cps]
    turma_opts = ["Todas as turmas"] + [c["name"] for c in cls]
    sede_sel = fc1.selectbox("Unidade (sede)", sede_opts, key=f"f_sede_{sid}")
    turma_sel = fc2.selectbox("Turma", turma_opts, key=f"f_turma_{sid}")
    sede_id = next((c["id"] for c in cps if c["name"] == sede_sel), None)

    tabs = st.tabs(["\U0001F464 Diretoria & Apoio", "\U0001F468‍\U0001F3EB Professores", "\U0001F393 Turmas", "\U0001F9D1‍\U0001F393 Alunos", "\U0001F3E2 Sedes"])

    col_user = [
        ("Papel", lambda u: _badge_papel(u["role"]), 1.0),
        ("Nome", lambda u: f"<span class='col-name'>{u['full_name']}</span>", 1.6),
        ("E-mail", lambda u: f"<span style='color:#666;font-size:0.85em'>{u['email']}</span>", 1.8),
        ("Status", lambda u: _badge_ativo(u["active"]), 0.7),
    ]

    with tabs[0]:
        st.caption("Diretor (admin), coordenacao e apoio (AEE) deste colegio.")
        _tabela(by_role.get("admin", []) + by_role.get("coordinator", []) + by_role.get("aee", []),
                col_user, vazio="Sem diretoria/apoio cadastrados ainda.")
        st.button("+ Novo Diretor / Coord. / Apoio", disabled=True, help="Cadastro com login chega na proxima atualizacao (#9).")

    with tabs[1]:
        st.caption("Corpo docente - com **materias** e **turmas** amarradas (a teia).")
        profs = list(by_role.get("teacher", []))
        if sede_id is not None:
            profs = [u for u in profs if sede_id in prof_campi.get(u["id"], set())]
        if turma_sel != "Todas as turmas":
            profs = [u for u in profs if turma_sel in prof_turmas.get(u["id"], set())]
        col_prof = [
            ("Professor", lambda u: f"<span class='col-name'>{u['full_name']}</span>"
                + (" <span class='col-badge col-b-reg'>REGENTE</span>" if prof_reg.get(u["id"]) else ""), 1.7),
            ("Materias", lambda u: _badges(sorted(prof_mat.get(u["id"], set())), "col-b-mat"), 1.8),
            ("Turmas", lambda u: _badges(sorted(prof_turmas.get(u["id"], set())), "col-b-turma"), 1.6),
            ("Status", lambda u: _badge_ativo(u["active"]), 0.7),
        ]
        _tabela(profs, col_prof, vazio="Nenhum professor (com os filtros atuais).")
        st.button("+ Novo Professor", disabled=True, help="Cadastro com login (GoTrue Admin API) chega na proxima atualizacao (#9).")

    with tabs[2]:
        st.caption("Turmas -> unidade (sede). Filtro de turma/unidade aplicado.")
        turmas = list(cls)
        if sede_id is not None:
            turmas = [c for c in turmas if c["campus_id"] == sede_id]
        if turma_sel != "Todas as turmas":
            turmas = [c for c in turmas if c["name"] == turma_sel]
        alunos_por_turma = defaultdict(int)
        for r in scl:
            if r["school_id"] == sid:
                alunos_por_turma[r["turma"]] += 1
        col_turma = [
            ("Turma", lambda c: f"<span class='col-name'>{c['name']}</span>", 1.0),
            ("Serie", lambda c: c["grade_level"], 1.2),
            ("Ano", lambda c: str(c["year"]), 0.6),
            ("Unidade", lambda c: campus_name.get(c["campus_id"], "<span class='col-muted'>- sem sede -</span>"), 1.4),
            ("Alunos", lambda c: str(alunos_por_turma.get(c["name"], 0)), 0.7),
        ]
        _tabela(turmas, col_turma, vazio="Nenhuma turma (com os filtros atuais).")
        st.button("+ Nova Turma", key="nova_turma", disabled=True, help="Chega na proxima atualizacao (#9).")

    with tabs[3]:
        alunos = list(sts)
        if sede_id is not None:
            alunos = [a for a in alunos if sede_id in stu_campi.get(a["id"], set())]
        if turma_sel != "Todas as turmas":
            alunos = [a for a in alunos if turma_sel in stu_turmas.get(a["id"], set())]
        st.caption(f"{len(alunos)} aluno(s) - com a **turma** amarrada.")
        col_aluno = [
            ("Matricula", lambda a: f"<span class='col-mono'>{a['code']}</span>", 1.0),
            ("Aluno", lambda a: f"<span class='col-name'>{a['full_name']}</span>", 2.0),
            ("Turma(s)", lambda a: _badges(sorted(stu_turmas.get(a["id"], set())), "col-b-turma"), 1.4),
            ("Unidade(s)", lambda a: _badges(sorted(campus_name.get(cid, "?") for cid in stu_campi.get(a["id"], set())), "col-b-coord"), 1.2),
        ]
        _tabela(alunos, col_aluno, vazio="Nenhum aluno (com os filtros atuais).")
        st.button("+ Novo Aluno", key="novo_aluno", disabled=True, help="Chega na proxima atualizacao (#9).")

    with tabs[4]:
        st.caption("Sedes (unidades) deste colegio.")
        col_sede = [
            ("Sede", lambda c: f"<span class='col-name'>{c['name']}</span>", 1.6),
            ("Cidade", lambda c: c["city"] or "-", 1.2),
            ("UF", lambda c: c["state"] or "-", 0.5),
            ("Status", lambda c: _badge_ativo(c["is_active"]), 0.7),
        ]
        _tabela(cps, col_sede, vazio="Sem sedes cadastradas ainda.")
        st.button("+ Nova Sede", key="nova_sede", disabled=True, help="Chega na proxima atualizacao (#9).")


# ============================================================================
# Roteador publico
# ============================================================================
def render_pagina_colegios():
    st.session_state.setdefault("colegio_em_gestao", None)

    if not _DB_OK:
        st.title("\U0001F3EB Colegios")
        st.error(f"Sem conexao com o banco (innova_bridge): {_DB_ERR}")
        return
    try:
        pool = run_async(get_pool())
        schools, users, students, campuses, classes, cts, scl = run_async(_carregar(pool))
    except Exception as e:
        st.title("\U0001F3EB Colegios")
        st.error(f"Falha ao ler o banco: {type(e).__name__} - {e}")
        return

    u_idx, st_idx, cp_idx, cl_idx = _idx(users), _idx(students), _idx(campuses), _idx(classes)

    sel = st.session_state.get("colegio_em_gestao")
    if sel:
        school = next((s for s in schools if str(s["id"]) == str(sel)), None)
        if not school:
            st.session_state["colegio_em_gestao"] = None
            st.rerun()
            return
        sid = school["id"]
        _render_gestao(school, u_idx.get(sid, []), st_idx.get(sid, []),
                       cp_idx.get(sid, []), cl_idx.get(sid, []), cts, scl)
    else:
        _render_lista(schools, u_idx, st_idx, cp_idx, cl_idx, pool)
