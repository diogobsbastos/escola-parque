"""
pagina_agentes_treinamento.py - Tela de Treinamento de Agentes.

Permite customizar o system prompt por (agente, modelo).

Estrutura:
    Agentes Conhecidos (Tabs no topo)
        - Agente 1 - Profile Builder
        - (futuro) Agente 2 - Adaptador

    Pra cada agente:
        - Default (constante hardcoded - readonly)
        - Custom Default (sobrescreve a constante)
        - Custom por modelo (especifico, sobrescreve o custom default)

Princípios:
    - Default fallback eh SEMPRE a constante hardcoded (THIN_SYSTEM).
    - Apagar customizacao volta automatico pro default.
    - Botao "Copiar do Default" facilita comecar customizando.
"""
from __future__ import annotations

import streamlit as st


# ============================================================================
# Imports tolerantes (sem quebrar se modulos faltarem)
# ============================================================================

try:
    from innova_bridge.agents.prompt_storage import (
        get_agent_prompt,
        save_agent_prompt,
        list_custom_prompts,
        delete_agent_prompt,
        list_known_agents,
        get_default_constant,
        ARQUIVO_PROMPTS,
        # API estendida (hiperparametros)
        get_agent_config,
        save_agent_config,
        # Sistema de backup versionado
        criar_backup,
        listar_backups,
        ler_backup,
        restaurar_modelo_do_backup,
        restaurar_backup_completo,
        excluir_backup,
    )
    _STORAGE_OK = True
    _STORAGE_ERR = None
except Exception as _e:
    _STORAGE_OK = False
    _STORAGE_ERR = str(_e)

try:
    from innova_bridge.agents.profile_builder import listar_modelos_disponiveis
    _MODELS_OK = True
except Exception:
    _MODELS_OK = False
    listar_modelos_disponiveis = None

try:
    from innova_bridge.repositories import agent_configs_repo
    _AGENT_CFG_OK = True
except Exception:
    _AGENT_CFG_OK = False
    agent_configs_repo = None


# ============================================================================
# Helpers
# ============================================================================

def _state_key(agente_id: str, suffix: str) -> str:
    return f"agentes::{agente_id}::{suffix}"


def _badge(text: str, bg: str, color: str = "#fff") -> str:
    return (
        f'<span style="display:inline-block; padding:3px 10px; border-radius:999px; '
        f'font-size:0.72em; font-weight:700; background:{bg}; color:{color}; '
        f'margin-right:6px;">{text}</span>'
    )


def _render_header():
    st.markdown("# 🤖 Treinamento de Agentes")
    st.caption(
        "Customize o system prompt por (agente, modelo). Sem customizacao, "
        "o sistema usa a constante padrao validada na spec do projeto."
    )


def _render_storage_status():
    """Mostra status do storage no topo (deixa transparente se algo der errado)."""
    if not _STORAGE_OK:
        st.error(
            f"⚠️ Storage de prompts nao disponivel: {_STORAGE_ERR}\n\n"
            "Verifique que `innova_bridge/agents/prompt_storage.py` esta instalado."
        )
        return False
    return True


def _render_lista_modelos_disponiveis(agente_id: str) -> list[dict]:
    """Retorna lista de modelos no pool LiteLLM. Falla suave se nao disponivel."""
    if not _MODELS_OK or listar_modelos_disponiveis is None:
        st.warning(
            "Lista de modelos LLM nao disponivel. Cadastre provedores em "
            "Configuracoes → LiteLLM."
        )
        return []
    try:
        modelos = listar_modelos_disponiveis()
        return [m for m in modelos if m.get("is_executable")]
    except Exception as e:
        st.warning(f"Erro listando modelos: {e}")
        return []


