import streamlit as st
import os
import json
import time

# --- REGRA DE OURO 3: Blindagem de Importação ---
try: 
    import backend_alunos as bk
except ImportError: 
    bk = None

# ─── F1.5: Adapter Supabase BR (Innova V2) — fonte alternativa de alunos ───
# Falha silenciosa: se innova_bridge nao estiver disponivel ou asyncpg ausente,
# o toggle de origem nao exibe a opcao Supabase.
try:
    from pagina_pai_renderer import render_pai_view_from_fixture, render_pai_view
except Exception:
    render_pai_view_from_fixture = None
    render_pai_view = None

try:
    from aluno_questionario_base import render_questionario_base_tab
except Exception:
    render_questionario_base_tab = None

try:
    from innova_bridge.repositories import students_repo
except Exception:
    students_repo = None

erro_real_ocr = None
try: 
    import backend_ocr as ocr
except Exception as e: 
    ocr = None
    erro_real_ocr = str(e)

try:
    import backend_rag_export as rag
except ImportError:
    rag = None

try:
    import pagina_debug_ocr as debug_page
except ImportError:
    debug_page = None

# Acesso aos moldes treinados (Página de Treinamento de Molde)
try:
    import backend_molde as bmolde
except Exception:
    bmolde = None


# --- MODAL: NOVO ALUNO ---
@st.dialog("🎒 Cadastrar Novo Aluno")
def modal_novo_aluno():
    st.caption("O sistema gerará um ID Anonimizado automaticamente para uso na Inteligência Artificial.")
    apelido = st.text_input("Apelido / Primeiro Nome")
    
    col1, col2 = st.columns(2)
    serie = col1.selectbox("Série", ["6o ano", "7o ano", "8o ano", "9o ano", "1o ano EM", "2o ano EM", "3o ano EM"])
    turma = col2.text_input("Turma (Ex: 1601)")
    
    if st.button("Salvar Cadastro", type="primary", use_container_width=True):
        if apelido and turma:
            if bk and bk.criar_aluno(apelido, serie, turma):
                st.toast("Aluno cadastrado com sucesso!", icon="✅")
                st.rerun()
            else:
                st.error("Erro ao conectar com o banco de dados local.")
        else:
            st.warning("Preencha o apelido e a turma.")


def render_pagina_alunos():
    if 'aluno_selecionado' not in st.session_state:
        st.session_state.aluno_selecionado = None

    if st.session_state.aluno_selecionado is None:
        render_lista_geral()
    else:
        render_prontuario_aluno(st.session_state.aluno_selecionado)

def _origem_dados() -> str:
    """Retorna a origem ativa: 'sqlite' (default) ou 'supabase'.

    Persiste em session_state. Se innova_bridge nao estiver disponivel,
    forca 'sqlite'.
    """
    if students_repo is None:
        return "sqlite"
    return st.session_state.get("alunos_origem", "supabase")  # [REORG] default = Supabase BR


def _render_toggle_origem() -> None:
    """Renderiza o radio de selecao de origem no topo da pagina."""
    if students_repo is None:
        st.caption(":grey[Fonte: SQLite local (innova_bridge indisponivel)]")
        return

    cor_origem = st.session_state.get("alunos_origem", "supabase")  # [REORG] default = Supabase BR
    cols_orig = st.columns([3, 2])
    with cols_orig[1]:
        nova = st.radio(
            "Origem dos dados",
            options=["sqlite", "supabase"],
            format_func=lambda v: "SQLite Local" if v == "sqlite" else "Supabase BR (Innova V2)",
            index=0 if cor_origem == "sqlite" else 1,
            horizontal=True,
            key="alunos_origem_radio",
            label_visibility="collapsed",
        )
        if nova != cor_origem:
            st.session_state["alunos_origem"] = nova
            try:
                students_repo.invalidar_cache()
            except Exception:
                pass
            st.rerun()


def _buscar_lista_alunos_roteado():
    """Roteia entre backend_alunos (SQLite) ou students_repo (Supabase)."""
    if _origem_dados() == "supabase" and students_repo is not None:
        return students_repo.listar_alunos_supabase()
    return bk.buscar_lista_alunos() if bk else None


def _obter_detalhes_aluno_roteado(aluno_id):
    """Roteia entre backend_alunos (SQLite) ou students_repo (Supabase)."""
    if _origem_dados() == "supabase" and students_repo is not None:
        return students_repo.obter_detalhes_aluno_supabase(str(aluno_id))
    return bk.obter_detalhes_aluno(aluno_id) if bk else None


