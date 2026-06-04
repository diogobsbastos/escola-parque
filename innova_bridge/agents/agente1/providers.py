"""
innova_bridge/agents/agente1/providers.py

Camada multi-provedor pra chamar a LLM fina do Motor Hibrido 2.0.

Provedores cobertos (secao 6 da ESPEC):
  - anthropic                       -> POST https://api.anthropic.com/v1/messages
  - google (Gemini openai-compat)   -> POST {base}/chat/completions
  - openai                          -> POST {base}/chat/completions
  - moonshot                        -> POST {base}/chat/completions
  - custom/local (Ollama, vLLM)     -> POST {base}/chat/completions
  - alibaba (Qwen via dashscope)    -> POST {base}/chat/completions

Funcoes publicas:
  - call_thin_llm(provider, model, api_key, base_url, system, user,
                  max_tokens=4096, timeout=60) -> (text, usage)
  - get_provider_credentials(provider_key_id) -> dict | None
  - try_extract_json(text) -> dict | None

Robustez (regras 5 e 6 da secao 12):
  - Retry com backoff em 429, 500, 502, 503, 529 (ate 3 tentativas)
  - response_format=json_object pros OpenAI-compatible
  - Normaliza nome do modelo: remove prefixo "models/" (Gemini)
  - Decripta API key via Fernet (utils_cripto.py)
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

import requests


# ============================================================================
# Constantes
# ============================================================================

# Bases default por provider quando o usuario nao cadastra base_url.
# IMPORTANTE: cobrir aliases comuns - o pool cadastra como "gemini" mas a chave
# canonica do dict era "google". Isso causava fallback silencioso pra Ollama
# (404 em localhost:11434) quando o usuario escolhia Gemini cloud sem base_url.
OPENAI_COMPAT_BASE: dict[str, str] = {
    "google":    "https://generativelanguage.googleapis.com/v1beta/openai",
    "gemini":    "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai":    "https://api.openai.com/v1",
    "moonshot":  "https://api.moonshot.cn/v1",
    "groq":      "https://api.groq.com/openai/v1",
    "alibaba":   "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen":      "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi":      "https://api.moonshot.cn/v1",
}

# Provedores que NAO sao OpenAI-compatible (tem rota propria em call_thin_llm).
# Listados aqui pra _resolve_base_url nao mandar pra Ollama por engano.
NATIVE_ROUTE_PROVIDERS: set[str] = {"anthropic", "claude"}

# Status HTTP que justificam retry (rate limit, server hiccup, overload).
RETRYABLE_STATUS: set[int] = {429, 500, 502, 503, 529}

# Backoff progressivo entre tentativas (em segundos).
BACKOFF_SECONDS: tuple[float, ...] = (1.5, 3.0, 6.0)


# ============================================================================
# Helpers de normalizacao
# ============================================================================

def _normalize_model(model: str) -> str:
    """Remove prefixo 'models/' (comum em Gemini) - regra 4 da secao 12 da ESPEC.

    Exemplos:
        "models/gemini-2.5-flash"   -> "gemini-2.5-flash"
        "gemini/gemini-2.5-flash"   -> "gemini-2.5-flash"
        "ollama/qwen2.5vl:7b"       -> "qwen2.5vl:7b"
    """
    if not model:
        return model
    # Remove qualquer prefixo "X/" (gemini/, ollama/, models/, ...)
    if "/" in model:
        return model.rsplit("/", 1)[-1]
    return model


def _provider_is_local(provider: str) -> bool:
    """True se o provider eh Ollama/vLLM/LM Studio local (nao precisa de api_key)."""
    p = (provider or "").lower()
    return any(tag in p for tag in ("custom", "local", "ollama", "vllm", "lm studio"))


def _resolve_base_url(provider: str, base_url: Optional[str]) -> str:
    """Resolve base_url: usa o cadastrado se houver; senao usa default por provider.

    Regras:
      1. Se base_url cadastrado, usa esse (caminho rapido).
      2. Senao, procura nome do provedor em OPENAI_COMPAT_BASE (gemini, openai, ...).
      3. Se provedor eh explicitamente local (custom/local/ollama/vllm), cai
         pro default Ollama localhost.
      4. Caso contrario, levanta ValueError com mensagem clara - melhor falhar
         alto do que mandar uma chave Gemini pra http://localhost:11434 (404).
    """
    if base_url:
        return base_url.rstrip("/")
    key = (provider or "").lower()
    # Procura por chave que esteja contida no nome do provider
    # ("gemini" em "gemini", "google" em "google", "openai" em "openai/gpt-x", etc)
    for k, v in OPENAI_COMPAT_BASE.items():
        if k in key:
            return v
    # Local explicito -> Ollama default
    if _provider_is_local(provider):
        return "http://localhost:11434/v1"
    # Cloud sem mapeamento: nao podemos chutar Ollama (geraria 404 misterioso).
    raise ValueError(
        f"_resolve_base_url: provedor {provider!r} nao tem base_url cadastrado "
        f"e nao bate com nenhum default em OPENAI_COMPAT_BASE. "
        f"Cadastre uma Base URL pro provedor em Configuracoes -> LiteLLM, "
        f"ou adicione um alias em providers.OPENAI_COMPAT_BASE."
    )


# ============================================================================
# Extrator robusto de JSON da resposta da LLM
# ============================================================================

def try_extract_json(text: str) -> Optional[dict]:
    """Pega 1o `{` ate ultimo `}` e tenta json.loads.

    LLMs as vezes envolvem JSON em markdown fences ou em prosa.
    Esta funcao eh tolerante a isso.

    Returns:
        dict parseado, ou None se nao conseguir extrair JSON valido.
    """
    if not text:
        return None
    # Remove fences ```json ... ``` ou ``` ... ```
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        candidato = fence.group(1).strip()
        try:
            return json.loads(candidato)
        except json.JSONDecodeError:
            pass
    # Fallback: pega do 1o { ate o ultimo }
    primeiro = text.find("{")
    ultimo = text.rfind("}")
    if primeiro >= 0 and ultimo > primeiro:
        try:
            return json.loads(text[primeiro:ultimo + 1])
        except json.JSONDecodeError:
            return None
    return None


# ============================================================================
# Chamadas HTTP nativas por provider
# ============================================================================

def _call_anthropic(
    model: str,
    api_key: str,
    system: str,
    user: str,
    max_tokens: int,
    timeout: int,
) -> tuple[str, dict]:
    """POST https://api.anthropic.com/v1/messages (formato nativo Anthropic)."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": user}]}
        ],
    }
    r = requests.post(url, json=body, headers=headers, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    text = ""
    if j.get("content") and isinstance(j["content"], list):
        # Concatena todos os blocos de texto
        text = "".join(b.get("text", "") for b in j["content"] if b.get("type") == "text")
    usage = j.get("usage") or {}
    return text, {
        "input_tokens":  int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0)),
    }


