"""
aluno_questionario_base_v3.py - UI do MOLDE NOVO (Agente 1 - native/hybrid).

Renderiza dentro da tab Questionario Base do prontuario do aluno
quando o toggle "Molde" estiver em "Novo (NEEI v3.0)".

Funcionalidades:
  1. Seletor de engine (native default - protecao de custo)
  2. Dropdown de fixture pra teste rapido (3 fixtures pre-cadastrados)
  3. Botao "Gerar PAI" disparando router.gerar_pai()
  4. Telemetria do resultado (custo, tempo, status, fallback)
  5. Lista de responses_v3/ ja processadas
  6. Lista de pais_gerados/ ja salvos
"""
from __future__ import annotations

from typing import Optional

import streamlit as st


# ============================================================================
# Imports tolerantes
# ============================================================================

try:
    from innova_bridge.formularios.adapters.from_neei_v3_0 import (
        carregar_fixture,
        listar_fixtures_disponiveis,
        salvar_response_v3,
        listar_responses_v3_do_aluno,
        csv_to_questionnaire_response,
        listar_respostas_csv,
    )
    _ADAPTER_OK = True
    _ADAPTER_ERR: Optional[str] = None
except Exception as _e:
    _ADAPTER_OK = False
    _ADAPTER_ERR = str(_e)
    carregar_fixture = None
    listar_fixtures_disponiveis = None
    salvar_response_v3 = None
    listar_responses_v3_do_aluno = None
    csv_to_questionnaire_response = None
    listar_respostas_csv = None

try:
    from innova_bridge.agents.agente1.router import gerar_pai
    _ROUTER_OK = True
    _ROUTER_ERR: Optional[str] = None
except Exception as _e:
    _ROUTER_OK = False
    _ROUTER_ERR = str(_e)
    gerar_pai = None

try:
    from innova_bridge.agents.agente1.persistence import (
        listar_pais_do_aluno,
        listar_pais_vigentes,
        carregar_pai_mais_recente,
    )
    _PERSIST_OK = True
except Exception:
    _PERSIST_OK = False
    listar_pais_do_aluno = None
    listar_pais_vigentes = None
    carregar_pai_mais_recente = None

# Modelos LLM (reusa o helper que ja existe)
try:
    from innova_bridge.agents.profile_builder import listar_modelos_disponiveis
    _MODELS_OK = True
except Exception:
    _MODELS_OK = False
    listar_modelos_disponiveis = None


# ============================================================================
# Helpers de estado
# ============================================================================

def _state_key(aluno_id: str, suffix: str) -> str:
    return f"v3::{aluno_id}::{suffix}"


def _resolver_fixture_id_curto(aluno_id: str) -> Optional[str]:
    """Resolve o ID curto do fixture (ex: 'INTENSO', 'U2') a partir da label
    completa que ficou no session_state. Retorna None se nao conseguir.
    """
    if not _ADAPTER_OK or listar_fixtures_disponiveis is None:
        return None
    label_selecionada = st.session_state.get(_state_key(aluno_id, "fixture_id"))
    if not label_selecionada:
        return None
    try:
        for f in listar_fixtures_disponiveis():
            if f.get("label") == label_selecionada:
                return f.get("id")
    except Exception:
        return None
    return None


# ============================================================================
# Renderers
# ============================================================================

def _render_status_modulos() -> bool:
    """Verifica se os 3 modulos do agente1 carregaram. Retorna False se algum faltar."""
    problemas = []
    if not _ADAPTER_OK:
        problemas.append(f"adapter: {_ADAPTER_ERR}")
    if not _ROUTER_OK:
        problemas.append(f"router: {_ROUTER_ERR}")
    if not _PERSIST_OK:
        problemas.append("persistence module")

    if problemas:
        st.error(
            "⚠️ **Molde Novo nao pode rodar - modulos faltando:**\n\n"
            + "\n".join(f"- {p}" for p in problemas)
        )
        st.caption(
            "Verifique que `innova_bridge/agents/agente1/` esta completo e "
            "que `pydantic` esta instalado."
        )
        return False
    return True


