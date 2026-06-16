"""
pages/9_Gestao_e_Hierarquia.py - Console de Gestao & Hierarquia (F2).

Read-only: ver colegios, logins por papel, alunos, sedes/turmas + matriz de acesso.
Le o Postgres ativo (VPS innova) via innova_bridge (run_async/get_pool).

E uma pagina NATIVA do Streamlit (multipage) - de proposito, pra NAO tocar no
app.py de 1670 linhas. Aparece no menu de paginas do Streamlit como
"Gestao e Hierarquia". O CRUD de cadastros vem na proxima etapa.
"""
from __future__ import annotations

from collections import defaultdict

import streamlit as st

st.set_page_config(page_title="Gestao & Hierarquia", page_icon="\U0001F5C2", layout="wide")

try:
    from innova_bridge.db import run_async, get_pool
    _DB_OK, _DB_ERR = True, ""
except Exception as e:  # pragma: no cover
    _DB_OK, _DB_ERR = False, f"{type(e).__name__}: {e}"

ROLE_LABELS = {
    "super_admin": "\U0001F6E1️ Plataforma (super_admin)",
    "admin": "\U0001F3EB Diretor / Adm do Colegio",
    "coordinator": "\U0001F4CB Coordenacao",
    "teacher": "\U0001F468‍\U0001F3EB Professor",
    "aee": "\U0001F9E9 Apoio (AEE)",
    "student": "\U0001F393 Aluno",
    "guardian": "\U0001F46A Responsavel",
}
ROLE_ORDER = ["super_admin", "admin", "coordinator", "teacher", "aee", "student", "guardian"]

ACCESS_MATRIX = [
    ("super_admin", "Plataforma", "Todos os colegios; cria/edita colegio+sede; ponte backend<->frontend; custos globais"),
    ("admin", "1 colegio", "Tudo do seu colegio: sedes, turmas, usuarios, alunos, PAIs, provas"),
    ("coordinator", "1 colegio", "Visao pedagogica: PAIs, provas, alunos especiais, aprovacoes"),
    ("teacher", "Suas turmas", "Seus alunos, provas (subir->adaptar), correcao, PAIs dos seus alunos"),
    ("aee", "Seus alunos", "Alunos acompanhados; parte AEE do questionario; PAIs"),
    ("student", "So o proprio", "Seu perfil, seu PAI, suas provas adaptadas, suas notas"),
    ("guardian", "So o filho", "Perfil/PAI/notas do(s) aluno(s) vinculado(s)"),
]


async def _carregar(pool):
    schools = await pool.fetch("SELECT id, name, slug FROM schools ORDER BY name")
    users = await pool.fetch(
        "SELECT school_id, role::text AS role, email, full_name, active FROM users ORDER BY email"
    )
    students = await pool.fetch(
        "SELECT school_id, code, full_name FROM students WHERE archived_at IS NULL ORDER BY full_name"
    )
    campuses = await pool.fetch(
        "SELECT school_id, name, city, state, is_active FROM campuses ORDER BY name"
    )
    classes = await pool.fetch(
        "SELECT school_id, name, grade_level, year FROM classes ORDER BY name"
    )
    try:
        accessos = await pool.fetch(
            "SELECT sa.access_type::text AS tipo, u.email, st.full_name AS aluno, st.school_id "
            "FROM student_access sa "
            "JOIN users u ON u.id = sa.user_id "
            "JOIN students st ON st.id = sa.student_id "
            "ORDER BY st.full_name"
        )
    except Exception:
        accessos = []
    return schools, users, students, campuses, classes, accessos


st.title("\U0001F5C2️ Gestao & Hierarquia")
st.caption(
    "Toda a estrutura: colegios, logins por papel, alunos, sedes/turmas e a matriz de "
    "acesso. (Somente leitura - o cadastro/edicao vem na proxima etapa.)"
)

if not _DB_OK:
    st.error(f"Sem conexao com o banco (innova_bridge): {_DB_ERR}")
    st.stop()

try:
    pool = run_async(get_pool())
    schools, users, students, campuses, classes, accessos = run_async(_carregar(pool))
except Exception as e:
    st.error(f"Falha ao ler o banco: {type(e).__name__}: {e}")
    st.stop()

u_by, st_by, cp_by, cl_by = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
for u in users:
    u_by[u["school_id"]].append(u)
for s in students:
    st_by[s["school_id"]].append(s)
for c in campuses:
    cp_by[c["school_id"]].append(c)
for c in classes:
    cl_by[c["school_id"]].append(c)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Colegios", len(schools))
c2.metric("Logins", len(users))
c3.metric("Alunos", len(students))
c4.metric("Sedes", len(campuses))
st.divider()

for sc in schools:
    sid = sc["id"]
    us, sts = u_by.get(sid, []), st_by.get(sid, [])
    cps, cls = cp_by.get(sid, []), cl_by.get(sid, [])
    titulo = f"\U0001F3EB {sc['name']}  -  {len(us)} logins - {len(sts)} alunos - {len(cps)} sedes - {len(cls)} turmas"
    with st.expander(titulo, expanded=True):
        st.markdown("**Logins (por papel)**")
        by_role = defaultdict(list)
        for u in us:
            by_role[u["role"]].append(u)
        algum = False
        for role in ROLE_ORDER:
            lst = by_role.get(role, [])
            if not lst:
                continue
            algum = True
            st.markdown(f"_{ROLE_LABELS.get(role, role)}_ - {len(lst)}")
            st.dataframe(
                [{"Nome": u["full_name"], "E-mail": u["email"], "Ativo": "sim" if u["active"] else "-"} for u in lst],
                hide_index=True, use_container_width=True,
            )
        if not algum:
            st.caption("Sem logins neste colegio.")

        if cps:
            st.markdown("**Sedes (campus)**")
            st.dataframe(
                [{"Sede": c["name"], "Cidade": c["city"] or "-", "UF": c["state"] or "-",
                  "Ativa": "sim" if c["is_active"] else "-"} for c in cps],
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("Sem sedes (campus) cadastradas ainda.")

        if cls:
            st.markdown("**Turmas**")
            st.dataframe(
                [{"Turma": c["name"], "Serie": c["grade_level"], "Ano": c["year"]} for c in cls],
                hide_index=True, use_container_width=True,
            )

        st.markdown(f"**Alunos ({len(sts)})**")
        if sts:
            st.dataframe(
                [{"Matricula": s["code"], "Aluno": s["full_name"]} for s in sts],
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("Sem alunos.")

st.divider()
st.subheader("\U0001F511 Logins de aluno / responsavel")
if accessos:
    st.dataframe(
        [{"Tipo": "Aluno" if a["tipo"] == "self" else "Responsavel",
          "Login": a["email"], "Aluno vinculado": a["aluno"]} for a in accessos],
        hide_index=True, use_container_width=True,
    )
else:
    st.caption("Nenhum login de aluno/responsavel vinculado ainda (vem no estagio do login de aluno).")

st.divider()
st.subheader("\U0001F9ED Hierarquia de acesso (quem pode o que)")
st.dataframe(
    [{"Papel": ROLE_LABELS.get(r, r), "Escopo": esc, "Acessa": desc} for (r, esc, desc) in ACCESS_MATRIX],
    hide_index=True, use_container_width=True,
)

st.caption("Proxima etapa: cadastro/edicao (CRUD) de Colegio, Sede, Diretor, Professor, AEE e Aluno - com criacao do login via GoTrue Admin API.")
