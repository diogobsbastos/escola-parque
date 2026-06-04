"""
pagina_formularios.py - UI da Area 0 (Formularios) do MLOps Escola Parque V3.

Responsabilidade: gerenciar SCHEMAS declarativos de questionarios.
NAO importa respostas de alunos - isso vive em ALUNO > Questionario Base.

Mostra:
  - Lista de schemas declarativos disponiveis (NEEI v2.0, futuros)
  - Editor visual via botao 👁 (3 abas: Mapping, Value Maps, Metadata)
"""
from __future__ import annotations
import json
from pathlib import Path

import streamlit as st

try:
    from pagina_formularios_editor import render_editor_schema
    _EDITOR_OK = True
    _EDITOR_ERR = None
except Exception as _e_editor:
    _EDITOR_OK = False
    _EDITOR_ERR = str(_e_editor)

SCHEMAS_DIR = Path(__file__).resolve().parent / "innova_bridge" / "formularios" / "schemas"


def _listar_schemas():
    """Retorna lista de schemas declarativos disponiveis."""
    if not SCHEMAS_DIR.exists():
        return []
    schemas = []
    for arq in sorted(SCHEMAS_DIR.glob("*.json")):
        try:
            with open(arq, "r", encoding="utf-8") as f:
                data = json.load(f)
            schemas.append({
                "path": str(arq),
                "filename": arq.name,
                "schema_version": data.get("schema_version", arq.stem),
                "title": data.get("title", arq.stem),
                "produced_at": data.get("produced_at", "-"),
                "n_fields": len(data.get("mapping", {})),
            })
        except Exception as e:
            schemas.append({"path": str(arq), "filename": arq.name, "erro": str(e)})
    return schemas


def _card_schema(schema: dict, em_uso: bool) -> None:
    """Renderiza UM card de schema com botao 👁 que abre/fecha o editor visual."""
    filename = schema.get("filename", "-")
    key_aberto = "schema_em_edicao"  # global: so um editor aberto por vez
    aberto = (st.session_state.get(key_aberto) == filename)

    with st.container(border=True):
        col_badge, col_info, col_acao = st.columns([1.4, 5.0, 1.0], vertical_alignment="center")
        with col_badge:
            if em_uso:
                st.markdown("🟢 **EM USO**")
            else:
                st.markdown("⚪ DISPONIVEL")
        with col_info:
            st.markdown(f"**{schema.get('title', '-')}**")
            st.caption(
                f"`{schema.get('schema_version', '-')}` · "
                f"{schema.get('n_fields', 0)} campos · "
                f"arquivo: `{filename}`"
            )
        with col_acao:
            icone = "✕" if aberto else "👁️"
            tooltip = "Fechar editor" if aberto else "Editar schema visualmente"
            if st.button(icone, key=f"ver_{filename}", help=tooltip):
                if aberto:
                    st.session_state.pop(key_aberto, None)
                else:
                    st.session_state[key_aberto] = filename
                st.rerun()

        if aberto:
            st.divider()
            if not _EDITOR_OK:
                st.error(f"Editor nao disponivel: {_EDITOR_ERR}")
            else:
                render_editor_schema(schema["path"])


def render_pagina_formularios() -> None:
    """Funcao publica chamada pelo app.py."""

    # Cabecalho
    col_titulo, col_badge = st.columns([3, 1])
    with col_titulo:
        st.title("Formulários")
        st.caption(
            "Schemas declarativos de questionários. Cada formulário define os campos "
            "que serão preenchidos pelo professor + AEE, e tem um adapter Python que "
            "converte a resposta (CSV/JSON) no formato canônico universal."
        )
    with col_badge:
        st.markdown("<br>", unsafe_allow_html=True)
        st.info(
            "**📋 Area 0 — MLOps**\n\nGestão dos schemas.\n\n"
            "Para importar a resposta de um aluno, vá em **Alunos → Questionário Base**.",
            icon="🧩",
        )

    st.divider()

    schemas = _listar_schemas()
    if not schemas:
        st.warning("Nenhum schema cadastrado em innova_bridge/formularios/schemas/")
        st.info("Crie um arquivo JSON declarativo (ex: neei_v2_0.json) para começar.")
        return

    st.markdown("### Schemas cadastrados")
    em_uso_default = schemas[0]["filename"]
    for sc in schemas:
        _card_schema(sc, em_uso=(sc["filename"] == em_uso_default))