def _render_editor_prompt(agente_id: str, alvo: str, alvo_label: str):
    """Renderiza editor de prompt pra um alvo especifico (modelo ou _default_).

    Args:
        agente_id: ex "agente1"
        alvo: chave de storage ("_default_" ou nome do modelo)
        alvo_label: label visivel pro usuario
    """
    if not _STORAGE_OK:
        return

    default_constante = get_default_constant(agente_id)
    # Texto atual: custom se existir, senao default
    customs = list_custom_prompts(agente_id)
    custom_atual = customs.get(alvo, "")
    eh_custom = bool(custom_atual.strip())

    # Status visual
    col_status, col_chars = st.columns([3, 1])
    with col_status:
        if eh_custom:
            st.markdown(
                _badge("✏️ CUSTOMIZADO", "#e3a008") +
                f'<span style="font-size:0.8em; color:#666;">'
                f'Sobrescreve a constante padrao pra <code>{alvo_label}</code></span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                _badge("📋 PADRAO", "#888") +
                f'<span style="font-size:0.8em; color:#666;">'
                f'Sem customizacao - usa a constante padrao do agente</span>',
                unsafe_allow_html=True,
            )
    with col_chars:
        n_chars = len(custom_atual if eh_custom else default_constante)
        st.markdown(
            f'<div style="text-align:right; font-size:0.8em; color:#666;">'
            f'{n_chars} chars</div>',
            unsafe_allow_html=True,
        )

    # Textarea editavel
    key_textarea = _state_key(agente_id, f"editor::{alvo}")
    valor_inicial = custom_atual if eh_custom else default_constante
    novo_texto = st.text_area(
        f"System prompt pra {alvo_label}",
        value=valor_inicial,
        height=400,
        key=key_textarea,
        help=(
            "Edite livremente. Salvar persiste a customizacao. "
            "Resetar volta pra constante padrao do agente."
        ),
    )

    # ========================================================================
    # EXPANDER: Hiperparametros (temperature, max_tokens, force_json)
    # ========================================================================
    cfg_atual = get_agent_config(agente_id, alvo) if alvo != "_default_" else {}
    # Pro _default_, lemos direto do storage (sem fallback de outro alvo)
    if alvo == "_default_" and _STORAGE_OK:
        from innova_bridge.agents.prompt_storage import list_custom_configs
        all_configs = list_custom_configs(agente_id)
        cfg_atual = all_configs.get("_default_", {})

    # Pra _default_ ser autoritativo, releemos do storage diretamente
    if alvo != "_default_" and _STORAGE_OK:
        from innova_bridge.agents.prompt_storage import list_custom_configs
        all_configs = list_custom_configs(agente_id)
        cfg_alvo = all_configs.get(alvo, {})
    else:
        cfg_alvo = cfg_atual

    temp_atual = cfg_alvo.get("temperature")
    maxt_atual = cfg_alvo.get("max_tokens")
    fj_atual = cfg_alvo.get("force_json")
    seed_atual = cfg_alvo.get("seed")
    ctx_atual = cfg_alvo.get("num_ctx")

    n_custom_params = sum(
        1 for v in (temp_atual, maxt_atual, fj_atual, seed_atual, ctx_atual) if v is not None
    )
    expander_label = f"⚙️ Parametros avançados ({n_custom_params}/5 customizados)" if n_custom_params \
                     else "⚙️ Parametros avançados (todos no default)"

    with st.expander(expander_label, expanded=n_custom_params > 0):
        st.caption(
            "Cada slider/toggle vira override. Deixe 'Auto' (default) pra usar a logica "
            "padrao do sistema (temp=0.3 local, default cloud · max_tokens=4096 · "
            "force_json=auto · seed=aleatorio). Ative 'Custom seed' pra obter "
            "REPRODUCIBILIDADE TOTAL: mesmo prompt + mesmo seed = mesmo output."
        )

        col_t, col_mt, col_fj, col_sd, col_ctx = st.columns(5)

        # --- Temperature ---
        with col_t:
            usa_temp_custom = st.checkbox(
                "Custom temperatura",
                value=temp_atual is not None,
                key=_state_key(agente_id, f"use_temp::{alvo}"),
                help="0 = deterministico · 1 = livre · 2 = caotico (nao recomendado).",
            )
            if usa_temp_custom:
                temp_val = st.slider(
                    "Temperature",
                    min_value=0.0, max_value=2.0,
                    value=float(temp_atual) if temp_atual is not None else 0.3,
                    step=0.05,
                    key=_state_key(agente_id, f"temp::{alvo}"),
                    label_visibility="collapsed",
                )
            else:
                temp_val = None
                st.markdown(
                    '<div style="font-size:0.85em; color:#999; padding:8px;">Auto (sistema)</div>',
                    unsafe_allow_html=True,
                )

        # --- Max Tokens ---
        with col_mt:
            usa_maxt_custom = st.checkbox(
                "Custom max_tokens",
                value=maxt_atual is not None,
                key=_state_key(agente_id, f"use_maxt::{alvo}"),
                help="Ceiling do output. 4096 eh suficiente pro JSON tipico.",
            )
            if usa_maxt_custom:
                maxt_val = st.number_input(
                    "Max tokens",
                    min_value=256, max_value=32768,
                    value=int(maxt_atual) if maxt_atual is not None else 4096,
                    step=256,
                    key=_state_key(agente_id, f"maxt::{alvo}"),
                    label_visibility="collapsed",
                )
            else:
                maxt_val = None
                st.markdown(
                    '<div style="font-size:0.85em; color:#999; padding:8px;">Auto (4096)</div>',
                    unsafe_allow_html=True,
                )

        # --- Force JSON ---
        with col_fj:
            usa_fj_custom = st.checkbox(
                "Custom force_json",
                value=fj_atual is not None,
                key=_state_key(agente_id, f"use_fj::{alvo}"),
                help="True = forca response_format JSON · False = LLM responde livre (Ollama).",
            )
            if usa_fj_custom:
                fj_val = st.radio(
                    "Force JSON",
                    options=[True, False],
                    index=0 if fj_atual in (None, True) else 1,
                    format_func=lambda x: "✅ Forcar JSON" if x else "❌ Texto livre",
                    key=_state_key(agente_id, f"fj::{alvo}"),
                    label_visibility="collapsed",
                    horizontal=True,
                )
            else:
                fj_val = None
                st.markdown(
                    '<div style="font-size:0.85em; color:#999; padding:8px;">Auto (cloud=True, local=False)</div>',
                    unsafe_allow_html=True,
                )

        # --- Seed (reproducibilidade) ---
        with col_sd:
            usa_seed_custom = st.checkbox(
                "Custom seed",
                value=seed_atual is not None,
                key=_state_key(agente_id, f"use_seed::{alvo}"),
                help=(
                    "Fixa o seed do sampler. Mesmo prompt + mesmo seed = mesmo "
                    "output (reproducibilidade). Sem seed (Auto) = sampling "
                    "probabilistico, pode variar entre runs. Range: 0 a 2^32-1."
                ),
            )
            if usa_seed_custom:
                seed_val = st.number_input(
                    "Seed",
                    min_value=0, max_value=4_294_967_295,
                    value=int(seed_atual) if seed_atual is not None else 42,
                    step=1,
                    key=_state_key(agente_id, f"seed::{alvo}"),
                    label_visibility="collapsed",
                    help="42 eh tradicional. Qualquer inteiro do range serve - so precisa ser FIXO.",
                )
            else:
                seed_val = None
                st.markdown(
                    '<div style="font-size:0.85em; color:#999; padding:8px;">Auto (aleatorio)</div>',
                    unsafe_allow_html=True,
                )

        # --- num_ctx (janela de contexto - Ollama LOCAL) ---
        with col_ctx:
            usa_ctx_custom = st.checkbox(
                "Custom num_ctx",
                value=ctx_atual is not None,
                key=_state_key(agente_id, f"use_ctx::{alvo}"),
                help=(
                    "Janela de contexto do Ollama (so vale pra modelos LOCAIS). "
                    "Prompt grande exige num_ctx maior, senao o Ollama da 500. "
                    "Maior = mais VRAM. Ignorado por cloud. Range: 256 a 131072."
                ),
            )
            if usa_ctx_custom:
                ctx_val = st.number_input(
                    "num_ctx",
                    min_value=256, max_value=131072,
                    value=int(ctx_atual) if ctx_atual is not None else 8192,
                    step=512,
                    key=_state_key(agente_id, f"ctx::{alvo}"),
                    label_visibility="collapsed",
                    help="8192 cobre prompts de ~14k chars. So aplicado a Ollama local.",
                )
            else:
                ctx_val = None
                st.markdown(
                    '<div style="font-size:0.85em; color:#999; padding:8px;">Auto (default Ollama)</div>',
                    unsafe_allow_html=True,
                )

    # Botoes de acao
    col1, col2, col3, col4 = st.columns([1.2, 1.5, 1.2, 2])
    with col1:
        if st.button("💾 Salvar tudo", key=_state_key(agente_id, f"save::{alvo}"),
                     type="primary", use_container_width=True,
                     help="Salva prompt + parametros customizados."):
            # Decide se vai usar novo_texto: se for igual ao default,
            # NAO salva o prompt (mantém usando o default constante)
            prompt_pra_salvar = novo_texto if novo_texto != default_constante else None
            config_completa = {
                "system_prompt": prompt_pra_salvar,
                "temperature": temp_val,
                "max_tokens": maxt_val,
                "force_json": fj_val,
                "seed": seed_val,
                "num_ctx": ctx_val,
            }
            ok = save_agent_config(agente_id, alvo, config_completa)
            if ok:
                st.success(f"✅ Config salva pra `{alvo_label}`")
                st.rerun()
            else:
                st.error("Falha ao salvar (problema de I/O?).")

    with col2:
        if st.button("🔄 Resetar pro Padrao",
                     key=_state_key(agente_id, f"reset::{alvo}"),
                     disabled=not (eh_custom or n_custom_params > 0),
                     use_container_width=True,
                     help="Remove TUDO (prompt + parametros). Sistema volta a usar defaults."):
            ok = delete_agent_prompt(agente_id, alvo)
            if ok:
                st.success(f"🔄 Customizacao removida pra `{alvo_label}`")
                st.rerun()

    with col3:
        if st.button("📋 Copiar Padrao",
                     key=_state_key(agente_id, f"copy::{alvo}"),
                     use_container_width=True,
                     help="Copia o texto da constante padrao pra editar a partir dela."):
            st.session_state[key_textarea] = default_constante
            st.rerun()

    with col4:
        # Diff size
        if eh_custom:
            diff = len(custom_atual) - len(default_constante)
            sinal = "+" if diff >= 0 else ""
            st.markdown(
                f'<div style="text-align:right; font-size:0.78em; color:#888; '
                f'padding-top:8px;">'
                f'Custom: {len(custom_atual)} chars · vs Padrao: {len(default_constante)} '
                f'<strong>({sinal}{diff})</strong></div>',
                unsafe_allow_html=True,
            )


