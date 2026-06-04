"""
innova_bridge/agents/agente1/logging_cost.py

Calculo + registro de custo por execucao do Agente 1.

Secao 8 da ESPEC:
    cost_usd = input/1e6 * preco_in + output/1e6 * preco_out
    cost_brl = cost_usd * cotacao_dolar
    Tabela de precos por (provider, model) - lemos via storage_litellm.

Native loga tokens=0 e custo=0 (pra aparecer no dashboard como "executado").

Integracao com o sistema atual:
  - Reaproveita funcoes_fla.registrar_consumo (mesmo log do OCR/Adapter)
  - Reaproveita storage_litellm.get_custos_provedor (tabela de precos viva)
  - Formato do campo `processo`:
        "Agente1_Native ()"
        "Agente1_Hybrid (gemini-2.5-flash)"
        "Agente1_LLM (claude-sonnet-4-6)"
"""
from __future__ import annotations

from typing import Any, Literal

EngineLabel = Literal["native", "hybrid", "llm"]


# ============================================================================
# Imports tolerantes (sem quebrar se modulos externos faltarem no sandbox)
# ============================================================================

try:
    from funcoes_fla import registrar_consumo as _registrar_consumo
    _LOG_OK = True
except Exception:
    _LOG_OK = False

    def _registrar_consumo(processo, modelo, total_tokens, custo_brl,
                            tempo_execucao=0, provedor="", tokens_in=0,
                            tokens_out=0, tokens_cache=0):
        return None

try:
    from funcoes_fla import calcular_custo_brl as _calcular_custo_brl_fla
    _CALC_OK = True
except Exception:
    _CALC_OK = False

    def _calcular_custo_brl_fla(modelo, input_tokens, output_tokens):
        return 0.0

try:
    from funcoes_fla import obter_dolar_persistido as _obter_dolar
except Exception:
    def _obter_dolar():
        return 5.25

try:
    import storage_litellm as _sl
    _SL_OK = True
except Exception:
    _SL_OK = False
    _sl = None  # type: ignore


# ============================================================================
# Mapeamento engine -> display name (resolve LLM != Llm)
# ============================================================================

_ENGINE_LABEL_DISPLAY: dict[str, str] = {
    "native": "Native",
    "hybrid": "Hybrid",
    "llm":    "LLM",
}


# ============================================================================
# Tabela de precos com fallback hardcoded
# ============================================================================

def get_custos_modelo(modelo: str) -> dict[str, float]:
    """Retorna custos {in_usd_1M, out_usd_1M, cache_usd_1M} do modelo."""
    # 1) Pool LiteLLM
    if _SL_OK and _sl is not None:
        try:
            c = _sl.get_custos_provedor(modelo) or {}
            if c and (c.get("in_usd_1M") or c.get("out_usd_1M")):
                return {
                    "in_usd_1M": float(c.get("in_usd_1M", 0.0)),
                    "out_usd_1M": float(c.get("out_usd_1M", 0.0)),
                    "cache_usd_1M": float(c.get("cache_usd_1M", 0.0)),
                }
        except Exception:
            pass

    # 2) Fallback hardcoded (precos publicos por 1M tokens)
    nome = modelo.split("/")[-1] if "/" in modelo else modelo
    fallback = {
        "gemini-2.5-flash":             {"in_usd_1M": 0.30,  "out_usd_1M": 2.50},
        "gemini-2.5-pro":               {"in_usd_1M": 1.25,  "out_usd_1M": 10.00},
        "claude-sonnet-4-6":            {"in_usd_1M": 3.00,  "out_usd_1M": 15.00},
        "claude-opus-4-7":              {"in_usd_1M": 15.00, "out_usd_1M": 75.00},
        "claude-haiku-4-5-20251001":    {"in_usd_1M": 0.80,  "out_usd_1M": 4.00},
        "gpt-4o":                       {"in_usd_1M": 2.50,  "out_usd_1M": 10.00},
        "gpt-4o-mini":                  {"in_usd_1M": 0.15,  "out_usd_1M": 0.60},
        "qwen-plus":                    {"in_usd_1M": 0.40,  "out_usd_1M": 1.20},
    }
    if nome in fallback:
        c = fallback[nome]
        return {**c, "cache_usd_1M": 0.0}

    # 3) Modelo desconhecido / local: zera
    return {"in_usd_1M": 0.0, "out_usd_1M": 0.0, "cache_usd_1M": 0.0}


def _modelo_eh_local(modelo: str) -> bool:
    """Detecta se um modelo roda em localhost real (Ollama/vLLM/LM Studio).

    Consulta o pool LiteLLM pra pegar a base_url e verifica se contem
    localhost / 127 / 0.0.0.0 / ::1. Se nao achar o modelo no pool, retorna
    False (assume cloud - mais conservador).

    Importante: provedor "custom/local" eh polivalente - pode estar apontando
    pra OpenRouter cloud. Por isso a verificacao eh pela BASE_URL real.
    """
    if not _SL_OK or _sl is None:
        return False
    try:
        pool = _sl.load_ativos()
    except Exception:
        return False
    for p in pool:
        if p.get("modelo") == modelo:
            base_url = (p.get("base_url", "") or "").lower()
            return any(
                h in base_url
                for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
            )
    return False


