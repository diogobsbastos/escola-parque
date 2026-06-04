"""
═══════════════════════════════════════════════════════════════════════════
UTILS_ESTILO.PY — Identidade visual GLOBAL do Escola Parque V3
═══════════════════════════════════════════════════════════════════════════
Módulo central que padroniza o look-and-feel de todas as páginas.

Uso:
    # No app.py, logo após st.set_page_config:
    from utils_estilo import injetar_css_global
    injetar_css_global()

Cobertura:
  • st.tabs       — abas com aba selecionada em VERMELHO destacado
  • st.radio (sidebar) — opções com a selecionada em VERMELHO destacado
  • Botões consistentes
  • Cor primária = vermelho (#d62728), mesma usada em type="primary"

Princípio: defina o estilo UMA vez, herde em todo o app.
═══════════════════════════════════════════════════════════════════════════
"""
import streamlit as st


# Cor primária da identidade Escola Parque (mesma do type="primary")
COR_PRIMARIA = "#d62728"
COR_PRIMARIA_FRACA = "#fff5f5"   # fundo sutil pra estado selecionado
COR_TEXTO_NORMAL = "#555"
COR_TEXTO_HOVER = "#222"
COR_HOVER_BG = "#f5f5f5"


def injetar_css_global():
    """Injeta o CSS global do projeto. Chame UMA vez no início do app.py.

    Cobre:
      1. st.tabs       — abas horizontais (qualquer página do app)
      2. st.radio na sidebar — menu lateral (Configurações, etc.)
      3. Pequenos ajustes de consistência

    Como Streamlit reusa o componente entre páginas, basta chamar uma vez
    no entry point que TODAS as instâncias herdam o estilo.
    """
    st.markdown(
        f"""
        <style>
        /* ════════════════════════════════════════════════════════════════
           ABAS HORIZONTAIS (st.tabs)
           Aba selecionada: vermelho destacado, negrito, sublinhado grosso.
           Outras abas: cinza escuro legível, hover com fundo sutil.
           ════════════════════════════════════════════════════════════════ */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 4px;
            border-bottom: 2px solid #e6e6e6;
            margin-bottom: 16px;
        }}
        .stTabs [data-baseweb="tab-list"] button[data-baseweb="tab"] {{
            color: {COR_TEXTO_NORMAL} !important;
            font-weight: 600 !important;
            font-size: 1em !important;
            padding: 10px 18px !important;
            background: transparent !important;
            border-radius: 6px 6px 0 0 !important;
            transition: all 0.15s ease;
        }}
        .stTabs [data-baseweb="tab-list"] button[data-baseweb="tab"]:hover {{
            color: {COR_TEXTO_HOVER} !important;
            background: {COR_HOVER_BG} !important;
        }}
        .stTabs [data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] {{
            color: {COR_PRIMARIA} !important;
            font-weight: 800 !important;
            background: {COR_PRIMARIA_FRACA} !important;
        }}
        .stTabs [data-baseweb="tab-highlight"] {{
            background-color: {COR_PRIMARIA} !important;
            height: 3px !important;
        }}

        /* ════════════════════════════════════════════════════════════════
           MENU LATERAL (sidebar) — st.radio com mesmo visual das abas
           A opção SELECIONADA fica vermelha destacada; outras opções
           ficam mais nítidas (cinza escuro, não cinza claro).
           ════════════════════════════════════════════════════════════════ */
        section[data-testid="stSidebar"] div[role="radiogroup"] label {{
            color: {COR_TEXTO_NORMAL} !important;
            font-weight: 600 !important;
            padding: 8px 12px !important;
            border-radius: 6px !important;
            margin-bottom: 2px !important;
            transition: all 0.15s ease;
            cursor: pointer;
        }}
        section[data-testid="stSidebar"] div[role="radiogroup"] label:hover {{
            color: {COR_TEXTO_HOVER} !important;
            background: {COR_HOVER_BG} !important;
        }}
        /* Opção SELECIONADA — radio com aria-checked="true" */
        section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {{
            color: {COR_PRIMARIA} !important;
            font-weight: 800 !important;
            background: {COR_PRIMARIA_FRACA} !important;
            border-left: 3px solid {COR_PRIMARIA} !important;
            padding-left: 9px !important;
        }}
        /* Esconde o círculo do radio (visual mais limpo, parece menu de fato) */
        section[data-testid="stSidebar"] div[role="radiogroup"] label > div:first-child {{
            display: none !important;
        }}

        /* ════════════════════════════════════════════════════════════════
           AJUSTES DE CONSISTÊNCIA
           ════════════════════════════════════════════════════════════════ */
        /* Caption mais discreto */
        .element-container .stCaption {{
            color: #888 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
