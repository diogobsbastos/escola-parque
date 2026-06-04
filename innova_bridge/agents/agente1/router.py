"""
innova_bridge/agents/agente1/router.py

Engine selector + orquestrador do Agente 1 (Molde Novo).

API:
    gerar_pai(payload, engine="native", provider_key_id=None, ...) -> dict

Default engine="native" (proteção de custo - regra 7 da seção 12 da ESPEC:
nunca rodar modelo caro por acidente).

Esta funcao eh O UNICO ponto de entrada que a UI deveria chamar.
Internamente faz:
    1. Dispatch entre native | hybrid | llm
    2. Persistencia (salvar_pai com supersede + status_rule)
    3. Log de custo (registrar_custo_agente1 no historico_consumo.json)
    4. Retorna telemetria completa pra UI mostrar
"""
from __future__ import annotations

import time
from typing import Any, Literal, Optional

from .native import build_pai_native, build_pai_native_validated
from .hybrid import run_hybrid
from .persistence import salvar_pai
from .logging_cost import registrar_custo_agente1


EngineLabel = Literal["native", "hybrid", "llm"]


def gerar_pai(
    payload: dict | Any,
    *,
    engine: EngineLabel = "native",
    provider_key_id: Optional[str] = None,
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
    api_key_override: Optional[str] = None,
    base_url_override: Optional[str] = None,
    salvar: bool = True,
    validar: bool = True,
    strict_no_fallback: bool = False,
) -> dict[str, Any]:
    """Orquestrador unico do Agente 1.

    Args:
        payload: dict NEEI cru OU NEEIInput.
        engine: "native" (default, gratis) | "hybrid" (com LLM fina) | "llm" (delegado ao molde antigo).
        provider_key_id: chave do pool LiteLLM (so hybrid).
        provider_override / model_override / api_key_override / base_url_override:
            overrides diretos pro hybrid (bypass do storage_litellm).
        salvar: se True, persiste em pais_gerados/ via salvar_pai().
        validar: se True, valida o PAI final contra PaiV1 Pydantic.

    Returns:
        {
            "ok": bool,
            "engine": str,
            "pai": dict,
            "telemetria_engine": dict,    # do hybrid ou simulada pro native
            "metadata_persistencia": dict | None,  # {aluno_id, versao, status, ...}
            "log_custo": dict | None,
            "path_salvo": str | None,
            "tempo_total_s": float,
            "mensagem": str,
        }
    """
    t0 = time.time()
    resultado: dict[str, Any] = {
        "ok": False,
        "engine": engine,
        "pai": {},
        "telemetria_engine": {},
        "metadata_persistencia": None,
        "log_custo": None,
        "path_salvo": None,
        "tempo_total_s": 0.0,
        "mensagem": "",
    }

    # ------------------------------------------------------------------
    # 1) Dispatch por engine
    # ------------------------------------------------------------------
    if engine == "native":
        try:
            pai = build_pai_native_validated(payload) if validar else build_pai_native(payload)
            tele = {
                "ok": True,
                "engine": "native",
                "modelo": "",
                "provedor": "",
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_cache": 0,
                "tempo_s": round(time.time() - t0, 3),
                "fallback_used": False,
                "fallback_reason": None,
                "mensagem": "PAI nativo gerado (R$ 0,00).",
            }
        except Exception as e:
            resultado["mensagem"] = f"build_pai_native falhou: {type(e).__name__}: {e}"
            resultado["tempo_total_s"] = round(time.time() - t0, 3)
            return resultado

    elif engine == "hybrid":
        try:
            pai, tele = run_hybrid(
                payload,
                provider_key_id=provider_key_id,
                provider_override=provider_override,
                model_override=model_override,
                api_key_override=api_key_override,
                base_url_override=base_url_override,
                validate=validar,
                strict_no_fallback=strict_no_fallback,
            )
        except Exception as e:
            resultado["mensagem"] = f"run_hybrid lancou: {type(e).__name__}: {e}"
            resultado["tempo_total_s"] = round(time.time() - t0, 3)
            return resultado

        if not pai:
            resultado["telemetria_engine"] = tele
            resultado["mensagem"] = tele.get("mensagem", "hybrid retornou PAI vazio")
            resultado["tempo_total_s"] = round(time.time() - t0, 3)
            return resultado

    elif engine == "llm":
        # Spec marca "evitar". Por enquanto delegamos ao Molde Antigo.
        # A UI pode escolher chamar profile_builder.build_pai() diretamente.
        resultado["mensagem"] = (
            "engine='llm' delegado ao Molde Antigo "
            "(innova_bridge.agents.profile_builder.build_pai). "
            "Use a UI atual ou chame direto."
        )
        resultado["tempo_total_s"] = round(time.time() - t0, 3)
        return resultado

    else:
        resultado["mensagem"] = f"engine desconhecido: {engine!r} (use 'native' | 'hybrid' | 'llm')"
        resultado["tempo_total_s"] = round(time.time() - t0, 3)
        return resultado

    resultado["pai"] = pai
    resultado["telemetria_engine"] = tele

    # ------------------------------------------------------------------
    # 2) Calcular custo e enriquecer pai.meta.llm_meta ANTES de salvar.
    # Assim o PDF/UI mostra qual LLM rodou, se foi local/cloud, e custo BRL.
    # ------------------------------------------------------------------
    try:
        log = registrar_custo_agente1(
            engine=engine,
            modelo=tele.get("modelo", "") or "",
            provedor=tele.get("provedor", "") or "",
            tokens_in=int(tele.get("tokens_in", 0) or 0),
            tokens_out=int(tele.get("tokens_out", 0) or 0),
            tokens_cache=int(tele.get("tokens_cache", 0) or 0),
            tempo_s=float(tele.get("tempo_s", 0.0) or 0.0),
            fallback_used=bool(tele.get("fallback_used", False)),
        )
        resultado["log_custo"] = log
    except Exception as e:
        log = {"erro": str(e), "registrado": False, "custo_brl": 0.0,
               "custo_usd_estimado": 0.0}
        resultado["log_custo"] = log

    # Detecta is_local: consulta base_url do provedor cadastrado.
    # Defensivo - se algo der errado, assume CLOUD (mais conservador).
    is_local = False
    base_url_resolved = ""
    try:
        if engine != "native":
            from .providers import get_provider_credentials
            creds = get_provider_credentials(tele.get("modelo", "") or "")
            if creds:
                base_url_resolved = creds.get("base_url", "") or ""
                bu = base_url_resolved.lower()
                is_local = any(h in bu for h in
                               ("localhost", "127.0.0.1", "0.0.0.0", "::1"))
    except Exception:
        pass

    # Injeta llm_meta em pai.meta (compatibilidade retroativa: campo opcional)
    # system_prompt_chars + prompt_source = auditoria de qual versao do prompt
    # rodou (resolve A/B de prompt sem ambiguidade).
    if engine != "native":
        # AUDIT_SIGNATURE: assinatura unica de reprodutibilidade.
        # PAIs com a mesma signature DEVEM produzir output identico se rodados
        # no mesmo backend (Ollama versao + driver + arquitetura).
        modelo_curto = (tele.get("modelo", "") or "?").split("/")[-1]
        digest = (tele.get("model_digest", "") or "")
        digest_curto = digest[:16] if digest else "no-digest"
        quant = tele.get("model_quantization", "") or "?"
        seed_v = tele.get("seed_used")
        temp_v = tele.get("temperature_used")
        seed_str = f"seed={seed_v}" if seed_v is not None else "seed=auto"
        temp_str = f"t={temp_v}" if temp_v is not None else "t=auto"
        chars_str = f"chars={int(tele.get('system_prompt_chars', 0) or 0)}"
        audit_signature = ":".join([modelo_curto, digest_curto, quant,
                                     seed_str, temp_str, chars_str])

        pai["meta"]["llm_meta"] = {
            "modelo": tele.get("modelo", "") or "",
            "provedor": tele.get("provedor", "") or "",
            "base_url": base_url_resolved,
            "is_local": bool(is_local),
            "custo_brl": float(log.get("custo_brl", 0.0) or 0.0),
            "custo_usd": float(log.get("custo_usd_estimado", 0.0) or 0.0),
            "tokens_in": int(tele.get("tokens_in", 0) or 0),
            "tokens_out": int(tele.get("tokens_out", 0) or 0),
            "tempo_s": float(tele.get("tempo_s", 0.0) or 0.0),
            "fallback_used": bool(tele.get("fallback_used", False)),
            "engine": engine,
            "system_prompt_chars": int(tele.get("system_prompt_chars", 0) or 0),
            "prompt_source": tele.get("prompt_source", "") or "",
            # Etapa 1 - REPRODUCIBILIDADE:
            "seed_used": tele.get("seed_used"),
            "temperature_used": tele.get("temperature_used"),
            "force_json_used": tele.get("force_json_used"),
            "model_digest": digest,
            "model_quantization": quant if quant != "?" else "",
            "model_family": tele.get("model_family", "") or "",
            "model_param_size": tele.get("model_param_size", "") or "",
            "ollama_version": tele.get("ollama_version", "") or "",
            "system_fingerprint": tele.get("system_fingerprint", "") or "",
            "audit_signature": audit_signature,
        }
    else:
        pai["meta"]["llm_meta"] = {
            "modelo": "",
            "provedor": "native-deterministic",
            "is_local": True,
            "custo_brl": 0.0,
            "engine": "native",
            "system_prompt_chars": 0,
            "prompt_source": "native",
            "seed_used": None,
            "temperature_used": None,
            "force_json_used": None,
            "model_digest": "",
            "model_quantization": "",
            "ollama_version": "",
            "system_fingerprint": "",
            "audit_signature": "native-deterministic",
        }

    # ------------------------------------------------------------------
    # 3) Persistencia (supersede + status_rule + versionamento)
    # ------------------------------------------------------------------
    if salvar:
        try:
            path, meta = salvar_pai(pai)
            resultado["path_salvo"] = str(path)
            resultado["metadata_persistencia"] = meta
        except Exception as e:
            resultado["mensagem"] = f"salvar_pai falhou: {type(e).__name__}: {e}"
            resultado["tempo_total_s"] = round(time.time() - t0, 3)
            return resultado

    resultado["ok"] = True
    fallback_tag = " [fallback]" if tele.get("fallback_used") else ""
    resultado["mensagem"] = (
        f"PAI {engine}{fallback_tag} gerado, persistido"
        f"{' e custo logado' if resultado['log_custo'] and resultado['log_custo'].get('registrado') else ''}."
    )
    resultado["tempo_total_s"] = round(time.time() - t0, 3)
    return resultado


__all__ = ["gerar_pai", "EngineLabel"]