def _render_seletor_engine(aluno_id: str) -> dict:
    """Selectbox de engine + (se hybrid) selector de modelo LLM.

    Retorna dict {engine, modelo_label, modelo_dict} ja com defaults.
    """
    key_eng = _state_key(aluno_id, "engine")
    key_modelo = _state_key(aluno_id, "modelo_label")

    col1, col2 = st.columns([1, 2])
    with col1:
        engine = st.radio(
            "Motor",
            options=["native", "hybrid"],  # [REORG] "llm" (LLM completo) APOSENTADO - anti-padrao
            index=1,  # default = Híbrido (config testada e aprovada)
            format_func=lambda x: {
                "native": "Nativo (R$ 0)",
                "hybrid": "Híbrido (~R$ 0.002)",
            }[x],
            key=key_eng,
            horizontal=False,
            help="Nativo: Python puro determinístico, R$ 0, offline (fallback grátis). "
                 "Híbrido: nativo decide + LLM fina poli a prosa (recomendado).",
        )

    modelo_dict = {}
    modelo_label = ""

    with col2:
        if engine == "hybrid":
            if not _MODELS_OK or listar_modelos_disponiveis is None:
                st.warning("Lista de modelos LLM nao disponivel.")
            else:
                modelos = listar_modelos_disponiveis()
                # Filtro = is_executable: cloud com api_key OU local com base_url.
                # Bate exatamente com o pool exibido em "Provedores Configurados".
                # Locais (Ollama/vLLM/LM Studio) entram porque hybrid.py linhas
                # 140-147 toleram api_key vazia pra eles - e zeram o custo da
                # camada fina (caso de uso ideal pro Hybrid em escala).
                executaveis = [m for m in modelos if m.get("is_executable")]
                if not executaveis:
                    st.warning(
                        "Nenhum provedor executável no pool. "
                        "Cadastre uma chave (cloud) ou base URL (local Ollama/vLLM) "
                        "em Configuracoes → LiteLLM."
                    )
                else:
                    # Default = ativo, senao primeiro cloud, senao primeiro qualquer
                    idx_default = 0
                    for i, m in enumerate(executaveis):
                        if m.get("is_active"):
                            idx_default = i
                            break
                    else:
                        # nenhum ativo -> prefere cloud (geralmente mais confiavel pra prosa)
                        for i, m in enumerate(executaveis):
                            if not m.get("is_local"):
                                idx_default = i
                                break

                    n_cloud = sum(1 for m in executaveis if not m.get("is_local"))
                    n_local = len(executaveis) - n_cloud
                    st.caption(
                        f"📋 {len(executaveis)} provedor(es) disponíveis no pool "
                        f"({n_cloud} cloud · {n_local} local). "
                        f"Locais (Ollama/vLLM) custam R$ 0 — ideais pra Hybrid em volume."
                    )
                    modelo_label = st.selectbox(
                        "Modelo da LLM fina",
                        options=[m["label"] for m in executaveis],
                        index=idx_default,
                        key=key_modelo,
                        help="So afeta o hybrid - native nao usa LLM. "
                             "Todos os provedores executáveis do pool aparecem aqui.",
                    )
                    modelo_dict = next(m for m in executaveis if m["label"] == modelo_label)

        elif engine == "native":
            st.caption(
                "✅ **Motor nativo selecionado.** Custo R$ 0, latência ~1ms, "
                "100% das decisões estruturais idênticas ao golden Anthropic."
            )
        else:  # llm
            st.caption(
                "⚠️ Motor LLM completo é evitado pela ESPEC (caro + risco de alucinar restrições). "
                "Use Molde Antigo se quiser engine LLM full."
            )

    # Modo estrito: so faz sentido pro hybrid - native ja eh deterministico
    strict_no_fallback = False
    if engine == "hybrid":
        strict_no_fallback = st.checkbox(
            "🔒 Modo estrito — NÃO substituir por Native se a LLM falhar",
            value=True,
            key=_state_key(aluno_id, "strict"),
            help="Quando ligado, se a LLM escolhida falhar, o resultado vem VAZIO "
                 "com o erro real (em vez de gerar um Native disfarçado de Hybrid). "
                 "Recomendado pra testes: você sabe exatamente qual modelo rodou.",
        )

    return {
        "engine": engine,
        "modelo_label": modelo_label,
        "modelo_dict": modelo_dict,
        "strict_no_fallback": strict_no_fallback,
    }


