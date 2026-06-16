"""
pagina_email.py — Painel "Configurar E-mail" (Escola Parque V3)
----------------------------------------------------------------
Mesma pegada do painel de Provedores LiteLLM: você cadastra VÁRIOS canais de
envio (Gmail, SMTP próprio...) e o sistema usa em ordem de prioridade com
FAILOVER — se o canal 1 cai, ele tenta o 2, depois o 3.

Esses canais são usados para os e-mails do sistema: convite/senha provisória de
novos logins, reset de senha, avisos.
"""

import streamlit as st

import storage_email
from email_sender import enviar_email

_STATUS_BADGE = {
    "ativo": "🟢 Ativo (último envio OK)",
    "falhou": "🔴 Falhou no último teste",
    "nao_testado": "⚪ Não testado ainda",
}


def _badge(status):
    return _STATUS_BADGE.get(status or "nao_testado", _STATUS_BADGE["nao_testado"])


def render_pagina_email():
    st.markdown("## ✉️ Configurar E-mail")
    st.caption(
        "Cadastre um ou mais canais de envio. O sistema tenta na ordem de "
        "prioridade e, se um cair, usa o próximo automaticamente (failover)."
    )

    canais = storage_email.load_canais()

    # ── Resumo / estado geral ────────────────────────────────────────────────
    habilitados = [c for c in canais if c.get("habilitado", True)]
    if not canais:
        st.info("Nenhum canal cadastrado ainda. Adicione o primeiro abaixo (ex.: Gmail).")
    elif not habilitados:
        st.warning("Você tem canais cadastrados, mas TODOS estão desligados. Nenhum e-mail será enviado.")
    else:
        st.success(f"{len(habilitados)} canal(is) habilitado(s) na fila de failover.")

    # ── Lista de canais (ordem de prioridade) ────────────────────────────────
    if canais:
        st.markdown("### Canais cadastrados")
        ordenados = sorted(canais, key=lambda c: int(c.get("prioridade", 0) or 0))
        for c in ordenados:
            nome = c.get("nome", "?")
            titulo = f"#{c.get('prioridade', '?')} · {nome}  —  {_badge(c.get('status'))}"
            if not c.get("habilitado", True):
                titulo += "  ·  ⏸️ desligado"
            with st.expander(titulo):
                st.write(
                    f"**Tipo:** {c.get('tipo')}  ·  **Host:** {c.get('host')}:{c.get('porta')} "
                    f"({c.get('seguranca')})"
                )
                st.write(f"**Usuário:** {c.get('usuario')}  ·  **Remetente:** "
                         f"{c.get('remetente_nome')} <{c.get('remetente_email')}>")
                if c.get("ultimo_teste"):
                    st.caption(f"Último teste: {c.get('ultimo_teste')}")

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    if st.button("⬆️ Subir", key=f"up_{nome}", use_container_width=True):
                        storage_email.mover_prioridade(nome, -1)
                        st.rerun()
                with col2:
                    if st.button("⬇️ Descer", key=f"down_{nome}", use_container_width=True):
                        storage_email.mover_prioridade(nome, +1)
                        st.rerun()
                with col3:
                    rotulo = "⏸️ Desligar" if c.get("habilitado", True) else "▶️ Ligar"
                    if st.button(rotulo, key=f"tog_{nome}", use_container_width=True):
                        storage_email.set_habilitado(nome, not c.get("habilitado", True))
                        st.rerun()
                with col4:
                    if st.button("🗑️ Remover", key=f"rm_{nome}", use_container_width=True):
                        storage_email.remove_canal(nome)
                        st.rerun()

                # Edição (senha em branco = mantém a guardada)
                with st.form(key=f"edit_{nome}"):
                    st.markdown("**Editar canal**")
                    e_user = st.text_input("Usuário (login SMTP)", value=c.get("usuario", ""))
                    e_senha = st.text_input("Senha / App-password (em branco = manter)",
                                            value="", type="password")
                    e_host = st.text_input("Host", value=c.get("host", ""))
                    cporta, cseg = st.columns(2)
                    with cporta:
                        e_porta = st.number_input("Porta", value=int(c.get("porta", 587) or 587),
                                                  step=1)
                    with cseg:
                        e_seg = st.selectbox("Segurança", ["starttls", "ssl"],
                                             index=0 if c.get("seguranca") != "ssl" else 1)
                    e_rnome = st.text_input("Nome do remetente", value=c.get("remetente_nome", ""))
                    e_remail = st.text_input("E-mail do remetente", value=c.get("remetente_email", ""))
                    if st.form_submit_button("💾 Salvar alterações"):
                        storage_email.update_canal(
                            nome, usuario=e_user, senha=e_senha, host=e_host,
                            porta=e_porta, seguranca=e_seg,
                            remetente_nome=e_rnome, remetente_email=e_remail,
                        )
                        st.success("Canal atualizado.")
                        st.rerun()

    st.divider()

    # ── Adicionar canal ──────────────────────────────────────────────────────
    st.markdown("### ➕ Adicionar canal")
    tipo = st.selectbox(
        "Tipo de canal",
        ["gmail", "outlook", "smtp"],
        format_func=lambda t: {
            "gmail": "Gmail (smtp.gmail.com — precisa de App-password)",
            "outlook": "Outlook / Office365",
            "smtp": "SMTP próprio (informe host/porta)",
        }[t],
    )

    if tipo == "gmail":
        st.info(
            "Para Gmail você precisa de uma **App-password** (não a senha normal): "
            "ative a verificação em 2 etapas na conta Google e gere uma senha de app "
            "em myaccount.google.com → Segurança → Senhas de app. Cole os 16 dígitos abaixo."
        )

    with st.form(key="add_canal"):
        nome = st.text_input("Nome do canal", placeholder="Ex.: Gmail Secretaria")
        usuario = st.text_input("Usuário (e-mail de login)", placeholder="conta@gmail.com")
        senha = st.text_input("Senha / App-password", type="password")
        rem_nome = st.text_input("Nome do remetente", value="Escola Parque")
        rem_email = st.text_input("E-mail do remetente (em branco = usar o usuário)",
                                  placeholder="(opcional)")

        host = porta = seg = None
        if tipo == "smtp":
            host = st.text_input("Host SMTP", placeholder="smtp.seudominio.com")
            cp, cs = st.columns(2)
            with cp:
                porta = st.number_input("Porta", value=587, step=1)
            with cs:
                seg = st.selectbox("Segurança", ["starttls", "ssl"])

        if st.form_submit_button("➕ Cadastrar canal"):
            ok, msg = storage_email.add_canal(
                nome=nome, tipo=tipo, usuario=usuario, senha=senha,
                remetente_nome=rem_nome, remetente_email=rem_email,
                host=host, porta=porta, seguranca=seg,
            )
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    st.divider()

    # ── Testar envio ─────────────────────────────────────────────────────────
    st.markdown("### 🧪 Testar envio")
    if not canais:
        st.caption("Cadastre um canal primeiro.")
        return

    nomes = [c.get("nome") for c in sorted(canais, key=lambda x: int(x.get("prioridade", 0) or 0))]
    col_a, col_b = st.columns([2, 1])
    with col_a:
        dest = st.text_input("Enviar e-mail de teste para", placeholder="voce@exemplo.com")
    with col_b:
        modo = st.selectbox("Canal", ["Failover (ordem)"] + nomes)

    if st.button("📨 Enviar teste", type="primary"):
        if not dest.strip():
            st.error("Informe o e-mail de destino.")
        else:
            forcado = None if modo == "Failover (ordem)" else modo
            ok, canal_usado, log = enviar_email(
                destinatario=dest.strip(),
                assunto="Teste de envio — Escola Parque",
                corpo_html=(
                    "<h2>Funcionou! ✅</h2>"
                    "<p>Este é um e-mail de teste do painel <b>Configurar E-mail</b> "
                    "da Escola Parque. Se você recebeu isto, o canal está pronto para "
                    "enviar os acessos dos usuários.</p>"
                ),
                canal_forcado=forcado,
            )
            if ok:
                st.success(f"Enviado com sucesso pelo canal: {canal_usado}")
            else:
                st.error("Não consegui enviar por nenhum canal.")
            with st.expander("Log da tentativa (debug)", expanded=not ok):
                for linha in log:
                    st.code(linha)
            st.rerun()
