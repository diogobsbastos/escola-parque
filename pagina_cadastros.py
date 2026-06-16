"""
pagina_cadastros.py — Cadastro de Usuários com login (Escola Parque V3)
-----------------------------------------------------------------------
Cria contas de acesso (Diretor, Coordenação, Professor, AEE, Aluno, Responsável)
com login no GoTrue + public.users + vínculo do papel, e manda a senha
provisória por e-mail (canais de Configurar E-mail, com failover).

Padrão visual (espelha pagina_professores / pagina_alunos):
  - Título + caption no topo.
  - Barra: busca à esquerda, botão "➕ Novo Usuário" no canto direito.
  - Lista de usuários como tela principal.
  - Formulário de criação dentro de um modal (@st.dialog), com campos
    dinâmicos (o papel decide o seletor de aluno; o colégio filtra os alunos).
"""

import streamlit as st

import backend_auth as auth


def _papel_options():
    return list(auth.PAPEIS_VALIDOS)


# ════════════════════════════════════════════════════════════════════
# Modal: Novo usuário
# ════════════════════════════════════════════════════════════════════
@st.dialog("➕ Novo usuário")
def _modal_novo_usuario():
    # Senha provisória persistida na sessão (single source = key do widget).
    st.session_state.setdefault("cad_senha_field", auth.gerar_senha_provisoria())

    def _regerar_senha():
        st.session_state["cad_senha_field"] = auth.gerar_senha_provisoria()

    # Papel + dados básicos (reagem na hora — dialog re-roda a cada interação).
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
    csenha, cbtn = st.columns([3, 1])
    with csenha:
        senha = st.text_input("Senha provisória", key="cad_senha_field")
    with cbtn:
        st.write("")
        st.write("")
        st.button("🔄 Gerar nova", use_container_width=True, on_click=_regerar_senha)

    enviar = st.checkbox("Enviar e-mail de boas-vindas com a senha provisória", value=True)

    if st.button("✅ Criar usuário", type="primary", use_container_width=True):
        with st.spinner("Criando login e conta..."):
            res = auth.cadastrar_usuario(
                email=email, full_name=full_name, role=role,
                school_id=escola_id, senha=senha, student_id=student_id,
            )
        if not res.get("ok"):
            st.error(f"Falhou na etapa '{res.get('etapa')}': {res.get('mensagem')}")
            return

        # Guarda o resultado pra exibir na tela principal (o rerun fecha o modal).
        resultado = {
            "mensagem": res.get("mensagem"),
            "login": (email or "").strip().lower(),
            "senha": res.get("senha"),
            "warn": res.get("mensagem") if res.get("etapa") == "vinculo" else None,
        }
        if enviar:
            ok_mail, log_mail = auth.enviar_boas_vindas(
                email=(email or "").strip().lower(), full_name=full_name, senha=res.get("senha"),
            )
            resultado["email_ok"] = ok_mail
            resultado["email_log"] = log_mail

        st.session_state["cad_resultado"] = resultado
        st.session_state["cad_senha_field"] = auth.gerar_senha_provisoria()
        st.rerun()


# ════════════════════════════════════════════════════════════════════
# Página: lista + topo
# ════════════════════════════════════════════════════════════════════
def render_pagina_cadastros():
    st.title("👤 Cadastro de Usuários")
    st.caption(
        "Crie contas de acesso com login. A senha provisória pode ser enviada "
        "por e-mail automaticamente (configure os canais em ✉️ Configurar E-mail)."
    )

    # Resultado do último cadastro (vindo do modal, após fechar).
    res = st.session_state.pop("cad_resultado", None)
    if res:
        st.success(f"✅ {res['mensagem']}")
        st.info(f"**Login:** {res['login']}  ·  **Senha provisória:** `{res['senha']}`")
        if res.get("warn"):
            st.warning(res["warn"])
        if "email_ok" in res:
            if res["email_ok"]:
                st.success(f"📧 E-mail de boas-vindas enviado. {res['email_log']}")
            else:
                st.warning(
                    "Usuário criado, mas o e-mail NÃO saiu (anote a senha acima e "
                    f"envie manualmente). Motivo: {res['email_log']}"
                )

    # Barra de ferramentas: busca (esquerda) + Novo Usuário (canto direito).
    col_busca, col_novo = st.columns([4, 1.3])
    with col_busca:
        busca = st.text_input(
            "Buscar usuário",
            placeholder="Buscar por nome ou e-mail...",
            label_visibility="collapsed",
            key="cad_busca",
        )
    with col_novo:
        if st.button("➕ Novo Usuário", type="primary", use_container_width=True):
            _modal_novo_usuario()

    # Lista de usuários.
    try:
        usuarios = auth.listar_usuarios()
    except Exception as e:
        st.error(f"Não consegui listar usuários: {type(e).__name__}: {e}")
        return

    total = len(usuarios)
    if busca and len(busca) >= 2:
        b = busca.lower()
        usuarios = [
            u for u in usuarios
            if b in (u.get("full_name") or "").lower() or b in (u.get("email") or "").lower()
        ]

    if not usuarios:
        if total == 0:
            st.info("Nenhum usuário cadastrado. Clique em **➕ Novo Usuário** para começar.")
        else:
            st.warning(f"Nenhum usuário encontrado com a busca ({total} no total).")
        return

    if len(usuarios) < total:
        st.caption(f":material/group: **{len(usuarios)} de {total}** usuário(s) — busca aplicada")
    else:
        st.caption(f":material/group: **{total} usuário(s) cadastrado(s)**")

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
