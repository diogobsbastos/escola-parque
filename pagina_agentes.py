"""
pagina_agentes.py — UI da nova area AGENTES (Streamlit).
Mostra os 3 Agentes (1=Construtor de Perfil, 2=Adaptador, 3=Validador)
em cards com badge do agente DEFAULT em uso.

USO no app.py:
    elif view_mode == "agentes":
        from pagina_agentes import render_pagina_agentes
        render_pagina_agentes()
"""
from __future__ import annotations
import streamlit as st

try:
    from innova_bridge.agents import registry as ag_reg
except Exception as e:
    ag_reg = None
    _erro_import = str(e)

# Config REALMENTE consumida pelo worker/frontend (tabela agent_configs).
# E a fonte da verdade do que esta ATIVO — o registry e so o catalogo.
try:
    from innova_bridge.repositories import agent_configs_repo as _cfg_repo
except Exception:
    _cfg_repo = None


# ====================================================================
# Helpers
# ====================================================================

AGENT_TYPES = [
    ("profile_builder", "Agente 1", "Construtor de Perfil", "🧠"),
    ("adapter",         "Agente 2", "Adaptador de Provas",   "📝"),
    ("validator",       "Agente 3", "Validador",             "✅"),
]


def _card_agente(agent_type: str, label: str, descricao: str, icon: str) -> None:
    """Renderiza UM card de agente com info do default em uso."""
    if ag_reg is None:
        st.error(f"innova_bridge nao carregado: {_erro_import}")
        return

    default = ag_reg.get_default(agent_type)
    todos = ag_reg.listar(agent_type=agent_type)

    with st.container(border=True):
        # Titulo + engrenagem na MESMA LINHA, vertical_alignment=center
        col_titulo, col_acao = st.columns([5, 1], vertical_alignment="center")
        with col_titulo:
            st.markdown(f"### {icon} {label}")
        with col_acao:
            if st.button("⚙️", key=f"btn_config_{agent_type}", help="Configurar este agente"):
                st.session_state["agente_aberto"] = agent_type
                st.rerun()

        # Descricao em linha separada, full width
        st.caption(descricao)

        # --- 1) O QUE ESTA ATIVO DE VERDADE (agent_configs / "Default consumido") ---
        cfg = _cfg_repo.read_config(agent_type) if _cfg_repo else None
        if cfg:
            _eng = cfg.get("engine") or "hybrid"
            _mod = cfg.get("model") or "—"
            _est = "sim" if cfg.get("strict_no_fallback", True) else "nao"
            st.markdown(
                f"""
                <div style='font-size: 0.82em; line-height: 1.55; margin-top: 6px;'>
                  <div style='font-weight: 700; color: #28a745; margin-bottom: 2px;'>🟢 EM USO (worker / frontend)</div>
                  <div><strong>Motor:</strong> <code>{_eng}</code> &middot;
                       <strong>Modelo:</strong> <code>{_mod}</code> &middot;
                       <strong>Estrito:</strong> {_est}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.caption("⚠️ Config consumida (agent_configs) indisponivel — exibindo apenas o catalogo.")

        # --- 2) Default do CATALOGO (identidade/prompt do agente — NAO e o modelo ativo) ---
        if default:
            # Fonte pequena pra mostrar maxima informacao sem cortar
            st.markdown(
                f"""
                <div style='font-size: 0.78em; line-height: 1.55; margin-top: 6px;'>
                  <div style='font-weight: 600; color: #b8860b; margin-bottom: 4px;'>📌 CATALOGO (prompt/identidade)</div>
                  <div><strong>Label:</strong> {default.get('label', '-')}</div>
                  <div><strong>Prompt:</strong> <code>{default.get('prompt_version', '-')}</code></div>
                  <div><strong>Cadastrados:</strong> {len(todos)}</div>
                  <div style='opacity: 0.7; font-size: 0.9em;'>id: <code>{default.get('id', '-')}</code></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.warning(f"Nenhum agente default cadastrado para {label}. Clique na engrenagem.")


def _renderizar_detalhes(agent_type: str) -> None:
    """Painel de detalhes/edicao de um agent_type (todos os agentes cadastrados desse tipo)."""
    todos = ag_reg.listar(agent_type=agent_type)
    label_tipo = {
        "profile_builder": "Agente 1 — Construtor de Perfil",
        "adapter":         "Agente 2 — Adaptador",
        "validator":       "Agente 3 — Validador",
    }.get(agent_type, agent_type)

    st.markdown(f"## ⚙️ Configuracao: {label_tipo}")
    if st.button("← Voltar aos Agentes"):
        st.session_state.pop("agente_aberto", None)
        st.rerun()

    st.caption(
        f"{len(todos)} configuracao(oes) cadastrada(s). O default do CATALOGO define a identidade/prompt do agente. "
        "O motor/modelo EM USO de verdade e o do painel 'Default consumido (worker/frontend)'."
    )

    for i, ag in enumerate(todos):
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 1, 1])
            with c1:
                badge = "📌 Default do catalogo" if ag.get("is_default") else "⚪ Disponivel"
                st.markdown(f"**{badge}** &middot; **{ag['label']}**", unsafe_allow_html=True)
                st.caption(f"`{ag['llm_provider']}` / `{ag['llm_model']}` / prompt `{ag.get('prompt_version', '-')}`")
                st.caption(f"id: `{ag['id']}`")
            with c2:
                if not ag.get("is_default"):
                    if st.button("Tornar default do catalogo", key=f"set_default_{ag['id']}", type="primary", use_container_width=True):
                        ok, msg = ag_reg.set_default(ag["id"])
                        st.success(msg) if ok else st.error(msg)
                        st.rerun()
            with c3:
                if not ag.get("is_default"):
                    if st.button("🗑️ Remover", key=f"rm_{ag['id']}", use_container_width=True):
                        ok, msg = ag_reg.remover(ag["id"])
                        st.success(msg) if ok else st.error(msg)
                        st.rerun()

    # [REORG] Treinamento do Agente 1 embutido aqui (antes era a pagina separada
    # "Treinamento de Agentes"). Reutiliza as funcoes existentes do modulo de
    # treinamento - nenhuma logica muda, so o LUGAR onde o painel aparece.
    if agent_type == "profile_builder":
        try:
            import pagina_agentes_treinamento as _pat
        except Exception as _e:
            st.error(f"Treinamento embutido indisponivel: {_e}")
            return
        if _pat._render_storage_status():
            _ag1 = next(
                (a for a in _pat.list_known_agents() if a.get("id") == "agente1"),
                None,
            )
            if _ag1:
                st.divider()
                _pat._render_agente_tab(_ag1)
                st.divider()
                _pat._render_backups_panel()