def _agent_enum(agente_id: str, agente_nome: str = "") -> str | None:
    """Mapeia o id/nome da aba pro enum agent_name do banco (agent_configs)."""
    s = f"{agente_id} {agente_nome}".lower()
    if any(t in s for t in ("profile", "perfil", "agente1", "agente 1")):
        return "profile_builder"
    if any(t in s for t in ("adapt", "agente2", "agente 2")):
        return "adapter"
    if any(t in s for t in ("valid", "agente3", "agente 3")):
        return "validator"
    return None


def _render_default_runtime(agente_id: str, agente_nome: str, modelos_pool: list[dict]):
    """Painel do DEFAULT consumido pelo worker/frontend (grava em agent_configs).

    Esta e a fonte da verdade que o worker Python LE pra rodar o agente. Trocar
    aqui pra um modelo [LOCAL] = testes a R$ 0.
    """
    if not _AGENT_CFG_OK:
        return
    agent_enum = _agent_enum(agente_id, agente_nome)
    if agent_enum is None:
        return

    cfg = agent_configs_repo.read_config(agent_enum) or {}
    cur_engine = cfg.get("engine") or "hybrid"
    cur_model = cfg.get("model")
    cur_strict = bool(cfg.get("strict_no_fallback", True))

    with st.container(border=True):
        st.markdown("#### 🎯 Default consumido (worker / frontend)")
        st.caption(
            "Config que o **worker Python** (e o frontend, via Supabase) usam de "
            "verdade pra rodar este agente. Salva em `agent_configs`. "
            "Escolha um modelo **[LOCAL]** pra rodar a R$ 0."
        )
        if cfg:
            st.caption(
                f"Em uso agora: **{cur_engine}** · modelo `{cur_model or '—'}` · "
                f"estrito={'sim' if cur_strict else 'não'}"
            )

        col1, col2 = st.columns([1, 1])
        with col1:
            engine = st.radio(
                "Motor",
                options=["native", "hybrid"],
                index=0 if cur_engine == "native" else 1,
                format_func=lambda e: "Nativo (R$ 0)" if e == "native" else "Híbrido (LLM fina)",
                key=_state_key(agente_id, "rt_engine"),
                horizontal=True,
            )
        with col2:
            strict = st.checkbox(
                "Modo estrito (não cair pro Nativo se a LLM falhar)",
                value=cur_strict,
                key=_state_key(agente_id, "rt_strict"),
            )

        model_opts = [m.get("model") for m in (modelos_pool or []) if m.get("model")]
        labels = {m.get("model"): m.get("label", m.get("model")) for m in (modelos_pool or [])}
        if cur_model and cur_model not in model_opts:
            model_opts = [cur_model] + model_opts
            labels.setdefault(cur_model, f"{cur_model} (fora do pool)")

        if model_opts:
            idx = model_opts.index(cur_model) if cur_model in model_opts else 0
            model = st.selectbox(
                "Modelo da LLM (usado no Híbrido) — prefira um [LOCAL] pra custo R$ 0",
                options=model_opts,
                index=idx,
                format_func=lambda m: labels.get(m, m),
                key=_state_key(agente_id, "rt_model"),
                disabled=(engine == "native"),
            )
        else:
            model = cur_model
            st.info("Nenhum modelo no pool. Cadastre em Configurações → LiteLLM.")

        if st.button("💾 Salvar default", type="primary",
                     key=_state_key(agente_id, "rt_save")):
            ok, msg = agent_configs_repo.save_config(
                agent_enum,
                engine=engine,
                model=model,
                strict_no_fallback=strict,
            )
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)


