import streamlit as st
import os
import time
import json
import re

# --- AUTOSTART DO BACKEND CENTRAL (worker Python) ---
# Sobe o worker automaticamente junto com o Streamlit. Idempotente: só dispara
# se NÃO houver heartbeat fresco no Supabase (evita duplicados em reruns).
# Assim não é preciso ligar o worker na mão.
@st.cache_resource
def _autostart_backend_central():
    from innova_bridge.workers.autostart import ensure_worker_running
    return ensure_worker_running()


_autostart_backend_central()

# --- IMPORTS DE PÁGINAS E BACKENDS ---
try:
    import pagina_diagnostico
except ImportError:
    pagina_diagnostico = None

try:
    from funcoes_fla import (
        load_key, save_key, registrar_consumo,
        ler_taxas_local, atualizar_taxas_local,
        info_dolar, obter_dolar_persistido, atualizar_dolar_agora
    )
except ImportError:
    st.error("Arquivo 'funcoes_fla.py' não encontrado na raiz.")
    def info_dolar(): return {"valor": 5.25, "atualizado_em": "—"}
    def obter_dolar_persistido(): return 5.25
    def atualizar_dolar_agora(): return False, {"valor": 5.25, "atualizado_em": "—"}, "indisponível"

try:
    from funcoes_lab import (
        testar_conexao_gemini,
        listar_modelos_disponiveis,
        testar_modelo_especifico,
        save_model_pref, load_model_pref
    )
except ImportError:
    st.error("Arquivo 'funcoes_lab.py' não encontrado.")

try:
    from backend_infra import (
        load_db_config, save_db_config, testar_conexao_postgres,
        load_mcp_config, save_mcp_config
    )
except ImportError:
    st.warning("Aviso: 'backend_infra.py' (Módulo de Configuração de BD) incompleto ou ausente.")
    save_db_config = None
    testar_conexao_postgres = None
    save_mcp_config = None
    load_mcp_config = None

# --- [NOVO] IMPORTS DO CARROSSEL GEMINI ---
try:
    from storage_gemini import (
        load_gemini_pool, save_gemini_pool, get_next_valid_key,
        mark_key_as_standby, add_key_to_pool,
        reset_key_standby, set_key_as_primary  # <--- ADICIONADOS AQUI
    )
except ImportError:
    st.error("🚨 ERRO CRÍTICO: Arquivo 'storage_gemini.py' não encontrado na mesma pasta do app.py!")
    # Estas linhas abaixo são "curativos". Elas impedem o App de quebrar se o arquivo sumir.
    def add_key_to_pool(k): return False, "Erro: Arquivo storage_gemini.py não existe!"
    def load_gemini_pool(): return []
    def get_next_valid_key(): return None
    def mark_key_as_standby(k): pass
    def reset_key_standby(k): pass       # <--- ADICIONADO AQUI
    def set_key_as_primary(k): pass      # <--- ADICIONADO AQUI


# --- [NOVO F2] IMPORT DA PAGINA DE AGENTES (Sistema Adaptativo v2.0) ---
try:
    from pagina_agentes import render_pagina_agentes
except Exception as _e_agt:
    st.warning(f"Aviso: 'pagina_agentes.py' nao carregado ({type(_e_agt).__name__}).")
    def render_pagina_agentes():
        st.error("Modulo de Agentes inoperante.")

# --- [NOVO F2.5] IMPORT DA PAGINA DE FORMULARIOS (Area 0 do MLOps) ---
try:
    from pagina_formularios import render_pagina_formularios
except Exception as _e_form:
    st.warning(f"Aviso: 'pagina_formularios.py' nao carregado ({type(_e_form).__name__}).")
    def render_pagina_formularios():
        st.error("Modulo de Formularios inoperante.")

# --- [NOVO F2.7] IMPORT DA PAGINA DE PROFESSORES (espelho de Alunos) ---
try:
    from pagina_professores import render_pagina_professores
except Exception as _e_prof:
    st.warning(f"Aviso: 'pagina_professores.py' nao carregado ({type(_e_prof).__name__}).")
    def render_pagina_professores():
        st.error("Modulo de Professores inoperante.")


# --- [NOVO] IMPORTS DO CARROSSEL DE BANCOS DE DADOS (Supabase / Innova V2) ---
try:
    from pagina_config_bd import render_pagina_config_bd
except ImportError:
    st.warning("Aviso: 'pagina_config_bd.py' ou 'storage_bancos.py' não encontrados.")
    def render_pagina_config_bd():
        st.error("Módulo do Carrossel de BD não carregado. Verifique pagina_config_bd.py e storage_bancos.py.")

# --- [NOVO] IMPORTS DO POOL LITELLM (MULTI-PROVEDOR) ---
try:
    from storage_litellm import (
        load_providers, save_providers, add_provider,
        remove_provider, set_active_model, get_active_provider,
        update_status, listar_modelos_cadastrados,
        get_custos_provedor, set_custos_provedor,
        update_provider,
        get_max_output_tokens, set_max_output_tokens,
        get_prompt_reforco, set_prompt_reforco,
        get_estrategia_ocr, set_estrategia_ocr,
        clonar_provedor_com_novo_modelo,
        load_ativos, arquivar_provedor, substituir_e_arquivar
    )
except ImportError:
    st.warning("Aviso: 'storage_litellm.py' não encontrado — painel LiteLLM em modo degradado.")
    def load_providers(): return []
    def save_providers(p): return False
    def add_provider(prov, modelo, key="", base=""): return False, "storage_litellm.py ausente"
    def remove_provider(m): pass
    def set_active_model(m): return False
    def get_active_provider(): return None
    def update_status(m, s, msg=""): pass
    def listar_modelos_cadastrados(): return []
    def get_custos_provedor(m): return {"in_usd_1M": 0.0, "out_usd_1M": 0.0, "cache_usd_1M": 0.0}
    def set_custos_provedor(m, **kw): return False
    def update_provider(m_old, **kw): return False, "storage_litellm.py ausente"
    def get_max_output_tokens(m, default=16384): return int(default)
    def set_max_output_tokens(m, valor): return False
    def get_prompt_reforco(m): return ""
    def set_prompt_reforco(m, texto): return False
    def get_estrategia_ocr(m, default="auto"): return default
    def set_estrategia_ocr(m, estrategia): return False
    def clonar_provedor_com_novo_modelo(m_old, m_new, tornar_ativo=True): return False, "storage_litellm.py ausente"
    def load_ativos(): return []
    def arquivar_provedor(m): return False
    def substituir_e_arquivar(m_old, m_new, tornar_ativo=True): return False, "storage_litellm.py ausente"

try:
    from backend_litellm import (
        validar_provedor, obter_custos, snapshot_custos,
        listar_provedores_suportados, hint_base_url, hint_modelo,
        listar_modelos_provedor, pingar_provedor_http,
        buscar_custos_no_catalogo, sugerir_modelos_similares,
        debug_catalogo
    )
except ImportError:
    st.warning("Aviso: 'backend_litellm.py' não encontrado — validação e custos LiteLLM indisponíveis.")
    def validar_provedor(prov, modelo, key="", base=""): return False, "backend_litellm.py ausente"
    def obter_custos(m): return {"in": 0.0, "out": 0.0, "fonte": "indisponível"}
    def snapshot_custos(filtro_provedor=None, limite=500): return []
    def listar_provedores_suportados(): return ["gemini", "openai", "anthropic", "groq", "alibaba", "kimi", "custom/local (Ollama, vLLM, LM Studio)"]
    def hint_base_url(p): return ""
    def hint_modelo(p): return ""
    def listar_modelos_provedor(prov, key="", base=""): return False, "backend_litellm.py ausente", []
    def pingar_provedor_http(prov, modelo, key="", base=""): return False, "backend_litellm.py ausente"
    def buscar_custos_no_catalogo(m): return False, 0.0, 0.0, 0.0
    def sugerir_modelos_similares(m, limite=15): return []
    def debug_catalogo(radical=""): return {"versao_litellm": "ausente", "total_modelos": 0, "chaves_com_radical": [], "amostra_inicial": []}

try:
    from pagina_alunos import render_pagina_alunos
except ImportError:
    render_pagina_alunos = None

try:
    import pagina_treinamento
except ImportError:
    pagina_treinamento = None

try:
    import pagina_agentes_treinamento
except ImportError:
    pagina_agentes_treinamento = None

try:
    import pagina_motor
except ImportError:
    pagina_motor = None

try:
    import pagina_metas
except ImportError:
    pagina_metas = None


# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Escola Parque V3", page_icon="🎒", layout="wide", initial_sidebar_state="expanded")

# --- IDENTIDADE VISUAL GLOBAL ---
# Aplica CSS unificado em TODAS as páginas: st.tabs e st.radio na sidebar
# com aba/opção selecionada em vermelho destacado (padrão Escola Parque).
try:
    from utils_estilo import injetar_css_global
    injetar_css_global()
except ImportError:
    pass  # Se faltar o módulo, o app continua funcionando (degradação graceful)

# --- INICIALIZAÇÃO DE ESTADOS ---
if 'modelo_ativo' not in st.session_state:
    try:
        st.session_state['modelo_ativo'] = load_model_pref()
    except:
        st.session_state['modelo_ativo'] = "gemini-1.5-flash"

if 'view_mode' not in st.session_state:
    st.session_state['view_mode'] = 'alunos'

if 'lista_modelos' not in st.session_state:
    st.session_state['lista_modelos'] = []