def _call_openai_compatible(
    base_url: str,
    model: str,
    api_key: str,
    system: str,
    user: str,
    max_tokens: int,
    timeout: int,
    force_json: bool = True,
    temperature: Optional[float] = None,
    ollama_no_think: bool = False,
    seed: Optional[int] = None,
) -> tuple[str, dict]:
    """POST {base}/chat/completions (formato OpenAI: openai, gemini, moonshot, etc).

    Extensoes Ollama:
        temperature: se passado, sobrescreve o default do modelo (ex: 0.3
                     pra Qwen3 que vem com 1.0 - alta variabilidade quebra
                     output JSON estruturado).
        ollama_no_think: True -> apenda " /no_think" no user message (truque
                     oficial Qwen3 pra desligar thinking) E passa
                     "think": false no body (Ollama API native field).
                     Sem isso, modelos thinking gastam 3-5x mais tokens em
                     raciocinio interno antes da resposta JSON.
        seed: int >= 0. Quando passado, fixa o sampler -> mesmo prompt
                     produz o MESMO output em runs consecutivos
                     (reproducibilidade total + auditavel).
                     Suportado por Ollama, OpenAI, Gemini (openai-compat),
                     Groq, DashScope. Ignorado silenciosamente por providers
                     que nao implementarem (no-op seguro).
                     None (default) = mantem comportamento probabilistico atual.
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    user_msg = f"{user} /no_think" if ollama_no_think else user
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
    }
    if force_json:
        body["response_format"] = {"type": "json_object"}
    if temperature is not None:
        body["temperature"] = float(temperature)
    if seed is not None:
        # Padrao OpenAI Chat Completions - Ollama tambem aceita.
        # Sem seed = sampler aleatorio (default). Com seed = determinismo.
        body["seed"] = int(seed)
    if ollama_no_think:
        # Campo nativo do Ollama (ignorado por outros provedores OpenAI-compat).
        # Belt-and-suspenders junto com o " /no_think" no user message.
        body["think"] = False

    r = requests.post(url, json=body, headers=headers, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    text = ""
    try:
        text = j["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        text = ""
    usage = j.get("usage") or {}
    # system_fingerprint: campo nativo OpenAI/Gemini que identifica versao do
    # backend. Quando muda entre runs, o output pode ter mudado mesmo com
    # mesmo seed - sinal de que o provedor atualizou o modelo silenciosamente.
    sys_fp = j.get("system_fingerprint", "") or ""
    return text, {
        "input_tokens":  int(usage.get("prompt_tokens", 0)),
        "output_tokens": int(usage.get("completion_tokens", 0)),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0)),
        "system_fingerprint": str(sys_fp),
    }


def _call_ollama_native(
    base_url: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    timeout: int,
    force_json: bool = False,
    temperature: Optional[float] = None,
    ollama_no_think: bool = False,
    seed: Optional[int] = None,
    num_ctx: Optional[int] = None,
) -> tuple[str, dict]:
    """POST {raiz}/api/chat - endpoint NATIVO do Ollama (provedores LOCAIS).

    Motivo de existir: o endpoint OpenAI-compat (/v1/chat/completions) NAO aceita
    num_ctx. Aqui tudo vai via `options`: num_ctx (janela de contexto),
    num_predict (ceiling de output), temperature e seed -> controle TOTAL de
    reprodutibilidade por modelo.

    base_url chega como ".../v1" (ex: http://localhost:11434/v1); convertemos
    pra raiz e batemos em /api/chat.
    """
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")].rstrip("/")
    url = f"{root}/api/chat"

    user_msg = f"{user} /no_think" if ollama_no_think else user

    options: dict[str, Any] = {"num_predict": int(max_tokens)}
    if temperature is not None:
        options["temperature"] = float(temperature)
    if seed is not None:
        options["seed"] = int(seed)
    if num_ctx is not None:
        options["num_ctx"] = int(num_ctx)

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        "stream": False,
        "options": options,
    }
    if force_json:
        body["format"] = "json"
    if ollama_no_think:
        body["think"] = False

    r = requests.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    text = ""
    try:
        text = (j.get("message") or {}).get("content") or ""
    except (KeyError, TypeError):
        text = ""
    return text, {
        "input_tokens":  int(j.get("prompt_eval_count", 0) or 0),
        "output_tokens": int(j.get("eval_count", 0) or 0),
        "cache_read_input_tokens": 0,
        "system_fingerprint": "",
    }


# ============================================================================
# Introspeccao de modelos locais (Ollama) - reproducibilidade cross-machine
# ============================================================================

def get_ollama_model_info(base_url: str, model: str, timeout: int = 5) -> dict:
    """Consulta Ollama pra pegar digest + quantization + family + param size.

    Estrategia em 2 chamadas (Ollama 0.24+ separou digest do show):
      1. POST /api/show     -> retorna details (quantization, family, param_size)
      2. GET  /api/tags     -> lista modelos com digest. Procuramos match pelo nome.

    Versoes antigas do Ollama (<0.24) tambem retornam digest direto em /api/show -
    nesse caso a regra 1 ja captura, e regra 2 vira no-op.

    Retorno (tudo string, nunca None):
        {
            "model_digest": "sha256:abc123...",    # hash imutavel do modelo
            "model_quantization": "Q4_K_M",        # nivel de quantizacao
            "model_family": "qwen2",               # familia do modelo
            "model_param_size": "7B",              # tamanho dos parametros (com encoder VL)
        }
    Retorna {} se Ollama estiver fora ou base nao for Ollama.
    Defensivo - NUNCA quebra a chamada principal.
    """
    try:
        # /v1/chat/completions -> raiz do Ollama (/api/* eh nativo, fora do /v1)
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        modelo_norm = _normalize_model(model)

        # ----------------------------------------------------------------
        # 1) /api/show -> details (quantization, family, parameter_size)
        # ----------------------------------------------------------------
        info = {
            "model_digest": "",
            "model_quantization": "",
            "model_family": "",
            "model_param_size": "",
        }
        try:
            r = requests.post(
                f"{root}/api/show",
                json={"name": modelo_norm},
                timeout=timeout,
            )
            if r.ok:
                j = r.json() or {}
                details = j.get("details") or {}
                info["model_digest"] = str(j.get("digest", "") or "")
                info["model_quantization"] = str(details.get("quantization_level", "") or "")
                info["model_family"] = str(details.get("family", "") or "")
                info["model_param_size"] = str(details.get("parameter_size", "") or "")
        except Exception:
            pass  # Continua pra /api/tags - pode pelo menos pegar digest

        # ----------------------------------------------------------------
        # 2) /api/tags -> lista de modelos com digest (cobre Ollama 0.24+)
        #    Se /api/show ja deu digest, ignora. Senao, faz match por nome.
        # ----------------------------------------------------------------
        if not info["model_digest"]:
            try:
                r = requests.get(f"{root}/api/tags", timeout=timeout)
                if r.ok:
                    j = r.json() or {}
                    models = j.get("models") or []
                    for m in models:
                        # Match flexivel: aceita "qwen2.5vl:7b" e "qwen2.5vl:7b-..."
                        nome = str(m.get("name", "") or m.get("model", "") or "")
                        if nome == modelo_norm or nome.split(":")[0] == modelo_norm.split(":")[0]:
                            info["model_digest"] = str(m.get("digest", "") or "")
                            # Se /api/show falhou, tenta pegar details aqui tambem
                            if not info["model_quantization"]:
                                d = m.get("details") or {}
                                info["model_quantization"] = str(d.get("quantization_level", "") or "")
                                info["model_family"] = str(d.get("family", "") or "")
                                info["model_param_size"] = str(d.get("parameter_size", "") or "")
                            break
            except Exception:
                pass

        return info
    except Exception:
        return {}


def get_ollama_version(base_url: str, timeout: int = 5) -> str:
    """Consulta /api/version do Ollama daemon. '' se falhar."""
    try:
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        r = requests.get(f"{root}/api/version", timeout=timeout)
        if not r.ok:
            return ""
        j = r.json() or {}
        return str(j.get("version", "") or "")
    except Exception:
        return ""


# ============================================================================
# API publica: call_thin_llm com retry e dispatch por provider
# ============================================================================

def call_thin_llm(
    provider: str,
    model: str,
    api_key: str,
    base_url: Optional[str] = None,
    *,
    system: str,
    user: str,
    max_tokens: int = 4096,
    timeout: int = 60,
    temperature_override: Optional[float] = None,
    force_json_override: Optional[bool] = None,
    seed_override: Optional[int] = None,
    num_ctx_override: Optional[int] = None,
) -> tuple[str, dict]:
    """Chama a LLM fina e devolve (text, usage_dict).

    Args:
        provider:   "anthropic" | "google" | "openai" | "moonshot" | "alibaba"
                    | "groq" | "kimi" | "custom/local (...)" | "ollama" | ...
        model:      nome do modelo (ex: "claude-sonnet-4-6", "gemini-2.5-flash",
                    "qwen2.5vl:7b"). Sera normalizado (remove prefixo X/).
        api_key:    chave de API ja DECRIPTADA (em runtime). Pode ser "" pra Ollama local.
        base_url:   override de base_url. Se None, usa default por provider.
        system:     system prompt (THIN_SYSTEM).
        user:       user message (output de build_thin_user_payload).
        max_tokens: ceiling de output. Default 4096 (suficiente pro JSON do thin).
        timeout:    segundos por tentativa.

    Returns:
        (text, usage) onde:
            text  = string que pode conter JSON envolvido em fences/prosa
                    (use try_extract_json depois)
            usage = {"input_tokens": int, "output_tokens": int,
                     "cache_read_input_tokens": int}

    Raises:
        requests.exceptions.HTTPError em caso de erro nao-retryable
        (4xx que nao seja 429), ou apos todas as tentativas esgotadas.
    """
    model_norm = _normalize_model(model)
    p = (provider or "").lower()

    # Ate 4 tentativas (inicial + 3 retries)
    last_exc: Optional[Exception] = None
    for tentativa in range(len(BACKOFF_SECONDS) + 1):
        try:
            if "anthropic" in p:
                return _call_anthropic(
                    model=model_norm, api_key=api_key,
                    system=system, user=user,
                    max_tokens=max_tokens, timeout=timeout,
                )
            # Demais provedores: OpenAI-compatible
            url_base = _resolve_base_url(provider, base_url)
            is_local = _provider_is_local(provider)

            # Defaults automaticos por tipo de provider:
            ollama_no_think = False
            temperature = None
            force_json = not is_local  # Ollama local nao costuma respeitar response_format

            if is_local:
                temperature = 0.3
                # Detecta modelos com thinking nativo (qwen3, deepseek-r1, etc)
                model_lower = model_norm.lower()
                if any(tag in model_lower for tag in ("qwen3", "qwen3.5", "qwen3.6", "deepseek-r1", "r1", "thinking")):
                    ollama_no_think = True

            # OVERRIDES da UI (Treinamento de Agentes) - sobrescrevem os defaults
            if temperature_override is not None:
                temperature = float(temperature_override)
            if force_json_override is not None:
                force_json = bool(force_json_override)
            # seed eh None por default (sampling probabilistico).
            # Quando passado, fixa o seed -> determinismo total.
            seed_eff: Optional[int] = (
                int(seed_override) if seed_override is not None else None
            )
            # num_ctx: janela de contexto - so aplicado a Ollama local (via /api/chat).
            num_ctx_eff: Optional[int] = (
                int(num_ctx_override) if num_ctx_override is not None else None
            )

            if is_local:
                # Endpoint NATIVO do Ollama (/api/chat) - unico que aceita num_ctx.
                # O /v1/chat/completions ignora num_ctx silenciosamente.
                text, usage = _call_ollama_native(
                    base_url=url_base, model=model_norm,
                    system=system, user=user,
                    max_tokens=max_tokens, timeout=timeout,
                    force_json=force_json,
                    temperature=temperature,
                    ollama_no_think=ollama_no_think,
                    seed=seed_eff,
                    num_ctx=num_ctx_eff,
                )
            else:
                text, usage = _call_openai_compatible(
                    base_url=url_base, model=model_norm, api_key=api_key,
                    system=system, user=user,
                    max_tokens=max_tokens, timeout=timeout,
                    force_json=force_json,
                    temperature=temperature,
                    ollama_no_think=ollama_no_think,
                    seed=seed_eff,
                )
            # Enriquece usage com PARAMETROS USADOS (reproducibilidade)
            usage["seed_used"] = int(seed_eff) if seed_eff is not None else None
            usage["temperature_used"] = (
                float(temperature) if temperature is not None else None
            )
            usage["force_json_used"] = bool(force_json)
            usage["num_ctx_used"] = int(num_ctx_eff) if num_ctx_eff is not None else None
            # Pra LOCAL: introspecciona Ollama (digest + quantization + version)
            if is_local:
                info = get_ollama_model_info(url_base, model_norm)
                usage.update(info)
                usage["ollama_version"] = get_ollama_version(url_base)
            else:
                # Cloud: sem digest local, mas system_fingerprint ja foi capturado
                usage.setdefault("model_digest", "")
                usage.setdefault("model_quantization", "")
                usage.setdefault("ollama_version", "")
            return text, usage
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status in RETRYABLE_STATUS and tentativa < len(BACKOFF_SECONDS):
                time.sleep(BACKOFF_SECONDS[tentativa])
                last_exc = e
                continue
            raise
        except requests.RequestException as e:
            # Erros de conexao / timeout: retry
            if tentativa < len(BACKOFF_SECONDS):
                time.sleep(BACKOFF_SECONDS[tentativa])
                last_exc = e
                continue
            raise

    # Defesa: nunca deveria chegar aqui, mas se chegar levanta a ultima excecao
    if last_exc:
        raise last_exc
    raise RuntimeError("call_thin_llm: esgotou tentativas sem excecao registrada")


# ============================================================================
# Credenciais: decripta API key via Fernet (storage_litellm)
# ============================================================================

def get_provider_credentials(provider_key_id: str) -> Optional[dict]:
    """Resolve as credenciais de um provider cadastrado.

    Args:
        provider_key_id: chave unica do provider no pool. No nosso projeto,
                          usamos o `modelo` como identificador (ex:
                          "gemini/gemini-2.5-flash"). Tambem aceita o
                          nome do provedor + modelo separados por '::'.

    Returns:
        dict com {provider, model, api_key, base_url} OU None se nao encontrar.
        api_key vem JA DECRIPTADA (em runtime, conforme regra 7 da secao 12).
    """
    try:
        import storage_litellm as _sl
    except Exception:
        return None

    try:
        pool = _sl.load_ativos()  # filtra apenas_precos
    except Exception:
        return None

    target_provider = None
    target_model = provider_key_id
    if "::" in provider_key_id:
        target_provider, target_model = provider_key_id.split("::", 1)
        target_provider = target_provider.strip()
        target_model = target_model.strip()

    for p in pool:
        modelo = p.get("modelo", "")
        provedor = p.get("provedor", "")
        if target_provider and target_provider not in provedor.lower():
            continue
        if modelo != target_model:
            continue
        # Match!
        # API key vem ja decriptada de storage_litellm.load_providers
        # (ele decripta no load via _decifrar_campos)
        return {
            "provider": provedor,
            "model":    modelo,
            "api_key":  p.get("api_key", "") or "",
            "base_url": p.get("base_url", "") or None,
        }
    return None


__all__ = [
    "call_thin_llm",
    "get_provider_credentials",
    "try_extract_json",
    "get_ollama_model_info",
    "get_ollama_version",
    "OPENAI_COMPAT_BASE",
    "RETRYABLE_STATUS",
    "BACKOFF_SECONDS",
]
