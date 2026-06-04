"""
pagina_formularios_editor.py - Editor visual de schemas declarativos NEEI v2.x.

Abas:
  - Mapping     -> field_id -> coluna CSV (read-only field_id, edita coluna)
  - Value Maps  -> traducao texto bruto -> valor canonical (com/sem acento)
  - Metadata    -> schema_version, title, produced_at

Salvar:
  - "Salvar alteracoes" sobrescreve o arquivo atual
  - "Salvar como nova versao" gera neei_v2_(N+1).json automatico

Validacao:
  - Diff de colunas mapeadas vs colunas reais do ultimo CSV em session_state
  - Highlight de colunas faltando / colunas no CSV sem mapping

Sem custo de LLM. Tudo Python puro + pandas + streamlit.
"""
from __future__ import annotations

import json
import re
import hashlib
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st


SCHEMAS_DIR = Path(__file__).resolve().parent / "innova_bridge" / "formularios" / "schemas"


# ============================================================================
# Helpers de categorizacao por prefixo do field_id
# ============================================================================

CATEGORIAS = [
    ("meta",        "Meta",            re.compile(r"^meta\.")),
    ("characteriz", "Caracterizacao",  re.compile(r"^characterization\.")),
    ("capability",  "Capacidades",     re.compile(r"^capability_")),
    ("barriers",    "Barreiras",       re.compile(r"^barriers_")),
    ("support",     "Suportes",        re.compile(r"^support_")),
    ("auth",        "Autorizacoes",    re.compile(r"^auth_")),
    ("restrict",    "Restricoes",      re.compile(r"^restrictions\.")),
    ("aee",         "AEE",             re.compile(r"^aee\.")),
]


def _categoria_de(field_id: str) -> str:
    """Retorna o label da categoria detectada pelo prefixo do field_id."""
    for _slug, label, regex in CATEGORIAS:
        if regex.match(field_id):
            return label
    return "Outros"


# Valores canonicais aceitos pelo Pydantic em cada grupo de value_map.
VALORES_CANONICAL = {
    "capability":          ["without_support", "with_support", "cannot", "not_observed"],
    "support":             ["yes_alone", "yes_with_support", "no", "not_tested"],
    "authorization":       ["not_authorized", "light", "moderate", "intense"],
    "has_clinical_report": [True, False],
    "extra_time":          [True, False],
}


# ============================================================================
# State helpers
# ============================================================================

def _state_key(schema_path: str, suffix: str) -> str:
    """Key estavel pra session_state, namespaced por schema."""
    stem = Path(schema_path).stem
    return f"schema_editor::{stem}::{suffix}"


def _load_schema(schema_path: str) -> dict:
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _next_version_filename(current_filename: str) -> str:
    """neei_v2_0.json -> neei_v2_1.json. Generico pra qualquer _vMAJOR_MINOR."""
    m = re.match(r"(.+_v\d+_)(\d+)\.json$", current_filename)
    if m:
        prefix, num = m.group(1), int(m.group(2))
        return f"{prefix}{num + 1}.json"
    return f"{Path(current_filename).stem}_new.json"


def _hash_schema(schema: dict) -> str:
    """MD5 dos primeiros 12 chars, ignorando _hash interno."""
    clean = {k: v for k, v in schema.items() if k != "_hash"}
    blob = json.dumps(clean, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.md5(blob).hexdigest()[:12]


# ============================================================================
# Aba 1: Mapping (73 field_ids)
# ============================================================================

def _render_aba_mapping(schema: dict, schema_path: str) -> dict:
    mapping = schema.get("mapping", {})

    rows = []
    for fid, col in mapping.items():
        rows.append({
            "Categoria": _categoria_de(fid),
            "field_id": fid,
            "Coluna CSV": col,
        })
    df = pd.DataFrame(rows)

    st.caption(
        f"**{len(df)} campos mapeados.** Edite 'Coluna CSV' pra ajustar ao nome real "
        "que aparece no header do Google Forms exportado. field_id e Categoria sao read-only."
    )

    # Filtro por categoria pra navegar mais rapido
    cats_disponiveis = ["(todas)"] + sorted(df["Categoria"].unique().tolist())
    cat_filtro = st.selectbox(
        "Filtrar categoria",
        cats_disponiveis,
        key=_state_key(schema_path, "mapping_filter"),
    )

    if cat_filtro != "(todas)":
        df_view = df[df["Categoria"] == cat_filtro].reset_index(drop=True)
    else:
        df_view = df

    edited = st.data_editor(
        df_view,
        key=_state_key(schema_path, "mapping_editor"),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Categoria": st.column_config.TextColumn("Categoria", disabled=True, width="small"),
            "field_id":  st.column_config.TextColumn("field_id", disabled=True, width="medium"),
            "Coluna CSV": st.column_config.TextColumn("Coluna CSV (editavel)", width="large"),
        },
        num_rows="fixed",
        height=600,
    )

    # Reconstroi o dict mapping a partir da view editada (merge com nao-filtrados).
    # Se filtrou, precisa preservar as linhas que NAO estao em df_view.
    new_mapping = dict(mapping)  # comeca com tudo
    for _, row in edited.iterrows():
        new_mapping[row["field_id"]] = row["Coluna CSV"]

    schema["mapping"] = new_mapping
    return schema


