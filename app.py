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

# --- [F2] IMPORTS DAS PAGINAS DE COLEGIOS E INICIO ---
try:
    from pagina_colegios import render_pagina_colegios
except Exception as _e_col:
    st.warning(f"Aviso: 'pagina_colegios.py' nao carregado ({type(_e_col).__name__}).")
    def render_pagina_colegios():
        st.error("Modulo de Colegios inoperante.")

try:
    from pagina_home import render_pagina_home
except Exception as _e_home:
    st.warning(f"Aviso: 'pagina_home.py' nao carregado ({type(_e_home).__name__}).")
    def render_pagina_home():
        st.error("Modulo de Inicio inoperante.")

# --- [F2] REGISTRO DINAMICO DE PAGINAS EXTRAS (congela o app.py) ---
try:
    from paginas_extras import PAGINAS_EXTRAS
except Exception as _e_pe:
    st.warning(f"Aviso: 'paginas_extras.py' nao carregado ({type(_e_pe).__name__}).")
    PAGINAS_EXTRAS = []


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
    st.session_state['view_mode'] = 'home'

if 'lista_modelos' not in st.session_state:
    st.session_state['lista_modelos'] = []


# --- POPUP CONFIG: PAINEL PROFISSIONAL ---
# --- [F2] DIALOGO extraido p/ pagina_configuracoes.py ---
from pagina_configuracoes import abrir_configuracoes
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

    st.link_button("↩️ Voltar para o Frontend", "https://escolaparque-app.duckdns.org", use_container_width=True)

    st.divider()

    if st.button("🏠 Início", type="primary" if st.session_state['view_mode'] == 'home' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'home'
        st.rerun()

    if st.button("👥 Área de Alunos", type="primary" if st.session_state['view_mode'] == 'alunos' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'alunos'
        st.rerun()

    if st.button("👨‍🏫 Professores", type="primary" if st.session_state['view_mode'] == 'professores' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'professores'
        st.rerun()

    if st.button("🏫 Colégios", type="primary" if st.session_state['view_mode'] == 'colegios' else "secondary", use_container_width=True):
        st.session_state['view_mode'] = 'colegios'
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

    for _pg in PAGINAS_EXTRAS:
        if st.button(_pg.get("label", _pg["view"]), type="primary" if st.session_state['view_mode'] == _pg["view"] else "secondary", use_container_width=True, key="navextra_" + _pg["view"]):
            st.session_state['view_mode'] = _pg["view"]
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

elif st.session_state['view_mode'] == 'colegios':
    render_pagina_colegios()

elif st.session_state['view_mode'] == 'home':
    render_pagina_home()

for _pg in PAGINAS_EXTRAS:
    if st.session_state['view_mode'] == _pg["view"]:
        try:
            _pg["render"]()
        except Exception as _e_render:
            st.error(f"Erro: {_e_render}")
        break