def _render_origem_resposta(aluno_id: str) -> Optional[dict]:
    """Origem da resposta: fixture demo OU upload de CSV do Google Forms.

    Blindagem: o caminho de fixtures continua igual; o CSV real é ADITIVO.
    Retorna o payload canonico {questionnaire_response, ...} ou None.
    """
    if not _ADAPTER_OK or listar_fixtures_disponiveis is None:
        return None

    st.markdown("##### Origem da resposta")
    fonte = st.radio(
        "Fonte",
        ["📋 Fixture pré-cadastrado (demo)", "📤 Subir CSV do Google Forms (real)"],
        index=1,  # [REORG] default = CSV real (fixtures viram só demo)
        key=_state_key(aluno_id, "fonte_resposta"),
        horizontal=True,
        label_visibility="collapsed",
    )

    payload: Optional[dict] = None

    # ---------- Caminho A: fixtures demo (inalterado) ----------
    if fonte.startswith("📋"):
        fixtures = listar_fixtures_disponiveis()
        disponiveis = [f for f in fixtures if f["available"]]
        if not disponiveis:
            st.error(
                "Nenhum fixture disponível em `tests/fixtures/`. "
                "Espera-se INPUT_INTENSO_formulario.json, INPUT_U2_formulario.json, "
                "INPUT_U1_reconstruido.json."
            )
            return None
        st.caption("Perfis demo pra testar o pipeline end-to-end.")
        opcoes_label = {f["label"]: f["id"] for f in disponiveis}
        label_escolhido = st.selectbox(
            "Fixture pré-cadastrado",
            list(opcoes_label.keys()),
            key=_state_key(aluno_id, "fixture_id"),
            help="U1_intenso e U1_reconstruido têm laudo (TEA s2). "
                 "U2 é neurotípico (sem laudo).",
        )
        try:
            payload = carregar_fixture(opcoes_label[label_escolhido])
        except Exception as e:
            st.error(f"Falha carregando fixture: {e}")
            return None

    # ---------- Caminho B: CSV real do Google Forms ----------
    else:
        if csv_to_questionnaire_response is None or listar_respostas_csv is None:
            st.error("Adapter de CSV indisponível neste ambiente.")
            return None
        st.caption(
            "Suba o CSV exportado do Google Forms (Questionário Integrado de Perfil "
            "Pedagógico). A estrutura vira canônica; a prosa é a palavra real da professora."
        )
        arquivo = st.file_uploader(
            "CSV do Google Forms",
            type=["csv"],
            key=_state_key(aluno_id, "csv_upload"),
            label_visibility="collapsed",
        )
        if arquivo is None:
            st.info("Aguardando o CSV do formulário preenchido…")
            return None
        try:
            conteudo = arquivo.getvalue()  # bytes - seguro pra ler 2x
            respostas = listar_respostas_csv(conteudo)
        except Exception as e:
            st.error(f"Falha lendo o CSV: {e}")
            return None
        if not respostas:
            st.error("Nenhuma resposta encontrada no CSV.")
            return None

        if len(respostas) == 1:
            linha_sel = 0
            st.caption(f"1 resposta no arquivo: **{respostas[0]['student_id']}**.")
        else:
            rotulo = {
                f"linha {r['linha']} — {r['student_id']} ({r['age']} anos, {r['grade_level']})": r["linha"]
                for r in respostas
            }
            escolha = st.selectbox(
                "Qual resposta usar?",
                list(rotulo.keys()),
                key=_state_key(aluno_id, "csv_linha"),
            )
            linha_sel = rotulo[escolha]

        try:
            payload = csv_to_questionnaire_response(conteudo, linha_sel)
        except Exception as e:
            st.error(f"Falha convertendo a resposta {linha_sel}: {e}")
            return None

    if payload is None:
        return None

    # ---------- Resumo do payload (igual pros dois caminhos) ----------
    qr = payload.get("questionnaire_response", {})
    ident = qr.get("identification", {})
    char = qr.get("characterization", {})
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("student_id", ident.get("student_id", "?"))
        c2.metric("idade", ident.get("age", "?"))
        c3.metric("ano/série", str(ident.get("grade_level", "?"))[:12])
        c4.metric("laudo", "Sim" if char.get("has_clinical_report") else "Não")

    return payload