# ============================================================================
# Aba 2: Value Maps (5 grupos)
# ============================================================================

def _render_aba_value_maps(schema: dict, schema_path: str) -> dict:
    vm = schema.get("value_maps", {})
    new_vm = {}

    st.caption(
        "Mapeia o texto bruto do CSV para os valores canonicais aceitos pelo Pydantic. "
        "Adicione variacoes (com/sem acento, typos) apontando pro mesmo valor canonical."
    )

    for grupo_key in ["capability", "support", "authorization", "has_clinical_report", "extra_time"]:
        bloco = vm.get(grupo_key, {})
        opcoes_canon = VALORES_CANONICAL.get(grupo_key, [])

        with st.expander(f"{grupo_key}  ({len(bloco)} variacoes)", expanded=False):
            rows = [{"Texto bruto (CSV)": k, "Valor canonical": v} for k, v in bloco.items()]
            if not rows:
                rows = [{"Texto bruto (CSV)": "", "Valor canonical": opcoes_canon[0] if opcoes_canon else ""}]
            df = pd.DataFrame(rows)

            col_cfg = {
                "Texto bruto (CSV)": st.column_config.TextColumn(
                    "Texto bruto (CSV)", width="large", required=True,
                ),
                "Valor canonical": st.column_config.SelectboxColumn(
                    "Valor canonical", options=opcoes_canon, required=True, width="medium",
                ),
            }

            edited = st.data_editor(
                df,
                key=_state_key(schema_path, f"vm_{grupo_key}"),
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                column_config=col_cfg,
            )

            new_dict = {}
            for _, row in edited.iterrows():
                k = str(row["Texto bruto (CSV)"]).strip()
                v = row["Valor canonical"]
                if k:
                    new_dict[k] = v
            new_vm[grupo_key] = new_dict

    schema["value_maps"] = new_vm
    return schema


# ============================================================================
# Aba 3: Metadata
# ============================================================================

def _render_aba_metadata(schema: dict, schema_path: str) -> dict:
    st.caption("Metadados do schema. schema_version e usado pra identificar o adapter compativel.")

    col1, col2 = st.columns(2)
    with col1:
        sv = st.text_input(
            "schema_version",
            value=schema.get("schema_version", ""),
            key=_state_key(schema_path, "meta_version"),
            help="Ex: NEEI_v2.0 / NEEI_v2.1",
        )
    with col2:
        try:
            d_atual = date.fromisoformat(schema.get("produced_at", ""))
        except Exception:
            d_atual = date.today()
        pa = st.date_input(
            "produced_at",
            value=d_atual,
            key=_state_key(schema_path, "meta_produced"),
        )

    title = st.text_input(
        "title",
        value=schema.get("title", ""),
        key=_state_key(schema_path, "meta_title"),
    )

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total field_ids", len(schema.get("mapping", {})))
    c2.metric("Value maps", len(schema.get("value_maps", {})))
    c3.metric("Hash MD5 (12)", _hash_schema(schema))

    schema["schema_version"] = sv
    schema["title"] = title
    schema["produced_at"] = pa.isoformat() if hasattr(pa, "isoformat") else str(pa)
    return schema


# ============================================================================
# Validacao contra CSV em session_state
# ============================================================================

