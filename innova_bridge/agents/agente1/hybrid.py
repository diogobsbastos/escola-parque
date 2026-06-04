"""
innova_bridge/agents/agente1/hybrid.py

Motor Hibrido 2.0 - secao 5.3 da ESPEC_COMPLETA.

Combina:
  1. build_pai_native(payload) -> PAI base 100% deterministico
  2. call_thin_llm(THIN_SYSTEM, build_thin_user_payload(payload, base))
     -> {summary_for_teacher_ptbr, low_confidence_areas, missing_evidence}
  3. MERGE: substitui esses 3 campos do rationale com a versao da LLM fina
  4. Atualiza meta.created_by = "ProfileBuilderHibrido_v2.0"

Fallback gracioso (regra 6 da secao 12):
  Se a LLM fina falhar (timeout, JSON invalido, HTTP error), o resumo nativo
  EH USADO em vez de quebrar a geracao. Telemetria registra `fallback_used`.

Custo-alvo: ~R$ 0.002 por execucao com Gemini 2.5 Flash (320-430x mais barato
que o LLM completo). 100% das decisoes estruturais identicas ao golden.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .native import build_pai_native
from .thin_prompt import THIN_SYSTEM, build_thin_user_payload
from .providers import call_thin_llm, get_provider_credentials, try_extract_json
from .schemas import PaiV1


# ============================================================================
# API publica
# ============================================================================

def run_hybrid(
    payload: dict | Any,
    provider_key_id: Optional[str] = None,
    *,
    # Overrides diretos (uteis pros testes e quando o caller ja resolveu creds)
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
    api_key_override: Optional[str] = None,
    base_url_override: Optional[str] = None,
    max_tokens: int = 4096,
    timeout: int = 300,
    validate: bool = True,
    strict_no_fallback: bool = False,
) -> tuple[dict, dict]:
    """Motor Hibrido 2.0: NEEIInput -> PAI v1.0 com prosa polida por LLM fina.

    Args:
        payload: dict cru OU NEEIInput (convertido via model_dump).
        provider_key_id: chave do provider no pool LiteLLM (ex: "gemini/gemini-2.5-flash").
                          Se None, exige overrides diretos abaixo.
        provider_override: forca um provider especifico (bypass get_provider_credentials).
        model_override: forca um modelo especifico.
        api_key_override: forca uma API key (ja decriptada).
        base_url_override: forca uma base URL.
        max_tokens: ceiling do output da LLM fina (default 4096, suficiente pro JSON).
        timeout: segundos por tentativa HTTP.
        validate: se True, valida o PAI final contra PaiV1 Pydantic.

    Returns:
        (pai_dict, telemetria) onde:

        pai_dict tem `meta.created_by = "ProfileBuilderHibrido_v2.0"` e
        `rationale.summary_for_teacher_ptbr / low_confidence_areas /
        missing_evidence` vindos da LLM fina (ou do native se fallback).

        telemetria = {
            "ok": bool,
            "engine": "hybrid",
            "modelo": str,
            "provedor": str,
            "tokens_in": int,
            "tokens_out": int,
            "tokens_cache": int,
            "tempo_s": float,
            "fallback_used": bool,
            "fallback_reason": str | None,
            "mensagem": str,
        }

    Nunca levanta excecao - encapsula tudo via fallback gracioso.
    """
    t0 = time.time()
    telemetria: dict[str, Any] = {
        "ok": False,
        "engine": "hybrid",
        "modelo": "?",
        "provedor": "?",
        "tokens_in": 0,
        "tokens_out": 0,
        "tokens_cache": 0,
        "tempo_s": 0.0,
        "fallback_used": False,
        "fallback_reason": None,
        "mensagem": "",
        # Campos de REPRODUCIBILIDADE (Etapa 1):
        "seed_used": None,
        "temperature_used": None,
        "force_json_used": None,
        "model_digest": "",
        "model_quantization": "",
        "model_family": "",
        "model_param_size": "",
        "ollama_version": "",
        "system_fingerprint": "",
    }

    # --- 1) Base PAI deterministica (a peca-chave: zera o risco do LLM alucinar decisao) ---
    try:
        base = build_pai_native(payload)
    except Exception as e:
        telemetria["mensagem"] = f"build_pai_native falhou: {type(e).__name__}: {e}"
        telemetria["tempo_s"] = round(time.time() - t0, 3)
        return {}, telemetria

    # --- 2) Resolver credenciais ---
    if provider_override and model_override and (api_key_override is not None):
        # Modo direto
        provedor = provider_override
        modelo = model_override
        api_key = api_key_override
        base_url = base_url_override
    elif provider_key_id:
        creds = get_provider_credentials(provider_key_id)
        if creds is None:
            return _falhar_ou_fallback(
                base=base, telemetria=telemetria, t0=t0,
                model_label="(sem credenciais)",
                reason=f"get_provider_credentials({provider_key_id!r}) retornou None",
                strict=strict_no_fallback,
            )
        provedor = creds["provider"]
        modelo = creds["model"]
        api_key = creds["api_key"]
        base_url = creds.get("base_url")
    else:
        return _falhar_ou_fallback(
            base=base, telemetria=telemetria, t0=t0,
            model_label="(sem creds)",
            reason="run_hybrid sem provider_key_id e sem overrides diretos",
            strict=strict_no_fallback,
        )

    telemetria["provedor"] = provedor
    telemetria["modelo"] = modelo

    # API key vazia eh tolerada apenas pra providers locais (Ollama)
    is_local = any(tag in (provedor or "").lower()
                   for tag in ("custom", "local", "ollama", "vllm"))
    if not api_key and not is_local:
        return _falhar_ou_fallback(
            base=base, telemetria=telemetria, t0=t0,
            model_label=modelo,
            reason=f"API key vazia pro provedor {provedor!r}",
            strict=strict_no_fallback,
        )

    # --- 3) Chamar LLM fina ---
    try:
        user_payload = build_thin_user_payload(payload, base)
    except Exception as e:
        return _falhar_ou_fallback(
            base=base, telemetria=telemetria, t0=t0,
            model_label=modelo,
            reason=f"build_thin_user_payload falhou: {type(e).__name__}: {e}",
            strict=strict_no_fallback,
        )

    # Resolve config efetiva (prompt + hiperparametros) por (agente, modelo).
    # BLINDAGEM: qualquer erro no storage -> usa defaults intocados.
    system_prompt_efetivo = THIN_SYSTEM
    max_tokens_efetivo = max_tokens
    cfg_overrides = {}  # passado pra call_thin_llm como kwargs opcionais
    try:
        from innova_bridge.agents.prompt_storage import get_agent_config
        cfg = get_agent_config("agente1", modelo)
        # 1) system_prompt
        custom_prompt = cfg.get("system_prompt")
        if isinstance(custom_prompt, str) and custom_prompt.strip():
            system_prompt_efetivo = custom_prompt
        # 2) max_tokens
        custom_max = cfg.get("max_tokens")
        if isinstance(custom_max, int) and 256 <= custom_max <= 32768:
            max_tokens_efetivo = custom_max
        # 3) temperature (passado via kwarg opcional)
        custom_temp = cfg.get("temperature")
        if isinstance(custom_temp, (int, float)) and 0.0 <= custom_temp <= 2.0:
            cfg_overrides["temperature_override"] = float(custom_temp)
        # 4) force_json (passado via kwarg opcional)
        custom_fj = cfg.get("force_json")
        if isinstance(custom_fj, bool):
            cfg_overrides["force_json_override"] = custom_fj
        # 5) seed (passado via kwarg opcional) - reproducibilidade total
        #    quando definido. Range OpenAI/Ollama: 0 a 2^32-1.
        custom_seed = cfg.get("seed")
        if isinstance(custom_seed, int) and 0 <= custom_seed <= 4_294_967_295:
            cfg_overrides["seed_override"] = int(custom_seed)
        # 6) num_ctx (Ollama local) - janela de contexto, passado via kwarg.
        #    Cloud ignora (no-op). Resolve o 500 do Ollama com prompt grande.
        custom_ctx = cfg.get("num_ctx")
        if isinstance(custom_ctx, int) and 256 <= custom_ctx <= 131072:
            cfg_overrides["num_ctx_override"] = int(custom_ctx)
    except Exception:
        # Storage eh OPT-IN - falha silenciosa mantém defaults
        pass

    # Telemetria de auditoria do PROMPT efetivo (resolve "qual versao rodou?"):
    #   - system_prompt_chars: tamanho exato do prompt enviado a LLM
    #   - prompt_source: "custom" (veio do agent_prompts.json) | "default" (THIN_SYSTEM)
    # Permite testes A/B verificaveis - se voce mudar o prompt de 7800 pra 13000
    # chars e nao ver isso refletido no badge do PAI, sabe que algo errou no caminho.
    telemetria["system_prompt_chars"] = len(system_prompt_efetivo or "")
    telemetria["prompt_source"] = (
        "custom" if system_prompt_efetivo != THIN_SYSTEM else "default"
    )

    try:
        text, usage = call_thin_llm(
            provider=provedor,
            model=modelo,
            api_key=api_key,
            base_url=base_url,
            system=system_prompt_efetivo,
            user=user_payload,
            max_tokens=max_tokens_efetivo,
            timeout=timeout,
            **cfg_overrides,
        )
        telemetria["tokens_in"] = int(usage.get("input_tokens", 0))
        telemetria["tokens_out"] = int(usage.get("output_tokens", 0))
        telemetria["tokens_cache"] = int(usage.get("cache_read_input_tokens", 0))
        # Campos de REPRODUCIBILIDADE (Etapa 1) - copia do usage enriquecido
        telemetria["seed_used"] = usage.get("seed_used")
        telemetria["temperature_used"] = usage.get("temperature_used")
        telemetria["force_json_used"] = usage.get("force_json_used")
        telemetria["num_ctx_used"] = usage.get("num_ctx_used")
        telemetria["model_digest"] = str(usage.get("model_digest", "") or "")
        telemetria["model_quantization"] = str(
            usage.get("model_quantization", "") or ""
        )
        telemetria["model_family"] = str(usage.get("model_family", "") or "")
        telemetria["model_param_size"] = str(usage.get("model_param_size", "") or "")
        telemetria["ollama_version"] = str(usage.get("ollama_version", "") or "")
        telemetria["system_fingerprint"] = str(
            usage.get("system_fingerprint", "") or ""
        )
    except Exception as e:
        return _falhar_ou_fallback(
            base=base, telemetria=telemetria, t0=t0,
            model_label=modelo,
            reason=f"call_thin_llm falhou: {type(e).__name__}: {str(e)[:200]}",
            strict=strict_no_fallback,
        )

    # --- 4) Parsear JSON da LLM fina ---
    parsed = try_extract_json(text)
    if parsed is None or not isinstance(parsed, dict):
        return _falhar_ou_fallback(
            base=base, telemetria=telemetria, t0=t0,
            model_label=modelo,
            reason=f"LLM fina nao retornou JSON valido (text={text[:120]!r})",
            strict=strict_no_fallback,
        )

    # --- 5) Merge: substitui apenas summary + low_confidence + missing_evidence
    #            + personality_notes_ptbr (estendido com orientacao acionavel) ---
    summary = parsed.get("summary_for_teacher_ptbr") \
              or base["rationale"]["summary_for_teacher_ptbr"]
    low = [s for s in (parsed.get("low_confidence_areas") or []) if isinstance(s, str)]
    missing = [s for s in (parsed.get("missing_evidence") or []) if isinstance(s, str)]

    # --- 5a) missing_evidence DETERMINISTICO (Hybrid 2.0: native possui o fato binario) ---
    # Os itens historico / AEE-Parte7 / Parte 1.5 sao fatos derivados direto dos flags do
    # payload. O LLM nao decide mais esses: o native os INJETA a partir dos flags (presentes
    # quando devem, ausentes quando nao se aplicam). Isso corrige os DOIS lados do erro que
    # so o LLM cometia: o item FALSO (ex.: 14B afirmando "Parte 1.5 em branco" com a 1.5
    # preenchida) E a OMISSAO (ex.: 14B esquecer o historico). O LLM segue dono dos itens de
    # JULGAMENTO (calibracao, laudo sem doc, AEE parcial...). Para quem ja acertava (Gemini),
    # o resultado e equivalente. Tambem limpa a LCA de itens que pertencem a missing_evidence.
    import unicodedata

    def _norm(s: str) -> str:
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()

    _p = payload.model_dump() if hasattr(payload, "model_dump") else payload
    _qr = (_p.get("questionnaire_response") or {}) if isinstance(_p, dict) else {}
    _char = _qr.get("characterization") or {}
    _ident = _qr.get("identification") or {}
    _hist_present = bool(_p.get("historical_data")) if isinstance(_p, dict) else False
    _has_aee = bool(_ident.get("aee_professional_name"))
    _wdnw_present = bool(_char.get("what_did_not_work"))

    # Itens deterministicos que o NATIVE possui (texto canonico unico, igual ao few-shot).
    _det_missing: list[str] = []
    if not _hist_present:
        _det_missing.append("Histórico de provas adaptadas ainda indisponível (primeiro PAI do ano).")
    if not _has_aee:
        _det_missing.append("Sem acompanhamento AEE — Parte 7 em branco.")
    if not _wdnw_present:
        _det_missing.append("Parte 1.5 ('o que não funcionou') deixada em branco.")

    def _eh_item_deterministico(s: str) -> bool:
        # Classifica se a string e um dos 3 fatos atados a flag (em qualquer fraseado).
        n = _norm(s)
        if ("historico" in n) and ("indisponivel" in n or "primeiro pai" in n or "primeira execucao" in n):
            return True
        if ("aee" in n or "parte 7" in n) and "branco" in n:
            return True
        if ("1.5" in n) and ("branco" in n or "nao funcionou" in n):
            return True
        return False

    # missing_evidence = deterministicos (native) + itens de JULGAMENTO do LLM, sem duplicar.
    _det_norms = {_norm(d) for d in _det_missing}
    _llm_julgamento = [s for s in missing if not _eh_item_deterministico(s)]
    missing = _det_missing + [s for s in _llm_julgamento if _norm(s) not in _det_norms]

    # LCA: remove qualquer item deterministico (pertence a missing_evidence, nao a baixa-confianca).
    low = [s for s in low if not _eh_item_deterministico(s)]

    # --- 5b) Fecho nativo de LCA vazia (Hybrid 2.0: fato deterministico, fora do LLM) ---
    # Roda DEPOIS do guard: se a filtragem esvaziou a LCA, o fecho dispara aqui.
    # O prompt v6.0 NAO instrui mais a LLM a escrever essa frase; o native a anexa,
    # garantindo presenca byte-estavel. Idempotente: o guard "consistente" evita frase dupla.
    if not low:
        _fecho = ("Evidências cruzadas — capacidades, barreiras, suportes e "
                  "autorizações — consistentes, sem lacunas que comprometam o plano.")
        if "consistente" not in summary[-160:].lower():
            summary = summary.rstrip()
            if summary and summary[-1] not in ".!?":
                summary += "."
            summary = f"{summary} {_fecho}"

    # personality_notes_ptbr: a LLM estende a versao do input com 1 frase
    # de orientacao pedagogica. Se vier vazio/curto, mantem a versao do native
    # (que ja copia o personality_notes original do questionario).
    # IMPORTANTE: na estrutura PaiV1 esse campo vive em `hard_restrictions`
    # (nao em `rationale`) - eh o renderer pagina_pai_renderer.py que le dali.
    pn_llm = parsed.get("personality_notes_ptbr")
    pn_base = (base.get("hard_restrictions") or {}).get("personality_notes_ptbr") or ""
    if isinstance(pn_llm, str) and len(pn_llm.strip()) > len(pn_base.strip()):
        personality = pn_llm.strip()
    else:
        personality = pn_base

    pai = {
        **base,
        "meta": {
            **base["meta"],
            "created_by": "ProfileBuilderHibrido_v2.0",
        },
        "hard_restrictions": {
            **(base.get("hard_restrictions") or {}),
            "personality_notes_ptbr": personality,
        },
        "rationale": {
            **base["rationale"],
            "summary_for_teacher_ptbr": summary,
            "low_confidence_areas": low,
            "missing_evidence": missing,
        },
    }

    # --- 6) Validacao final opcional ---
    if validate:
        try:
            PaiV1.model_validate(pai)
        except Exception as e:
            telemetria["mensagem"] = f"PAI nao validou Pydantic: {type(e).__name__}: {str(e)[:200]}"
            telemetria["tempo_s"] = round(time.time() - t0, 3)
            # Devolve mesmo assim - cabe ao caller decidir
            return pai, telemetria

    telemetria["ok"] = True
    telemetria["tempo_s"] = round(time.time() - t0, 3)
    telemetria["mensagem"] = "PAI hibrido gerado, validado, merged."
    return pai, telemetria


def _falhar_ou_fallback(
    *,
    base: dict,
    telemetria: dict,
    t0: float,
    model_label: str,
    reason: str,
    strict: bool,
) -> tuple[dict, dict]:
    """Switch: modo estrito retorna PAI vazio + telemetria com erro REAL;
    modo gracioso (default) gera PAI Native com aviso de fallback.

    O modo estrito atende o pedido de NUNCA mandar pra outro modelo
    silenciosamente - se a LLM escolhida falha, voce ve o erro real
    em vez de receber um Native disfarcado de hybrid.
    """
    if strict:
        telemetria["ok"] = False
        telemetria["fallback_used"] = False
        telemetria["fallback_reason"] = None
        telemetria["mensagem"] = (
            f"[MODO ESTRITO] {model_label} falhou e fallback Native esta DESLIGADO. "
            f"Causa: {reason}"
        )
        telemetria["tempo_s"] = round(time.time() - t0, 3)
        return {}, telemetria  # PAI vazio sinaliza falha pro router
    return _fallback_pai_e_telemetria(
        base=base, telemetria=telemetria, t0=t0,
        model_label=model_label, reason=reason,
    )


def _fallback_pai_e_telemetria(
    *,
    base: dict,
    telemetria: dict,
    t0: float,
    model_label: str,
    reason: str,
) -> tuple[dict, dict]:
    """Helper: marca fallback no PAI base + atualiza telemetria.

    Quando a LLM fina nao roda (sem creds, falhou, JSON invalido), retornamos
    o native COM:
      - meta.created_by = "ProfileBuilderHibrido_v2.0 (fallback nativo)"
      - rationale.missing_evidence ganha um aviso visivel
      - telemetria.fallback_used = True + razao
    """
    pai = {
        **base,
        "meta": {
            **base["meta"],
            "created_by": "ProfileBuilderHibrido_v2.0 (fallback nativo)",
        },
        "rationale": {
            **base["rationale"],
            "missing_evidence": [
                f"Camada fina ({model_label}) nao retornou JSON valido; "
                f"resumo nativo usado. Causa: {reason[:160]}",
                *base["rationale"]["missing_evidence"],
            ],
        },
    }
    telemetria["fallback_used"] = True
    telemetria["fallback_reason"] = reason
    telemetria["ok"] = True
    telemetria["mensagem"] = f"Fallback: {reason[:120]}"
    telemetria["tempo_s"] = round(time.time() - t0, 3)
    return pai, telemetria


__all__ = ["run_hybrid"]