def _render_botao_gerar_e_resultado(
    aluno_id: str,
    payload: dict,
    config_engine: dict,
) -> None:
    """Botao Gerar PAI + render do resultado."""
    if not _ROUTER_OK or gerar_pai is None:
        st.error(f"Router nao disponivel: {_ROUTER_ERR}")
        return

    engine = config_engine["engine"]
    modelo_dict = config_engine["modelo_dict"]

    # Desabilita hybrid se nao tem modelo escolhido
    disabled = False
    motivo_disabled = ""
    if engine == "hybrid" and not modelo_dict:
        disabled = True
        motivo_disabled = "Hybrid exige modelo selecionado"
    elif engine == "llm":
        disabled = True
        motivo_disabled = "Use o Molde Antigo para engine=llm"

    col_btn, col_msg = st.columns([1, 3])
    with col_btn:
        clicked = st.button(
            "🤖 Gerar PAI",
            key=_state_key(aluno_id, "btn_gerar"),
            type="primary",
            disabled=disabled,
            use_container_width=True,
            help=motivo_disabled or f"Roda engine={engine}",
        )
    with col_msg:
        if engine == "native":
            st.caption("Custo estimado: **R$ 0,00**, tempo ~1ms")
        elif engine == "hybrid" and modelo_dict:
            # Estimativa dinâmica baseada na realidade do modelo escolhido.
            # is_local agora reflete localhost real (após o fix do _formatar_label).
            is_local_real = bool(modelo_dict.get("is_local", False))
            in_usd_1M = float(modelo_dict.get("in_usd_1M", 0.0) or 0.0)
            out_usd_1M = float(modelo_dict.get("out_usd_1M", 0.0) or 0.0)

            if is_local_real or (in_usd_1M == 0 and out_usd_1M == 0):
                # Local de verdade OU cloud cadastrado com preços zerados
                tag = "🖥️ LOCAL" if is_local_real else "💰 grátis"
                st.caption(
                    f"Modelo: `{modelo_dict.get('model', '?')}` · "
                    f"**{tag}** · custo: **R$ 0,00**"
                )
            else:
                # Cloud pago - estima range pro hybrid típico
                # (~1700-3000 tokens in, ~400-700 tokens out)
                try:
                    from funcoes_fla import obter_dolar_persistido
                    dolar = obter_dolar_persistido() or 5.25
                except Exception:
                    dolar = 5.25
                min_cost = (1700 * in_usd_1M + 400 * out_usd_1M) / 1_000_000 * dolar
                max_cost = (3000 * in_usd_1M + 700 * out_usd_1M) / 1_000_000 * dolar
                st.caption(
                    f"Modelo: `{modelo_dict.get('model', '?')}` · "
                    f"🌐 CLOUD · custo estimado: **R$ {min_cost:.4f} – {max_cost:.4f}** "
                    f"(camada fina)"
                )

    key_resultado = _state_key(aluno_id, "resultado")

    if clicked:
        # Persiste o payload v3 antes de chamar o agente.
        # IMPORTANTE: source_label deve ser o ID curto do fixture (ex: "INTENSO",
        # "U2"), NAO a label cheia de "/", "\", parens. O selectbox guarda a
        # label, entao puxamos o id curto via _resolver_fixture_id_curto.
        if _ADAPTER_OK and salvar_response_v3 is not None:
            try:
                # [REORG] Rotula a origem REAL: CSV do Forms vs fixture demo.
                # CSV -> "csv_forms_<student_id>" (ex.: csv_forms_U1); fixture -> id curto.
                _fonte_val = st.session_state.get(_state_key(aluno_id, "fonte_resposta"), "")
                if ("CSV" in _fonte_val) or ("Forms" in _fonte_val):
                    _sid = ((payload.get("questionnaire_response") or {}).get("identification") or {}).get("student_id") or "?"
                    source = f"csv_forms_{_sid}"
                else:
                    source = _resolver_fixture_id_curto(aluno_id) or "fixture"
                salvar_response_v3(aluno_id, payload, source_label=source)
            except Exception as e:
                st.warning(f"Response v3 nao foi persistido: {e}")

        with st.spinner(f"Rodando Agente 1 (engine={engine})..."):
            try:
                kwargs = {
                    "engine": engine,
                    "salvar": True,
                    "validar": True,
                }
                if engine == "hybrid" and modelo_dict:
                    # IMPORTANTE: passamos provider_key_id (= o nome do modelo).
                    # O run_hybrid resolve provider+api_key+base_url via
                    # get_provider_credentials(modelo). Se tentarmos só
                    # provider_override+model_override SEM api_key_override,
                    # o hybrid cai no fallback nativo (regra do else final).
                    kwargs["provider_key_id"] = modelo_dict.get("model")
                    kwargs["strict_no_fallback"] = bool(config_engine.get("strict_no_fallback"))
                # Substitui aluno_id no payload pra coerencia
                payload_local = dict(payload)
                qr = dict(payload_local.get("questionnaire_response") or {})
                ident = dict(qr.get("identification") or {})
                ident["student_id"] = aluno_id
                qr["identification"] = ident
                payload_local["questionnaire_response"] = qr

                resultado = gerar_pai(payload_local, **kwargs)
                st.session_state[key_resultado] = resultado
            except Exception as e:
                import traceback as _tb
                st.error(f"Erro inesperado: {type(e).__name__}: {e}")
                with st.expander("Ver traceback"):
                    st.code(_tb.format_exc())
                return

    # Renderiza o resultado se ja existe (persiste entre reruns)
    resultado = st.session_state.get(key_resultado)
    if resultado:
        _render_resultado(resultado)

        col_a, col_b = st.columns([1, 4])
        with col_a:
            if st.button("Limpar resultado", key=_state_key(aluno_id, "btn_clear")):
                st.session_state.pop(key_resultado, None)
                st.rerun()


