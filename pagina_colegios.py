"""
pagina_colegios.py - Gestao por Colegio (F2) com a TEIA relacional VIVA.

Cada colegio e um AMBIENTE PROPRIO de gestao, com CRUD e associacoes:
  Colegio -> Sede (Unidade) -> Turma -> Alunos
  Professor <-> Materia <-> Turma <-> Colegio   (class_teacher_subjects)

Funcoes:
  - Editar colegio; criar Sede; criar Turma (vinculada a sede).
  - Area da Turma: matricular aluno (student_classes) e vincular professor
    a uma materia + regente (class_teacher_subjects).
  - Filtros por Sede/Turma; tudo derivado das associacoes.

Visual estilizado (tabelas HTML/CSS), igual a pagina de Professores.
Leitura/escrita no Postgres innova (VPS) via innova_bridge.
Roteador publico: render_pagina_colegios()  (chamado pelo app.py).
"""
from __future__ import annotations

from collections import defaultdict

import streamlit as st

try:
    from innova_bridge.db import run_async, get_pool
    _DB_OK, _DB_ERR = True, ""
except Exception as e:  # pragma: no cover
    _DB_OK, _DB_ERR = False, f"{type(e).__name__}: {e}"


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
.col-b-admin { background:#fdeede; color:#9a5b07; }
.col-b-coord { background:#e7f0fb; color:#1f4e79; }
.col-b-teacher { background:#e8f5e9; color:#1e7e34; }
.col-b-aee { background:#fdeef3; color:#a13b69; }
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
    "admin": ("col-b-admin", "Diretor / Adm"),
    "coordinator": ("col-b-coord", "Coordenacao"),
    "teacher": ("col-b-teacher", "Professor"),
    "aee": ("col-b-aee", "Apoio (AEE)"),
}


def _badge_papel(role):
    cls, lbl = _ROLE_BADGE.get(role, ("col-b-coord", role))
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
    subjects = await pool.fetch("SELECT id, name FROM subjects ORDER BY name")
    cts = await pool.fetch(
        "SELECT cts.user_id, cts.class_id, cts.is_homeroom, cts.subject_id, "
        "       s.name AS subject, c.name AS turma, c.campus_id, c.school_id "
        "FROM class_teacher_subjects cts "
        "JOIN subjects s ON s.id = cts.subject_id JOIN classes c ON c.id = cts.class_id"
    )
    scl = await pool.fetch(
        "SELECT sc.student_id, c.id AS class_id, c.name AS turma, c.campus_id, c.school_id "
        "FROM student_classes sc JOIN classes c ON c.id = sc.class_id"
    )
    return schools, users, students, campuses, classes, subjects, cts, scl


async def _exec(pool, sql, *args):
    return await pool.execute(sql, *args)


@st.dialog("Novo Colegio")
def _modal_novo_colegio(pool):
    st.caption("Cria um novo colegio (tenant).")
    nome = st.text_input("Nome do colegio *", placeholder="Ex.: Colegio Inovacao")
    slug = st.text_input("Slug *", placeholder="colegio-inovacao", help="Curto, sem espacos/acentos.")
    if st.button("Criar colegio", type="primary", use_container_width=True):
        n, s = nome.strip(), slug.strip().lower().replace(" ", "-")
        if not n or not s:
            st.error("Nome e slug sao obrigatorios."); return
        try:
            run_async(_exec(pool, "INSERT INTO schools (name, slug) VALUES ($1,$2)", n, s))
            st.success("Colegio criado."); st.rerun()
        except Exception as e:
            st.error(f"Falha: {type(e).__name__} - {e}")


@st.dialog("Editar Colegio")
def _modal_editar_colegio(pool, school):
    nome = st.text_input("Nome", value=school["name"])
    slug = st.text_input("Slug", value=school["slug"])
    if st.button("Salvar", type="primary", use_container_width=True):
        try:
            run_async(_exec(pool, "UPDATE schools SET name=$1, slug=$2 WHERE id=$3",
                            nome.strip(), slug.strip().lower().replace(" ", "-"), school["id"]))
            st.success("Atualizado."); st.rerun()
        except Exception as e:
            st.error(f"Falha: {type(e).__name__} - {e}")


@st.dialog("Nova Sede (Unidade)")
def _modal_nova_sede(pool, school_id):
    st.caption("Unidade fisica do colegio. (No frontend o CEP puxa o endereco; aqui e manual.)")
    nome = st.text_input("Nome da sede *", placeholder="Ex.: Unidade Centro")
    c1, c2 = st.columns(2)
    cnpj = c1.text_input("CNPJ")
    tel = c2.text_input("Telefone de contato")
    cep = c1.text_input("CEP")
    cidade = c2.text_input("Cidade")
    uf = c1.text_input("UF", max_chars=2)
    if st.button("Criar sede", type="primary", use_container_width=True):
        if not nome.strip():
            st.error("Nome e obrigatorio."); return
        try:
            run_async(_exec(pool,
                "INSERT INTO campuses (school_id, name, cnpj, contact_phone, cep, city, state) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                school_id, nome.strip(), cnpj.strip() or None, tel.strip() or None,
                cep.strip() or None, cidade.strip() or None, (uf.strip().upper() or None)))
            st.success("Sede criada."); st.rerun()
        except Exception as e:
            st.error(f"Falha: {type(e).__name__} - {e}")


@st.dialog("Nova Turma")
def _modal_nova_turma(pool, school_id, campuses):
    nome = st.text_input("Nome da turma *", placeholder="Ex.: 1601")
    c1, c2 = st.columns(2)
    serie = c1.text_input("Serie *", placeholder="6_ano_ef")
    ano = c2.number_input("Ano *", min_value=2024, max_value=2035, value=2026, step=1)
    sede_nome = "- sem sede -"
    if campuses:
        sede_nome = st.selectbox("Unidade (sede)", ["- sem sede -"] + [c["name"] for c in campuses])
    if st.button("Criar turma", type="primary", use_container_width=True):
        if not nome.strip() or not serie.strip():
            st.error("Nome e serie sao obrigatorios."); return
        campus_id = next((c["id"] for c in campuses if c["name"] == sede_nome), None)
        try:
            run_async(_exec(pool,
                "INSERT INTO classes (school_id, name, grade_level, year, campus_id) VALUES ($1,$2,$3,$4,$5)",
                school_id, nome.strip(), serie.strip(), int(ano), campus_id))
            st.success("Turma criada."); st.rerun()
        except Exception as e:
            st.error(f"Falha: {type(e).__name__} - {e}")


@st.dialog("Matricular aluno na turma")
def _modal_matricular(pool, class_id, disponiveis):
    if not disponiveis:
        st.info("Todos os alunos do colegio ja estao nesta turma (ou nao ha alunos)."); return
    opt = {f"{a['full_name']} ({a['code']})": a["id"] for a in disponiveis}
    sel = st.multiselect("Alunos a matricular", list(opt.keys()))
    if st.button("Matricular", type="primary", use_container_width=True):
        if not sel:
            st.error("Selecione ao menos um aluno."); return
        try:
            for nome in sel:
                run_async(_exec(pool,
                    "INSERT INTO student_classes (student_id, class_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    opt[nome], class_id))
            st.success(f"{len(sel)} aluno(s) matriculado(s)."); st.rerun()
        except Exception as e:
            st.error(f"Falha: {type(e).__name__} - {e}")


@st.dialog("Vincular professor a turma")
def _modal_vincular_prof(pool, class_id, professores, subjects):
    if not professores:
        st.info("Nenhum professor neste colegio. Cadastre professores primeiro."); return
    if not subjects:
        st.info("Nenhuma materia cadastrada (tabela subjects)."); return
    opt_p = {f"{p['full_name']} ({p['email']})": p["id"] for p in professores}
    opt_s = {s["name"]: s["id"] for s in subjects}
    prof = st.selectbox("Professor", list(opt_p.keys()))
    mat = st.selectbox("Materia", list(opt_s.keys()))
    regente = st.toggle("E regente (homeroom) desta turma?", value=False)
    if st.button("Vincular", type="primary", use_container_width=True):
        try:
            run_async(_exec(pool,
                "INSERT INTO class_teacher_subjects (class_id, user_id, subject_id, is_homeroom) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                class_id, opt_p[prof], opt_s[mat], bool(regente)))
            st.success("Professor vinculado."); st.rerun()
        except Exception as e:
            st.error(f"Falha: {type(e).__name__} - {e}")


def _render_lista(schools, u_idx, st_idx, cp_idx, cl_idx, pool):
    col_t, col_btn = st.columns([4, 1.2])
    with col_t:
        st.title("\U0001F3EB Colegios")
        st.caption("Cada colegio e um ambiente proprio de gestao. Clique em **Gerir** para entrar.")
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


def _render_area_turma(pool, turma, school, school_students, school_teachers, subjects, scl, cts, campus_name):
    cid = turma["id"]
    cb, ct = st.columns([1, 5])
    with cb:
        if st.button("← Voltar ao colegio", use_container_width=True):
            st.session_state["turma_em_gestao"] = None
            st.rerun()
    with ct:
        sede = campus_name.get(turma["campus_id"], "sem sede")
        st.markdown(f"### \U0001F393 Turma {turma['name']} - {turma['grade_level']} - {turma['year']} "
                    f"<span class='col-mono'>{sede}</span>", unsafe_allow_html=True)
    st.markdown(_CSS, unsafe_allow_html=True)

    alunos_ids = [r["student_id"] for r in scl if r["class_id"] == cid]
    alunos = [a for a in school_students if a["id"] in alunos_ids]
    profs_links = [r for r in cts if r["class_id"] == cid]

    k = st.columns(3)
    k[0].markdown(f"<div class='col-kpi'><b>{len(alunos)}</b><br><span>Alunos</span></div>", unsafe_allow_html=True)
    k[1].markdown(f"<div class='col-kpi'><b>{len(set(p['user_id'] for p in profs_links))}</b><br><span>Professores</span></div>", unsafe_allow_html=True)
    n_reg = sum(1 for p in profs_links if p["is_homeroom"])
    k[2].markdown(f"<div class='col-kpi'><b>{n_reg}</b><br><span>Regentes</span></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    ca, cp = st.tabs(["\U0001F9D1‍\U0001F393 Alunos da turma", "\U0001F468‍\U0001F3EB Professores da turma"])

    with ca:
        topo = st.columns([4, 1.3])
        topo[0].caption("Alunos matriculados nesta turma.")
        if topo[1].button("+ Matricular aluno", use_container_width=True, type="primary"):
            disponiveis = [a for a in school_students if a["id"] not in alunos_ids]
            _modal_matricular(pool, cid, disponiveis)
        _tabela(alunos, [
            ("Matricula", lambda a: f"<span class='col-mono'>{a['code']}</span>", 1.0),
            ("Aluno", lambda a: f"<span class='col-name'>{a['full_name']}</span>", 3.0),
        ], vazio="Nenhum aluno matriculado ainda. Clique em **+ Matricular aluno**.")

    with cp:
        topo = st.columns([4, 1.3])
        topo[0].caption("Professores vinculados (materia + regente).")
        if topo[1].button("+ Vincular professor", use_container_width=True, type="primary"):
            _modal_vincular_prof(pool, cid, school_teachers, subjects)
        nome_prof = {t["id"]: t["full_name"] for t in school_teachers}
        _tabela(profs_links, [
            ("Professor", lambda r: f"<span class='col-name'>{nome_prof.get(r['user_id'], '?')}</span>"
                + (" <span class='col-badge col-b-reg'>REGENTE</span>" if r["is_homeroom"] else ""), 2.2),
            ("Materia", lambda r: f"<span class='col-badge col-b-mat'>{r['subject']}</span>", 1.6),
        ], vazio="Nenhum professor vinculado ainda. Clique em **+ Vincular professor**.")


def _render_gestao(pool, school, us, sts, cps, cls, subjects, cts, scl):
    sid = school["id"]
    cb, ct, ce = st.columns([1, 4, 1.2])
    with cb:
        if st.button("← Voltar", use_container_width=True):
            st.session_state["colegio_em_gestao"] = None
            st.rerun()
    with ct:
        st.markdown(f"### \U0001F3EB {school['name']} <span class='col-mono'>{school['slug']}</span>", unsafe_allow_html=True)
    with ce:
        if st.button("✏️ Editar colegio", use_container_width=True):
            _modal_editar_colegio(pool, school)

    st.markdown(_CSS, unsafe_allow_html=True)

    campus_name = {c["id"]: c["name"] for c in cps}
    by_role = defaultdict(list)
    for u in us:
        by_role[u["role"]].append(u)

    prof_mat, prof_turmas, prof_reg, prof_campi = defaultdict(set), defaultdict(set), defaultdict(bool), defaultdict(set)
    for r in cts:
        if r["school_id"] != sid:
            continue
        prof_mat[r["user_id"]].add(r["subject"]); prof_turmas[r["user_id"]].add(r["turma"])
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
        ("Alunos", len(sts)), ("Turmas", len(cls)),
    ]):
        col.markdown(f"<div class='col-kpi'><b>{val}</b><br><span>{lbl}</span></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    fc1, fc2, _ = st.columns([2, 2, 4])
    sede_sel = fc1.selectbox("Unidade (sede)", ["Todas as unidades"] + [c["name"] for c in cps], key=f"f_sede_{sid}")
    turma_sel = fc2.selectbox("Turma", ["Todas as turmas"] + [c["name"] for c in cls], key=f"f_turma_{sid}")
    sede_id = next((c["id"] for c in cps if c["name"] == sede_sel), None)

    tabs = st.tabs(["\U0001F464 Diretoria & Apoio", "\U0001F468‍\U0001F3EB Professores", "\U0001F393 Turmas", "\U0001F9D1‍\U0001F393 Alunos", "\U0001F3E2 Sedes"])

    col_user = [
        ("Papel", lambda u: _badge_papel(u["role"]), 1.0),
        ("Nome", lambda u: f"<span class='col-name'>{u['full_name']}</span>", 1.6),
        ("E-mail", lambda u: f"<span style='color:#666;font-size:0.85em'>{u['email']}</span>", 1.8),
        ("Status", lambda u: _badge_ativo(u["active"]), 0.7),
    ]

    with tabs[0]:
        st.caption("Diretor (admin), coordenacao e apoio (AEE).")
        _tabela(by_role.get("admin", []) + by_role.get("coordinator", []) + by_role.get("aee", []),
                col_user, vazio="Sem diretoria/apoio ainda.")
        st.button("+ Novo Diretor / Coord. / Apoio", disabled=True, help="Cadastro com login chega no #9.")

    with tabs[1]:
        st.caption("Corpo docente - com **materias** e **turmas** amarradas.")
        profs = list(by_role.get("teacher", []))
        if sede_id is not None:
            profs = [u for u in profs if sede_id in prof_campi.get(u["id"], set())]
        if turma_sel != "Todas as turmas":
            profs = [u for u in profs if turma_sel in prof_turmas.get(u["id"], set())]
        _tabela(profs, [
            ("Professor", lambda u: f"<span class='col-name'>{u['full_name']}</span>"
                + (" <span class='col-badge col-b-reg'>REGENTE</span>" if prof_reg.get(u["id"]) else ""), 1.7),
            ("Materias", lambda u: _badges(sorted(prof_mat.get(u["id"], set())), "col-b-mat"), 1.8),
            ("Turmas", lambda u: _badges(sorted(prof_turmas.get(u["id"], set())), "col-b-turma"), 1.6),
            ("Status", lambda u: _badge_ativo(u["active"]), 0.7),
        ], vazio="Nenhum professor (com os filtros).")
        st.button("+ Novo Professor", disabled=True, help="Cadastro com login (GoTrue Admin API) chega no #9.")
        st.caption("Para amarrar professor a turma/materia, entre numa **Turma** (aba Turmas -> Gerir).")

    with tabs[2]:
        topo = st.columns([4, 1.3])
        topo[0].caption("Turmas -> unidade. Entre na turma pra matricular alunos e vincular professores.")
        if topo[1].button("+ Nova Turma", use_container_width=True, type="primary"):
            _modal_nova_turma(pool, sid, cps)
        turmas = list(cls)
        if sede_id is not None:
            turmas = [c for c in turmas if c["campus_id"] == sede_id]
        if turma_sel != "Todas as turmas":
            turmas = [c for c in turmas if c["name"] == turma_sel]
        alunos_por_turma = defaultdict(int)
        for r in scl:
            if r["school_id"] == sid:
                alunos_por_turma[r["turma"]] += 1
        larguras = [1.0, 1.1, 0.5, 1.3, 0.7, 0.9]
        with st.container(border=True):
            hc = st.columns(larguras)
            for col, lbl in zip(hc, ["Turma", "Serie", "Ano", "Unidade", "Alunos", ""]):
                col.markdown(f"<div class='col-header'>{lbl}</div>", unsafe_allow_html=True)
            if not turmas:
                st.caption("Nenhuma turma (com os filtros). Clique em **+ Nova Turma**.")
            for i, c in enumerate(turmas):
                cells = st.columns(larguras)
                kl = "col-cell" + (" col-cell-alt" if i % 2 else "")
                cells[0].markdown(f"<div class='{kl}'><span class='col-name'>{c['name']}</span></div>", unsafe_allow_html=True)
                cells[1].markdown(f"<div class='{kl}'>{c['grade_level']}</div>", unsafe_allow_html=True)
                cells[2].markdown(f"<div class='{kl}'>{c['year']}</div>", unsafe_allow_html=True)
                cells[3].markdown(f"<div class='{kl}'>{campus_name.get(c['campus_id'], 'sem sede')}</div>", unsafe_allow_html=True)
                cells[4].markdown(f"<div class='{kl}'>{alunos_por_turma.get(c['name'], 0)}</div>", unsafe_allow_html=True)
                with cells[5]:
                    if st.button("Gerir →", key=f"turma_{c['id']}", use_container_width=True):
                        st.session_state["turma_em_gestao"] = str(c["id"])
                        st.rerun()

    with tabs[3]:
        alunos = list(sts)
        if sede_id is not None:
            alunos = [a for a in alunos if sede_id in stu_campi.get(a["id"], set())]
        if turma_sel != "Todas as turmas":
            alunos = [a for a in alunos if turma_sel in stu_turmas.get(a["id"], set())]
        st.caption(f"{len(alunos)} aluno(s) - com a **turma** amarrada.")
        _tabela(alunos, [
            ("Matricula", lambda a: f"<span class='col-mono'>{a['code']}</span>", 1.0),
            ("Aluno", lambda a: f"<span class='col-name'>{a['full_name']}</span>", 2.0),
            ("Turma(s)", lambda a: _badges(sorted(stu_turmas.get(a["id"], set())), "col-b-turma"), 1.4),
            ("Unidade(s)", lambda a: _badges(sorted(campus_name.get(x, "?") for x in stu_campi.get(a["id"], set())), "col-b-coord"), 1.2),
        ], vazio="Nenhum aluno (com os filtros).")
        st.caption("Para matricular aluno numa turma, entre na **Turma** (aba Turmas -> Gerir).")

    with tabs[4]:
        topo = st.columns([4, 1.3])
        topo[0].caption("Sedes (unidades) deste colegio.")
        if topo[1].button("+ Nova Sede", use_container_width=True, type="primary"):
            _modal_nova_sede(pool, sid)
        _tabela(cps, [
            ("Sede", lambda c: f"<span class='col-name'>{c['name']}</span>", 1.6),
            ("Cidade", lambda c: c["city"] or "-", 1.2),
            ("UF", lambda c: c["state"] or "-", 0.5),
            ("Status", lambda c: _badge_ativo(c["is_active"]), 0.7),
        ], vazio="Sem sedes ainda.")


def render_pagina_colegios():
    st.session_state.setdefault("colegio_em_gestao", None)
    st.session_state.setdefault("turma_em_gestao", None)

    if not _DB_OK:
        st.title("\U0001F3EB Colegios"); st.error(f"Sem conexao com o banco: {_DB_ERR}"); return
    try:
        pool = run_async(get_pool())
        schools, users, students, campuses, classes, subjects, cts, scl = run_async(_carregar(pool))
    except Exception as e:
        st.title("\U0001F3EB Colegios"); st.error(f"Falha ao ler o banco: {type(e).__name__} - {e}"); return

    u_idx, st_idx, cp_idx, cl_idx = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for u in users: u_idx[u["school_id"]].append(u)
    for s in students: st_idx[s["school_id"]].append(s)
    for c in campuses: cp_idx[c["school_id"]].append(c)
    for c in classes: cl_idx[c["school_id"]].append(c)

    sel = st.session_state.get("colegio_em_gestao")
    turma_sel = st.session_state.get("turma_em_gestao")

    if sel:
        school = next((s for s in schools if str(s["id"]) == str(sel)), None)
        if not school:
            st.session_state["colegio_em_gestao"] = None; st.rerun(); return
        sid = school["id"]
        if turma_sel:
            turma = next((c for c in classes if str(c["id"]) == str(turma_sel)), None)
            if not turma:
                st.session_state["turma_em_gestao"] = None; st.rerun(); return
            campus_name = {c["id"]: c["name"] for c in cp_idx.get(sid, [])}
            _render_area_turma(pool, turma, school, st_idx.get(sid, []),
                               [u for u in u_idx.get(sid, []) if u["role"] == "teacher"],
                               subjects, scl, cts, campus_name)
        else:
            _render_gestao(pool, school, u_idx.get(sid, []), st_idx.get(sid, []),
                           cp_idx.get(sid, []), cl_idx.get(sid, []), subjects, cts, scl)
    else:
        _render_lista(schools, u_idx, st_idx, cp_idx, cl_idx, pool)
