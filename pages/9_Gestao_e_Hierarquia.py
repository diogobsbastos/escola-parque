"""
pages/9_Gestao_e_Hierarquia.py - entrada de Gestao por Colegio.

Wrapper fino: delega pra pagina_colegios.render_pagina_colegios() (a teia
relacional: colegio -> sede -> turma -> alunos; professor <-> materia <-> turma).
Mantido como pagina nativa so TEMPORARIAMENTE - o destino e um botao na
sidebar custom do app.py (proximo passo).
"""
import streamlit as st

st.set_page_config(page_title="Colegios - Gestao", page_icon="\U0001F3EB", layout="wide")

try:
    from pagina_colegios import render_pagina_colegios
    render_pagina_colegios()
except Exception as e:  # pragma: no cover
    st.title("\U0001F3EB Colegios")
    st.error(f"Falha ao carregar a pagina de Colegios: {type(e).__name__} - {e}")
    import traceback
    with st.expander("Traceback"):
        st.code(traceback.format_exc())