def _render_resultado(resultado: dict) -> None:
    """Renderiza o dict de retorno do router.gerar_pai()."""
    with st.container(border=True):
        tele = resultado.get("telemetria_engine") or {}
        meta_pers = resultado.get("metadata_persistencia") or {}
        log = resultado.get("log_custo") or {}
        fallback = bool(tele.get("fallback_used"))
        ok = bool(resultado.get("ok"))
        engine = resultado.get("engine", "?")
        modelo_alvo = tele.get("modelo") or "—"

        # Status visual EXPLICITO - prioridade sobre o ok flag interno.
        # Regra: se Hybrid acabou rodando Native (fallback), mostra VERMELHO -
        # porque o usuario escolheu uma LLM e nao queria substituicao silenciosa.
        if not ok:
            st.error(
                f"❌ **{modelo_alvo} NAO rodou.** PAI nao foi gerado. "
                f"Causa: {resultado.get('mensagem', '?')}"
            )
        elif fallback and engine == "hybrid":
            st.error(
                f"⚠️ **{modelo_alvo} FALHOU — PAI veio do fallback Native, "
                f"NAO da LLM escolhida.** Nao contabilize como teste do Hybrid."
            )
        else:
            st.success(resultado.get("mensagem", "PAI gerado"))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Engine", engine)
        c2.metric("Versão", meta_pers.get("versao", "—"))
        c3.metric("Status", meta_pers.get("status", "—"))
        c4.metric("Tempo (s)", resultado.get("tempo_total_s", 0.0))

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Tokens in",  tele.get("tokens_in", 0))
        c6.metric("Tokens out", tele.get("tokens_out", 0))
        c7.metric("Custo BRL",  f"R$ {log.get('custo_brl', 0.0):.4f}")
        c8.metric("Fallback",   "Sim" if fallback else "Não")

        if fallback:
            st.error(
                f"🚨 **Modelo alvo:** `{tele.get('modelo','—') or '—'}` · "
                f"**Erro real:** {tele.get('fallback_reason', '?')[:300]}"
            )

        st.caption(
            f"Modelo: `{tele.get('modelo','—') or '—'}` · "
            f"Provedor: `{tele.get('provedor','—') or '—'}` · "
            f"Processo no log: `{log.get('processo','?')}`"
        )

        if resultado.get("path_salvo"):
            from pathlib import Path as _P
            st.caption(f"📁 Salvo em: `pais_gerados/{_P(resultado['path_salvo']).name}`")

        with st.expander("Ver PAI gerado (JSON cru)", expanded=False):
            st.json(resultado.get("pai") or {}, expanded=False)