def _render_agente_tab(agente: dict):
    """Renderiza a tab de UM agente: sub-tabs Default + modelos cadastrados."""
    agente_id = agente["id"]

    # Header com nome + botao de refresh
    col_t, col_btn = st.columns([5, 1])
    with col_t:
        st.markdown(f"### {agente['nome']}")
        st.caption(agente["descricao"])
    with col_btn:
        if st.button("🔄 Recarregar pool",
                     key=_state_key(agente_id, "refresh_pool"),
                     help="Re-le providers_litellm.json pra detectar modelos novos ou removidos.",
                     use_container_width=True):
            # Forca re-execucao - listar_modelos_disponiveis NAO eh cached entao
            # qualquer mudanca em providers_litellm.json eh refletida automaticamente.
            st.rerun()

    # Carrega POOL ATUAL (sempre dinamico - sem cache)
    modelos_pool = _render_lista_modelos_disponiveis(agente_id)
    modelos_no_pool = {m.get("model", "?") for m in modelos_pool}

    # Detecta ORPHANS: customizacoes de modelos que nao existem mais no pool
    customs = list_custom_prompts(agente_id) if _STORAGE_OK else {}
    orphans = {
        k: v for k, v in customs.items()
        if k != "_default_" and k not in modelos_no_pool
    }

    # Status bar
    n_customs = len([k for k in customs if k != "_default_"])
    has_default_custom = "_default_" in customs
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Modelos no pool", len(modelos_no_pool))
    with col_b:
        st.metric("Customs ativas", n_customs + (1 if has_default_custom else 0))
    with col_c:
        if orphans:
            st.metric("⚠️ Orphans", len(orphans), help="Customs de modelos removidos")
        else:
            st.metric("Orphans", 0)

    # Aviso sobre orphans
    if orphans:
        st.warning(
            f"⚠️ **{len(orphans)} customizacao(es) orfaa(s)** detectada(s) - "
            f"modelos que voce customizou mas que nao estao mais no pool. "
            f"Vai pra aba **🧹 Limpeza** pra remove-las."
        )

    # Painel do DEFAULT consumido (grava em agent_configs — fonte do worker/frontend)
    _render_default_runtime(agente_id, agente.get("nome", ""), modelos_pool)

    st.divider()

    # Constroi as sub-tabs DINAMICAMENTE conforme o pool atual
    sub_tab_labels = ["🎯 Default do Agente"]
    sub_tab_alvos = ["_default_"]

    for m in modelos_pool:
        modelo = m.get("model", "?")
        nome_curto = modelo.split("/")[-1] if "/" in modelo else modelo
        tipo = "[LOCAL]" if m.get("is_local") else "[CLOUD]"
        # Indica se ja tem custom pra esse modelo
        marker = " ✏️" if modelo in customs else ""
        sub_tab_labels.append(f"{tipo} {nome_curto}{marker}")
        sub_tab_alvos.append(modelo)

    # Sub-tab de Limpeza (so aparece quando ha orphans)
    if orphans:
        sub_tab_labels.append(f"🧹 Limpeza ({len(orphans)})")
        sub_tab_alvos.append("__orphans__")

    if len(modelos_pool) == 0:
        st.info(
            "Nenhum modelo executavel cadastrado. Cadastre em "
            "Configuracoes → LiteLLM pra customizar por modelo."
        )

    tabs = st.tabs(sub_tab_labels)
    for tab, alvo, label in zip(tabs, sub_tab_alvos, sub_tab_labels):
        with tab:
            if alvo == "__orphans__":
                _render_orphans(agente_id, orphans)
            elif alvo == "_default_":
                st.caption(
                    "ℹ️ Customizacao DEFAULT do agente - sobrescreve a constante "
                    "hardcoded pra TODOS os modelos que nao tem custom proprio."
                )
                _render_editor_prompt(agente_id, alvo, label)
            else:
                st.caption(
                    f"ℹ️ Customizacao especifica pra `{alvo}` - sobrescreve o "
                    "Default do Agente quando este modelo for o escolhido."
                )
                _render_editor_prompt(agente_id, alvo, label)