# --- POPUP CONFIG: PAINEL PROFISSIONAL ---
@st.dialog("⚙️ Infraestrutura do Sistema", width="large")
def abrir_configuracoes():
    # NOTA: callbacks de botões dentro deste dialog disparam st.rerun()
    # implicitamente, o que FECHA o dialog. Para manter o usuário aqui,
    # cada callback que quer preservar o dialog deve setar:
    #     st.session_state["_reabrir_config_dialog"] = True
    # E logo após esta função estar definida, há um bloco que verifica
    # essa flag e re-chama abrir_configuracoes() automaticamente.
    col_nav, col_conteudo = st.columns([1, 2.5], gap="large")

    with col_nav:
        st.markdown("#### Menu")
        opcao = st.radio(
            "Navegação",
            ["🐘 Banco Vetorial (Supabase/Neon)", "💾 Banco de Dados (Innova V2)", "🤖 Motores IA (LiteLLM)", "🔗 Protocolos (MCP/RAG)"],
            label_visibility="collapsed",
            key="config_nav_aba",  # ← FIX: sem key, o radio perde estado a cada st.rerun()
        )
        st.divider()
        st.success(f"Modelo:\n**{st.session_state['modelo_ativo']}**", icon="✅")

    with col_conteudo:
        # --- ABA 1: BANCO DE DADOS ---
        if opcao == "🐘 Banco Vetorial (Supabase/Neon)":
            st.subheader("Conexão PostgreSQL + pgvector")
            try:
                db_conf = load_db_config()
            except:
                db_conf = {}

            c_host, c_porta = st.columns([3, 1])
            with c_host: host = st.text_input("Host", value=db_conf.get('host', ''))
            with c_porta: porta = st.text_input("Porta", value=db_conf.get('porta', '5432'))

            c_user, c_pass, c_db = st.columns([2, 2, 1.5])
            with c_user: user = st.text_input("Usuário", value=db_conf.get('user', 'postgres'))
            with c_pass: senha = st.text_input("Senha", type="password", value=db_conf.get('senha', ''))
            with c_db: dbname = st.text_input("Banco", value=db_conf.get('dbname', 'neondb'))

            c_teste, c_salvar = st.columns([1, 1])

            with c_teste:
                if st.button("🔌 Testar Conexão", use_container_width=True):
                    if testar_conexao_postgres:
                        with st.spinner("Pingando servidor Neon..."):
                            sucesso, msg = testar_conexao_postgres(host, porta, user, senha, dbname)
                            if sucesso:
                                st.success(msg)
                            else:
                                st.error(msg)
                    else:
                        st.error("Módulo de teste 'backend_infra' não carregado.")

            with c_salvar:
                if st.button("💾 Salvar Credenciais", type="primary", use_container_width=True):
                    if save_db_config:
                        try:
                            save_db_config(host, porta, user, senha, dbname)
                            st.toast("Banco configurado com sucesso!", icon="✅")
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao salvar JSON: {str(e)}")
                    else:
                        st.error("Módulo de salvamento não configurado. Verifique o backend_infra.py.")

            st.divider()
            st.markdown("##### 🚀 Preparação do Banco")
            st.caption("Clique abaixo apenas na primeira vez para instalar o pgvector e criar as tabelas.")
            if st.button("Transformar em Banco Vetorial", use_container_width=True):
                try:
                    from backend_banco_vetorial import inicializar_infraestrutura_vetorial
                    if inicializar_infraestrutura_vetorial():
                        st.success("✅ Extensão pgvector ativada e tabelas criadas com sucesso!")
                        st.balloons()
                    else:
                        st.error("Falha ao inicializar. Verifique as credenciais salvas.")
                except ImportError:
                    st.error("Arquivo 'backend_banco_vetorial.py' não encontrado.")


        # --- ABA NOVA: BANCO DE DADOS (INNOVA V2 / SUPABASE COMPARTILHADO) ---
        elif opcao == "💾 Banco de Dados (Innova V2)":
            render_pagina_config_bd()

        # --- ABA 2: MOTORES IA (LITELLM MULTI-PROVIDER) ---
        elif opcao == "🤖 Motores IA (LiteLLM)":
            st.subheader("Motores IA — LiteLLM Multi-Provider")
            st.caption("Arquitetura unificada para Gemini, OpenAI, Anthropic, Groq, Alibaba (Qwen), Kimi (Moonshot) e modelos locais (Ollama / vLLM / LM Studio).")

            # ─────────────────────────────────────────────────────────────
            # PAINEL 1 — PROVEDORES CONFIGURADOS
            # ─────────────────────────────────────────────────────────────
            with st.container(border=True):
                # ── Cabeçalho com CTA destacado no topo ──
                col_titulo_p1, col_btn_novo_p1 = st.columns([3, 1])
                with col_titulo_p1:
                    st.markdown("##### 🔌 Provedores Configurados")
                with col_btn_novo_p1:
                    if st.button(
                        "➕ Inserir Nova LLM",
                        key="btn_abrir_inserir_provedor_topo",
                        type="primary",
                        use_container_width=True,
                        help="Adicionar um novo provedor / modelo LLM ao pool.",
                    ):
                        st.session_state["__mostrar_inserir_provedor__"] = True

                try:
                    provedores = load_ativos()   # ← Painel 1 mostra SÓ os em uso (não-arquivados)
                    provedor_ativo = get_active_provider()
                except Exception:
                    provedores = []
                    provedor_ativo = None

                modelo_ativo_litellm = provedor_ativo.get("modelo") if provedor_ativo else None

                # ── Placeholder onde o formulário "Inserir Novo Provedor" será renderizado ──
                # Esse placeholder fica AQUI (logo abaixo do botão "Inserir Nova LLM"),
                # mas o código do formulário está mais abaixo. O `st.empty()` permite
                # "teleportar" a renderização para este local sem mover ~200 linhas.
                _form_inserir_placeholder = st.empty()

                # ── Auto-abre se NÃO houver provedor cadastrado ──
                if not provedores:
                    st.session_state.setdefault("__mostrar_inserir_provedor__", True)
                    st.info("Nenhum provedor cadastrado. Use **➕ Inserir Nova LLM** acima para começar.")
                else:
                    st.markdown(f"**{len(provedores)} provedor(es) no pool:**")

                    for i, p in enumerate(provedores):
                        with st.container(border=True):
                            # 6 colunas: status | info | ✏️edit | ⭐usar | ⚡ping | 🗑️del
                            c_st, c_info, c_edit, c_acao, c_test, c_del = st.columns([1.4, 3.4, 1, 1, 1, 1])

                            # Status visual (🔵 ativo / 🟢 ok / 🔴 falhou)
                            with c_st:
                                if p.get("modelo") == modelo_ativo_litellm:
                                    st.markdown("🔵 **EM USO**")
                                elif p.get("status") == "falhou":
                                    st.markdown("🔴 **FALHOU**")
                                else:
                                    st.markdown("🟢 **OK**")

                            with c_info:
                                provedor_lbl = p.get("provedor", "—")
                                modelo_lbl   = p.get("modelo",   "—")
                                base_lbl     = p.get("base_url", "")
                                key_lbl      = p.get("api_key",  "")

                                # Badge LOCAL/CLOUD baseado na base_url real
                                # (provider "custom/local" eh polivalente - pode rodar
                                # tanto em localhost quanto em OpenRouter cloud).
                                bu_low = (base_lbl or "").lower()
                                eh_local_real = any(
                                    h in bu_low for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
                                )
                                if eh_local_real:
                                    badge_html = (
                                        '<span style="display:inline-block; padding:2px 8px; '
                                        'border-radius:999px; font-size:0.68em; font-weight:700; '
                                        'background:#e6f4ea; color:#137333; border:1px solid #b6dfb9; '
                                        'margin-right:6px;">🖥️ LOCAL</span>'
                                    )
                                else:
                                    badge_html = (
                                        '<span style="display:inline-block; padding:2px 8px; '
                                        'border-radius:999px; font-size:0.68em; font-weight:700; '
                                        'background:#e8f0fe; color:#1967d2; border:1px solid #aecbfa; '
                                        'margin-right:6px;">🌐 CLOUD</span>'
                                    )

                                st.markdown(
                                    f"{badge_html}**{provedor_lbl}** · `{modelo_lbl}`",
                                    unsafe_allow_html=True,
                                )
                                if base_lbl:
                                    st.caption(f"🌐 Base URL: `{base_lbl}`")
                                if key_lbl:
                                    masc = f"{key_lbl[:6]}…{key_lbl[-4:]}" if len(key_lbl) > 10 else "•••"
                                    st.caption(f"🔑 Key: `{masc}`")
                                if p.get("ultimo_teste"):
                                    st.caption(f"📡 Último teste: {str(p['ultimo_teste'])[:90]}")

                            with c_edit:
                                modelo_editando_key = "editando_provedor"
                                ja_editando = st.session_state.get(modelo_editando_key) == p.get("modelo")

                                def _cb_toggle_edit(m=p.get("modelo")):
                                    atual = st.session_state.get("editando_provedor")
                                    st.session_state["editando_provedor"] = None if atual == m else m

                                st.button(
                                    "✖️" if ja_editando else "✏️",
                                    key=f"litellm_edit_{i}",
                                    help="Cancelar edição" if ja_editando else "Editar este provedor",
                                    on_click=_cb_toggle_edit,
                                )

                            with c_acao:
                                if p.get("modelo") != modelo_ativo_litellm:
                                    def _cb_set_active(m=p.get("modelo")):
                                        set_active_model(m)
                                        try: save_model_pref(m)
                                        except: pass
                                        st.session_state["modelo_ativo"] = m
                                        st.session_state["_msg_litellm_acao"] = f"⭐ Modelo ativo agora: {m}"

                                    st.button(
                                        "⭐",
                                        key=f"litellm_setactive_{i}",
                                        help="Tornar este o cérebro principal",
                                        on_click=_cb_set_active,
                                    )

                            with c_test:
                                def _cb_ping_painel1(prov=p.get("provedor", ""),
                                                     modelo=p.get("modelo", ""),
                                                     key=p.get("api_key", ""),
                                                     base=p.get("base_url", "")):
                                    ok, msg = pingar_provedor_http(prov, modelo, key, base)
                                    update_status(modelo, "ativo" if ok else "falhou", msg)
                                    if ok:
                                        st.session_state["_msg_litellm_acao"] = f"✅ `{modelo}` respondeu OK ao ping HTTP."
                                    else:
                                        st.session_state["_msg_litellm_acao"] = f"❌ Ping falhou em `{modelo}`: {msg}"

                                st.button(
                                    "⚡",
                                    key=f"litellm_ping_{i}",
                                    help="Pingar provedor via HTTP direto (sem usar LiteLLM no caminho).",
                                    on_click=_cb_ping_painel1,
                                )

                            with c_del:
                                def _cb_arquivar(m=p.get("modelo")):
                                    arquivar_provedor(m)
                                    st.session_state["_msg_litellm_acao"] = f"📚 Provedor '{m}' arquivado — fica disponível na Biblioteca de Preços (Painel 3) com botão 🗑️ para deletar de vez."

                                st.button(
                                    "📚",
                                    key=f"litellm_del_{i}",
                                    help="📚 ARQUIVAR este modelo — sai do Painel 1, mas fica na Biblioteca de Preços (Painel 3) com seus custos preservados. Para deletar de vez, use 🗑️ no Painel 3.",
                                    on_click=_cb_arquivar,
                                )

                            # ── Bloco de edição inline (aparece quando o usuario clica em ✏️) ──
                            if st.session_state.get("editando_provedor") == p.get("modelo"):
                                with st.container(border=True):
                                    st.markdown("##### ✏️ Editando provedor")
                                    st.caption(f"Modelo atual: `{p.get('modelo')}`. Alterando o nome do modelo, **os custos serão resetados** (nova linha na tabela de preços).")

                                    e1, e2 = st.columns([1, 2])
                                    with e1:
                                        edit_provedor = st.selectbox(
                                            "Provedor",
                                            listar_provedores_suportados(),
                                            index=listar_provedores_suportados().index(p.get("provedor")) if p.get("provedor") in listar_provedores_suportados() else 0,
                                            key=f"litellm_edit_prov_{i}",
                                        )
                                    with e2:
                                        # Verifica se ha modelos carregados via API para ESTE provedor
                                        modelos_edit_descobertos = st.session_state.get(f"litellm_edit_modelos_desc_{i}", [])
                                        if modelos_edit_descobertos:
                                            # ─── BUSCA cirúrgica acima do selectbox ───
                                            # Quando o catálogo é gigante (OpenRouter tem 350+),
                                            # rolar até achar é inviável. text_input filtra a lista
                                            # por substring (case-insensitive) antes do selectbox.
                                            modelo_atual = p.get("modelo", "")
                                            _filtro_key = f"litellm_edit_modelo_filtro_{i}"
                                            filtro = st.text_input(
                                                "🔎 Buscar modelo (ex: 'qwen', 'gemini', 'vision', '72b')",
                                                key=_filtro_key,
                                                placeholder="Digite parte do nome para filtrar os "
                                                            f"{len(modelos_edit_descobertos)} modelos descobertos…",
                                                help="Filtra a lista abaixo por substring. "
                                                     "Apague para ver todos novamente.",
                                            )
                                            _f = (filtro or "").strip().lower()
                                            if _f:
                                                modelos_filtrados = [
                                                    m for m in modelos_edit_descobertos
                                                    if _f in (m or "").lower()
                                                ]
                                                if not modelos_filtrados:
                                                    st.warning(
                                                        f"⚠️ Nenhum modelo bate com **{filtro}**. "
                                                        f"Limpe o filtro ou tente outro termo."
                                                    )
                                                    modelos_filtrados = modelos_edit_descobertos
                                                else:
                                                    st.caption(
                                                        f"✂️ {len(modelos_filtrados)} de "
                                                        f"{len(modelos_edit_descobertos)} modelos batem com "
                                                        f"**{filtro}**"
                                                    )
                                            else:
                                                modelos_filtrados = modelos_edit_descobertos

                                            # Modo selectbox — com modelos descobertos/filtrados da API
                                            try:
                                                idx_inicial = modelos_filtrados.index(modelo_atual)
                                            except ValueError:
                                                # Se o modelo atual nao esta na lista filtrada, adiciona no topo
                                                modelos_filtrados = [modelo_atual] + modelos_filtrados
                                                idx_inicial = 0
                                            edit_modelo = st.selectbox(
                                                "Model String (descoberto via API)",
                                                options=modelos_filtrados,
                                                index=idx_inicial,
                                                key=f"litellm_edit_modelo_sel_{i}",
                                            )
                                        else:
                                            edit_modelo = st.text_input(
                                                "Model String",
                                                value=p.get("modelo", ""),
                                                key=f"litellm_edit_modelo_{i}",
                                                help="Edite manualmente ou clique em 🔄 Carregar Modelos abaixo para escolher de uma lista.",
                                            )

                                    e3, e4 = st.columns([1, 1])
                                    with e3:
                                        edit_key = st.text_input(
                                            "API Key",
                                            value=p.get("api_key", ""),
                                            type="password",
                                            key=f"litellm_edit_key_{i}",
                                        )
                                    with e4:
                                        edit_base = st.text_input(
                                            "Base URL (opcional)",
                                            value=p.get("base_url", ""),
                                            key=f"litellm_edit_base_{i}",
                                        )

                                    # ── Botões: Carregar Modelos · Testar Ping · Texto Livre ──
                                    c_load, c_ping, c_freelance = st.columns([2, 2, 1])
                                    with c_load:
                                        def _cb_carregar_edit(idx_p=i, prov_k=f"litellm_edit_prov_{i}",
                                                              key_k=f"litellm_edit_key_{i}",
                                                              base_k=f"litellm_edit_base_{i}"):
                                            _prov = st.session_state.get(prov_k, "")
                                            _key  = st.session_state.get(key_k, "")
                                            _base = st.session_state.get(base_k, "")
                                            ok_d, msg_d, modelos_d = listar_modelos_provedor(_prov, _key, _base)
                                            if ok_d:
                                                st.session_state[f"litellm_edit_modelos_desc_{idx_p}"] = modelos_d
                                                st.session_state[f"_msg_litellm_acao"] = f"✅ {len(modelos_d)} modelos carregados da API"
                                            else:
                                                st.session_state.pop(f"litellm_edit_modelos_desc_{idx_p}", None)
                                                st.session_state[f"_msg_litellm_acao"] = f"❌ {msg_d}"

                                        st.button(
                                            "🔄 Carregar Modelos do Provedor",
                                            use_container_width=True,
                                            type="primary",
                                            key=f"litellm_edit_carregar_{i}",
                                            on_click=_cb_carregar_edit,
                                            help="Consulta a API do provedor com a API Key acima e lista os modelos disponíveis para escolha rápida.",
                                        )

                                    with c_ping:
                                        # 🔌 TESTAR PING — usa os valores ATUAIS dos inputs (sem precisar salvar antes)
                                        def _cb_ping_edit(idx_p=i,
                                                          prov_k=f"litellm_edit_prov_{i}",
                                                          modelo_k=f"litellm_edit_modelo_{i}",
                                                          modelo_sel_k=f"litellm_edit_modelo_sel_{i}",
                                                          key_k=f"litellm_edit_key_{i}",
                                                          base_k=f"litellm_edit_base_{i}"):
                                            _prov   = st.session_state.get(prov_k, "")
                                            # Modelo pode vir do selectbox (descoberto) OU do text_input livre
                                            _modelo = (st.session_state.get(modelo_sel_k) or st.session_state.get(modelo_k) or "").strip()
                                            _key    = st.session_state.get(key_k, "")
                                            _base   = st.session_state.get(base_k, "")

                                            if not _modelo:
                                                st.session_state["_msg_litellm_acao"] = "❌ Escolha um Model String antes de pingar."
                                                return

                                            ok_p, msg_p = pingar_provedor_http(_prov, _modelo, _key, _base)
                                            if ok_p:
                                                st.session_state["_msg_litellm_acao"] = f"✅ Ping OK em `{_modelo}` — pode salvar com segurança."
                                            else:
                                                st.session_state["_msg_litellm_acao"] = f"❌ Ping falhou em `{_modelo}`: {msg_p}"

                                        st.button(
                                            "🔌 Testar Ping",
                                            use_container_width=True,
                                            key=f"litellm_edit_ping_{i}",
                                            on_click=_cb_ping_edit,
                                            help="Pinga o provedor com o Model String escolhido + API Key + Base URL atuais (HTTP direto, sem LiteLLM). Use ANTES de salvar para confirmar que o novo modelo responde.",
                                        )

                                    with c_freelance:
                                        if st.session_state.get(f"litellm_edit_modelos_desc_{i}"):
                                            def _cb_freelance_edit(idx_p=i):
                                                st.session_state.pop(f"litellm_edit_modelos_desc_{idx_p}", None)
                                            st.button(
                                                "✏️ Livre",
                                                use_container_width=True,
                                                key=f"litellm_edit_freelance_{i}",
                                                on_click=_cb_freelance_edit,
                                                help="Voltar a digitar a Model String manualmente.",
                                            )

                                    # Max Output Tokens (campo unico, personalizavel por provedor)
                                    e5, e5_hint = st.columns([1, 2])
                                    with e5:
                                        valor_atual_max = int(p.get("max_output_tokens", 16384) or 16384)
                                        edit_max_out = st.number_input(
                                            "📏 Max Output Tokens",
                                            min_value=256,
                                            max_value=200000,
                                            value=valor_atual_max,
                                            step=512,
                                            key=f"litellm_edit_max_out_{i}",
                                            help="Teto de tokens da resposta. Gemini Flash até 65k, GPT-4o até 16k, Claude 3.5 até 8k.",
                                        )
                                    with e5_hint:
                                        st.markdown("<br>", unsafe_allow_html=True)
                                        st.caption(
                                            "💡 Aumente se o LLM truncar a resposta antes do gabarito completo. "
                                            "Diminua para economizar tokens em modelos com janela curta."
                                        )

                                    # ───────── 🛤️ ESTRATÉGIA OCR (Modo 1 / Turbo / Modo 2 / Auto) ─────────
                                    # BLINDAGEM: default = "auto" → preserva 100% o fluxo Gemini de 6 fatias.
                                    estrategia_atual = (p.get("estrategia_ocr", "auto") or "auto").strip().lower()
                                    if estrategia_atual not in ("auto", "modo1_6fatias", "modo1_turbo", "modo2_microvision"):
                                        estrategia_atual = "auto"

                                    OPCOES_OCR_LABELS = {
                                        "auto":             "🤖 Auto (recomendado) — Gemini→Modo 1, Local→Modo 2",
                                        "modo1_6fatias":    "🅰️ Modo 1 — 6 fatias clássico (Gemini 100% calibrado) BLINDADO",
                                        "modo1_turbo":      "🚀 MODO 1 TURBO - EXP (clone para experimentação)",
                                        "modo2_microvision":"🅱️ Modo 2 v7 — Fatias adaptativas guiadas pelo molde (Local/Llama)",
                                    }
                                    chaves_ocr = list(OPCOES_OCR_LABELS.keys())
                                    idx_inicial_ocr = chaves_ocr.index(estrategia_atual) if estrategia_atual in chaves_ocr else 0

                                    edit_estrategia = st.selectbox(
                                        "🛤️ Estratégia OCR de Provas",
                                        options=chaves_ocr,
                                        index=idx_inicial_ocr,
                                        format_func=lambda k: OPCOES_OCR_LABELS[k],
                                        key=f"litellm_edit_estrategia_{i}",
                                        help=(
                                            "🤖 Auto — comportamento clássico (Gemini cloud usa Modo 1; modelos locais usam Modo 2). NÃO MUDA NADA do que já funciona.\n\n"
                                            "🅰️ Modo 1 — esteira tradicional: rasteriza a prova em 6 fatias e manda todas pro LLM. Excelente para Gemini/cloud com janela de contexto larga. **BLINDADO** (não recebe alterações).\n\n"
                                            "🚀 Modo 1 TURBO - EXP — clone IDÊNTICO do Modo 1 hoje. Serve como bancada de experimentação para prompts novos, multi-pass, calibrações etc. SEM tocar no Modo 1 original.\n\n"
                                            "🅱️ Modo 2 v7 — Micro-Vision com Fatias Adaptativas: usa as coordenadas do molde treinado para cortar a página em pedaços de K=5 checkboxes, manda cada fatia anotada [#N] para o LLM. Determinístico no recorte, cirúrgico, mitiga alucinação."
                                        ),
                                    )
                                    if edit_estrategia == "modo1_6fatias":
                                        st.caption("🅰️ Modo 1 ativo — esteira 6 fatias completa (BLINDADO).")
                                    elif edit_estrategia == "modo1_turbo":
                                        st.caption("🚀 Modo 1 TURBO - EXP ativo — clone idêntico, pronto para experimentação.")
                                    elif edit_estrategia == "modo2_microvision":
                                        st.caption("🅱️ Modo 2 v7 ativo — fatias adaptativas (K=5) guiadas pelo molde, anotação [#N].")
                                    else:
                                        st.caption("🤖 Auto — fluxo clássico preservado.")

                                    # ───────── 🎯 PROMPT-PAI DINÂMICO (muda conforme estratégia escolhida) ─────────
                                    # UM ÚNICO text_area que mostra/edita o Prompt-PAI da estratégia atualmente
                                    # selecionada no selectbox acima. Mais limpo que 3 campos simultâneos.
                                    try:
                                        from storage_litellm import (
                                            get_prompt_por_estrategia, set_prompt_por_estrategia,
                                            PROMPT_TEMPLATE_MODO1_6FATIAS,
                                            PROMPT_TEMPLATE_MODO1_TURBO,
                                            PROMPT_TEMPLATE_MODO2_LOCAL,
                                        )
                                        _esp_ok = True
                                    except Exception:
                                        _esp_ok = False

                                    modelo_atual_p = p.get("modelo", "")

                                    # Mapa: estratégia → (label, template, descrição)
                                    _MAPA_PAI = {
                                        "modo1_6fatias": (
                                            "🅰️ Prompt-PAI · Modo 1 — 6 fatias clássico (BLINDADO)",
                                            PROMPT_TEMPLATE_MODO1_6FATIAS if _esp_ok else "",
                                            "Esteira clássica Gemini cloud. Template Ideal 4507 chars (anti-falso-positivo).",
                                        ),
                                        "modo1_turbo": (
                                            "🚀 Prompt-PAI · MODO 1 TURBO - EXP (v7 Gemini cloud)",
                                            PROMPT_TEMPLATE_MODO1_TURBO if _esp_ok else "",
                                            "Esteira de fatias adaptativas dedicada ao Gemini cloud. Template ~1500 chars formato M/V CSV.",
                                        ),
                                        "modo2_microvision": (
                                            "🅱️ Prompt-PAI · Modo 2 v7 — Fatias adaptativas (LLMs locais)",
                                            PROMPT_TEMPLATE_MODO2_LOCAL if _esp_ok else "",
                                            "Esteira de fatias para Llama/Qwen local. Template ~700 chars sem safety triggers.",
                                        ),
                                        "auto": (
                                            "🎯 Prompt-PAI GERAL (legado — usado quando estratégia=Auto)",
                                            "",
                                            "Prompt-PAI usado quando nenhuma estratégia específica está selecionada (modo Auto).",
                                        ),
                                    }

                                    _est_atual = edit_estrategia if edit_estrategia in _MAPA_PAI else "auto"
                                    _label_pai, _template_pai, _desc_pai = _MAPA_PAI[_est_atual]

                                    # Lê valor atual: específico da estratégia OU prompt_reforco legado se Auto
                                    if _est_atual == "auto":
                                        valor_atual_pai_dyn = p.get("prompt_reforco", "") or ""
                                    else:
                                        valor_atual_pai_dyn = (
                                            get_prompt_por_estrategia(modelo_atual_p, _est_atual)
                                            if _esp_ok else ""
                                        )

                                    st.markdown(f"#### {_label_pai}")
                                    st.caption(_desc_pai)

                                    edit_prompt_pai_dyn = st.text_area(
                                        "Prompt-PAI",
                                        value=valor_atual_pai_dyn,
                                        height=200,
                                        key=f"litellm_edit_pai_dyn_{i}_{_est_atual}",
                                        placeholder="VAZIO = sem reforço (modelo usa apenas prompt forense base).",
                                        label_visibility="collapsed",
                                    )

                                    if valor_atual_pai_dyn:
                                        st.caption(f"✅ Reforço ATIVO ({len(valor_atual_pai_dyn)} caracteres) para esta estratégia")
                                    else:
                                        st.caption("⚪ Reforço VAZIO para esta estratégia")

                                    # Botões: Carregar template + Limpar
                                    _est_atual_local = _est_atual
                                    _template_local  = _template_pai
                                    _modelo_local    = modelo_atual_p

                                    cpai1, cpai2 = st.columns([1, 1])
                                    with cpai1:
                                        def _cb_load_template(m=_modelo_local, e=_est_atual_local, t=_template_local):
                                            # FIX duplo:
                                            # (1) Flag _reabrir_config_dialog mantém o dialog aberto após rerun.
                                            # (2) Streamlit 1.30+ PROIBE st.warning/st.toast dentro de callback
                                            #     de fragment (@st.dialog é fragment). Renderizar elementos
                                            #     crasha a tela em branco. Mensagens vão por session_state
                                            #     e são exibidas no rerun (mesmo padrão de _msg_litellm_acao).
                                            st.session_state["_reabrir_config_dialog"] = True
                                            if e == "auto":
                                                # Para "auto", não há template — usa apenas o legado vazio
                                                st.session_state["_msg_litellm_acao"] = (
                                                    "⚠️ Estratégia 'Auto' usa o Prompt-PAI Geral. "
                                                    "Não há template específico — escreva manualmente "
                                                    "ou escolha outra estratégia."
                                                )
                                            elif _esp_ok and t:
                                                set_prompt_por_estrategia(m, e, t)
                                                st.session_state["_msg_litellm_acao"] = (
                                                    f"📋 Template carregado para {e} ({len(t)} chars)"
                                                )
                                        st.button(
                                            "📋 Carregar template padrão",
                                            key=f"btn_load_pai_{i}_{_est_atual}",
                                            on_click=_cb_load_template,
                                            use_container_width=True,
                                            disabled=(_est_atual == "auto"),
                                            help="Cola o template recomendado para esta estratégia.",
                                        )

                                    with cpai2:
                                        def _cb_limpar(m=_modelo_local, e=_est_atual_local):
                                            # FIX duplo: flag + mensagem diferida (st.toast PROIBIDO em fragment callback)
                                            st.session_state["_reabrir_config_dialog"] = True
                                            if e == "auto":
                                                pool = load_providers()
                                                for pp in pool:
                                                    if pp.get("modelo") == m:
                                                        pp["prompt_reforco"] = ""
                                                        save_providers(pool)
                                                        break
                                            elif _esp_ok:
                                                set_prompt_por_estrategia(m, e, "")
                                            st.session_state["_msg_litellm_acao"] = f"🗑️ Prompt-PAI de {e} limpo!"
                                        st.button(
                                            "🗑️ Limpar este Prompt-PAI",
                                            key=f"btn_clear_pai_{i}_{_est_atual}",
                                            on_click=_cb_limpar,
                                            use_container_width=True,
                                            help="Limpa o Prompt-PAI específico desta estratégia.",
                                        )

                                    # Botão de salvar (manual, caso o usuário edite o texto sem clicar no template)
                                    def _cb_salvar_pai_dyn(m=_modelo_local, e=_est_atual_local, idx=i):
                                        # FIX duplo: flag + mensagem diferida (st.toast PROIBIDO em fragment callback)
                                        # Bug original (tela branca): callback chamava st.toast dentro de @st.dialog;
                                        # Streamlit 1.30+ crasha a renderização nesse caso. Usar session_state.
                                        st.session_state["_reabrir_config_dialog"] = True
                                        novo = st.session_state.get(f"litellm_edit_pai_dyn_{idx}_{e}", "")
                                        if e == "auto":
                                            pool = load_providers()
                                            for pp in pool:
                                                if pp.get("modelo") == m:
                                                    pp["prompt_reforco"] = (novo or "").strip()
                                                    save_providers(pool)
                                                    break
                                        elif _esp_ok:
                                            set_prompt_por_estrategia(m, e, novo)
                                        st.session_state["_msg_litellm_acao"] = (
                                            f"💾 Prompt-PAI de {e} salvo ({len(novo or '')} chars)"
                                        )

                                    st.button(
                                        "💾 Salvar Prompt-PAI desta estratégia",
                                        key=f"btn_save_pai_dyn_{i}_{_est_atual}",
                                        on_click=_cb_salvar_pai_dyn,
                                        type="primary",
                                        use_container_width=True,
                                    )

                                    # Compatibilidade com bloco antigo: variável usada lá embaixo no salvar geral
                                    edit_prompt_pai = edit_prompt_pai_dyn
                                    valor_atual_pai = valor_atual_pai_dyn

                                    b1, b2 = st.columns([1, 1])
                                    with b1:
                                        def _cb_cancelar_edit():
                                            st.session_state["editando_provedor"] = None
                                            # FIX: mantém dialog aberto após rerun
                                            st.session_state["_reabrir_config_dialog"] = True

                                        st.button(
                                            "✖️ Cancelar",
                                            key=f"litellm_edit_cancel_{i}",
                                            use_container_width=True,
                                            on_click=_cb_cancelar_edit,
                                        )

                                    with b2:
                                        def _cb_salvar_edit(modelo_antigo=p.get("modelo"),
                                                            k_prov=f"litellm_edit_prov_{i}",
                                                            k_modelo=f"litellm_edit_modelo_{i}",
                                                            k_modelo_sel=f"litellm_edit_modelo_sel_{i}",
                                                            k_key=f"litellm_edit_key_{i}",
                                                            k_base=f"litellm_edit_base_{i}",
                                                            k_max=f"litellm_edit_max_out_{i}",
                                                            k_pai=f"litellm_edit_pai_{i}",
                                                            k_estr=f"litellm_edit_estrategia_{i}"):
                                            novo_prov = st.session_state.get(k_prov, "")
                                            # O campo do modelo pode ser selectbox (modelos descobertos) ou text_input
                                            novo_modelo = (st.session_state.get(k_modelo_sel) or st.session_state.get(k_modelo) or "").strip()
                                            nova_key    = st.session_state.get(k_key,    "")
                                            nova_base   = st.session_state.get(k_base,   "")
                                            novo_max    = st.session_state.get(k_max,    16384)
                                            novo_pai    = st.session_state.get(k_pai,    "") or ""
                                            nova_estr   = (st.session_state.get(k_estr, "auto") or "auto").strip().lower()

                                            # FIX: mantém dialog aberto após rerun
                                            st.session_state["_reabrir_config_dialog"] = True

                                            if not novo_modelo:
                                                st.session_state["_msg_litellm_acao"] = "❌ Model String não pode ficar em branco."
                                                return

                                            mudou_modelo = (novo_modelo != modelo_antigo)

                                            if mudou_modelo:
                                                # ─ TROCOU O MODELO → SUBSTITUI no Painel 1, ARQUIVA o antigo na Biblioteca de Preços ─
                                                ok_sub, msg_sub = substituir_e_arquivar(
                                                    modelo_antigo, novo_modelo, tornar_ativo=True
                                                )
                                                if not ok_sub:
                                                    st.session_state["_msg_litellm_acao"] = f"❌ {msg_sub}"
                                                    return

                                                # Aplica os campos editados no NOVO modelo
                                                try:
                                                    update_provider(novo_modelo,
                                                                    novo_provedor = novo_prov,
                                                                    nova_api_key  = nova_key,
                                                                    nova_base_url = nova_base)
                                                except Exception:
                                                    pass
                                                try: set_max_output_tokens(novo_modelo, int(novo_max))
                                                except Exception: pass
                                                try: set_prompt_reforco(novo_modelo, novo_pai)
                                                except Exception: pass
                                                try: set_estrategia_ocr(novo_modelo, nova_estr)
                                                except Exception: pass

                                                # Sincroniza model_pref.txt — o NOVO vira ativo
                                                try: save_model_pref(novo_modelo)
                                                except Exception: pass
                                                st.session_state["modelo_ativo"] = novo_modelo
                                                st.session_state["editando_provedor"] = None
                                                # Limpa cache de modelos descobertos da linha antiga
                                                st.session_state.pop(f"litellm_edit_modelos_desc_{i}", None)
                                                st.session_state["_msg_litellm_acao"] = f"✨ Modelo `{novo_modelo}` em uso. Antigo `{modelo_antigo}` arquivado na Biblioteca de Preços (Painel 3)."
                                            else:
                                                # ─ NÃO mudou o modelo — só atualiza os outros campos ─
                                                ok, msg = update_provider(
                                                    modelo_antigo,
                                                    novo_provedor   = novo_prov,
                                                    novo_modelo_str = None,  # mantém o nome
                                                    nova_api_key    = nova_key,
                                                    nova_base_url   = nova_base,
                                                )
                                                if ok:
                                                    try: set_max_output_tokens(modelo_antigo, int(novo_max))
                                                    except Exception: pass
                                                    try: set_prompt_reforco(modelo_antigo, novo_pai)
                                                    except Exception: pass
                                                    try: set_estrategia_ocr(modelo_antigo, nova_estr)
                                                    except Exception: pass
                                                    st.session_state["editando_provedor"] = None
                                                    pai_info = f" + reforço ({len(novo_pai)}c)" if novo_pai.strip() else ""
                                                    estr_info = f" · estratégia={nova_estr}" if nova_estr != "auto" else ""
                                                    st.session_state["_msg_litellm_acao"] = f"💾 Provedor `{modelo_antigo}` atualizado (max_out={novo_max}{pai_info}{estr_info})"
                                                else:
                                                    st.session_state["_msg_litellm_acao"] = f"❌ {msg}"

                                        st.button(
                                            "💾 Salvar Alterações",
                                            key=f"litellm_edit_save_{i}",
                                            type="primary",
                                            use_container_width=True,
                                            on_click=_cb_salvar_edit,
                                        )

                    # Toast pendente dos callbacks deste painel
                    msg_painel1 = st.session_state.pop("_msg_litellm_acao", None)
                    if msg_painel1:
                        st.toast(msg_painel1, icon="ℹ️")

            # ─────────────────────────────────────────────────────────────
            # PAINEL 2 — INSERIR NOVO PROVEDOR / LLM
            # Renderizado NO PLACEHOLDER definido acima, logo abaixo do botão
            # vermelho. Assim aparece DENTRO do mesmo card dos Provedores.
            # ─────────────────────────────────────────────────────────────
            if st.session_state.get("__mostrar_inserir_provedor__", False):
              # Usa o placeholder criado lá em cima — teleporta para o topo
              with _form_inserir_placeholder.container(border=True):
                col_h1, col_h2 = st.columns([4, 1])
                with col_h1:
                    st.markdown("##### ➕ Inserir Novo Provedor / LLM")
                with col_h2:
                    def _cb_fechar_inserir():
                        st.session_state["__mostrar_inserir_provedor__"] = False
                        # FIX: mantém dialog Configurações aberto após o rerun automático
                        st.session_state["_reabrir_config_dialog"] = True
                    st.button("✖️ Fechar",
                              key="btn_fechar_inserir_provedor",
                              use_container_width=True,
                              on_click=_cb_fechar_inserir)
                provedores_suportados = listar_provedores_suportados()

                # ── Linha 1: Provedor + API Key ──
                c_p, c_k = st.columns([1, 2])
                with c_p:
                    novo_prov = st.selectbox(
                        "Provedor",
                        provedores_suportados,
                        key="litellm_new_prov",
                    )
                with c_k:
                    nova_key = st.text_input(
                        "API Key",
                        type="password",
                        key="litellm_new_key",
                        placeholder="Cole a chave do provedor (deixe vazio para modelos locais)",
                    )

                # ── Linha 2: Base URL (opcional) ──
                nova_base = st.text_input(
                    "Base URL (opcional)",
                    placeholder=hint_base_url(novo_prov),
                    key="litellm_new_base",
                    help="Obrigatório para Ollama / LM Studio / vLLM e endpoints OpenAI-compatible (Alibaba Dashscope, Kimi Moonshot etc.).",
                )

                # ── Linha 3: 🔵 BOTÃO AZUL DE DESCOBERTA AUTOMÁTICA ──
                c_buscar, c_limpar = st.columns([3, 1])
                with c_buscar:
                    if st.button(
                        "🔄  Buscar Modelos do Provedor",
                        use_container_width=True,
                        type="primary",
                        key="litellm_btn_buscar_modelos",
                        help="Consulta o catálogo de modelos disponíveis para a chave informada (Gemini /v1beta/models, Anthropic /v1/models, OpenAI-compat /v1/models, Ollama /v1/models).",
                    ):
                        with st.spinner(f"Consultando catálogo de '{novo_prov}'..."):
                            ok_d, msg_d, modelos_d = listar_modelos_provedor(novo_prov, nova_key, nova_base)
                            if ok_d:
                                st.session_state["litellm_modelos_descobertos"] = {
                                    "provedor": novo_prov,
                                    "modelos":  modelos_d,
                                }
                                st.success(msg_d)
                            else:
                                st.error(msg_d)
                                st.session_state.pop("litellm_modelos_descobertos", None)

                # Recupera lista descoberta (apenas se for do mesmo provedor selecionado agora)
                descoberta = st.session_state.get("litellm_modelos_descobertos")
                modelos_disp = []
                if descoberta and descoberta.get("provedor") == novo_prov:
                    modelos_disp = descoberta.get("modelos", [])

                with c_limpar:
                    if modelos_disp:
                        if st.button(
                            "✏️ Texto Livre",
                            use_container_width=True,
                            key="litellm_btn_modo_livre",
                            help="Voltar a digitar a Model String manualmente",
                        ):
                            st.session_state.pop("litellm_modelos_descobertos", None)
                            modelos_disp = []

                # ── Linha 4: Model String (selectbox dinâmico OU text_input livre) ──
                if modelos_disp:
                    st.caption(f"📦 {len(modelos_disp)} modelos descobertos via API · selecione abaixo:")
                    novo_modelo = st.selectbox(
                        "Model String (descoberta automática)",
                        options=modelos_disp,
                        key="litellm_new_modelo_sel",
                    )
                else:
                    novo_modelo = st.text_input(
                        "Model String (formato LiteLLM)",
                        placeholder=hint_modelo(novo_prov),
                        key="litellm_new_modelo",
                        help="Exemplos: `gpt-4o-mini`, `gemini/gemini-1.5-flash`, `claude-3-5-sonnet-20241022`, `groq/llama-3.1-8b-instant`, `ollama/qwen2.5-coder`. Clique em 🔄 Buscar Modelos do Provedor para descobrir a lista automaticamente.",
                    )

                # ── Linha 5: Ações finais ──
                c_test_novo, c_save_novo = st.columns([1, 1])

                with c_test_novo:
                    if st.button("🔌 Testar Conexão", use_container_width=True, key="litellm_btn_test_novo"):
                        if not novo_modelo:
                            st.error("Informe a Model String antes de testar (ou clique em 🔄 Buscar Modelos).")
                        else:
                            with st.spinner(f"Pingando provedor '{novo_prov}' diretamente no endpoint nativo..."):
                                ok, msg = pingar_provedor_http(novo_prov, novo_modelo, nova_key, nova_base)
                                if ok:
                                    st.success(msg)
                                else:
                                    st.error(msg)

                with c_save_novo:
                    if st.button("💾 Testar e Salvar", type="primary", use_container_width=True, key="litellm_btn_save_novo"):
                        if not novo_modelo:
                            st.error("Informe a Model String antes de salvar (ou clique em 🔄 Buscar Modelos).")
                        else:
                            with st.spinner(f"Pingando provedor '{novo_prov}' diretamente no endpoint nativo antes de persistir..."):
                                ok, msg = pingar_provedor_http(novo_prov, novo_modelo, nova_key, nova_base)
                                if ok:
                                    sucesso, msg_add = add_provider(novo_prov, novo_modelo, nova_key, nova_base)
                                    if sucesso:
                                        update_status(novo_modelo, "ativo", msg)
                                        # Se for o primeiro provedor cadastrado, ele já vira ativo (add_provider faz isso).
                                        # Sincroniza model_pref.txt para o backend_ocr enxergar o novo cérebro.
                                        if len(load_providers()) == 1:
                                            try: save_model_pref(novo_modelo)
                                            except: pass
                                            st.session_state["modelo_ativo"] = novo_modelo
                                        st.success(f"Provedor cadastrado e validado: `{novo_modelo}`")
                                        st.balloons()
                                        # Mantém a descoberta para o próximo cadastro
                                        time.sleep(0.8)
                                        st.rerun()
                                    else:
                                        st.warning(msg_add)
                                else:
                                    st.error(f"Não salvo (falhou no ping): {msg}")

            # ─────────────────────────────────────────────────────────────
            # PAINEL 3 — TABELA DE PREÇOS (editável por modelo cadastrado)
            # ─────────────────────────────────────────────────────────────
            with st.container(border=True):
                st.markdown("##### 📊 Biblioteca de Preços (Editável)")
                st.caption("Modelos EM USO (Painel 1) + modelos ARQUIVADOS. Use 🔄 para puxar do catálogo LiteLLM ou edite à mão. 💾 salva. 🗑️ aqui DELETA DE VEZ. Modelos arquivados ficam aqui para você reativar no futuro sem perder seus preços.")

                # Checagem CRITICA: o pacote litellm esta instalado e com catalogo?
                _info_diag = debug_catalogo(radical="")
                if _info_diag.get("total_modelos", 0) == 0:
                    st.error(
                        "🚨 **Catálogo LiteLLM vazio ou pacote não instalado!**  \n"
                        "Os botões 🔄 (Buscar Preços) não conseguem trabalhar porque a biblioteca `litellm` "
                        "não está disponível no ambiente Python deste app.  \n\n"
                        "**Como corrigir** — abra o terminal (mesmo onde você roda o Streamlit) e execute:\n"
                        "```\npip install -U litellm\n```\n"
                        "Depois feche o Streamlit (Ctrl+C) e reinicie com `streamlit run app.py`.  \n\n"
                        "💡 *Enquanto isso, você pode editar os preços manualmente na tabela abaixo e clicar 💾 para salvar.*"
                    )
                else:
                    st.caption(f"📚 LiteLLM v{_info_diag.get('versao_litellm', '?')} carregado — **{_info_diag.get('total_modelos', 0)} modelos** disponíveis no catálogo.")

                # Dolar PERSISTIDO em disco (so atualiza quando o usuario clica)
                try:
                    info_d = info_dolar()
                    dolar_atual = float(info_d.get("valor", 5.25))
                    dolar_ts    = info_d.get("atualizado_em", "—")
                except Exception:
                    dolar_atual = 5.25
                    dolar_ts    = "—"

                # Topo: dolar (compacto, com botao discreto) + botao "Atualizar Todos" menor
                c_dolar, c_dolar_btn, c_buscar_all = st.columns([1.4, 0.6, 1.2])
                with c_dolar:
                    st.metric("💵 Dólar Salvo", f"R$ {dolar_atual:.4f}", help="Cotação USD/BRL persistida — clique no botão azul à direita para atualizar")
                    st.caption(f"📅 Atualizado em: {dolar_ts}")
                with c_dolar_btn:
                    st.markdown("<br>", unsafe_allow_html=True)

                    def _cb_atualizar_dolar():
                        ok, nova_info, msg = atualizar_dolar_agora()
                        if ok:
                            st.session_state["_msg_dolar"] = ("ok", msg)
                        else:
                            st.session_state["_msg_dolar"] = ("err", msg)

                    st.button(
                        "🔄",
                        key="litellm_btn_atualizar_dolar",
                        type="primary",
                        on_click=_cb_atualizar_dolar,
                        help="Consulta a API de câmbio AGORA e salva o novo valor",
                    )

                    msg_dolar = st.session_state.pop("_msg_dolar", None)
                    if msg_dolar:
                        nivel, txt = msg_dolar
                        if nivel == "ok":
                            st.toast(txt, icon="✅")
                        else:
                            st.toast(txt, icon="❌")
                with c_buscar_all:
                    st.markdown("<br>", unsafe_allow_html=True)
                    def _cb_buscar_todos():
                        atualizados = 0
                        nao_encontrados = []
                        for p_loop in load_providers():
                            modelo_tmp = p_loop.get("modelo", "")
                            if not modelo_tmp:
                                continue
                            achou, in_u, out_u, cache_u = buscar_custos_no_catalogo(modelo_tmp)
                            if achou:
                                set_custos_provedor(modelo_tmp, in_usd_1M=in_u, out_usd_1M=out_u, cache_usd_1M=cache_u)
                                atualizados += 1
                                st.session_state.pop(f"sugestoes_{modelo_tmp}", None)
                                # Atualiza os widgets state (vai surtir efeito no proximo render)
                                # Como os widgets ainda nao foram instanciados neste run, podemos modificar
                                # mas precisamos descobrir o idx — usamos a ordem do pool
                            else:
                                nao_encontrados.append(modelo_tmp)
                                st.session_state[f"sugestoes_{modelo_tmp}"] = sugerir_modelos_similares(modelo_tmp, limite=20)
                        # Tambem atualiza os session_state[sk_*] correspondentes (descobertos)
                        for idx_p, p_loop in enumerate(load_providers()):
                            modelo_tmp = p_loop.get("modelo", "")
                            if not modelo_tmp:
                                continue
                            custos_atual = get_custos_provedor(modelo_tmp)
                            for campo, val in (("in", custos_atual["in_usd_1M"]),
                                               ("out", custos_atual["out_usd_1M"]),
                                               ("cache", custos_atual["cache_usd_1M"])):
                                sk = f"precos_{campo}_{idx_p}_{modelo_tmp}"
                                st.session_state[sk] = float(val)
                        st.session_state["_msg_buscar_todos"] = (atualizados, nao_encontrados)

                    st.button(
                        "🔄 Atualizar Todos",
                        use_container_width=True,
                        type="primary",
                        key="litellm_buscar_todos_custos",
                        on_click=_cb_buscar_todos,
                        help="Consulta o catálogo LiteLLM para todos os modelos cadastrados — preserva os que não forem encontrados",
                    )

                    # Renderiza resultado do clique anterior (se houver)
                    if "_msg_buscar_todos" in st.session_state:
                        atualizados, nao_encontrados = st.session_state.pop("_msg_buscar_todos")
                        if atualizados:
                            st.success(f"✅ {atualizados} modelo(s) atualizado(s) do catálogo LiteLLM.")
                        if nao_encontrados:
                            st.warning(f"⚠️ Não achados no catálogo (preservados): {', '.join(nao_encontrados)} — abra o **🔍 expander de sugestões** na linha correspondente para ver modelos parecidos.")

                st.divider()

                provedores_para_tabela = load_providers()
                if not provedores_para_tabela:
                    st.info("Nenhum modelo cadastrado ainda. Use o **➕ Inserir Novo Provedor / LLM** acima para adicionar — ele aparecerá aqui com valores zerados.")
                else:
                    # Cabecalho da tabela editavel (8 colunas: provedor + modelo + 3 precos + 3 acoes)
                    h0, h1, h2, h3, h4, h5, h6, h7 = st.columns([1.3, 2.0, 1.2, 1.2, 1.2, 0.7, 0.7, 0.7])
                    h0.caption("**Provedor**")
                    h1.caption("**Modelo**")
                    h2.caption("**📥 Entrada US$/1M**")
                    h3.caption("**📤 Saída US$/1M**")
                    h4.caption("**💾 Cache US$/1M**")
                    h5.caption("**🔄**")
                    h6.caption("**💾**")
                    h7.caption("**🗑️**")

                    for idx, p in enumerate(provedores_para_tabela):
                        modelo_str = p.get("modelo", "")
                        prov_lbl   = p.get("provedor", "—")
                        is_arquivado = bool(p.get("apenas_precos", False))

                        # Carrega os custos atuais do JSON
                        custos_persistidos = get_custos_provedor(modelo_str)

                        # Chave do state para esta linha (permite o botao Buscar atualizar os inputs sem rerun)
                        sk_in    = f"precos_in_{idx}_{modelo_str}"
                        sk_out   = f"precos_out_{idx}_{modelo_str}"
                        sk_cache = f"precos_cache_{idx}_{modelo_str}"

                        # Inicializa o state se ainda nao existe
                        if sk_in    not in st.session_state: st.session_state[sk_in]    = float(custos_persistidos.get("in_usd_1M",    0.0))
                        if sk_out   not in st.session_state: st.session_state[sk_out]   = float(custos_persistidos.get("out_usd_1M",   0.0))
                        if sk_cache not in st.session_state: st.session_state[sk_cache] = float(custos_persistidos.get("cache_usd_1M", 0.0))

                        with st.container(border=True):
                            r0, r1, r2, r3, r4, r5, r6, r7 = st.columns([1.3, 2.0, 1.2, 1.2, 1.2, 0.7, 0.7, 0.7])

                            with r0:
                                if is_arquivado:
                                    st.markdown(f"📚 `{prov_lbl}`", help="Arquivado — só na biblioteca de preços. Cadastre de novo no Painel 2 para usar.")
                                else:
                                    st.markdown(f"🔵 `{prov_lbl}`", help="Em uso (aparece no Painel 1).")
                            with r1:
                                st.markdown(f"**{modelo_str}**")
                                # Mostra valores em R$ baseados no state atual (preview ao vivo)
                                val_in_brl    = st.session_state[sk_in]    * dolar_atual
                                val_out_brl   = st.session_state[sk_out]   * dolar_atual
                                val_cache_brl = st.session_state[sk_cache] * dolar_atual
                                st.caption(f"R$ {val_in_brl:.4f} / {val_out_brl:.4f} / {val_cache_brl:.4f}")

                            with r2:
                                st.number_input(
                                    "in", min_value=0.0, step=0.0001, format="%.4f",
                                    key=sk_in, label_visibility="collapsed"
                                )
                            with r3:
                                st.number_input(
                                    "out", min_value=0.0, step=0.0001, format="%.4f",
                                    key=sk_out, label_visibility="collapsed"
                                )
                            with r4:
                                st.number_input(
                                    "cache", min_value=0.0, step=0.0001, format="%.4f",
                                    key=sk_cache, label_visibility="collapsed"
                                )

                            with r5:
                                def _cb_buscar_linha(m=modelo_str, k_in=sk_in, k_out=sk_out, k_cache=sk_cache):
                                    achou, in_u, out_u, cache_u = buscar_custos_no_catalogo(m)
                                    if achou:
                                        st.session_state[k_in]    = float(in_u)
                                        st.session_state[k_out]   = float(out_u)
                                        st.session_state[k_cache] = float(cache_u)
                                        st.session_state.pop(f"sugestoes_{m}", None)
                                        st.session_state[f"_msg_busca_{m}"] = ("ok", f"✅ Preços de '{m}' atualizados.")
                                    else:
                                        st.session_state[f"sugestoes_{m}"] = sugerir_modelos_similares(m, limite=20)
                                        st.session_state[f"_msg_busca_{m}"] = ("warn", f"⚠️ '{m}' não encontrado — veja sugestões abaixo.")

                                st.button(
                                    "🔄",
                                    key=f"precos_buscar_{idx}",
                                    help="Buscar este modelo no catálogo LiteLLM",
                                    on_click=_cb_buscar_linha,
                                )

                            with r6:
                                def _cb_salvar_linha(m=modelo_str, k_in=sk_in, k_out=sk_out, k_cache=sk_cache):
                                    ok = set_custos_provedor(
                                        m,
                                        in_usd_1M    = st.session_state.get(k_in,    0.0),
                                        out_usd_1M   = st.session_state.get(k_out,   0.0),
                                        cache_usd_1M = st.session_state.get(k_cache, 0.0),
                                    )
                                    if ok:
                                        st.session_state[f"_msg_busca_{m}"] = ("save", f"💾 Preços de '{m}' salvos!")
                                    else:
                                        st.session_state[f"_msg_busca_{m}"] = ("err", f"❌ Falha ao salvar '{m}'.")

                                st.button(
                                    "💾",
                                    key=f"precos_salvar_{idx}",
                                    help="Salvar esta linha em providers_litellm.json",
                                    on_click=_cb_salvar_linha,
                                )

                            with r7:
                                # Botao 🗑️ — DELETA DEFINITIVAMENTE (sai da Biblioteca de Preços)
                                # Bloqueado APENAS para o modelo ATIVO em uso
                                eh_ativo_em_uso = (
                                    not is_arquivado
                                    and modelo_str == (provedor_ativo.get("modelo") if provedor_ativo else None)
                                )
                                if eh_ativo_em_uso:
                                    st.markdown("🔒", help="Modelo ATIVO em uso. Troque o ativo no Painel 4 (ou arquive no Painel 1) antes de deletar.")
                                else:
                                    def _cb_del_preco(m=modelo_str):
                                        remove_provider(m)
                                        st.session_state[f"_msg_busca_{m}"] = ("ok", f"🗑️ '{m}' removido da Biblioteca de Preços.")
                                        for campo in ("in", "out", "cache"):
                                            sk = f"precos_{campo}_{idx}_{m}"
                                            if sk in st.session_state:
                                                del st.session_state[sk]

                                    st.button(
                                        "🗑️",
                                        key=f"precos_del_{idx}",
                                        help=f"DELETAR DEFINITIVAMENTE '{modelo_str}' da Biblioteca de Preços",
                                        on_click=_cb_del_preco,
                                    )

                            # Badge LOCAL/CLOUD na largura TOTAL da linha (canto direito inferior)
                            # Aparece DEPOIS de toda a linha de colunas, alinhado a direita real.
                            _base_url_p3 = (p.get("base_url", "") or "").lower()
                            _eh_local_p3 = any(
                                h in _base_url_p3
                                for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
                            )
                            if _eh_local_p3:
                                _badge_p3 = (
                                    '<div style="text-align:right; margin-top:6px;">'
                                    '<span style="display:inline-block; padding:3px 10px; '
                                    'border-radius:999px; font-size:0.72em; font-weight:700; '
                                    'background:#e6f4ea; color:#137333; border:1px solid #b6dfb9;">'
                                    '🖥️ LOCAL</span></div>'
                                )
                            else:
                                _badge_p3 = (
                                    '<div style="text-align:right; margin-top:6px;">'
                                    '<span style="display:inline-block; padding:3px 10px; '
                                    'border-radius:999px; font-size:0.72em; font-weight:700; '
                                    'background:#e8f0fe; color:#1967d2; border:1px solid #aecbfa;">'
                                    '🌐 CLOUD</span></div>'
                                )
                            st.markdown(_badge_p3, unsafe_allow_html=True)

                            # Se a busca anterior nao achou, mostra sugestoes do catalogo LiteLLM
                            sugestoes_linha = st.session_state.get(f"sugestoes_{modelo_str}", [])
                            if sugestoes_linha:
                                with st.expander(f"🔍 Modelos parecidos com `{modelo_str}` no catálogo LiteLLM ({len(sugestoes_linha)})", expanded=False):
                                    st.caption("Clique em **Usar** para aplicar os preços desse modelo do catálogo na sua linha. Se o nome correto for outro, copie e renomeie o modelo (remova e cadastre de novo no Painel 2).")
                                    for j, s in enumerate(sugestoes_linha):
                                        s_nome     = s.get("nome", "")
                                        s_in       = s.get("in_usd_1M", 0.0)
                                        s_out      = s.get("out_usd_1M", 0.0)
                                        s_cache    = s.get("cache_usd_1M", 0.0)
                                        cs1, cs2, cs3, cs4, cs5 = st.columns([3, 1, 1, 1, 1])
                                        cs1.code(s_nome, language=None)
                                        cs2.caption(f"📥 {s_in:.4f}")
                                        cs3.caption(f"📤 {s_out:.4f}")
                                        cs4.caption(f"💾 {s_cache:.4f}")
                                        with cs5:
                                            def _cb_usar_sugestao(m=modelo_str, k_in=sk_in, k_out=sk_out, k_cache=sk_cache,
                                                                  v_in=s_in, v_out=s_out, v_cache=s_cache, nome=s_nome):
                                                st.session_state[k_in]    = float(v_in)
                                                st.session_state[k_out]   = float(v_out)
                                                st.session_state[k_cache] = float(v_cache)
                                                st.session_state.pop(f"sugestoes_{m}", None)
                                                st.session_state[f"_msg_busca_{m}"] = ("ok", f"✅ Preços de `{nome}` aplicados — clique 💾 para salvar.")

                                            st.button(
                                                "Usar",
                                                key=f"usar_sug_{idx}_{j}",
                                                help=f"Aplicar os preços de {s_nome} nesta linha",
                                                on_click=_cb_usar_sugestao,
                                            )

                    # Renderiza toasts pendentes de TODAS as linhas (callbacks deixam mensagens aqui)
                    for p_msg in load_providers():
                        mod = p_msg.get("modelo", "")
                        if not mod:
                            continue
                        msg_pendente = st.session_state.pop(f"_msg_busca_{mod}", None)
                        if msg_pendente:
                            nivel, msg = msg_pendente
                            icones = {"ok": "✅", "warn": "⚠️", "save": "💾", "err": "❌"}
                            st.toast(msg, icon=icones.get(nivel, "ℹ️"))

                    st.caption("💡 Os valores em R$ logo abaixo do nome do modelo são preview ao vivo (US$/1M × cotação atual). O cálculo final do log de custos usa exatamente esses valores salvos.")

            # ─────────────────────────────────────────────────────────────
            # PAINEL 4 — MODELO ATIVO (CÉREBRO PRINCIPAL DO RAG)
            # ─────────────────────────────────────────────────────────────
            with st.container(border=True):
                st.markdown("##### 🎯 Modelo Ativo — Cérebro do RAG & Adaptação de Provas")
                st.caption("Este modelo será usado pelo `backend_ocr.py` (OCR Vision) e pelo motor de adaptação cirúrgica de provas para alunos TDAH.")

                modelos_cadastrados = listar_modelos_cadastrados()
                if not modelos_cadastrados:
                    st.warning("Cadastre ao menos um provedor para escolher o cérebro principal.")
                else:
                    try:
                        idx_atual = modelos_cadastrados.index(st.session_state.get("modelo_ativo", ""))
                    except ValueError:
                        idx_atual = 0

                    c_sel, c_save_padrao = st.columns([2, 1])
                    with c_sel:
                        escolha_ativa = st.selectbox(
                            "Selecione o modelo de produção:",
                            modelos_cadastrados,
                            index=idx_atual,
                            key="litellm_modelo_ativo_sel",
                        )
                    with c_save_padrao:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("💾 Salvar como Padrão", type="primary", use_container_width=True, key="litellm_btn_salvar_padrao"):
                            set_active_model(escolha_ativa)
                            try: save_model_pref(escolha_ativa)
                            except: pass
                            st.session_state["modelo_ativo"] = escolha_ativa
                            st.toast(f"Cérebro principal: {escolha_ativa}", icon="🎯")
                            time.sleep(0.5)
                            st.rerun()

                    st.info(f"📡 Modelo em produção (lido por `backend_ocr.py`): **{st.session_state.get('modelo_ativo', 'nenhum')}**")

        # --- ABA 3: MCP & RAG ---
        elif opcao == "🔗 Protocolos (MCP/RAG)":
            st.subheader("Configurações Avançadas e Obsidian")
            try:
                if load_mcp_config:
                    mcp_conf = load_mcp_config()
                else:
                    mcp_conf = {"mcp_ativo": True, "rag_ativo": True, "vault_path": ""}
            except:
                mcp_conf = {"mcp_ativo": True, "rag_ativo": True, "vault_path": ""}

            if 'vault_path_input' not in st.session_state:
                st.session_state['vault_path_input'] = mcp_conf.get('vault_path', '')

            def cb_selecionar_pasta():
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.attributes("-topmost", True)
                    root.withdraw()
                    pasta = filedialog.askdirectory(master=root, title="Selecione a pasta do Obsidian Vault")
                    root.destroy()
                    if pasta:
                        st.session_state['vault_path_input'] = pasta
                except Exception:
                    pass

            with st.container(border=True):
                mcp_ativo = st.toggle("Ativar Model Context Protocol (MCP)", value=mcp_conf.get('mcp_ativo', True))
                rag_ativo = st.toggle("RAG Cirúrgico", value=mcp_conf.get('rag_ativo', True))

            with st.container(border=True):
                st.markdown("##### 📓 Base Obsidian Local (Vault)")
                col_path, col_btn = st.columns([4, 1])

                with col_path:
                    st.text_input(
                        "Caminho do Vault:",
                        key='vault_path_input',
                        placeholder="Ex: C:/Users/SeuNome/Documents/EscolaParqueVault"
                    )

                with col_btn:
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.button("📁 Procurar", key="btn_explorer", use_container_width=True, on_click=cb_selecionar_pasta)

                c_test, c_save = st.columns([1, 1])

                with c_test:
                    if st.button("🔎 Testar Leitura do Vault", use_container_width=True):
                        try:
                            from backend_obsidian_mcp import varrer_vault_obsidian
                            with st.spinner("Lendo diretórios..."):
                                atual_path = st.session_state['vault_path_input']
                                sucesso, msg, notas = varrer_vault_obsidian(caminho_opcional=atual_path)
                                if sucesso:
                                    st.success(msg)
                                else:
                                    st.error(msg)
                        except ImportError:
                            st.error("Arquivo 'backend_obsidian_mcp.py' não encontrado.")

                with c_save:
                    if st.button("💾 Salvar Configurações", type="primary", use_container_width=True):
                        if save_mcp_config:
                            atual_path = st.session_state['vault_path_input']
                            save_mcp_config(mcp_ativo, rag_ativo, atual_path)
                            st.toast("Configurações do Obsidian salvas!", icon="✅")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("Módulo de salvamento não configurado.")