def _validar_contra_csv(schema: dict) -> Optional[dict]:
    csv_cols = st.session_state.get("ultimo_csv_colunas")
    if not csv_cols:
        return None
    mapped_cols = set(schema.get("mapping", {}).values())
    csv_cols_set = set(csv_cols)
    return {
        "csv_total": len(csv_cols),
        "mapeadas": len(mapped_cols),
        "faltando_no_csv": sorted(mapped_cols - csv_cols_set),
        "no_csv_sem_mapping": sorted(csv_cols_set - mapped_cols),
    }


# ============================================================================
# API publica
# ============================================================================

def render_editor_schema(schema_path: str) -> None:
    """Renderiza o editor visual completo pra UM schema. Chamado pelo card."""
    schema_path = str(schema_path)
    schema_arq = _load_schema(schema_path)

    st.markdown(f"### Editor: `{Path(schema_path).name}`")
    st.caption(
        f"**{schema_arq.get('schema_version', '?')}** - "
        f"{schema_arq.get('title', '?')} - "
        f"produzido em {schema_arq.get('produced_at', '?')}"
    )

    # Buffer no session_state pra preservar edicoes entre reruns.
    key_buf = _state_key(schema_path, "buffer")
    if key_buf not in st.session_state:
        st.session_state[key_buf] = json.loads(json.dumps(schema_arq))

    schema_buf = st.session_state[key_buf]

    tab_map, tab_vm, tab_meta = st.tabs(["Mapping", "Value Maps", "Metadata"])

    with tab_map:
        schema_buf = _render_aba_mapping(schema_buf, schema_path)
    with tab_vm:
        schema_buf = _render_aba_value_maps(schema_buf, schema_path)
    with tab_meta:
        schema_buf = _render_aba_metadata(schema_buf, schema_path)

    st.session_state[key_buf] = schema_buf

    st.divider()

    # Validacao contra CSV (se houver)
    val = _validar_contra_csv(schema_buf)
    if val is not None:
        with st.container(border=True):
            st.markdown("##### Validacao contra ultimo CSV carregado")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Colunas no CSV", val["csv_total"])
            c2.metric("Mapeadas", val["mapeadas"])
            c3.metric("Faltando no CSV", len(val["faltando_no_csv"]))
            c4.metric("CSV sem mapping", len(val["no_csv_sem_mapping"]))

            if val["faltando_no_csv"]:
                with st.expander(
                    f"AVISO: {len(val['faltando_no_csv'])} colunas mapeadas NAO existem no CSV",
                    expanded=True,
                ):
                    for c in val["faltando_no_csv"]:
                        st.markdown(f"- `{c}`")

            if val["no_csv_sem_mapping"]:
                with st.expander(
                    f"INFO: {len(val['no_csv_sem_mapping'])} colunas do CSV sem mapping no schema",
                    expanded=False,
                ):
                    for c in val["no_csv_sem_mapping"]:
                        st.markdown(f"- `{c}`")
    else:
        st.info("Suba um CSV no bloco Importar para validar este schema contra ele.")

    st.divider()

    # Botoes de salvar
    col_s1, col_s2, col_s3 = st.columns([1, 1, 1])
    with col_s1:
        if st.button("Salvar alteracoes", type="primary", use_container_width=True,
                     key=_state_key(schema_path, "btn_save")):
            with open(schema_path, "w", encoding="utf-8") as f:
                json.dump(schema_buf, f, ensure_ascii=False, indent=2)
            st.success(f"Salvo em {Path(schema_path).name}")
            st.session_state.pop(key_buf, None)
            st.rerun()

    with col_s2:
        if st.button("Salvar como nova versao", use_container_width=True,
                     key=_state_key(schema_path, "btn_save_new")):
            novo_nome = _next_version_filename(Path(schema_path).name)
            novo_path = Path(schema_path).parent / novo_nome
            with open(novo_path, "w", encoding="utf-8") as f:
                json.dump(schema_buf, f, ensure_ascii=False, indent=2)
            st.success(f"Nova versao criada: {novo_nome}")
            st.balloons()

    with col_s3:
        if st.button("Descartar alteracoes", use_container_width=True,
                     key=_state_key(schema_path, "btn_discard")):
            st.session_state.pop(key_buf, None)
            st.rerun()