def _render_orphans(agente_id: str, orphans: dict):
    """Renderiza UI pra limpar customizacoes orfaas.

    Orfa = custom de um modelo que nao existe mais no pool (foi removido,
    renomeado, ou arquivado). Continuam ocupando espaco no JSON.
    """
    st.markdown("#### 🧹 Customizacoes Orfaas")
    st.caption(
        "Estes modelos tinham customizacao salva, mas nao estao mais no pool atual. "
        "Provavel que voce removeu, renomeou ou arquivou. Pode limpar com seguranca - "
        "se voltar a cadastrar o modelo no pool, comeca com a constante padrao."
    )

    if not orphans:
        st.success("✅ Nenhuma orphan - tudo limpo.")
        return

    # Botao "Remover todas"
    col_clear, _, _ = st.columns([2, 1, 3])
    with col_clear:
        if st.button(
            f"🗑️ Remover TODAS ({len(orphans)})",
            key=_state_key(agente_id, "remove_all_orphans"),
            type="primary",
            use_container_width=True,
        ):
            removidas = 0
            for modelo in list(orphans.keys()):
                if delete_agent_prompt(agente_id, modelo):
                    removidas += 1
            st.success(f"✅ {removidas} orphan(s) removida(s)")
            st.rerun()

    st.divider()

    # Lista individual
    for modelo, prompt_text in orphans.items():
        with st.container(border=True):
            col_info, col_btn = st.columns([4, 1])
            with col_info:
                st.markdown(f"**`{modelo}`**")
                st.caption(
                    f"{len(prompt_text)} chars · "
                    f"Comeco: {prompt_text[:100]!r}..."
                )
            with col_btn:
                if st.button(
                    "🗑️ Remover",
                    key=_state_key(agente_id, f"remove_orphan::{modelo}"),
                    use_container_width=True,
                ):
                    if delete_agent_prompt(agente_id, modelo):
                        st.success(f"Removida customizacao de `{modelo}`")
                        st.rerun()


