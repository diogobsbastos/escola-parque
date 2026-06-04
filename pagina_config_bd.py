"""
pagina_config_bd.py - UI Streamlit do Carrossel de Bancos de Dados.

Renderiza no painel de Configuracoes um carrossel analogo ao do pool
LiteLLM (Painel 1 - Provedores Configurados), mas para bancos Supabase
compartilhados com o Innova V2 (Next.js).

Padrao visual (espelhado do LiteLLM):
  - st.container(border=True) envolve tudo
  - Cabecalho 2 colunas: titulo a esquerda + botao "Adicionar Novo Banco"
    a direita (canto superior direito), type="primary"
  - st.empty() placeholder pro form de Adicionar/Editar (tecnica do teleporte)
  - Auto-abre o form quando o pool esta vazio

CRITICO - bug do @st.dialog:
  O modal de Configuracoes em app.py e um @st.dialog. Qualquer st.rerun()
  dentro dele FECHA o dialog automaticamente. Para manter o usuario no
  dialog, todo rerun precisa ser precedido de:
      st.session_state["_reabrir_config_dialog"] = True
"""

from __future__ import annotations

import streamlit as st
import time

import storage_bancos as sb


# ============================================================================
# Helper critico - fix do @st.dialog fechando
# ============================================================================

def _rerun_mantendo_dialog() -> None:
    """Dispara st.rerun() preservando o @st.dialog de Configuracoes aberto.

    Padrao usado em ~10 lugares do app.py (linhas 700, 725, 749, 781, 810,
    901, etc.) para manter o usuario dentro do modal apos uma acao que
    dispara rerun.
    """
    st.session_state["_reabrir_config_dialog"] = True
    st.rerun()