# ====================================================================
# Render principal
# ====================================================================

def render_pagina_agentes() -> None:
    """Funcao publica chamada pelo app.py."""

    aberto = st.session_state.get("agente_aberto")
    if aberto:
        _renderizar_detalhes(aberto)
        return

    # Cabecalho
    col_titulo, col_badge = st.columns([3, 1])
    with col_titulo:
        st.title("Agentes")
        st.caption(
            "Pipeline de agentes LLM da Escola Parque V3. Cada agente tem versoes editaveis, "
            "e voce pode escolher qual usar (sistema A/B/N de configuracoes)."
        )
    with col_badge:
        st.markdown("<br>", unsafe_allow_html=True)
        st.info("**🛡️ Sistema Adaptativo v2.0**\n\nIntegrado ao Innova V2 (Supabase BR).", icon="🚀")

    st.divider()

    # 3 cards lado a lado
    cols = st.columns(3)
    for i, (atype, label, desc, icon) in enumerate(AGENT_TYPES):
        with cols[i]:
            _card_agente(atype, label, desc, icon)

    st.divider()

    # Rodape
    with st.expander("ℹ️ Sobre o sistema de Agentes", expanded=False):
        st.markdown(
            """
            **Arquitetura MLOps em 3 etapas:**

            1. **Agente 1 (Construtor de Perfil):** Le respostas de questionario (Google Forms,
               Form Proprio ou PDF OCR) ja convertidas pro formato canonico, e gera o PAI v1.0.

            2. **Agente 2 (Adaptador):** Le o PAI aprovado pela professora + prova original,
               e gera a prova adaptada para o aluno especifico.

            3. **Agente 3 (Validador):** Valida a prova adaptada. Pode dar veredito:
               PASS / PASS_WITH_NOTES / PATCH / FULL_RERUN.

            **Cada agente e EDITAVEL:** voce pode cadastrar varias configuracoes
            (LLM diferente, prompt diferente) e A/B testar qual gera melhor resultado.
            """
        )