# ============================================================================
# Painel de Backups Versionados (auto-backup + restauracao seletiva)
# ============================================================================

def _format_mtime(ts: float) -> str:
    """Formata timestamp Unix como '31/05/2026 18:45:00'."""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return "?"


def _render_backups_panel():
    """Painel completo de gerenciamento de backups (lista + inspecao + restore)."""
    if not _STORAGE_OK:
        return

    backups = listar_backups()

    with st.expander(
        f"📂 Histórico de Backups ({len(backups)} versões)",
        expanded=False,
    ):
        # Cabecalho explicativo + botao de backup manual
        col_h1, col_h2 = st.columns([3, 1])
        with col_h1:
            st.caption(
                "Cada **💾 Salvar tudo** cria um snapshot automatico do "
                "`agent_prompts.json`. Voce pode restaurar uma versao inteira "
                "OU apenas a config de UM modelo especifico, sem mexer nos outros."
            )
        with col_h2:
            if st.button(
                "📸 Criar backup agora",
                use_container_width=True,
                help="Backup manual do estado atual (alem do auto-backup do save).",
            ):
                nome = criar_backup(motivo="manual")
                if nome:
                    st.success(f"Backup: `{nome}`")
                    st.rerun()
                else:
                    st.error("Falha ao criar backup")

        if not backups:
            st.info(
                "Ainda nao ha backups. Salve uma config (💾 Salvar tudo em "
                "qualquer sub-tab) ou clique em 'Criar backup agora' acima."
            )
            return

        st.divider()

        # Lista de backups (mais recente primeiro)
        for b in backups:
            mtime_str = _format_mtime(b["mtime"])
            size_kb = b["size_bytes"] / 1024.0
            num_modelos = b.get("num_modelos", 0)
            corrupted = b.get("corrupted", False)

            with st.container(border=True):
                col_l, col_m, col_r = st.columns([5, 1.5, 1])

                with col_l:
                    if corrupted:
                        st.markdown(
                            f"⚠️ **{mtime_str}** · _backup corrompido_"
                        )
                    else:
                        st.markdown(
                            f"📅 **{mtime_str}** · "
                            f"{num_modelos} modelo(s) · "
                            f"{size_kb:.1f} KB"
                        )
                    st.caption(f"`{b['filename']}`")

                with col_m:
                    if not corrupted:
                        if st.button(
                            "🔍 Inspecionar",
                            key=f"insp_{b['filename']}",
                            use_container_width=True,
                        ):
                            curr = st.session_state.get(
                                f"inspect_{b['filename']}", False
                            )
                            st.session_state[f"inspect_{b['filename']}"] = (
                                not curr
                            )
                            st.rerun()

                with col_r:
                    if st.button(
                        "🗑️",
                        key=f"del_{b['filename']}",
                        help="Excluir este backup permanentemente",
                        use_container_width=True,
                    ):
                        if excluir_backup(b["filename"]):
                            st.success("Excluido")
                            st.rerun()
                        else:
                            st.error("Falha")

                # Inspecao expandida
                if (
                    not corrupted
                    and st.session_state.get(f"inspect_{b['filename']}", False)
                ):
                    _render_backup_inspecao(b["filename"])