def _css_local() -> None:
    """CSS especifico desta pagina (nao polui o resto do app)."""
    st.markdown(
        """
        <style>
        .bd-card {
            border: 1px solid rgba(150,150,150,0.25);
            border-radius: 10px;
            padding: 14px 16px;
            margin-bottom: 14px;
            background: rgba(255,255,255,0.02);
        }
        .bd-card.active {
            border-left: 4px solid #1e90ff;
            background: rgba(30,144,255,0.06);
        }
        .bd-card.reserve { border-left: 4px solid #28a745; }
        .bd-card.offline {
            border-left: 4px solid #d62728;
            background: rgba(214,39,40,0.05);
        }
        .bd-card.untested { border-left: 4px solid #888888; }
        .bd-titulo { font-size: 1.05rem; font-weight: 600; margin-bottom: 4px; }
        .bd-meta { font-size: 0.85rem; opacity: 0.85; line-height: 1.55; }
        .bd-meta code { font-size: 0.78rem; opacity: 0.85; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ============================================================================
# Card de banco
# ============================================================================

def _card_banco(bd: dict, idx: int) -> None:
    """Renderiza UM card de banco no padrao Motores IA / LiteLLM Painel 1.

    Layout:
      [badge + mini-botao Ativar]  [info]  [edit]  [ping]  [del]

    - Botoes a direita sao quadrados, soh com icone emoji (sem label).
    - 'Ativar' fica como mini-botao DENTRO da coluna do badge,
      so quando o BD nao e o EM USO atual.
    - 'Deletar' soh aparece se NAO for EM USO.
    """
    bd_id = bd["id"]
    status = bd.get("status", "untested")
    is_primary = bd.get("is_primary", False)
    bd_editando = st.session_state.get("bd_editando_inline_id") == bd_id

    with st.container(border=True):
        c_st, c_info, c_edit, c_test, c_del = st.columns([1.4, 5.5, 0.5, 0.5, 0.5])

        # ─── Coluna 1: badge + mini-botao Ativar ───
        with c_st:
            if is_primary:
                st.markdown("&#128309; **EM USO**", unsafe_allow_html=True)
            elif status == "offline":
                st.markdown("&#128308; **OFFLINE**", unsafe_allow_html=True)
            elif status in ("active", "reserve"):
                st.markdown("&#128994; **DISPONIVEL**", unsafe_allow_html=True)
            else:
                st.markdown("&#9898; **NAO TESTADO**", unsafe_allow_html=True)

            # Mini-botao "Ativar" so aparece se NAO for o EM USO atual
            if not is_primary:
                if st.button(
                    "Tornar EM USO",
                    key=f"bd_ativar_{idx}",
                    help="Promover este banco a EM USO (Python le e escreve nele).",
                    use_container_width=True,
                ):
                    ok, msg = sb.ativar_banco(bd_id)
                    st.session_state["_msg_bd_acao"] = msg
                    _rerun_mantendo_dialog()

        # ─── Coluna 2: info principal ───
        with c_info:
            label_lbl = bd.get("label", "(sem label)")
            region_lbl = bd.get("region", "-")
            url_lbl = bd.get("supabase_url", "-")
            pid_lbl = bd.get("project_id", "-")
            bandeira = sb.bandeira_regiao(region_lbl)

            st.markdown(f"**{bandeira} {label_lbl}** &middot; `{region_lbl}`", unsafe_allow_html=True)
            st.caption(f"&#127760; URL: `{url_lbl}`")
            st.caption(f"&#127380; Project: `{pid_lbl}`")

            ping_ms = bd.get("last_ping_ms")
            if ping_ms is not None:
                ping_emoji = sb.cor_latencia(ping_ms)
                last_at = bd.get("last_ping_at") or "-"
                st.caption(f"&#128202; Latencia: {ping_emoji} {ping_ms} ms &middot; Ultimo ping: {last_at}")
            else:
                st.caption("&#128202; Latencia: nao medida ainda")

        # ─── Coluna 3: Botao Ping (soh icone) ───
        with c_edit:
            if st.button(
                "⚡",
                key=f"bd_ping_{idx}",
                help="Testar conexao HTTP no endpoint /rest/v1 do Supabase.",
            ):
                with st.spinner("Pingando..."):
                    ok, msg, _ms = sb.testar_ping(bd_id)
                st.session_state["_msg_bd_acao"] = msg
                _rerun_mantendo_dialog()

        # ─── Coluna 4: Botao Editar (soh icone) ───
        with c_test:
            label_btn = "✖️" if bd_editando else "✏️"
            help_btn = "Cancelar edicao" if bd_editando else "Editar este banco"
            if st.button(
                label_btn,
                key=f"bd_edit_{idx}",
                help=help_btn,
            ):
                if bd_editando:
                    st.session_state.pop("bd_editando_inline_id", None)
                else:
                    st.session_state["bd_editando_inline_id"] = bd_id
                _rerun_mantendo_dialog()

        # ─── Coluna 5: Botao Deletar (soh icone, soh se NAO EM USO) ───
        with c_del:
            if not is_primary:
                if st.button(
                    "🗑️",
                    key=f"bd_del_{idx}",
                    help="Remover este banco do pool. Pede confirmacao.",
                ):
                    st.session_state["bd_confirmar_remover"] = bd_id
                    _rerun_mantendo_dialog()
            else:
                st.markdown("&nbsp;", unsafe_allow_html=True)

        # ─── Mensagem da ultima acao (se houver) ───
        if "_msg_bd_acao" in st.session_state:
            msg = st.session_state.pop("_msg_bd_acao")
            if msg:
                if any(s in msg.lower() for s in ["ok", "sucesso", "ativado", "removido", "atualizado", "cadastrado", "em uso"]):
                    st.success(msg)
                else:
                    st.info(msg)

        # ─── Bloco de confirmacao de remocao inline ───
        if st.session_state.get("bd_confirmar_remover") == bd_id:
            st.warning(
                f"Tem certeza que quer remover o banco **{bd.get('label')}**? "
                "Esta acao nao pode ser desfeita."
            )
            cc1, cc2, _ = st.columns([1, 1, 4])
            with cc1:
                if st.button("Sim, remover", key=f"bd_conf_sim_{idx}", type="primary", use_container_width=True):
                    ok, msg = sb.remover_banco(bd_id)
                    st.session_state.pop("bd_confirmar_remover", None)
                    st.session_state["_msg_bd_acao"] = msg
                    _rerun_mantendo_dialog()
            with cc2:
                if st.button("Cancelar", key=f"bd_conf_nao_{idx}", use_container_width=True):
                    st.session_state.pop("bd_confirmar_remover", None)
                    _rerun_mantendo_dialog()

        # ─── Bloco de edicao inline (aparece quando clicou em editar) ───
        if bd_editando:
            with st.container(border=True):
                st.markdown("##### Editando banco")
                st.caption(f"Banco: **{bd.get('label')}**. Campos em branco preservam os valores atuais.")
                _form_adicionar_ou_editar(bd)



# ============================================================================
# Formulario Adicionar / Editar
# ============================================================================

def _form_adicionar_ou_editar(bd_em_edicao: dict | None = None) -> None:
    """Form para criar um novo banco ou editar um existente."""
    modo_edicao = bd_em_edicao is not None
    titulo = "Editar banco" if modo_edicao else "Adicionar novo banco"

    with st.form(key="form_bd_addedit", clear_on_submit=not modo_edicao):
        st.markdown(f"##### {titulo}")

        col1, col2 = st.columns(2)
        with col1:
            label = st.text_input(
                "Label (nome amigavel) *",
                value=bd_em_edicao.get("label", "") if modo_edicao else "",
                placeholder="Ex.: Brasil - Innova V2 (producao)",
            )
            project_id = st.text_input(
                "Project ID *",
                value=bd_em_edicao.get("project_id", "") if modo_edicao else "",
                placeholder="awosfxlcjqotforkixps",
            )
            region = st.text_input(
                "Region",
                value=bd_em_edicao.get("region", "") if modo_edicao else "",
                placeholder="aws-1-sa-east-1",
            )
        with col2:
            supabase_url = st.text_input(
                "Supabase URL *",
                value=bd_em_edicao.get("supabase_url", "") if modo_edicao else "",
                placeholder="https://awosfxlcjqotforkixps.supabase.co",
            )
            db_password = st.text_input(
                "DB Password",
                value="",
                type="password",
                placeholder="(deixe vazio pra manter a atual)" if modo_edicao else "Senha do BD",
            )

        st.markdown("**Chaves JWT** (campos opcionais - em edicao, vazio mantem o valor atual)")
        anon_key = st.text_area(
            "Anon Key (eyJhbGciOi...)",
            value="",
            height=68,
            placeholder="(deixe vazio pra manter a atual)" if modo_edicao else "Cole o JWT da anon key",
        )
        service_role = st.text_area(
            "Service Role Key (eyJhbGciOi...)",
            value="",
            height=68,
            placeholder="(deixe vazio pra manter a atual)" if modo_edicao else "Cole o JWT da service_role",
        )
        database_url = st.text_input(
            "Database URL (Transaction Pooler - porta 6543)",
            value="",
            placeholder="(deixe vazio pra manter a atual)" if modo_edicao else "postgresql://postgres.<id>:<senha>@aws-1-sa-east-1.pooler.supabase.com:6543/postgres",
        )

        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            submit = st.form_submit_button(
                "Salvar" if modo_edicao else "Cadastrar",
                use_container_width=True,
                type="primary",
            )
        with col_btn2:
            cancelar = st.form_submit_button("Cancelar", use_container_width=True)

        if cancelar:
            st.session_state.pop("bd_editando_id", None)
            st.session_state.pop("bd_mostrando_form", None)
            _rerun_mantendo_dialog()

        if submit:
            if modo_edicao:
                campos = {
                    "label": label,
                    "project_id": project_id,
                    "region": region,
                    "supabase_url": supabase_url.rstrip("/") if supabase_url else "",
                    "anon_key": anon_key.strip(),
                    "service_role": service_role.strip(),
                    "database_url": database_url.strip(),
                    "db_password": db_password,
                }
                ok, msg = sb.atualizar_banco(bd_em_edicao["id"], campos)
            else:
                ok, msg, _id = sb.adicionar_banco(
                    label=label,
                    project_id=project_id,
                    region=region,
                    supabase_url=supabase_url,
                    anon_key=anon_key.strip(),
                    service_role=service_role.strip(),
                    database_url=database_url.strip(),
                    db_password=db_password,
                )
            (st.success if ok else st.error)(msg)
            if ok:
                st.session_state.pop("bd_editando_id", None)
                st.session_state.pop("bd_mostrando_form", None)
                _rerun_mantendo_dialog()


# ============================================================================
# Bloco de bootstrap (importar br-credentials.json)
# ============================================================================

def _bloco_bootstrap_inicial() -> None:
    """Bloco de import inicial - mostrado APENAS quando o pool esta vazio."""
    st.info("Nenhum banco cadastrado ainda. Voce pode importar o `br-credentials.json` de 2 jeitos:")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**A) Buscar no projeto**")
        st.caption("Procura nos caminhos conhecidos (raiz, Migracao BD/...).")
        if st.button("Importar do disco", type="primary", use_container_width=True, key="btn_import_disk"):
            ok, msg = sb.bootstrap_do_br_credentials()
            (st.success if ok else st.warning)(msg)
            if ok:
                _rerun_mantendo_dialog()

    with col_b:
        st.markdown("**B) Subir JSON manualmente**")
        st.caption("Arraste o br-credentials.json aqui.")
        arquivo = st.file_uploader(
            "Upload do br-credentials.json",
            type=["json"],
            key="upload_br_creds",
            label_visibility="collapsed",
        )
        if arquivo is not None:
            import json as _json
            try:
                creds = _json.loads(arquivo.read().decode("utf-8"))
                pid = creds.get("project_id", "")
                if not pid:
                    st.error("JSON invalido: faltou project_id.")
                else:
                    ok, msg, _id = sb.adicionar_banco(
                        label=creds.get("name", "Importado via upload"),
                        project_id=pid,
                        region=creds.get("region", ""),
                        supabase_url=creds.get("supabase_url", ""),
                        anon_key=creds.get("anon_key", ""),
                        service_role=creds.get("service_role", ""),
                        database_url=creds.get("database_url", ""),
                        db_password=creds.get("db_password", ""),
                        tornar_primary=True,
                    )
                    (st.success if ok else st.error)(msg)
                    if ok:
                        _rerun_mantendo_dialog()
            except Exception as e:
                st.error(f"Falha ao ler JSON: {e}")


# ============================================================================
# Render principal - funcao publica chamada pelo app.py
# ============================================================================

def render_pagina_config_bd() -> None:
    """Renderiza o carrossel completo de bancos de dados.

    Chame esta funcao no app.py, dentro do modal de Configuracoes,
    no ramo `elif opcao == "Banco de Dados (Innova V2)":`.
    """
    _css_local()

    # ============================================================
    # CABECALHO DA PAGINA (igual Motores IA - app.py linhas 267-268)
    # ============================================================
    st.subheader("Banco de Dados — Supabase Multi-Pool")
    st.caption(
        "Pool de bancos Supabase compartilhados com o Innova V2 (Next.js). "
        "Suporta multi-tenant (Brasil producão, EUA legado, staging futuros). "
        "O banco marcado como **EM USO** é o que o Python lê e escreve."
    )

    bancos = sb.listar_bancos(decifrar_para_ui=False)

    # ============================================================
    # PAINEL 1 - Carrossel (espelha o LiteLLM Painel 1)
    # ============================================================
    with st.container(border=True):

        # Cabecalho com CTA destacado no topo (igual app.py linha 274-286)
        col_titulo, col_btn_novo = st.columns([3, 1])
        with col_titulo:
            st.markdown("##### 💾 Bancos Configurados")
        with col_btn_novo:
            if st.button(
                "➕ Adicionar Novo Banco",
                key="btn_abrir_inserir_bd_topo",
                type="primary",
                use_container_width=True,
                help="Cadastrar manualmente um novo banco Supabase no pool.",
            ):
                st.session_state["bd_mostrando_form"] = True
                st.session_state.pop("bd_editando_id", None)
                _rerun_mantendo_dialog()

        # Placeholder pro form (tecnica do teleporte do LiteLLM linha 301)
        _form_placeholder = st.empty()

        # Bootstrap auto-mostrado quando o pool esta vazio E ninguem clicou em Adicionar
        if not bancos:
            if not st.session_state.get("bd_mostrando_form"):
                _bloco_bootstrap_inicial()
        else:
            st.markdown(f"**{len(bancos)} banco(s) no pool:**")

            ordem_status = {"active": 0, "reserve": 1, "untested": 2, "offline": 3}
            bancos_ord = sorted(
                bancos,
                key=lambda b: (not b.get("is_primary"), ordem_status.get(b.get("status", "untested"), 9)),
            )
            for idx, bd in enumerate(bancos_ord):
                _card_banco(bd, idx)

        # Renderiza o form de ADICIONAR no placeholder
        # (Edicao agora e INLINE dentro do proprio card via bd_editando_inline_id)
        if st.session_state.get("bd_mostrando_form", False):
            with _form_placeholder.container():
                _form_adicionar_ou_editar(None)

    # ============================================================
    # Rodape de diagnostico (sutil)
    # ============================================================
    with st.expander("Diagnostico tecnico", expanded=False):
        from utils_cripto import chave_existe, caminho_chave_str

        # ── BOTAO: rodar diagnostico de rede granular ──
        bd_ativo = sb.get_active_bd_decifrado()
        if bd_ativo:
            st.markdown("**Diagnostico de rede do BD em uso**")
            st.caption(
                "Mede separadamente DNS, TCP, TLS e 5 pings HTTP em sequencia "
                "(com sessao reaproveitada). Util para entender se a latencia "
                "alta vem de handshake (esperado, primeiro hit) ou de rota ruim."
            )
            if st.button(
                "Rodar diagnostico de rede",
                key="btn_diag_rede",
                help="Faz DNS lookup + TCP connect + TLS handshake + 5 HTTP HEADs com sessao reaproveitada.",
            ):
                with st.spinner("Rodando diagnostico (pode levar 3-5s)..."):
                    diag = sb.diagnostico_rede_supabase(bd_ativo["id"], n_pings=5)
                st.session_state["_diag_rede_result"] = diag
                _rerun_mantendo_dialog()

            # Renderiza ultimo resultado se existir
            if "_diag_rede_result" in st.session_state:
                d = st.session_state["_diag_rede_result"]
                if d.get("erros"):
                    for e in d["erros"]:
                        st.error(e)
                st.markdown(f"**Host pingado:** `{d.get('host')}` &middot; IP: `{d.get('resolved_ip', '-')}` &middot; Porta: `{d.get('porta')}`", unsafe_allow_html=True)

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("DNS lookup", f"{d.get('dns_ms', '-')} ms")
                with col2:
                    st.metric("TCP connect", f"{d.get('tcp_ms', '-')} ms")
                with col3:
                    st.metric("TLS handshake", f"{d.get('tls_ms', '-')} ms")
                with col4:
                    st.metric("HTTP 1o (frio)", f"{d.get('http_first_ms', '-')} ms")

                if d.get("http_warm_ms"):
                    st.markdown("**Pings HTTP warm (session reaproveitada — esta e a latencia REAL):**")
                    cw1, cw2, cw3 = st.columns(3)
                    with cw1:
                        st.metric("Min warm", f"{d.get('http_min_warm')} ms")
                    with cw2:
                        st.metric("Media warm", f"{d.get('http_avg_warm')} ms", delta=f"vs frio: -{d.get('http_first_ms') - d.get('http_avg_warm')} ms")
                    with cw3:
                        st.metric("Max warm", f"{d.get('http_max_warm')} ms")
                    st.caption(f"Pings individuais: {d.get('http_warm_ms')}")

                st.caption(
                    "**Interpretacao:** o ping warm e o tempo real de uma requisicao "
                    "HTTP quando a conexao ja esta estabelecida. Essa e a latencia "
                    "que vamos ter quando o `asyncpg` conectar via pooler (porta 6543) "
                    "e reutilizar a conexao para multiplas queries."
                )

                if st.button("Limpar resultado", key="btn_diag_limpar"):
                    st.session_state.pop("_diag_rede_result", None)
                    _rerun_mantendo_dialog()
            st.divider()

            # ── F1: BOTAO TESTAR CONEXAO SQL REAL VIA ASYNCPG ──
            st.markdown("**Conexao SQL real (asyncpg)**")
            st.caption(
                "Conecta no pooler PostgreSQL (porta 6543), roda SELECT version(), "
                "conta linhas das 22 tabelas do schema e lista schools + students. "
                "Esta e a prova viva de que Python consegue ler do mesmo BD que o Next.js."
            )
            if st.button(
                "Testar conexao SQL real",
                key="btn_asyncpg_test",
                help="Cria pool asyncpg + roda 4 queries de validacao. Demora 1-3s no cold start.",
            ):
                try:
                    from innova_bridge.db import run_async, get_pool, queries_basicas
                    with st.spinner("Conectando ao Supabase BR (pool asyncpg cold start)..."):
                        t0 = time.perf_counter() if False else None  # placeholder p/ futuro
                        pool = run_async(get_pool())
                        val, ms_um = run_async(queries_basicas.selecionar_um(pool))
                        v_text, ms_v = run_async(queries_basicas.obter_versao_pg(pool))
                        inventario = run_async(queries_basicas.inventario_completo(pool))
                        schools, ms_sch = run_async(queries_basicas.listar_schools(pool))
                        students, ms_stu = run_async(queries_basicas.listar_students(pool))
                    st.session_state["_asyncpg_result"] = {
                        "selecionar_um": (val, ms_um),
                        "versao": (v_text, ms_v),
                        "inventario": inventario,
                        "schools": (schools, ms_sch),
                        "students": (students, ms_stu),
                    }
                    _rerun_mantendo_dialog()
                except Exception as e:
                    import traceback
                    st.error(f"Falha ao conectar: **{type(e).__name__}** - {e}")
                    with st.expander("Ver traceback completo (debug)"):
                        st.code(traceback.format_exc())

            # ── Renderiza ultimo resultado asyncpg se houver ──
            if "_asyncpg_result" in st.session_state:
                r = st.session_state["_asyncpg_result"]

                cca, ccb = st.columns(2)
                with cca:
                    v, ms_um = r["selecionar_um"]
                    st.metric("SELECT 1", f"{ms_um} ms", help=f"Valor retornado: {v}")
                with ccb:
                    v_text, ms_v = r["versao"]
                    st.metric("SELECT version()", f"{ms_v} ms")
                st.code(r["versao"][0], language="text")

                # Inventario das 22 tabelas
                st.markdown("**Inventario das 22 tabelas do schema:**")
                inv = r["inventario"]
                # Renderiza como tabela simples (sem pandas pra nao forcar import)
                cabec = "| Tabela | Linhas | Tempo | Erro |\n|---|---:|---:|---|"
                linhas_md = [cabec]
                for row in inv:
                    count_str = str(row["count"]) if row["count"] is not None else "—"
                    erro_str = row["erro"] or ""
                    linhas_md.append(f"| `{row['tabela']}` | {count_str} | {row['ms']} ms | {erro_str} |")
                st.markdown("\n".join(linhas_md))

                # Schools + Students preview
                st.markdown("---")
                cs, cu = st.columns(2)
                with cs:
                    schools_list, _ms = r["schools"]
                    st.markdown(f"**Schools ({len(schools_list)} linha(s)):**")
                    if schools_list:
                        for s in schools_list:
                            st.markdown(f"- **{s.get('name', '?')}** (`slug={s.get('slug', '?')}`, id=`{s.get('id', '?')[:8]}...`)")
                    else:
                        st.caption("(Vazio)")
                with cu:
                    students_list, _ms = r["students"]
                    st.markdown(f"**Students ({len(students_list)} linha(s)):**")
                    if students_list:
                        for s in students_list:
                            st.markdown(f"- `{s.get('code', '?')}` - {s.get('full_name', '?')}")
                    else:
                        st.caption("(Vazio)")

                if st.button("Limpar resultado SQL", key="btn_asyncpg_limpar"):
                    st.session_state.pop("_asyncpg_result", None)
                    _rerun_mantendo_dialog()
            st.divider()
        from utils_cripto import chave_existe, caminho_chave_str
        st.markdown(
            f"""
            - **Pool em disco:** `bancos_pool.json` {'(existe)' if sb.arquivo_pool_existe() else '(ainda nao criado)'}
            - **Chave de criptografia:** {'Gerada' if chave_existe() else 'Nao gerada'} em `{caminho_chave_str()}`
            - **Bancos cadastrados:** {len(bancos)}
            - **Ativo principal:** {sum(1 for b in bancos if b.get('is_primary'))}
            - **Como o resto do sistema le o BD ativo:** `storage_bancos.get_active_bd_decifrado()` ->
              dict com `database_url`/`anon_key`/`service_role` em texto puro pra montar a conexao.
            """
        )
