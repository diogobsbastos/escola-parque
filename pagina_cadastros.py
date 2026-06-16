"""
pagina_cadastros.py — Cadastro de Usuários com login (Escola Parque V3)
-----------------------------------------------------------------------
Cria, EDITA e renova senha de contas de acesso (Diretor, Coordenação,
Professor, AEE, Aluno, Responsável) com login no GoTrue + public.users.

Padrão visual (espelha pagina_professores / pagina_alunos):
  - Título + caption no topo.
  - Barra: busca à esquerda, botão "➕ Novo Usuário" no canto direito.
  - Lista interativa de usuários com ações por linha (✏️ editar, 🔑 nova senha).
  - Criação/edição/senha em modais (@st.dialog), com campos dinâmicos.

Backends: backend_auth (criar) + backend_usuarios_admin (editar/reset).
"""

import streamlit as st

import backend_auth as auth

try:
    import backend_usuarios_admin as admin
except Exception as _e_admin:  # degradação graciosa
    admin = None
    _ERRO_ADMIN = str(_e_admin)


def _papel_options():
    return list(auth.PAPEIS_VALIDOS)


def _label_papel(r):
    return auth.PAPEL_LABEL.get(r, "Plataforma (super admin)" if r == "super_admin" else r)


# ════════════════════════════════════════════════════════════════════
# Modal: Novo usuário
# ════════════════════════════════════════════════════════════════════
@st.dialog("➕ Novo usuário")
def _modal_novo_usuario():
    st.session_state.setdefault("cad_senha_field", auth.gerar_senha_provisoria())

    def _regerar_senha():
        st.session_state["cad_senha_field"] = auth.gerar_senha_provisoria()

    col1, col2 = st.columns(2)
    with col1:
        role = st.selectbox("Papel", _papel_options(), format_func=_label_papel)
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
# Modal: Editar usuário
# ════════════════════════════════════════════════════════════════════
@st.dialog("✏️ Editar usuário")
def _modal_editar_usuario(u):
    if admin is None:
        st.error("backend_usuarios_admin não carregado.")
        return

    st.caption(f"Login: **{u.get('email')}** (o e-mail não é editável aqui).")

    full_name = st.text_input("Nome completo", value=u.get("full_name") or "")

    col1, col2 = st.columns(2)
    with col1:
        papeis = list(admin.PAPEIS_EDITAVEIS)
        atual = u.get("role")
        idx = papeis.index(atual) if atual in papeis else 0
        role = st.selectbox("Papel", papeis, index=idx, format_func=_label_papel)
    with col2:
        try:
            escolas = auth.listar_escolas()
        except Exception as e:
            st.error(f"Colégios indisponíveis: {e}")
            escolas = []
        if escolas:
            ids = [e["id"] for e in escolas]
            idx_esc = next((i for i, e in enumerate(escolas) if e["name"] == u.get("escola")), 0)
            escola_id = st.selectbox(
                "Colégio", ids, index=idx_esc,
                format_func=lambda i: next((e["name"] for e in escolas if e["id"] == i), i),
            )
        else:
            escola_id = None
            st.warning("Nenhum colégio cadastrado.")

    ativo = st.toggle("Conta ativa", value=bool(u.get("active")))

    if st.button("💾 Salvar alterações", type="primary", use_container_width=True):
        res = admin.atualizar_usuario(u["id"], full_name, role, escola_id, ativo)
        if res.get("ok"):
            st.session_state["cad_flash"] = ("success", f"✅ {res['mensagem']}")
            st.rerun()
        else:
            st.error(res.get("mensagem"))


# ════════════════════════════════════════════════════════════════════
# Modal: Nova senha
# ════════════════════════════════════════════════════════════════════
@st.dialog("🔑 Renovar senha")
def _modal_nova_senha(u):
    if admin is None:
        st.error("backend_usuarios_admin não carregado.")
        return

    st.caption(f"Usuário: **{u.get('full_name')}** · {u.get('email')}")
    st.info(
        "A senha atual **não pode ser vista** (fica criptografada no GoTrue). "
        "Aqui você define uma **nova** senha provisória."
    )
    enviar = st.checkbox("Enviar a nova senha por e-mail ao usuário", value=True)

    if st.button("🔄 Gerar e aplicar nova senha", type="primary", use_container_width=True):
        res = admin.resetar_senha(u["id"])
        if not res.get("ok"):
            st.error(res.get("mensagem"))
            return
        st.success("✅ Senha redefinida.")
        st.code(res["senha"], language=None)
        st.caption("Copie agora — ao fechar este modal, ela não aparece de novo.")
        if enviar:
            ok_mail, log_mail = auth.enviar_boas_vindas(
                email=u.get("email"), full_name=u.get("full_name") or "", senha=res["senha"],
            )
            if ok_mail:
                st.success(f"📧 Enviada por e-mail. {log_mail}")
            else:
                st.warning(f"Senha trocada, mas o e-mail NÃO saiu. Motivo: {log_mail}")


# ════════════════════════════════════════════════════════════════════
# Página: lista + topo
# ════════════════════════════════════════════════════════════════════
def render_pagina_cadastros():
    st.title("👤 Cadastro de Usuários")
    st.caption(
        "Crie, edite e renove senha de contas de acesso. A senha provisória pode "
        "ser enviada por e-mail automaticamente (configure os canais em ✉️ Configurar E-mail)."
    )

    # Flash de edição (vindo de modal, após fechar).
    flash = st.session_state.pop("cad_flash", None)
    if flash:
        kind, msg = flash
        getattr(st, kind, st.info)(msg)

    # Resultado do último cadastro.
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

    # Tabela interativa (lista + ações por linha).
    larguras = [2.2, 2.6, 1.6, 1.6, 0.6, 0.5, 0.5]
    labels = ["Nome", "E-mail", "Papel", "Colégio", "Ativo", "", ""]

    with st.container(border=True):
        hdr = st.columns(larguras)
        for c, t in zip(hdr, labels):
            c.markdown(f"**{t}**" if t else "&nbsp;", unsafe_allow_html=True)

        for u in usuarios:
            row = st.columns(larguras)
            row[0].write(u.get("full_name") or "—")
            row[1].write(u.get("email") or "—")
            row[2].write(_label_papel(u.get("role")))
            row[3].write(u.get("escola") or "—")
            row[4].write("✅" if u.get("active") else "❌")
            if row[5].button("✏️", key=f"edit_{u['id']}", help="Editar usuário"):
                _modal_editar_usuario(u)
            if row[6].button("🔑", key=f"pwd_{u['id']}", help="Renovar senha"):
                _modal_nova_senha(u)