def _render_backup_inspecao(filename: str):
    """Renderiza detalhe inspecionavel de UM backup: lista (agente,modelo) +
    botoes de restauracao por item ou total.
    """
    content = ler_backup(filename)
    if not isinstance(content, dict):
        st.warning("Nao foi possivel ler o backup.")
        return

    st.markdown("##### 📋 Conteúdo do backup")
    if not content:
        st.info("Backup vazio (sem agentes salvos).")
        return

    for ag_id, modelos in content.items():
        if not isinstance(modelos, dict) or not modelos:
            continue
        st.markdown(f"**Agente:** `{ag_id}`")

        for modelo_nome, cfg in modelos.items():
            with st.container(border=True):
                col_ml, col_mr = st.columns([4, 1.3])

                with col_ml:
                    st.markdown(f"`{modelo_nome}`")
                    if isinstance(cfg, dict):
                        prompt = cfg.get("system_prompt", "")
                        prompt_chars = (
                            len(prompt) if isinstance(prompt, str) else 0
                        )
                        partes = [f"📝 {prompt_chars} chars"]
                        if cfg.get("temperature") is not None:
                            partes.append(
                                f"🌡️ temp={cfg['temperature']}"
                            )
                        if cfg.get("max_tokens") is not None:
                            partes.append(
                                f"🎯 max_tokens={cfg['max_tokens']}"
                            )
                        if cfg.get("force_json") is not None:
                            partes.append(
                                f"📦 force_json={cfg['force_json']}"
                            )
                        if cfg.get("seed") is not None:
                            partes.append(f"🌱 seed={cfg['seed']}")
                        if cfg.get("num_ctx") is not None:
                            partes.append(f"🪟 num_ctx={cfg['num_ctx']}")
                        st.caption(" · ".join(partes))

                        # Preview do prompt
                        if isinstance(prompt, str) and prompt:
                            with st.expander("Ver prompt completo"):
                                st.code(prompt, language="text")

                with col_mr:
                    if st.button(
                        "↩️ Restaurar este modelo",
                        key=f"restore_{filename}_{ag_id}_{modelo_nome}",
                        use_container_width=True,
                        help=(
                            f"Substitui APENAS a config de {modelo_nome} pela "
                            f"versao deste backup. Os outros modelos do "
                            f"agent_prompts.json atual ficam intactos."
                        ),
                    ):
                        ok = restaurar_modelo_do_backup(
                            filename, ag_id, modelo_nome
                        )
                        if ok:
                            st.success(
                                f"`{modelo_nome}` restaurado deste backup!"
                            )
                            st.session_state[f"inspect_{filename}"] = False
                            st.rerun()
                        else:
                            st.error("Falha ao restaurar")

    # Acoes em massa: restaurar tudo / fechar
    st.divider()
    col_rt, col_close = st.columns(2)
    with col_rt:
        if st.button(
            "↩️ Restaurar TUDO deste backup",
            key=f"restore_all_{filename}",
            type="primary",
            use_container_width=True,
            help=(
                "Sobrescreve o agent_prompts.json INTEIRO com o conteudo "
                "deste backup. Antes de sobrescrever, cria um backup do "
                "estado atual (motivo: pre_restore_completo) pra permitir "
                "desfazer."
            ),
        ):
            if restaurar_backup_completo(filename):
                st.success("Backup restaurado completamente!")
                st.session_state[f"inspect_{filename}"] = False
                st.rerun()
            else:
                st.error("Falha ao restaurar")

    with col_close:
        if st.button(
            "Fechar inspeção",
            key=f"close_{filename}",
            use_container_width=True,
        ):
            st.session_state[f"inspect_{filename}"] = False
            st.rerun()


# ============================================================================
# API publica - chamada pelo app.py
# ============================================================================

def render():
    """Renderer principal - chamado pelo menu do app.py."""
    _render_header()
    if not _render_storage_status():
        return

    agentes = list_known_agents()
    if not agentes:
        st.warning("Nenhum agente registrado no sistema.")
        return

    if len(agentes) == 1:
        _render_agente_tab(agentes[0])
    else:
        labels = [a["nome"] for a in agentes]
        tabs = st.tabs(labels)
        for tab, agente in zip(tabs, agentes):
            with tab:
                _render_agente_tab(agente)

    # Painel de backups (auto-backup + restauracao versionada).
    # Sempre no FIM da pagina, recolhido por default.
    st.divider()
    _render_backups_panel()