def calcular_custo_brl(modelo: str, tokens_in: int, tokens_out: int,
                        tokens_cache: int = 0) -> float:
    """Calcula custo BRL: tokens * preco_USD_por_1M * cotacao_dolar.

    Ordem de prioridade (revisada em 2026-05-31 apos bug do Qwen local):
      0. SE modelo eh LOCAL (base_url=localhost) -> R$ 0,00 (sem rede paga)
      1. storage_litellm pool (custos cadastrados pelo usuario via UI)
      2. funcoes_fla legado (taxas_config.json + obter_precos_do_pdf)
      3. Fallback hardcoded (modelo desconhecido = R$ 0)

    A regra 0 eh BLINDAGEM ARQUITETURAL: modelo local NUNCA gera custo real
    independente de preco cadastrado errado, do fallback default ou de bug
    em qualquer outro lugar. Localhost = sem chamada externa = R$ 0.
    """
    # 0) BLINDAGEM: LOCAL real (localhost) NUNCA cobra
    if _modelo_eh_local(modelo):
        return 0.0

    # 1) Pool LiteLLM (custos cadastrados pelo usuario)
    custos = get_custos_modelo(modelo)
    if custos.get("in_usd_1M", 0.0) > 0 or custos.get("out_usd_1M", 0.0) > 0:
        in_usd = (tokens_in / 1_000_000.0) * custos["in_usd_1M"]
        out_usd = (tokens_out / 1_000_000.0) * custos["out_usd_1M"]
        cache_usd = (tokens_cache / 1_000_000.0) * custos["cache_usd_1M"]
        total_usd = in_usd + out_usd + cache_usd
        cotacao = _obter_dolar() or 5.25
        return float(total_usd * cotacao)

    # 2) funcoes_fla legado (retrocompatibilidade)
    if _CALC_OK:
        try:
            return float(_calcular_custo_brl_fla(modelo, tokens_in, tokens_out))
        except Exception:
            pass

    # 3) Modelo nao bate em lugar nenhum: zera
    return 0.0


# ============================================================================
# Formatacao do nome `processo` (LLM != Llm)
# ============================================================================

def formatar_processo(engine: EngineLabel, modelo: str = "") -> str:
    """Padroniza o campo `processo` no historico_consumo.json."""
    engine_disp = _ENGINE_LABEL_DISPLAY.get(engine.lower(), engine.capitalize())
    nome_curto = modelo.split("/")[-1] if "/" in modelo else (modelo or "")
    return f"Agente1_{engine_disp} ({nome_curto})"


# ============================================================================
# API publica
# ============================================================================

def registrar_custo_agente1(
    *,
    engine: EngineLabel,
    modelo: str = "",
    provedor: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    tokens_cache: int = 0,
    tempo_s: float = 0.0,
    fallback_used: bool = False,
) -> dict[str, Any]:
    """Registra a execucao do Agente 1 no historico_consumo.json.

    Sempre retorna o dict da entrada gravada (mesmo se grava falhar).
    """
    if engine == "native":
        tokens_in = tokens_in or 0
        tokens_out = tokens_out or 0
        tokens_cache = 0
        custo_brl = 0.0
    else:
        custo_brl = calcular_custo_brl(modelo, tokens_in, tokens_out, tokens_cache)

    processo = formatar_processo(engine, modelo)
    if fallback_used:
        processo += " [fallback]"

    total_tokens = (tokens_in or 0) + (tokens_out or 0)

    registrado = False
    if _LOG_OK:
        try:
            _registrar_consumo(
                processo=processo,
                modelo=modelo or "native-deterministic",
                total_tokens=total_tokens,
                custo_brl=custo_brl,
                tempo_execucao=tempo_s,
                provedor=provedor,
                tokens_in=tokens_in or 0,
                tokens_out=tokens_out or 0,
                tokens_cache=tokens_cache or 0,
            )
            registrado = True
        except Exception:
            pass

    cotacao = _obter_dolar() or 5.25
    custo_usd_estimado = custo_brl / cotacao if cotacao else 0.0

    return {
        "processo": processo,
        "modelo": modelo or "native-deterministic",
        "provedor": provedor,
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "tokens_cache": int(tokens_cache or 0),
        "total_tokens": int(total_tokens),
        "custo_brl": round(custo_brl, 5),
        "custo_usd_estimado": round(custo_usd_estimado, 5),
        "tempo_s": round(float(tempo_s), 3),
        "registrado": registrado,
        "engine": engine,
        "fallback_used": fallback_used,
    }


__all__ = [
    "registrar_custo_agente1",
    "calcular_custo_brl",
    "get_custos_modelo",
    "formatar_processo",
]