# --- BARRA LATERAL (MENU MAESTRO UNIFICADO) ---
with st.sidebar:
    st.title("🎛️ Maestro")

    st.success(f"🔌 RAG: **Ativo**", icon="✅")

    # --- Selo do Backend Central (worker Python): lê o heartbeat no Supabase ---
    # Online se o último sinal < 60s. try/except defensivo: nunca quebra a sidebar.
    try:
        from innova_bridge.db.client import get_pool, run_async

        async def _ler_heartbeat():
            pool = await get_pool()
            return await pool.fetchrow(
                "SELECT value->>'host' AS host, "
                "EXTRACT(EPOCH FROM (now() - (value->>'ts')::timestamptz)) AS idade "
                "FROM public.system_settings WHERE key = 'python_worker_heartbeat'"
            )

        _hb = run_async(_ler_heartbeat())
        if _hb and _hb["idade"] is not None and float(_hb["idade"]) < 60:
            _host_txt = f" · {_hb['host']}" if _hb["host"] else ""
            st.success(f"🧠 Backend Central: **Online**{_host_txt}", icon="✅")
        else:
            st.error("🧠 Backend Central: **Offline** (worker parado)", icon="🚨")
    except Exception:
        st.warning("🧠 Backend Central: status indisponível", icon="⚠️")

    st.divider()

    if st.button("👥 Área de Alunos", type="primary" if st.session_state['view_mode'] == 'alunos' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'alunos'
        st.rerun()

    if st.button("👨‍🏫 Professores", type="primary" if st.session_state['view_mode'] == 'professores' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'professores'
        st.rerun()

    if st.button("📝 Motor de Avaliações", type="primary" if st.session_state['view_mode'] == 'motor' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'motor'
        st.rerun()

    if st.button("🧠 Treinamento IA", type="primary" if st.session_state['view_mode'] == 'treinamento' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'treinamento'
        st.rerun()

    if st.button("🎓 Treinamento de Molde", type="primary" if st.session_state['view_mode'] == 'molde' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'molde'
        st.rerun()

    if st.button("🛠️ Diagnóstico", type="primary" if st.session_state['view_mode'] == 'diagnostico' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'diagnostico'
        st.rerun()

    if st.button("💸 Custos e Tokens", type="primary" if st.session_state['view_mode'] == 'financeiro' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'financeiro'

    # [NOVO F2.5] — Formularios (Area 0 do MLOps)
    if st.button("📋 Formularios", type="primary" if st.session_state['view_mode'] == 'formularios' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'formularios'
        st.rerun()

    # [NOVO F2] — Sistema Adaptativo v2.0 (Innova V2)
    if st.button("🤖 Agentes", type="primary" if st.session_state['view_mode'] == 'agentes' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'agentes'
        st.rerun()
        st.rerun()

    if st.button("⚙️ Configurações", use_container_width=True):
        abrir_configuracoes()

# ─── FIX: re-abre dialog automaticamente quando flag ativa ───
# Callbacks dentro do @st.dialog disparam rerun que FECHA o dialog.
# Para preservar a tela de Configurações, callbacks setam a flag e
# aqui re-abrimos imediatamente após a navegação ser renderizada.
if st.session_state.get("_reabrir_config_dialog", False):
    st.session_state["_reabrir_config_dialog"] = False  # consome a flag
    abrir_configuracoes()

# Toast pendente dos callbacks do dialog (st.toast/st.warning não funcionam
# dentro de fragment callback — gravamos em _msg_litellm_acao e exibimos aqui)
_msg_pendente = st.session_state.pop("_msg_litellm_acao", None)
if _msg_pendente:
    st.toast(_msg_pendente, icon="ℹ️")

# --- CONTROLADOR DE VISUALIZAÇÃO PRINCIPAL ---
st.title("🎒 Escola Parque - Surgical RAG")

if st.session_state['view_mode'] == 'alunos':
    if render_pagina_alunos:
        render_pagina_alunos()
    else:
        st.error("Módulo 'pagina_alunos.py' corrompido ou não encontrado.")

elif st.session_state['view_mode'] == 'motor':
    try:
        import pagina_motor
        pagina_motor.renderizar()
    except Exception as e:
        st.error(f"Erro ao carregar Motor de Avaliações: {e}")

elif st.session_state['view_mode'] == 'treinamento':
    try:
        import pagina_treinamento
        pagina_treinamento.renderizar()
    except Exception as e:
        st.error(f"Erro ao carregar Treinamento IA: {e}")

elif st.session_state['view_mode'] == 'treinamento_agentes':
    # [REORG] "Treinamento de Agentes" foi consolidado dentro de Agentes > Agente 1.
    # Mantemos este branch apenas como REDIRECT seguro pra sessoes antigas que ainda
    # tenham este view_mode persistido (sticky session_state) - assim ninguem cai
    # numa tela em branco. O painel agora vive em render_pagina_agentes().
    st.session_state['view_mode'] = 'agentes'
    st.rerun()

elif st.session_state['view_mode'] == 'molde':
    try:
        import pagina_molde
        pagina_molde.renderizar()
    except Exception as e:
        st.error(f"Erro ao carregar Treinamento de Molde: {e}")

elif st.session_state['view_mode'] == 'diagnostico':
    try:
        import pagina_diagnostico
        pagina_diagnostico.renderizar()
    except Exception as e:
        st.error(f"Erro ao carregar Diagnóstico: {e}")

elif st.session_state['view_mode'] == 'financeiro':
    try:
        import pagina_financeiro
        pagina_financeiro.renderizar()
    except Exception as e:
        st.error(f"Erro ao carregar Custos e Tokens: {e}")

elif st.session_state['view_mode'] == 'formularios':
    render_pagina_formularios()

elif st.session_state['view_mode'] == 'agentes':
    render_pagina_agentes()

elif st.session_state['view_mode'] == 'professores':
    render_pagina_professores()
