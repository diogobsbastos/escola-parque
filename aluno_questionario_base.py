"""
aluno_questionario_base.py - Tab "Questionario Base" dentro do prontuario do aluno.

Responsabilidade: importar e listar as RESPOSTAS de questionarios NEEI v2.x
preenchidas por esse aluno especifico.

Pipeline:
  CSV (Google Forms / Forms Proprio) -> adapter -> canonical -> arquivo local

Localizacao dos canonicals salvos:
  innova_bridge/formularios/canonicals/{aluno_id}_{schema_version}_{timestamp}.json

Diferenca CRITICA vs pagina_formularios.py:
  - Formularios = cadastro/edicao dos SCHEMAS (templates compartilhados)
  - Aluno > Questionario Base = RESPOSTAS daquele aluno especifico
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st

# Tentativa de import do adapter
try:
    from innova_bridge.formularios.adapters.from_neei_v2_0 import csv_to_canonical
    _ADAPTER_OK = True
    _ADAPTER_ERR = None
except Exception as _e:
    _ADAPTER_OK = False
    _ADAPTER_ERR = str(_e)

# Agente 1 (Profile Builder) - opcional pra UI mostrar botao Gerar PAI
try:
    from innova_bridge.agents import profile_builder
    _AGENTE1_OK = True
    _AGENTE1_ERR = None
except Exception as _e_pb:
    profile_builder = None
    _AGENTE1_OK = False
    _AGENTE1_ERR = str(_e_pb)


BASE_DIR = Path(__file__).resolve().parent
SCHEMAS_DIR = BASE_DIR / "innova_bridge" / "formularios" / "schemas"
CANONICALS_DIR = BASE_DIR / "innova_bridge" / "formularios" / "canonicals"


def _garantir_pasta_canonicals() -> None:
    """Cria a pasta se nao existir (pode estar ausente no primeiro uso)."""
    CANONICALS_DIR.mkdir(parents=True, exist_ok=True)


def _listar_schemas_disponiveis() -> list[dict]:
    """Lista os schemas declarativos cadastrados em innova_bridge/formularios/schemas/."""
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
            })
        except Exception:
            pass
    return schemas


def _listar_canonicals_do_aluno(aluno_id: str) -> list[dict]:
    """Lista os canonicals ja importados para esse aluno."""
    if not CANONICALS_DIR.exists():
        return []
    encontrados = []
    for arq in sorted(CANONICALS_DIR.glob(f"{aluno_id}_*.json"), reverse=True):
        try:
            stat = arq.stat()
            with open(arq, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            encontrados.append({
                "path": str(arq),
                "filename": arq.name,
                "schema_version": meta.get("source_schema", meta.get("schema_version", "?")),
                "fill_date": meta.get("fill_date", "?"),
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "capabilities_n": len(data.get("capabilities", {}).get("items", {})) if isinstance(data, dict) else 0,
                "barriers_n": len(data.get("barriers", {}).get("flags", {})) if isinstance(data, dict) else 0,
                "auth_n": len(data.get("authorizations", {}).get("intensities", {})) if isinstance(data, dict) else 0,
            })
        except Exception:
            pass
    return encontrados


def _salvar_canonical_local(aluno_id: str, schema_version: str, canon_dict: dict) -> Path:
    """Persiste o canonical em arquivo local. Retorna o Path criado."""
    _garantir_pasta_canonicals()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitiza schema_version pra filename (NEEI_v2.0 -> NEEI_v2_0)
    sv_safe = schema_version.replace(".", "_").replace("/", "_")
    nome = f"{aluno_id}_{sv_safe}_{timestamp}.json"
    destino = CANONICALS_DIR / nome
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(canon_dict, f, ensure_ascii=False, indent=2)
    return destino


# ============================================================================
# Sub-renderizadores
# ============================================================================

def _render_resultado_pai(filename: str, aluno_id: str) -> None:
    """Renderiza o resultado de uma chamada do Agente 1 ja feita (em session_state)."""
    key_resultado = f"resultado_pai_{filename}"
    res = st.session_state.get(key_resultado)
    if not res:
        return

    telemetria = res.get("telemetria", {})
    pai_dict = res.get("pai_dict", {})
    ok = telemetria.get("ok", False)

    with st.container(border=True):
        if ok:
            st.success("PAI v1.0 gerado, validado e salvo.")
        else:
            st.error(f"Geracao falhou: {telemetria.get('mensagem', '?')}")

        # Telemetria
        st.markdown("###### Telemetria")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Tokens in",  telemetria.get("tokens_in", 0))
        c2.metric("Tokens out", telemetria.get("tokens_out", 0))
        c3.metric("Custo (R$)", f"{telemetria.get('custo_brl', 0.0):.4f}")
        c4.metric("Tempo (s)",  f"{telemetria.get('tempo_s', 0.0):.1f}")

        st.caption(
            f"Modelo: `{telemetria.get('modelo','?')}` · "
            f"Provedor: `{telemetria.get('provedor','?')}` · "
            f"Agent: `{telemetria.get('agent_id','?')}`"
        )

        if telemetria.get("arquivo_salvo"):
            from pathlib import Path as _P
            arq_rel = _P(telemetria["arquivo_salvo"]).name
            st.caption(f"📁 Salvo em: `innova_bridge/formularios/pais_gerados/{arq_rel}`")

        # Preview JSON
        with st.expander("Ver PAI gerado (JSON cru)", expanded=False):
            st.json(pai_dict, expanded=False)

        # Acao principal: ir pra tab Perfil Pedagogico do aluno
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Limpar resultado",
                         key=f"limpar_pai_{filename}",
                         use_container_width=True):
                st.session_state.pop(key_resultado, None)
                st.rerun()
        with col_b:
            st.button("Ver na aba Perfil Pedagogico",
                      key=f"goto_ppo_{filename}",
                      type="primary",
                      use_container_width=True,
                      help="Clique na aba 'Perfil Pedagogico' acima para visualizar.",
                      disabled=True)


def _disparar_gerar_pai(canonical_path: str, filename: str, aluno_id: str,
                         modelo_escolhido: dict | None = None) -> None:
    """Chama profile_builder.build_pai e guarda o resultado em session_state.

    Se modelo_escolhido eh dict {provider, model, ...}, usa esse override.
    Senao, usa o default do registry.
    """
    if not _AGENTE1_OK or profile_builder is None:
        st.error(f"Agente 1 nao disponivel: {_AGENTE1_ERR}")
        return

    # Carrega o canonical do disco
    try:
        with open(canonical_path, "r", encoding="utf-8") as f:
            canonical_dict = json.load(f)
    except Exception as e:
        st.error(f"Falha lendo canonical: {e}")
        return

    # Laudo summary (opcional)
    laudo_summary = (
        canonical_dict.get("characterization", {}).get("clinical_summary")
        if canonical_dict.get("characterization", {}).get("has_clinical_report")
        else None
    )

    # Decide qual modelo usar
    provider_ovr = modelo_escolhido.get("provider") if modelo_escolhido else None
    model_ovr = modelo_escolhido.get("model") if modelo_escolhido else None
    label_modelo = modelo_escolhido.get("label", "agent default") if modelo_escolhido else "agent default"

    with st.spinner(
        f"Agente 1 ({label_modelo}) gerando PAI v1.0... "
        "Este passo pode levar 30-60s. Custo conforme modelo escolhido."
    ):
        try:
            pai_dict, telemetria = profile_builder.build_pai(
                canonical_dict=canonical_dict,
                laudo_summary=laudo_summary,
                provider_override=provider_ovr,
                model_override=model_ovr,
            )
        except Exception as e:
            st.error(f"Erro inesperado no Agente 1: **{type(e).__name__}** - {e}")
            import traceback as _tb
            with st.expander("Ver traceback"):
                st.code(_tb.format_exc())
            return

    st.session_state[f"resultado_pai_{filename}"] = {
        "pai_dict": pai_dict,
        "telemetria": telemetria,
        "aluno_id": aluno_id,
        "modelo_label": label_modelo,
    }


def _render_seletor_modelo_agente1(aluno_id: str) -> dict:
    """Selectbox de modelo LLM pra usar no Gerar PAI. Retorna o modelo escolhido."""
    if not _AGENTE1_OK or profile_builder is None:
        return {}
    try:
        modelos = profile_builder.listar_modelos_disponiveis()
    except Exception:
        modelos = []
    if not modelos:
        st.warning(
            "Nenhum modelo LLM disponivel. Cadastre em **Configuracoes -> LiteLLM**."
        )
        return {}

    # So mostra os que tem key SET (executaveis de verdade)
    executaveis = [m for m in modelos if m.get("has_key")]
    if not executaveis:
        st.warning("Nenhum modelo com API key cadastrada. Vai em Configuracoes -> LiteLLM.")
        return {}

    # Default: 1o ativo, senao o 1o da lista
    idx_default = 0
    for i, m in enumerate(executaveis):
        if m.get("is_active"):
            idx_default = i
            break

    key_sel = f"sel_modelo_agente1_{aluno_id}"
    col_sel, col_info = st.columns([3, 2])
    with col_sel:
        escolhido_label = st.selectbox(
            "Modelo do Agente 1 (Profile Builder)",
            options=[m["label"] for m in executaveis],
            index=idx_default,
            key=key_sel,
            help="Modelos cadastrados em Configuracoes -> LiteLLM. "
                 "Mude pra testar custo-beneficio (Gemini barato vs Claude qualidade).",
        )
    escolhido = next(m for m in executaveis if m["label"] == escolhido_label)
    with col_info:
        # Estimativa de custo (assumindo ~3500 in + ~5500 out por execucao)
        custo_est_usd = (3500/1_000_000) * escolhido["in_usd_1M"] + (5500/1_000_000) * escolhido["out_usd_1M"]
        custo_est_brl = custo_est_usd * 5.25  # cotacao aproximada
        st.markdown(
            f"<div style='padding-top:1.8rem; font-size:0.88em; color:#666;'>"
            f"Custo estimado: <b>~R$ {custo_est_brl:.3f}</b> "
            f"<small>(~3.5k in + ~5.5k out tokens)</small>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Persiste no session_state pra outras funcoes lerem
    st.session_state[f"modelo_agente1_{aluno_id}"] = escolhido
    return escolhido


def _render_lista_canonicals(aluno_id: str) -> None:
    """Lista os questionarios ja importados para esse aluno."""
    canonicals = _listar_canonicals_do_aluno(aluno_id)
    if not canonicals:
        st.info(
            f"Nenhum questionario base ainda importado para **{aluno_id}**. "
            "Clique em 'Importar novo' abaixo pra subir o primeiro CSV."
        )
        return

    st.markdown(f"##### Historico de questionarios ({len(canonicals)} versao(oes))")

    # Recupera o modelo escolhido (setado no topo da tab via _render_seletor_modelo_agente1)
    modelo_escolhido = st.session_state.get(f"modelo_agente1_{aluno_id}", {})

    for c in canonicals:
        with st.container(border=True):
            # Layout: info | metricas | 2 botoes acao (ver + gerar PAI)
            col_info, col_metrica, col_ver, col_pai = st.columns(
                [4, 3, 0.6, 1.4], vertical_alignment="center"
            )
            with col_info:
                st.markdown(f"**`{c['schema_version']}`** · importado em {c['modified']}")
                st.caption(f"Arquivo: `{c['filename']}` · {c['size_kb']} KB · fill_date: {c['fill_date']}")
            with col_metrica:
                m1, m2, m3 = st.columns(3)
                m1.metric("Capac.", c["capabilities_n"])
                m2.metric("Barreiras", c["barriers_n"])
                m3.metric("Autoriz.", c["auth_n"])
            with col_ver:
                if st.button("👁️", key=f"ver_canon_{c['filename']}", help="Ver canonical JSON"):
                    st.session_state[f"canon_aberto_{aluno_id}"] = c["filename"]
                    st.rerun()
            with col_pai:
                btn_label = "🤖 Gerar PAI"
                btn_help = (
                    "Dispara Agente 1 (Profile Builder) - LLM. ~R$ 3-5, ~30-60s."
                    if _AGENTE1_OK
                    else f"Agente 1 indisponivel: {_AGENTE1_ERR}"
                )
                if st.button(
                    btn_label,
                    key=f"gerar_pai_{c['filename']}",
                    type="primary",
                    help=btn_help,
                    use_container_width=True,
                    disabled=not _AGENTE1_OK or not modelo_escolhido,
                ):
                    _disparar_gerar_pai(
                        canonical_path=c["path"],
                        filename=c["filename"],
                        aluno_id=aluno_id,
                        modelo_escolhido=modelo_escolhido,
                    )
                    st.rerun()

            # JSON do canonical (se aberto pelo botao 👁)
            if st.session_state.get(f"canon_aberto_{aluno_id}") == c["filename"]:
                try:
                    with open(c["path"], "r", encoding="utf-8") as f:
                        dados = json.load(f)
                    with st.expander("Canonical JSON (clique pra fechar)", expanded=True):
                        st.json(dados, expanded=False)
                except Exception as e:
                    st.error(f"Falha ao ler: {e}")

            # Resultado do Gerar PAI (se ja foi disparado)
            _render_resultado_pai(c["filename"], aluno_id)


def _render_importer_inline(aluno_id: str) -> None:
    """Bloco de importacao de CSV NEEI v2.0 - sempre visivel embaixo."""
    if not _ADAPTER_OK:
        st.error(f"Adapter NEEI nao disponivel: {_ADAPTER_ERR}")
        return

    schemas = _listar_schemas_disponiveis()
    if not schemas:
        st.warning("Nenhum schema cadastrado em Formularios. Cadastre um schema antes de importar.")
        return

    st.markdown("##### Importar novo questionario (CSV)")
    st.caption(
        f"Suba o CSV exportado do Google Forms. O sistema valida e gera o JSON canonico "
        f"para o aluno **{aluno_id}** - sem custo de LLM."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        opcoes_schema = [s["schema_version"] for s in schemas]
        schema_sel = st.selectbox(
            "Schema do questionario",
            opcoes_schema,
            key=f"qb_schema_sel_{aluno_id}",
        )
    with col2:
        linha = st.number_input(
            "Linha do CSV",
            min_value=0, max_value=9999, value=0, step=1,
            key=f"qb_linha_{aluno_id}",
            help="Se o CSV tem varios alunos, escolha a linha (0 = primeira resposta).",
        )

    arquivo = st.file_uploader(
        "CSV do Google Forms",
        type=["csv"],
        key=f"qb_csv_upload_{aluno_id}",
        help="Arraste o CSV exportado ou clique para selecionar.",
    )

    if arquivo is None:
        st.info("Aguardando upload do CSV...")
        return

    # 2 botoes lado a lado
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        preview = st.button(
            "🔍 Pre-visualizar canonical",
            key=f"qb_btn_preview_{aluno_id}",
            type="secondary",
            use_container_width=True,
        )
    with col_btn2:
        salvar = st.button(
            "💾 Salvar canonical (local)",
            key=f"qb_btn_save_{aluno_id}",
            type="primary",
            use_container_width=True,
        )

    if preview or salvar:
        try:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                tmp.write(arquivo.getvalue())
                tmp_path = tmp.name

            with st.spinner("Rodando adapter (CSV -> canonical)..."):
                canonical = csv_to_canonical(tmp_path, linha=int(linha))

            try:
                canon_dict = canonical.model_dump()
            except AttributeError:
                canon_dict = canonical.dict()

            # Anota qual schema foi usado pra audit trail
            canon_dict.setdefault("meta", {})["source_schema"] = schema_sel
            canon_dict["meta"]["imported_aluno_id"] = aluno_id
            canon_dict["meta"]["imported_at"] = datetime.now().isoformat()

            # Resumo sempre
            st.success("✅ Canonical gerado com sucesso!")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Aluno (CSV)", canon_dict.get("meta", {}).get("student_id", "-"))
            c2.metric("Capabilities", len(canon_dict.get("capabilities", {}).get("items", {})))
            c3.metric("Barreiras", len(canon_dict.get("barriers", {}).get("flags", {})))
            c4.metric("Autorizacoes", len(canon_dict.get("authorizations", {}).get("intensities", {})))

            if preview:
                st.markdown("###### JSON canonico (preview)")
                st.json(canon_dict, expanded=False)

            if salvar:
                destino = _salvar_canonical_local(aluno_id, schema_sel, canon_dict)
                st.success(f"📁 Salvo em `{destino.relative_to(BASE_DIR)}`")
                st.balloons()
                # Limpa o uploader pra evitar resubmit acidental
                st.session_state.pop(f"qb_csv_upload_{aluno_id}", None)

        except Exception as e:
            st.error(f"Falha no adapter: **{type(e).__name__}** — {e}")
            import traceback
            with st.expander("Ver traceback"):
                st.code(traceback.format_exc())


# ============================================================================
# API publica
# ============================================================================

def render_questionario_base_tab(aluno_id: str) -> None:
    """Render da tab 'Questionario Base' do prontuario do aluno.

    Possui um TOGGLE no topo entre:
        - Molde Antigo (NEEI v2.0 + LLM completo via profile_builder.py)
        - Molde Novo  (NEEI v3.0 + 3 motores via agente1/router.py)
    """
    st.subheader("Questionario Base (Perfil Pedagogico)")
    st.caption(
        "Respostas dos questionarios NEEI preenchidos para este aluno. "
        "O canonical gerado aqui alimenta o Agente 1 que produz o PAI."
    )

    # =====================================================================
    # MOLDE ANTIGO (NEEI v2.0 + LLM completo) APOSENTADO em [REORG] - virou legado.
    # =====================================================================
    # O toggle foi removido; sempre renderiza o Molde Novo. O bloco do Molde
    # Antigo mais abaixo continua ARQUIVADO no codigo, porem inalcancavel
    # (molde == "novo" sempre). Pra reativar: restaure o backup .bak_*.
    molde = "novo"

    # =====================================================================
    # MOLDE NOVO - delega pra modulo separado
    # =====================================================================
    if molde == "novo":
        try:
            from aluno_questionario_base_v3 import render_molde_novo
            render_molde_novo(aluno_id)
        except Exception as e:
            st.error(
                f"Modulo aluno_questionario_base_v3.py nao carregou: "
                f"{type(e).__name__}: {e}"
            )
            import traceback as _tb
            with st.expander("Ver traceback"):
                st.code(_tb.format_exc())
        return

    # =====================================================================
    # MOLDE ANTIGO - codigo original (intacto)
    # =====================================================================

    # 0. Seletor de modelo do Agente 1
    if _AGENTE1_OK:
        with st.container(border=True):
            st.markdown(
                "<div style='font-size:0.78em; color:#666; text-transform:uppercase; "
                "letter-spacing:0.5px; font-weight:700; margin-bottom:8px;'>"
                "Configuracao do Agente 1 (Profile Builder)"
                "</div>",
                unsafe_allow_html=True,
            )
            _render_seletor_modelo_agente1(aluno_id)

    st.divider()

    # 1. Lista questionarios ja importados
    _render_lista_canonicals(aluno_id)

    st.divider()

    # 2. Importer inline embaixo
    _render_importer_inline(aluno_id)