def render_lista_geral():
    # ─── Cabecalho da pagina (titulo + descricao + toggle origem) ───
    col_titulo, col_origem = st.columns([3, 2])
    with col_titulo:
        st.title("Alunos")
        st.caption(
            "Lista de estudantes cadastrados. Use o filtro de turma e o campo de busca "
            "para encontrar rapidamente; o cadastro novo abre num diálogo."
        )
    with col_origem:
        st.markdown("<br>", unsafe_allow_html=True)
        _render_toggle_origem()

    origem = _origem_dados()

    if origem == "sqlite" and not bk:
        st.error("Backend de alunos (SQLite) inoperante.")
        return
    if origem == "supabase" and students_repo is None:
        st.error("Adapter Supabase nao disponivel - verifique innova_bridge.")
        return

    try:
        df = _buscar_lista_alunos_roteado()
    except Exception as e:
        st.error(f"Falha ao buscar alunos ({origem}): **{type(e).__name__}** - {e}")
        with st.expander("Ver traceback"):
            import traceback as _tb
            st.code(_tb.format_exc())
        return
    if df is None:
        st.error("Nenhuma fonte de dados disponivel.")
        return

    # ─── Barra de ferramentas unificada (busca + turma + importar + novo) ───
    # Inspirada no padrao do Next.js: filtros a esquerda, CTAs a direita.
    col_busca, col_turma, col_import, col_novo = st.columns([3, 2, 1.4, 1.2])

    with col_busca:
        busca = st.text_input(
            "Buscar por nome",
            placeholder="Digite ao menos 2 letras",
            key="alunos_filtro_busca",
        )

    with col_turma:
        # Opcoes dinamicas a partir do DataFrame atual
        if not df.empty and "turma" in df.columns:
            turmas_unicas = sorted([t for t in df["turma"].dropna().unique() if t and t != "-"])
        else:
            turmas_unicas = []
        opcoes_turma = ["Todas as turmas"] + turmas_unicas
        turma_sel = st.selectbox(
            "Turma",
            opcoes_turma,
            key="alunos_filtro_turma",
        )

    with col_import:
        st.markdown("<br>", unsafe_allow_html=True)
        # Wrapper st.container(key=) gera classe .st-key-bd-importar-planilha no DOM,
        # permitindo CSS especifico que vence o sabotador do stHorizontalBlock.
        with st.container(key="bd-importar-planilha"):
            if st.button(
                "📥 Importar planilha",
                key="btn_importar_planilha",
                use_container_width=True,
                help="Em breve: importar lista de alunos via XLSX/CSV.",
            ):
                st.toast("Em breve — funcionalidade na proxima sprint.", icon="🚧")

    with col_novo:
        st.markdown("<br>", unsafe_allow_html=True)
        # type="primary" + use_container_width — EXATAMENTE como "Novo Questionario"
        if st.button(
            "+ Novo Aluno",
            key="btn_novo_aluno_topo",
            type="primary",
            use_container_width=True,
        ):
            modal_novo_aluno()

    # ─── Aplica filtros (busca por nome + turma) ───
    total_antes = len(df)
    if busca and len(busca) >= 2:
        df = df[df["apelido"].str.contains(busca, case=False, na=False)]
    if turma_sel and turma_sel != "Todas as turmas":
        df = df[df["turma"] == turma_sel]
    total_depois = len(df)

    if df.empty:
        if total_antes == 0:
            st.info("Nenhum aluno cadastrado. Clique em **+ Novo Aluno** para começar.")
        else:
            st.warning(f"Nenhum aluno encontrado com os filtros aplicados ({total_antes} no total).")
        return

    # ───────────────────────────────────────────────────────────────────
    # TABELA COMPACTA v2 — densa, com nome, separação clara e ícone de ação
    # ───────────────────────────────────────────────────────────────────
    if total_depois < total_antes:
        st.caption(f"📋 **{total_depois} de {total_antes}** aluno(s) — filtros aplicados · origem: `{origem}`")
    else:
        st.caption(f"📋 **{total_antes} aluno(s) cadastrado(s)** · origem: `{origem}`")

    st.markdown(
        """
        <style>
        .alunos-cell {
            padding: 8px 4px;
            font-size: 0.92em;
            border-bottom: 1px solid #e6e6e6;
            min-height: 38px;
            display: flex;
            align-items: center;
        }
        .alunos-cell-alt { background: #fafafa; }
        .alunos-badge-ppo {
            display: inline-block;
            background: #e7f0fb;
            color: #1f4e79;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 500;
        }
        .alunos-badge-ppo-zero {
            display: inline-block;
            background: #f5f5f5;
            color: #999;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.85em;
        }
        .alunos-badge-quest {
            display: inline-block;
            background: #f0f0f0;
            color: #555;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.85em;
            min-width: 22px;
            text-align: center;
        }
        .alunos-header {
            font-weight: 700;
            font-size: 0.78em;
            color: #555;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 2px solid #999;
            padding-bottom: 8px;
            padding-top: 4px;
        }
        /* ════════════════════════════════════════════════════════════
           BOTOES ESPECIFICOS (override do sabotador do stHorizontalBlock)
           Streamlit 1.36+ - st.container(key=) gera classe .st-key-* no DOM.
           Como sao MAIS ESPECIFICOS, vencem o CSS generico de cima.
           ════════════════════════════════════════════════════════════ */

        /* "Importar planilha" — estilo identico ao "Gerar com IA" */
        .st-key-bd-importar-planilha button,
        div.st-key-bd-importar-planilha button {
            border: 1px solid rgba(49, 51, 63, 0.2) !important;
            background: #ffffff !important;
            background-color: #ffffff !important;
            color: #31333F !important;
            border-radius: 8px !important;
            padding: 4px 16px !important;
            min-height: 38px !important;
            height: auto !important;
            font-size: 1em !important;
            font-weight: 400 !important;
            line-height: 1.5 !important;
            box-shadow: none !important;
            transition: all 0.15s ease !important;
        }
        .st-key-bd-importar-planilha button:hover,
        div.st-key-bd-importar-planilha button:hover {
            border-color: #d62728 !important;
            color: #d62728 !important;
            background: #fff5f5 !important;
        }

        /* "Entrar" (🔍) - fundo preto, lupa branca */
        div[class*="st-key-bd-entrar-"] button {
            background: #1f1f1f !important;
            background-color: #1f1f1f !important;
            color: #ffffff !important;
            border: 1px solid #1f1f1f !important;
            border-radius: 6px !important;
            padding: 2px 12px !important;
            min-height: 32px !important;
            height: 32px !important;
            font-size: 1em !important;
            line-height: 1 !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1) !important;
            transition: all 0.15s ease !important;
        }
        div[class*="st-key-bd-entrar-"] button:hover {
            background: #333333 !important;
            background-color: #333333 !important;
            border-color: #d62728 !important;
            transform: translateY(-1px) !important;
            box-shadow: 0 3px 6px rgba(0,0,0,0.25) !important;
        }

        /* Header da coluna AÇÃO — espaço fantasma sem borda, mesma altura
           pra grid não desalinhar */
        .alunos-header-empty {
            border-bottom: 2px solid transparent;
            padding-bottom: 8px;
            padding-top: 4px;
            font-size: 0.78em;
            height: auto;
        }
        .alunos-nome { font-weight: 600; color: #222; }
        /* Wrapper .stButton — zera margem/padding pra ícone alinhar com
           o texto das outras células (Streamlit envolve botão em div extra) */
        div[data-testid="stHorizontalBlock"] .stButton {
            margin: 0 !important;
            padding: 0 !important;
            line-height: 0 !important;
        }
        /* Botão da coluna AÇÃO — vira ÍCONE PURO clicável sem borda.
           Seletores múltiplos pra pegar qualquer versão do Streamlit.
           CRITICO: :not([kind="primary"]) — caso contrário esse CSS apaga
           o vermelho de qualquer botão primary que esteja em columns()
           (ex: "+ Novo Aluno" da barra de filtros). */
        div[data-testid="stHorizontalBlock"] .stButton > button:not([kind="primary"]),
        div[data-testid="stHorizontalBlock"] button[kind="secondary"],
        div[data-testid="stHorizontalBlock"] button[data-testid="baseButton-secondary"] {
            border: none !important;
            border-radius: 0 !important;
            background: transparent !important;
            background-color: transparent !important;
            box-shadow: none !important;
            padding: 0 4px !important;
            margin: 0 !important;
            min-height: 38px !important;
            height: 38px !important;
            font-size: 1.4em !important;
            font-weight: 700 !important;
            line-height: 1 !important;
            color: #1f4e79 !important;
            border-bottom: 1px solid #e6e6e6 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 100% !important;
            cursor: pointer !important;
            transition: color 0.15s ease, transform 0.15s ease;
        }
        div[data-testid="stHorizontalBlock"] .stButton > button:hover,
        div[data-testid="stHorizontalBlock"] button[kind="secondary"]:hover,
        div[data-testid="stHorizontalBlock"] button[data-testid="baseButton-secondary"]:hover {
            color: #d62728 !important;
            transform: translateX(3px);
            background: transparent !important;
        }
        div[data-testid="stHorizontalBlock"] .stButton > button:focus,
        div[data-testid="stHorizontalBlock"] button[kind="secondary"]:focus {
            box-shadow: none !important;
            outline: none !important;
        }
        /* Header da coluna AÇÃO — esconde o separador inferior do label vazio */
        div[data-testid="stHorizontalBlock"]:first-child .alunos-header:empty,
        .alunos-header:empty {
            border-bottom: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Larguras: ID, NOME, SÉRIE, TURMA, PPOs, QUEST, CADASTRO, AÇÃO
    larguras = [0.4, 1.6, 0.9, 0.7, 1.0, 0.6, 1.0, 0.5]
    labels   = ["ID", "Nome", "Série", "Turma", "PPOs", "Quest", "Cadastro", ""]

    with st.container(border=True):
        # Cabeçalho — quando label vazio, NÃO renderiza markdown (evita
        # a linha-fantasma do border-bottom flutuando sobre o ícone abaixo).
        hcols = st.columns(larguras)
        for col, text in zip(hcols, labels):
            if text:
                col.markdown(f"<div class='alunos-header'>{text}</div>",
                             unsafe_allow_html=True)
            else:
                # Header invisível mas ocupa o espaço — só pra alinhar a grid.
                col.markdown("<div class='alunos-header-empty'>&nbsp;</div>",
                             unsafe_allow_html=True)

        # Linhas — uma por aluno
        for i, (_, row) in enumerate(df.iterrows()):
            cells = st.columns(larguras)
            cell_class = "alunos-cell" + (" alunos-cell-alt" if i % 2 else "")

            # PPOs com badge diferente quando zero
            if row['ppos']:
                ppo_html = f"<span class='alunos-badge-ppo'>{row['ppos']} ativo(s)</span>"
            else:
                ppo_html = "<span class='alunos-badge-ppo-zero'>0</span>"

            apelido = row.get('apelido', '—') or '—'

            cells[0].markdown(f"<div class='{cell_class}'>#{row['id']}</div>",
                              unsafe_allow_html=True)
            cells[1].markdown(
                f"<div class='{cell_class} alunos-nome'>{apelido}</div>",
                unsafe_allow_html=True,
            )
            cells[2].markdown(f"<div class='{cell_class}'>{row['serie']}</div>",
                              unsafe_allow_html=True)
            cells[3].markdown(f"<div class='{cell_class}'>{row['turma']}</div>",
                              unsafe_allow_html=True)
            cells[4].markdown(f"<div class='{cell_class}'>{ppo_html}</div>",
                              unsafe_allow_html=True)
            cells[5].markdown(
                f"<div class='{cell_class}'>"
                f"<span class='alunos-badge-quest'>{row['quest']}</span></div>",
                unsafe_allow_html=True,
            )
            cells[6].markdown(f"<div class='{cell_class}'>{row['cadastro']}</div>",
                              unsafe_allow_html=True)
            # Botao "Entrar" — lupa branca no fundo preto via container(key=)
            with cells[7]:
                with st.container(key=f"bd-entrar-{row['id']}"):
                    if st.button(
                        "🔍",
                        key=f"open_{row['id']}",
                        help=f"Abrir dossiê de {apelido}",
                    ):
                        st.session_state.aluno_selecionado = row['id']
                        st.rerun()


def render_prontuario_aluno(aluno_id):
    if st.button("← Voltar para Alunos"):
        st.session_state.aluno_selecionado = None
        st.rerun()

    aluno = _obter_detalhes_aluno_roteado(aluno_id)
    if not aluno:
        st.error("Aluno não encontrado.")
        return

    st.markdown(f"### {aluno['apelido']} — <small>{aluno['serie']} — Turma {aluno['turma']}</small>", unsafe_allow_html=True)

    # As abas herdam o estilo global injetado por utils_estilo.injetar_css_global()
    # no app.py — não precisa repetir CSS aqui.
    tab_info, tab_quest, tab_ppo, tab_debug = st.tabs(["Informações", "Questionário Base", "Perfil Pedagógico", "Relatório IA (Debug)"])

    with tab_info:
        with st.container(border=True):
            ci, ce = st.columns([3, 2])
            ci.subheader("Dossiê do Aluno")
            if ce.button("🧠 Consolidar no RAG (Exportar Estudo de Caso)", type="primary", use_container_width=True):
                if rag:
                    with st.spinner("Compilando dossiê, gerando vetores e sincronizando bancos..."):
                        sucesso, msg = rag.consolidar_estudo_de_caso(aluno_id)
                        if sucesso:
                            st.success(msg)
                            st.balloons()
                        else:
                            st.error(msg)
                else:
                    st.error("Erro: 'backend_rag_export.py' não encontrado.")
            
            # ───────────────────────────────────────────────────────────
            # DOSSIÊ COMPACTO — label inline + valor na MESMA linha,
            # separadores finos entre items, layout 2 colunas pareadas.
            # ───────────────────────────────────────────────────────────
            st.markdown(
                """
                <style>
                .dossie-item {
                    display: flex;
                    align-items: baseline;
                    gap: 8px;
                    padding: 7px 4px;
                    border-bottom: 1px solid #eee;
                    font-size: 0.93em;
                }
                .dossie-label {
                    font-weight: 700;
                    color: #555;
                    font-size: 0.78em;
                    text-transform: uppercase;
                    letter-spacing: 0.4px;
                    min-width: 130px;
                    flex-shrink: 0;
                }
                .dossie-valor { color: #222; font-weight: 500; }
                .dossie-codigo {
                    font-family: 'Courier New', monospace;
                    background: #e7f0fb;
                    color: #1f4e79;
                    padding: 1px 8px;
                    border-radius: 4px;
                    font-size: 0.9em;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )

            c1, c2 = st.columns(2)

            def _item(label, valor, codigo=False):
                cls = "dossie-codigo" if codigo else "dossie-valor"
                return (
                    f"<div class='dossie-item'>"
                    f"<span class='dossie-label'>{label}</span>"
                    f"<span class='{cls}'>{valor}</span>"
                    f"</div>"
                )

            with c1:
                st.markdown(_item("Nome / Apelido", aluno['apelido']),
                            unsafe_allow_html=True)
                st.markdown(_item("Série", aluno['serie']),
                            unsafe_allow_html=True)
                st.markdown(_item("PPOs Ativos", aluno['ppos_ativos']),
                            unsafe_allow_html=True)

            with c2:
                st.markdown(_item("ID Anonimizado", aluno['id_anon'], codigo=True),
                            unsafe_allow_html=True)
                st.markdown(_item("Turma", aluno['turma']),
                            unsafe_allow_html=True)
                st.markdown(_item("Questionários", aluno['questionarios']),
                            unsafe_allow_html=True)

            st.markdown("<div style='margin-top: 12px;'></div>",
                        unsafe_allow_html=True)
            st.button("🗑️ Excluir aluno", type="secondary")

    with tab_quest:
        if render_questionario_base_tab is None:
            st.error("Modulo aluno_questionario_base.py nao carregou. Verifique innova_bridge.")
        else:
            render_questionario_base_tab(aluno_id)


    with tab_ppo:
        render_ppo_tab(aluno_id)

    with tab_debug:
        if debug_page and hasattr(debug_page, 'renderizar'):
            debug_page.renderizar(aluno_id)
        else:
            st.error("Módulo 'pagina_debug_ocr.py' não encontrado.")


def render_ppo_tab(aluno_id):
    # ──────────────────────────────────────────────────────────────────
    # [NOVO F3] — Renderiza PAI v1.0 lendo de innova_bridge/formularios/pais_gerados/
    # Fallback pro fixture se nenhum PAI foi gerado ainda.
    # ──────────────────────────────────────────────────────────────────
    with st.container():
        # Header com botao Refazer
        col_titulo, col_refazer = st.columns([4, 1])
        with col_titulo:
            st.markdown("##### 🧬 Plano de Adaptação Individual (PAI v1.0)")
        with col_refazer:
            if st.button(
                "🔄 Refazer",
                key=f"refazer_pai_{aluno_id}",
                use_container_width=True,
                help="Recarrega o PAI mais recente do disco. "
                     "Pra gerar um novo, vá na aba 'Questionário Base'.",
            ):
                st.session_state.pop(f"pai_cache_{aluno_id}", None)
                st.rerun()

        # [F1 — FONTE ÚNICA] Tenta PRIMEIRO o Supabase: o worker (Backend Central)
        # grava lá, e front + Streamlit leem a MESMA tabela `pais`. Aceita code OU uuid.
        pais_sb = []
        try:
            from innova_bridge.repositories import pais_repo as _pr
            pais_sb = _pr.listar_pais_ativos_supabase(str(aluno_id))
        except Exception:
            pais_sb = []

        # Tenta carregar PAI gerado primeiro (Molde Novo)
        pai_real = None
        meta_persistencia = None
        try:
            from innova_bridge.agents.agente1.persistence import (
                carregar_pai_mais_recente, listar_pais_vigentes,
            )
            pai_real = carregar_pai_mais_recente(str(aluno_id))
            vigentes = listar_pais_vigentes(str(aluno_id))
            if vigentes:
                meta_persistencia = vigentes[0]
        except Exception:
            pai_real = None

        if pais_sb and render_pai_view is not None:
            # FONTE ÚNICA (Supabase): renderiza os PAIs vigentes (1 por família).
            for _item in pais_sb:
                st.caption(
                    f"🟢 {_item.get('familia','?')} · v{_item.get('version','?')} · "
                    f"status: **{_item.get('status','?')}** · "
                    f"origem: **{_item.get('created_via') or '—'}** · "
                    f"`{_item.get('generated_by_agent','?')}` · (Supabase)"
                )
                try:
                    render_pai_view(_item.get("content") or {})
                except Exception as _e:
                    st.warning(f"Falha ao renderizar PAI (Supabase): {_e}")
        elif pai_real is not None and render_pai_view is not None:
            # Banner com metadado da origem
            if meta_persistencia:
                status_emoji = {
                    "active": "🟢", "needs_review": "🟡",
                    "approved": "✅", "superseded": "⚪",
                }.get(meta_persistencia.get("status", "?"), "❔")
                created_by = meta_persistencia.get("created_by", "?")
                versao = meta_persistencia.get("versao", "?")
                st.caption(
                    f"{status_emoji} v{versao} · `{created_by}` · "
                    f"status: **{meta_persistencia.get('status','?')}** · "
                    f"origem: `pais_gerados/{meta_persistencia.get('filename','?')}`"
                )

                # NOVO: linha com infos da LLM usada (modelo, LOCAL/CLOUD, custo)
                # Le de pai_real.meta.llm_meta - PAIs antigos nao tem esse campo.
                llm_meta = (pai_real.get("meta") or {}).get("llm_meta") or {}
                if llm_meta:
                    modelo_curto = llm_meta.get("modelo", "")
                    if "/" in modelo_curto:
                        modelo_curto = modelo_curto.split("/")[-1]
                    if not modelo_curto:
                        modelo_curto = llm_meta.get("provedor", "?")

                    is_local_llm = bool(llm_meta.get("is_local", False))
                    custo_brl = float(llm_meta.get("custo_brl", 0.0) or 0.0)
                    tokens_in = int(llm_meta.get("tokens_in", 0) or 0)
                    tokens_out = int(llm_meta.get("tokens_out", 0) or 0)
                    tempo_s = float(llm_meta.get("tempo_s", 0.0) or 0.0)
                    fallback_used = bool(llm_meta.get("fallback_used", False))
                    # NOVO: auditoria de PROMPT (chars + origem custom/default)
                    prompt_chars = int(llm_meta.get("system_prompt_chars", 0) or 0)
                    prompt_source = str(llm_meta.get("prompt_source", "") or "")

                    # Badge LOCAL/CLOUD inline
                    if is_local_llm:
                        badge_llm = (
                            '<span style="display:inline-block; padding:1px 7px; '
                            'border-radius:999px; font-size:0.7em; font-weight:700; '
                            'background:#e6f4ea; color:#137333; border:1px solid #b6dfb9;">'
                            '🖥️ LOCAL</span>'
                        )
                    else:
                        badge_llm = (
                            '<span style="display:inline-block; padding:1px 7px; '
                            'border-radius:999px; font-size:0.7em; font-weight:700; '
                            'background:#e8f0fe; color:#1967d2; border:1px solid #aecbfa;">'
                            '🌐 CLOUD</span>'
                        )

                    # Formatacao do custo (mostra R$ 0,00 pra grátis)
                    if custo_brl > 0:
                        custo_txt = f"R$ {custo_brl:.4f}"
                    else:
                        custo_txt = "R$ 0,00"

                    fallback_tag = ' · <span style="color:#cc4400;">⚠️ fallback</span>' if fallback_used else ""

                    # Badge de PROMPT (auditoria de A/B):
                    #   custom  -> roxo (prompt customizado via UI Treinamento de Agentes)
                    #   default -> cinza (THIN_SYSTEM hardcoded em hybrid.py)
                    #   native  -> nao mostra (engine nativa nao usa LLM)
                    if prompt_chars > 0 and prompt_source in ("custom", "default"):
                        if prompt_source == "custom":
                            prompt_badge = (
                                f' · <span title="Prompt customizado via UI Treinamento de Agentes" '
                                f'style="display:inline-block; padding:1px 6px; border-radius:999px; '
                                f'font-size:0.95em; font-weight:600; background:#f3e8fd; color:#7b1fa2; '
                                f'border:1px solid #e1bee7;">'
                                f'📝 custom · {prompt_chars}c</span>'
                            )
                        else:
                            prompt_badge = (
                                f' · <span title="Prompt default (THIN_SYSTEM)" '
                                f'style="display:inline-block; padding:1px 6px; border-radius:999px; '
                                f'font-size:0.95em; font-weight:600; background:#f1f3f4; color:#5f6368; '
                                f'border:1px solid #dadce0;">'
                                f'📝 default · {prompt_chars}c</span>'
                            )
                    else:
                        prompt_badge = ""

                    extra_html = (
                        f'<div style="font-size:0.78em; color:#666; margin-top:-6px;">'
                        f'🤖 {badge_llm} <code style="background:#f5f5f5; padding:1px 5px; '
                        f'border-radius:3px;">{modelo_curto}</code> · '
                        f'💰 <strong>{custo_txt}</strong> · '
                        f'📥 {tokens_in} in / 📤 {tokens_out} out · '
                        f'⏱️ {tempo_s:.1f}s'
                        f'{prompt_badge}'
                        f'{fallback_tag}'
                        f'</div>'
                    )
                    st.markdown(extra_html, unsafe_allow_html=True)

                    # ----- EXPANDER: Detalhes tecnicos (auditoria de reprodutibilidade) -----
                    audit_sig = llm_meta.get("audit_signature", "") or ""
                    seed_used = llm_meta.get("seed_used")
                    temp_used = llm_meta.get("temperature_used")
                    fj_used = llm_meta.get("force_json_used")
                    digest = llm_meta.get("model_digest", "") or ""
                    quant = llm_meta.get("model_quantization", "") or ""
                    fam = llm_meta.get("model_family", "") or ""
                    psize = llm_meta.get("model_param_size", "") or ""
                    ov = llm_meta.get("ollama_version", "") or ""
                    sysfp = llm_meta.get("system_fingerprint", "") or ""

                    # So mostra se houver alguma info de reprodutibilidade
                    has_repro_info = (
                        audit_sig or seed_used is not None or digest or sysfp
                    )
                    if has_repro_info:
                        with st.expander(
                            "📋 Detalhes técnicos (auditoria de reprodutibilidade)",
                            expanded=False,
                        ):
                            st.markdown(
                                "**Assinatura de auditoria** (PAIs com mesma assinatura "
                                "produzem output idêntico no mesmo backend):"
                            )
                            st.code(audit_sig or "n/a", language="text")

                            col_l, col_r = st.columns(2)
                            with col_l:
                                st.markdown("**Parâmetros usados**")
                                seed_txt = (
                                    f"`{seed_used}`" if seed_used is not None
                                    else "_aleatório (não fixo)_"
                                )
                                temp_txt = (
                                    f"`{temp_used}`" if temp_used is not None
                                    else "_default do sistema_"
                                )
                                fj_txt = (
                                    f"`{fj_used}`" if fj_used is not None
                                    else "_auto_"
                                )
                                st.markdown(
                                    f"- Seed: {seed_txt}\n"
                                    f"- Temperature: {temp_txt}\n"
                                    f"- Force JSON: {fj_txt}\n"
                                    f"- Prompt: `{prompt_chars}` chars"
                                    f" ({prompt_source or '?'})"
                                )

                            with col_r:
                                st.markdown("**Backend / Modelo**")
                                if is_local_llm:
                                    digest_short = (
                                        digest[:32] + "..." if len(digest) > 32
                                        else (digest or "_n/a_")
                                    )
                                    st.markdown(
                                        f"- Digest: `{digest_short}`\n"
                                        f"- Quantização: `{quant or '?'}`\n"
                                        f"- Família: `{fam or '?'}`\n"
                                        f"- Tamanho: `{psize or '?'}`\n"
                                        f"- Ollama: `{ov or '?'}`"
                                    )
                                else:
                                    fp_short = (
                                        sysfp[:32] + "..." if len(sysfp) > 32
                                        else (sysfp or "_não devolvido_")
                                    )
                                    st.markdown(
                                        f"- System fingerprint:\n  `{fp_short}`\n"
                                        f"- Backend: cloud (digest não aplicável)"
                                    )

                            st.caption(
                                "💡 Pra reproduzir esse PAI em outra máquina: "
                                "mesmo modelo + mesmo digest + mesma quantização + "
                                "mesmo seed + mesma temperature + mesmo prompt = "
                                "**mesmo output byte-idêntico**."
                            )
            try:
                render_pai_view(pai_real)
            except Exception as _e:
                st.warning(f"Falha ao renderizar PAI real: {_e}. Caindo no fixture.")
                if render_pai_view_from_fixture is not None:
                    render_pai_view_from_fixture(student_code=str(aluno_id))
        elif render_pai_view_from_fixture is not None:
            st.caption(
                "⚠️ Nenhum PAI gerado pelo Molde Novo ainda. "
                "Renderizando do fixture (Innova V2). "
                "Pra gerar PAI real, vá em **Questionário Base → 🆕 Molde Novo → Gerar PAI**."
            )
            try:
                render_pai_view_from_fixture(student_code=str(aluno_id))
            except Exception as _e:
                st.info(f"PAI ainda não gerado para este aluno ({type(_e).__name__}).")
        else:
            st.info("Módulo de renderização do PAI não disponível.")

        st.divider()

    # ──────────────────────────────────────────────────────────────────
    # Conteudo LEGADO (mantido intacto) — PPO antigo OCR-based
    # ──────────────────────────────────────────────────────────────────
    cores = {0: "#E0E0E0", 1: "#00FF7F", 2: "#00e676", 3: "#FFA500", 4: "#FF4500", 5: "#D32F2F"}
    
    ph, pa, pm = st.columns([2, 1, 1])
    ph.subheader("Perfis Pedagógicos (PPO) — Legado")
    pa.button("✨ Gerar com IA", use_container_width=True)
    pm.button("+ Manual", use_container_width=True)

    if 'ultima_telemetria' in st.session_state:
        t = st.session_state['ultima_telemetria']
        st.info(f"📊 **IA:** {t.get('modelo', 'Gemini')} | **In:** {t.get('in', 0)} | **Out:** {t.get('out', 0)} | **Custo:** R$ {t.get('brl', 0):.4f}")

    caminho_cache = f"ocr_cache_{aluno_id}.json"
    if os.path.exists(caminho_cache):
        with open(caminho_cache, "r", encoding="utf-8") as f:
            ppo_data = json.load(f)

        for categoria, itens in ppo_data.items():
            # Pula metadados (_meta) — não é categoria
            if categoria.startswith("_"):
                continue
            if not isinstance(itens, list):
                continue
            st.markdown(f"**{categoria}**")
            for i in itens:
                with st.container(border=True):
                    col_txt, col_graph = st.columns([2, 2])
                    item_nome = i.get('pergunta', 'Item Desconhecido')
                    valor = i.get('escala', 0)
                    
                    col_txt.markdown(f"**{item_nome}**")
                    cor_barra = cores.get(valor, "#E0E0E0")
                    porcentagem = (valor / 5) * 100
                    
                    col_graph.markdown(f"""
                        <div style="background-color: #f0f2f6; border-radius: 10px; width: 100%; height: 12px; margin-top:10px;">
                            <div style="background-color: {cor_barra}; width: {porcentagem}%; height: 12px; border-radius: 10px;"></div>
                        </div>
                    """, unsafe_allow_html=True)
    else:
        st.info("Nenhum dado encontrado para o gráfico.")