def _render_historico(aluno_id: str) -> None:
    """Lista responses_v3 e pais_gerados deste aluno."""
    if not _ADAPTER_OK or not _PERSIST_OK:
        return

    col_r, col_p = st.columns(2)

    with col_r:
        st.markdown("##### Responses V3 (input do Agente 1)")
        try:
            responses = listar_responses_v3_do_aluno(aluno_id)
        except Exception as e:
            st.warning(f"Falha listando responses: {e}")
            responses = []
        if not responses:
            st.caption("Nenhum response v3 gravado para este aluno.")
        else:
            for r in responses[:5]:
                st.markdown(
                    f"- `{r['source']}` · {r['saved_at'][:19]} · "
                    f"{r['size_kb']} KB"
                )

    with col_p:
        st.markdown("##### PAIs Gerados (Molde Novo)")
        try:
            pais = listar_pais_do_aluno(aluno_id)
        except Exception as e:
            st.warning(f"Falha listando PAIs: {e}")
            pais = []
        if not pais:
            st.caption("Nenhum PAI gerado para este aluno ainda.")
        else:
            for p in pais[:5]:
                emoji = {
                    "active": "🟢",
                    "needs_review": "🟡",
                    "superseded": "⚪",
                }.get(p.get("status", "?"), "❔")
                st.markdown(
                    f"- {emoji} v{p['versao']} · {p['status']} · "
                    f"`{p['created_by'].replace('ProfileBuilder','PB')}` · "
                    f"{p['timestamp'][:8]}"
                )


# ============================================================================
# API publica
# ============================================================================

def render_molde_novo(aluno_id: str) -> None:
    """Renderer principal do Molde Novo - chamado pelo toggle em
    aluno_questionario_base.py.
    """
    st.markdown("#### 🆕 Molde Novo (NEEI v3.0 + 3 motores)")
    st.caption(
        "Pipeline conforme `ESPEC_COMPLETA_Agente1_Python.md` do sócio. "
        "Native (R$ 0) é o motor recomendado. Hybrid adiciona prosa polida "
        "via LLM fina (~R$ 0.002). LLM full delegado ao Molde Antigo."
    )

    if not _render_status_modulos():
        return

    st.divider()

    # 1) Engine
    with st.container(border=True):
        st.markdown(
            "<div style='font-size:0.78em; color:#666; text-transform:uppercase; "
            "letter-spacing:0.5px; font-weight:700; margin-bottom:8px;'>"
            "Configuração do Agente 1"
            "</div>",
            unsafe_allow_html=True,
        )
        config = _render_seletor_engine(aluno_id)

    st.divider()

    # 2) Origem da resposta
    payload = _render_origem_resposta(aluno_id)
    if payload is None:
        return

    st.divider()

    # 3) Botão Gerar + resultado
    _render_botao_gerar_e_resultado(aluno_id, payload, config)

    st.divider()

    # 4) Histórico (responses_v3 + pais_gerados)
    _render_historico(aluno_id)
