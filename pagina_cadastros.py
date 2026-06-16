"""
pagina_cadastros.py — Cadastro de Usuários com login (Escola Parque V3)
-----------------------------------------------------------------------
Cria contas de acesso (Diretor, Coordenação, Professor, AEE, Aluno, Responsável)
com login no GoTrue + public.users + vínculo do papel, e manda a senha
provisória por e-mail (canais de Configurar E-mail, com failover).

Não usa st.form porque os campos são dinâmicos (o papel decide se mostra o
seletor de aluno; o colégio filtra a lista de alunos) — st.form só atualiza no
submit, o que atrapalharia.
"""

import streamlit as st

import backend_auth as auth


def _papel_options():
    return list(auth.PAPEIS_VALIDOS)


def render_pagina_cadastros():
    st.markdown("## 👤 Cadastro de Usuários")
    st.caption(
        "Crie contas de acesso com login. A senha provisória pode ser enviada "
        "por e-mail automaticamente (configure os canais em ✉️ Configurar E-mail)."
    )

    # ── Usuários existentes ──────────────────────────────────────────────
    with st.expander("👥 Usuários já cadastrados", expanded=False):
        try:
            usuarios = auth.listar_usuarios()
            if not usuarios:
                st.caption("Nenhum usuário ainda.")
            else:
                st.dataframe(
                    [
                        {
                            "Nome": u["full_name"],
                            "E-mail": u["email"],
                            "Papel": auth.PAPEL_LABEL.get(u["role"], u["role"]),
                            "Colégio": u.get("escola") or "—",
                            "Ativo": "✅" if u.get("active") else "❌",
                        }
                        for u in usuarios
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
        except Exception as e:
            st.error(f"Não consegui listar usuários: {type(e).__name__}: {e}")

    st.divider()
    st.markdown("### ➕ Novo usuário")

    # Papel + dados básicos (fora de form pra reagir na hora)
    col1, col2 = st.columns(2)
    with col1:
        role = st.selectbox(
            "Papel",
            _papel_options(),
            format_func=lambda r: auth.PAPEL_LABEL.get(r, r),
        )
        full_name = st.text_input("Nome completo")
    with col2:
        email = st.text_input("E-mail (será o login)")
        try:
            escolas = auth.listar_escolas()
        except Exception as e:
            st.error(f"Não consegui carregar os colégios: {type(e).__name__}: {e}")
            escolas = []
        if escolas:
            escola_id = st.selectbox(
                "Colégio",
                [e["id"] for e in escolas],
                format_func=lambda i: next((e["name"] for e in escolas if e["id"] == i), i),
            )
        else:
            escola_id = None
            st.warning("Nenhum colégio cadastrado. Crie um colégio primeiro.")

    # Vínculo de aluno (só pra aluno / responsável / AEE)
    student_id = None
    if role in ("student", "guardian", "aee"):
        try:
            alunos = auth.listar_alunos(escola_id)
        except Exception as e:
            st.error(f"Não consegui carregar os alunos: {type(e).__name__}: {e}")
            alunos = []
        rotulo = {
            "student": "Aluno vinculado (a conta É deste aluno)",
            "guardian": "Aluno do qual é responsável",
            "aee": "Aluno que vai acompanhar (opcional)",
        }[role]
        if alunos:
            opcoes = [""] + [a["id"] for a in alunos] if role == "aee" else [a["id"] for a in alunos]
            student_id = st.selectbox(
                rotulo,
                opcoes,
                format_func=lambda i: "— (nenhum por enquanto)" if i == "" else
                next((f"{a['full_name']} (mat. {a['code']})" for a in alunos if a["id"] == i), i),
            )
            student_id = student_id or None
        else:
            st.info("Esse colégio ainda não tem alunos cadastrados.")

    # Senha provisória (gerada automaticamente, editável)
    if "cad_senha" not in st.session_state:
        st.session_state["cad_senha"] = auth.gerar_senha_provisoria()
    csenha, cbtn = st.columns([3, 1])
    with csenha:
        senha = st.text_input("Senha provisória", value=st.session_state["cad_senha"])
    with cbtn:
        st.write("")
        st.write("")
        if st.button("🔄 Gerar nova", use_container_width=True):
            st.session_state["cad_senha"] = auth.gerar_senha_provisoria()
            st.rerun()

    enviar = st.checkbox("Enviar e-mail de boas-vindas com a senha provisória", value=True)

    if st.button("✅ Criar usuário", type="primary"):
        with st.spinner("Criando login e conta..."):
            res = auth.cadastrar_usuario(
                email=email, full_name=full_name, role=role,
                school_id=escola_id, senha=senha, student_id=student_id,
            )
        if not res.get("ok"):
            st.error(f"Falhou na etapa '{res.get('etapa')}': {res.get('mensagem')}")
        else:
            st.success(f"✅ {res.get('mensagem')}")
            st.info(f"**Login:** {email.strip().lower()}  ·  **Senha provisória:** `{res.get('senha')}`")
            if res.get("etapa") == "vinculo":
                st.warning(res.get("mensagem"))
            st.session_state["cad_senha"] = auth.gerar_senha_provisoria()

            if enviar:
                ok_mail, log_mail = auth.enviar_boas_vindas(
                    email=email.strip().lower(), full_name=full_name, senha=res.get("senha"),
                )
                if ok_mail:
                    st.success(f"📧 E-mail de boas-vindas enviado. {log_mail}")
                else:
                    st.warning(
                        "Usuário criado, mas o e-mail NÃO saiu (anote a senha acima e "
                        f"envie manualmente). Motivo: {log_mail}"
                    )
