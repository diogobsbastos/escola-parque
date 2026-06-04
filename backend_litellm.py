"""
backend_litellm.py — Motor Unificado Multi-Provider (Escola Parque V3)
---------------------------------------------------------------------
Substitui a dependência monolítica do google-generativeai pelo LiteLLM,
permitindo que o mesmo código fale com Gemini, OpenAI, Anthropic, Groq,
Alibaba (Qwen), Kimi (Moonshot) e modelos locais (Ollama, vLLM, LM Studio).

Responsabilidades:
  • validar_provedor()  → ping mínimo com litellm.completion
  • obter_custos()      → lê litellm.model_cost (entrada/saída por 1M de tokens)
  • snapshot_custos()   → tabela completa para o painel de Custos Dinâmicos
  • gerar_resposta()    → wrapper unificado para chamadas LLM (futuro OCR)
  • hint_base_url() / hint_modelo() / listar_provedores_suportados()

REGRA DE OURO 3 (blindagem): tudo importado em try/except para que a UI
nunca quebre se o LiteLLM ainda não estiver instalado no ambiente.
"""

import time
import re

# REGRA DE OURO 3: Blindagem total das libs externas
try:
    import litellm
except ImportError:
    litellm = None

try:
    from funcoes_fla import buscar_cotacao_dolar_realtime
except ImportError:
    def buscar_cotacao_dolar_realtime():
        return 5.25


# ────────────────────────────────────────────────────────────────────────────
# Catálogo estático de provedores que a UI pode oferecer
# ────────────────────────────────────────────────────────────────────────────
PROVEDORES_SUPORTADOS = [
    "gemini",
    "openai",
    "anthropic",
    "groq",
    "alibaba",
    "kimi",
    "custom/local (Ollama, vLLM, LM Studio)",
]


# Sugestões de Base URL para provedores OpenAI-compatible
HINT_BASE_URL = {
    "gemini":     "",
    "openai":     "",
    "anthropic":  "",
    "groq":       "",
    "alibaba":    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "kimi":       "https://api.moonshot.cn/v1",
    "custom/local (Ollama, vLLM, LM Studio)": "http://localhost:11434/v1",
}


# Exemplos de Model String reconhecidos pelo LiteLLM
HINT_MODELO = {
    "gemini":     "gemini/gemini-1.5-flash",
    "openai":     "gpt-4o-mini",
    "anthropic":  "claude-3-5-sonnet-20241022",
    "groq":       "groq/llama-3.1-8b-instant",
    "alibaba":    "openai/qwen-plus",
    "kimi":       "openai/moonshot-v1-8k",
    "custom/local (Ollama, vLLM, LM Studio)": "ollama/qwen2.5-coder",
}


# ────────────────────────────────────────────────────────────────────────────
# Helpers de UI (placeholders)
# ────────────────────────────────────────────────────────────────────────────
def listar_provedores_suportados():
    """Lista de strings para o st.selectbox de provedores."""
    return list(PROVEDORES_SUPORTADOS)


def hint_base_url(provedor):
    """Placeholder de Base URL para o provedor selecionado."""
    return HINT_BASE_URL.get(provedor, "")


def hint_modelo(provedor):
    """Placeholder de Model String para o provedor selecionado."""
    return HINT_MODELO.get(provedor, "")


# ────────────────────────────────────────────────────────────────────────────
# Descoberta dinâmica de modelos (consulta o endpoint de cada provedor)
# ────────────────────────────────────────────────────────────────────────────
def _sem_prefixo_redundante(provedor, modelo):
    """Tira o prefixo 'X/' do modelo SOMENTE quando X repete o nome do provedor.

    Ex.: provedor 'gemini' + 'gemini/gemini-2.5-flash' -> 'gemini-2.5-flash'.
    Preserva prefixos que sao parte do id REAL do modelo (OpenRouter
    'meta-llama/...', 'google/gemini-...') e o 'ollama/' dos locais — nesses casos
    o prefixo NAO bate com o provedor ('custom/local'), entao nada e removido.
    """
    if not modelo or "/" not in modelo:
        return modelo
    prefixo, resto = modelo.split("/", 1)
    p = (prefixo or "").strip().lower()
    prov = (provedor or "").strip().lower()
    _ALIAS = {"google", "gemini"}
    if p == prov or (p in _ALIAS and any(a in prov for a in _ALIAS)):
        return resto
    return modelo


def listar_modelos_provedor(provedor, api_key="", base_url=""):
    """
    Consulta o catálogo de modelos disponíveis para a chave informada.
    Retorna (sucesso: bool, mensagem: str, modelos: list[str]).

    Estratégia por provedor:
      • gemini    → GET https://generativelanguage.googleapis.com/v1beta/models?key=KEY
      • anthropic → GET https://api.anthropic.com/v1/models (header x-api-key)
      • openai / groq / alibaba / kimi / custom-local → GET <base>/models (Bearer KEY)

    Os nomes retornados já vêm com o prefixo LiteLLM correto
    (ex.: "gemini/gemini-1.5-flash", "ollama/qwen2.5-coder",
    "groq/llama-3.1-8b-instant").
    """
    try:
        import requests
    except ImportError:
        return False, "Biblioteca 'requests' indisponível.", []

    if not provedor:
        return False, "Provedor não informado.", []

    prov_lower = provedor.lower()

    # ───────────── GEMINI (Google AI Studio) ─────────────
    if "gemini" in prov_lower:
        if not api_key:
            return False, "API Key obrigatória para listar modelos Gemini.", []
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}: {r.text[:240]}", []
            data = r.json() or {}
            modelos = []
            for m in data.get("models", []):
                nome = (m.get("name") or "").replace("models/", "")
                if not nome:
                    continue
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    modelos.append(_sem_prefixo_redundante(provedor, f"gemini/{nome}"))
            modelos = sorted(set(modelos))
            return True, f"✅ {len(modelos)} modelos Gemini descobertos.", modelos
        except Exception as e:
            return False, f"❌ Falha Gemini: {str(e)[:240]}", []

    # ───────────── ANTHROPIC ─────────────
    if "anthropic" in prov_lower:
        if not api_key:
            return False, "API Key obrigatória para Anthropic.", []
        try:
            url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/models"
            r = requests.get(
                url,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=15,
            )
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}: {r.text[:240]}", []
            data = r.json() or {}
            modelos = sorted({m.get("id") for m in data.get("data", []) if m.get("id")})
            return True, f"✅ {len(modelos)} modelos Anthropic descobertos.", modelos
        except Exception as e:
            return False, f"❌ Falha Anthropic: {str(e)[:240]}", []

    # ───────────── OpenAI-compatible (openai, groq, alibaba, kimi, custom/local) ─────────────
    bases_padrao = {
        "openai":  "https://api.openai.com/v1",
        "groq":    "https://api.groq.com/openai/v1",
        "alibaba": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "kimi":    "https://api.moonshot.cn/v1",
    }

    # Identifica chave de match (custom/local → tenta Ollama padrão)
    chave_prov = None
    for k in bases_padrao:
        if k in prov_lower:
            chave_prov = k
            break

    url_base = base_url or bases_padrao.get(chave_prov, "")
    if not url_base:
        if "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower:
            url_base = "http://localhost:11434/v1"
        else:
            return False, "Base URL não configurada para este provedor.", []

    try:
        url = url_base.rstrip("/") + "/models"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text[:240]}", []

        data = r.json() or {}
        modelos_raw = []
        if isinstance(data, dict) and "data" in data:
            modelos_raw = [m.get("id") for m in data["data"] if m.get("id")]
        elif isinstance(data, dict) and "models" in data:
            # Formato Ollama /api/tags
            modelos_raw = [(m.get("id") or m.get("name")) for m in data["models"]]
        modelos_raw = [m for m in modelos_raw if m]

        # Aplica prefixo LiteLLM apropriado
        prefixo_map = {
            "groq":    "groq/",
            "alibaba": "openai/",   # endpoint OpenAI-compat
            "kimi":    "openai/",   # endpoint OpenAI-compat
        }
        # Detecta endpoints CLOUD OpenAI-compatible (OpenRouter, Together, etc.)
        # que NÃO devem ganhar prefixo "ollama/" — o modelo já vem no formato
        # nativo (ex: "google/gemini-2.5-flash", "qwen/qwen2.5-vl-72b-instruct").
        # Prefixar com "ollama/" deixaria a nomenclatura confusa e poderia
        # confundir o LiteLLM routing.
        _CLOUD_OPENAI_COMPAT = (
            "openrouter.ai", "together.xyz", "together.ai",
            "fireworks.ai", "deepinfra.com", "perplexity.ai", "anyscale.com",
        )
        _base_lower = (url_base or "").lower()
        eh_cloud_openai_compat = any(d in _base_lower for d in _CLOUD_OPENAI_COMPAT)

        if eh_cloud_openai_compat:
            # OpenRouter & cia → sem prefixo (mantém formato nativo do endpoint)
            prefixo = ""
        elif "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower:
            # Ollama local REAL → prefixo ollama/ para LiteLLM rotear corretamente
            prefixo = "ollama/"
        else:
            prefixo = prefixo_map.get(chave_prov, "")

        modelos = []
        for m in modelos_raw:
            if prefixo and not m.startswith(prefixo):
                modelos.append(prefixo + m)
            else:
                modelos.append(m)
        # Limpa prefixo redundante (prefixo == provedor); preserva ollama/ e OpenRouter
        modelos = [_sem_prefixo_redundante(provedor, m) for m in modelos]
        modelos = sorted(set(modelos))
        return True, f"✅ {len(modelos)} modelos descobertos via {url_base}.", modelos
    except Exception as e:
        return False, f"❌ Falha OpenAI-compat: {str(e)[:240]}", []


# ────────────────────────────────────────────────────────────────────────────────
# Validação (ping)
# ───────────────────────────────────────────────────────────────────────────────
def pingar_provedor_http(provedor, modelo_str, api_key="", base_url=""):
    """
    Dispara uma chamada de completion REAL diretamente no endpoint nativo
    do provedor (Gemini /generateContent, Anthropic /v1/messages, OpenAI-compat
    /chat/completions). NAO usa litellm.completion - util para validar a chave
    antes mesmo de a biblioteca litellm estar instalada/configurada.

    Retorna (sucesso: bool, mensagem: str).
    """
    try:
        import requests
    except ImportError:
        return False, "Biblioteca 'requests' indisponivel."

    if not provedor:
        return False, "Provedor nao informado."
    if not modelo_str:
        return False, "Model String vazia."

    prov_lower = provedor.lower()

    # GEMINI
    if "gemini" in prov_lower:
        if not api_key:
            return False, "API Key obrigatoria para Gemini."
        modelo_limpo = modelo_str[len("gemini/"):] if modelo_str.startswith("gemini/") else modelo_str
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo_limpo}:generateContent?key={api_key}"
        body = {
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 8},
        }
        try:
            r = requests.post(url, json=body, timeout=20)
            if r.status_code == 200:
                data = r.json() or {}
                texto = ""
                try:
                    texto = data["candidates"][0]["content"]["parts"][0].get("text", "")
                except Exception:
                    pass
                return True, f"✅ OK Gemini ({modelo_limpo}) - resposta: '{texto[:40].strip()}'"
            return False, f"❌ HTTP {r.status_code}: {r.text[:240]}"
        except Exception as e:
            return False, f"❌ Falha Gemini: {str(e)[:240]}"

    # ANTHROPIC
    if "anthropic" in prov_lower:
        if not api_key:
            return False, "API Key obrigatoria para Anthropic."
        url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        try:
            r = requests.post(
                url,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": modelo_str,
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=20,
            )
            if r.status_code == 200:
                data = r.json() or {}
                texto = ""
                try:
                    texto = data["content"][0].get("text", "")
                except Exception:
                    pass
                return True, f"✅ OK Anthropic ({modelo_str}) - resposta: '{texto[:40].strip()}'"
            return False, f"❌ HTTP {r.status_code}: {r.text[:240]}"
        except Exception as e:
            return False, f"❌ Falha Anthropic: {str(e)[:240]}"

    # OpenAI-compatible (openai, groq, alibaba, kimi, custom/local)
    bases_padrao = {
        "openai":  "https://api.openai.com/v1",
        "groq":    "https://api.groq.com/openai/v1",
        "alibaba": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "kimi":    "https://api.moonshot.cn/v1",
    }
    chave_prov = None
    for k in bases_padrao:
        if k in prov_lower:
            chave_prov = k
            break

    url_base = base_url or bases_padrao.get(chave_prov, "")
    if not url_base:
        if "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower:
            url_base = "http://localhost:11434/v1"
        else:
            return False, "Base URL nao configurada para este provedor."

    # Remove prefixos LiteLLM (o endpoint nativo nao aceita "openai/", "groq/" etc.)
    modelo_limpo = modelo_str
    for prefixo in ("openai/", "groq/", "ollama/"):
        if modelo_limpo.startswith(prefixo):
            modelo_limpo = modelo_limpo[len(prefixo):]
            break

    url = url_base.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model":      modelo_limpo,
        "messages":   [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=20)
        if r.status_code == 200:
            data = r.json() or {}
            texto = ""
            try:
                texto = (data["choices"][0]["message"].get("content") or "")
            except Exception:
                pass
            return True, f"✅ OK ({modelo_limpo}) - resposta: '{texto[:40].strip()}'"
        return False, f"❌ HTTP {r.status_code}: {r.text[:240]}"
    except Exception as e:
        return False, f"❌ Falha: {str(e)[:240]}"


def validar_provedor(provedor, modelo_str, api_key="", base_url=""):
    """
    Dispara um ping mínimo via litellm.completion.
    Retorna (sucesso: bool, mensagem: str).
    """
    if not litellm:
        return False, "Biblioteca 'litellm' não instalada. Rode: pip install litellm"

    if not modelo_str:
        return False, "Model String vazia."

    try:
        kwargs = {
            "model":      modelo_str,
            "messages":   [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
            "timeout":    20,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["api_base"] = base_url

        resp = litellm.completion(**kwargs)

        texto = ""
        try:
            texto = resp.choices[0].message.content or ""
        except Exception:
            pass

        return True, f"✅ OK ({modelo_str}) — resposta: '{texto[:40].strip()}'"
    except Exception as e:
        return False, f"❌ Falha: {str(e)[:240]}"


# ───────────────────────────────────────────────────────────────────────────────
# Custos (litellm.model_cost)
# ───────────────────────────────────────────────────────────────────────────────
def obter_custos(modelo_str):
    """
    Lê litellm.model_cost para o modelo informado.
    Retorna {'in': USD/1M, 'out': USD/1M, 'fonte': str}.
    """
    if not litellm:
        return {"in": 0.0, "out": 0.0, "cache": 0.0, "fonte": "litellm-ausente"}

    try:
        info = litellm.model_cost.get(modelo_str, {})

        # Fallback: tenta sem o prefixo de provedor
        if not info and "/" in modelo_str:
            chave_curta = modelo_str.split("/", 1)[1]
            info = litellm.model_cost.get(chave_curta, {})

        in_per_token    = info.get("input_cost_per_token", 0.0) or 0.0
        out_per_token   = info.get("output_cost_per_token", 0.0) or 0.0
        cache_per_token = info.get("cache_read_input_token_cost", 0.0) or 0.0

        return {
            "in":    in_per_token    * 1_000_000,
            "out":   out_per_token   * 1_000_000,
            "cache": cache_per_token * 1_000_000,
            "fonte": "litellm.model_cost",
        }
    except Exception as e:
        return {"in": 0.0, "out": 0.0, "cache": 0.0, "fonte": f"erro: {e}"}


def snapshot_custos(filtro_provedor=None, limite=500):
    """
    Constrói uma tabela com todos os modelos conhecidos pelo LiteLLM.
    Inclui conversão USD → BRL usando a cotação ao vivo do dólar.
    """
    if not litellm:
        return []

    try:
        dolar = buscar_cotacao_dolar_realtime() or 5.25
    except Exception:
        dolar = 5.25

    linhas = []
    chave_busca = ""
    if filtro_provedor and filtro_provedor != "todos":
        chave_busca = filtro_provedor.split("/")[0].split(" ")[0].lower()

    for modelo, info in litellm.model_cost.items():
        if not isinstance(info, dict):
            continue
        provider = (info.get("litellm_provider", "") or "").lower()

        if chave_busca and chave_busca not in provider and chave_busca not in modelo.lower():
            continue

        in_usd    = (info.get("input_cost_per_token")        or 0.0) * 1_000_000
        out_usd   = (info.get("output_cost_per_token")       or 0.0) * 1_000_000
        cache_usd = (info.get("cache_read_input_token_cost") or 0.0) * 1_000_000

        linhas.append({
            "modelo":       modelo,
            "provedor":     provider or "—",
            "in_usd_1M":    round(in_usd,    4),
            "out_usd_1M":   round(out_usd,   4),
            "cache_usd_1M": round(cache_usd, 4),
            "in_brl_1M":    round(in_usd    * dolar, 4),
            "out_brl_1M":   round(out_usd   * dolar, 4),
            "cache_brl_1M": round(cache_usd * dolar, 4),
            "dolar":        round(dolar, 4),
        })

    linhas.sort(key=lambda x: x["modelo"])
    return linhas[:limite]


# ───────────────────────────────────────────────────────────────────────────────
# Wrapper unificado para chamadas LLM (uso futuro pelo backend_ocr)
# ───────────────────────────────────────────────────────────────────────────────
def _extrair_custos_do_info(info):
    """Extrai (in, out, cache) por 1M tokens de uma entrada do litellm.model_cost.
    Retorna None se o registro for vazio/zerado."""
    if not isinstance(info, dict):
        return None
    in_pt    = info.get("input_cost_per_token",        0.0) or 0.0
    out_pt   = info.get("output_cost_per_token",       0.0) or 0.0
    cache_pt = info.get("cache_read_input_token_cost", 0.0) or 0.0
    if in_pt == 0 and out_pt == 0 and cache_pt == 0:
        return None
    return (in_pt * 1_000_000, out_pt * 1_000_000, cache_pt * 1_000_000)


# Prefixos de provedor que precisam ser STRIPADOS antes de buscar no catalogo
PREFIXOS_PROVEDOR = (
    "gemini/", "anthropic/", "openai/", "groq/", "ollama/",
    "mistral/", "dashscope/", "azure/", "cohere/", "bedrock/",
    "vertex_ai/", "together_ai/", "fireworks_ai/", "replicate/",
    "perplexity/", "deepinfra/", "moonshot/", "qwen/",
)


def limpar_prefixos(nome):
    """
    Remove RECURSIVAMENTE qualquer prefixo de provedor conhecido.
    Exemplo:
      'gemini/gemini-2.5-flash' -> 'gemini-2.5-flash'
      'openai/qwen-plus'        -> 'qwen-plus'
      'gemini/models/gemini-x'  -> 'gemini-x'
    """
    if not nome:
        return nome
    n = nome.strip()
    mudou = True
    while mudou:
        mudou = False
        # tira prefixo conhecido
        for p in PREFIXOS_PROVEDOR:
            if n.lower().startswith(p):
                n = n[len(p):]
                mudou = True
                break
        # tira "models/" (Google AI prepends isso as vezes)
        if n.lower().startswith("models/"):
            n = n[len("models/"):]
            mudou = True
    return n


def _gerar_candidatos(modelo_str):
    """
    Gera lista AGRESSIVA de variantes para procurar no catalogo LiteLLM.

    REGRA DE OURO: o primeiro candidato testado e SEMPRE o nome LIMPO
    (sem prefixo de provedor), porque o litellm.model_cost indexa modelos
    sem o prefixo (ex.: 'gemini-2.5-flash', nao 'gemini/gemini-2.5-flash').

    Tenta tambem variantes com sufixos comuns (-001, -002, -latest, -preview,
    -exp, -04-17) que aparecem no catalogo do Google/OpenAI/Anthropic.
    """
    candidatos = []
    if not modelo_str:
        return candidatos

    # 1) Nome LIMPO (sem qualquer prefixo) — esse e o primeiro alvo
    nome_limpo = limpar_prefixos(modelo_str)
    candidatos.append(nome_limpo)

    # 2) Nome original (caso o catalogo guarde com prefixo)
    if modelo_str != nome_limpo:
        candidatos.append(modelo_str)

    # 3) Tenta com prefixos comuns (alguns provedores no catalogo usam isso)
    for pref in ("gemini/", "anthropic/", "openai/", "groq/", "ollama/", "mistral/"):
        candidatos.append(pref + nome_limpo)

    # 4) Variantes do nome limpo
    variantes = set()
    variantes.add(nome_limpo)

    # 4a) qwen2.5 <-> qwen-2.5 (insere/remove hifen entre letra e numero)
    variantes.add(re.sub(r"([a-zA-Z])(\d)", r"\1-\2", nome_limpo))
    variantes.add(re.sub(r"(\d)([a-zA-Z])", r"\1-\2", nome_limpo))

    # 4b) ponto <-> hifen
    variantes.add(nome_limpo.replace(".", "-"))
    variantes.add(nome_limpo.replace("-", "."))

    # 4c) remove sufixo de versao (-001, -002, -003, -latest, -preview, -exp)
    base_sem_sufixo = re.sub(r"-(00\d|latest|preview|exp|stable|beta|alpha)$", "", nome_limpo)
    if base_sem_sufixo != nome_limpo:
        variantes.add(base_sem_sufixo)

    # 4d) ADICIONA sufixos comuns (importante para Gemini, OpenAI, Anthropic novos)
    for sufixo in ("-latest", "-001", "-002", "-003", "-preview", "-exp",
                   "-preview-04-17", "-preview-05-20", "-preview-02-05",
                   "-stable", "-2024-09-12", "-2024-10-22", "-2024-12-17"):
        if not nome_limpo.endswith(sufixo):
            variantes.add(nome_limpo + sufixo)
            variantes.add(base_sem_sufixo + sufixo)

    # 5) Aplica todas as variantes (com e sem prefixos)
    for v in variantes:
        if not v or v == nome_limpo:
            continue
        candidatos.append(v)
        for pref in ("gemini/", "anthropic/", "openai/", "groq/", "ollama/", "mistral/"):
            candidatos.append(pref + v)

    # 6) Deduplica preservando ordem
    visto = set()
    saida = []
    for c in candidatos:
        if c and c not in visto:
            visto.add(c)
            saida.append(c)
    return saida


def buscar_custos_no_catalogo(modelo_str):
    """
    Busca robusta no catalogo LiteLLM (litellm.model_cost) com 3 niveis de fallback:
      1. Tenta o nome exato
      2. Tenta variantes geradas (com/sem prefixo, normalizacoes de hifen/ponto)
      3. Substring match (mais permissivo) — escolhe o mais proximo em tamanho

    Retorna (achou, in_usd_1M, out_usd_1M, cache_usd_1M).
    """
    if not litellm or not modelo_str:
        return False, 0.0, 0.0, 0.0

    try:
        # Nivel 1+2: candidatos diretos
        for cand in _gerar_candidatos(modelo_str):
            custos = _extrair_custos_do_info(litellm.model_cost.get(cand))
            if custos:
                return True, custos[0], custos[1], custos[2]

        # Nivel 3: substring match permissivo (compara ignorando hifen, ponto, underscore)
        def norm(s):
            return s.lower().replace("-", "").replace("_", "").replace(".", "").replace("/", "")

        # SEMPRE usa o nome JA LIMPO (sem prefixo) como alvo
        alvo_limpo = limpar_prefixos(modelo_str)
        alvo_norm  = norm(alvo_limpo)
        if len(alvo_norm) < 4:
            return False, 0.0, 0.0, 0.0

        substring_matches = []
        for chave, info in litellm.model_cost.items():
            if not isinstance(info, dict):
                continue
            chave_limpa = limpar_prefixos(chave)
            chave_norm  = norm(chave_limpa)

            # 3a) match em ambos sentidos (substring)
            if alvo_norm in chave_norm or chave_norm in alvo_norm:
                custos = _extrair_custos_do_info(info)
                if custos:
                    score = abs(len(chave_norm) - len(alvo_norm))
                    substring_matches.append((score, chave, custos))
                    continue

            # 3b) match parcial — pelo menos 70% dos caracteres do alvo presentes no inicio da chave
            if len(alvo_norm) >= 6:
                # Pega os primeiros N caracteres do alvo e ve se aparecem em sequencia na chave
                prefixo_alvo = alvo_norm[:max(6, int(len(alvo_norm) * 0.7))]
                if prefixo_alvo in chave_norm:
                    custos = _extrair_custos_do_info(info)
                    if custos:
                        score = abs(len(chave_norm) - len(alvo_norm)) + 5  # penalidade leve
                        substring_matches.append((score, chave, custos))

        if substring_matches:
            substring_matches.sort(key=lambda x: x[0])
            _, chave_encontrada, custos = substring_matches[0]
            return True, custos[0], custos[1], custos[2]

        return False, 0.0, 0.0, 0.0
    except Exception:
        return False, 0.0, 0.0, 0.0


def sugerir_modelos_similares(modelo_str, limite=15):
    """
    Devolve lista de chaves do litellm.model_cost que tem texto em comum com modelo_str.
    Usado quando buscar_custos_no_catalogo falha — ajuda o usuario a achar o nome certo.

    Retorna lista de dicts: [{"nome": str, "in_usd_1M": float, "out_usd_1M": float, "cache_usd_1M": float}]
    """
    if not litellm or not modelo_str:
        return []

    try:
        nome_base = limpar_prefixos(modelo_str).lower()
        # Pega o "radical" do nome (primeira sequencia alfa-numerica)
        m = re.search(r"[a-z]+", nome_base)
        radical = m.group(0) if m else nome_base
        if len(radical) < 3:
            radical = nome_base[:3] if len(nome_base) >= 3 else nome_base

        achados = []
        for chave, info in litellm.model_cost.items():
            if not isinstance(info, dict):
                continue
            if radical not in chave.lower():
                continue
            in_pt  = info.get("input_cost_per_token",  0.0) or 0.0
            out_pt = info.get("output_cost_per_token", 0.0) or 0.0
            if not (in_pt or out_pt):
                continue
            cache_pt = info.get("cache_read_input_token_cost", 0.0) or 0.0
            achados.append({
                "nome":         chave,
                "in_usd_1M":    round(in_pt  * 1_000_000, 4),
                "out_usd_1M":   round(out_pt * 1_000_000, 4),
                "cache_usd_1M": round(cache_pt * 1_000_000, 4),
            })

        # Ordena: chaves mais curtas (mais especificas) primeiro, depois alfabetico
        achados.sort(key=lambda x: (len(x["nome"]), x["nome"]))
        return achados[:limite]
    except Exception:
        return []


def debug_catalogo(radical=""):
    """
    DIAGNOSTICO: retorna informacoes do catalogo litellm.model_cost real do ambiente.

    Util para o usuario entender PORQUE um modelo nao foi achado — pode ser que a
    versao do litellm instalada simplesmente nao conhece esse modelo ainda.

    Retorna dict com:
      • versao_litellm        — versao instalada (ou "ausente")
      • total_modelos         — qtd total de chaves em litellm.model_cost
      • chaves_com_radical    — todas as chaves que contem o radical informado
      • amostra_inicial       — primeiras 15 chaves do catalogo (para referencia)
    """
    info = {
        "versao_litellm":     "ausente",
        "total_modelos":      0,
        "chaves_com_radical": [],
        "amostra_inicial":    [],
    }

    if not litellm:
        return info

    try:
        info["versao_litellm"] = getattr(litellm, "__version__", "desconhecida")
    except Exception:
        info["versao_litellm"] = "desconhecida"

    try:
        chaves = list(litellm.model_cost.keys()) if hasattr(litellm, "model_cost") else []
        info["total_modelos"] = len(chaves)
        info["amostra_inicial"] = sorted(chaves)[:15]

        if radical:
            radical_lower = radical.lower().strip()
            # Tira hifens/pontos/slashes pra match mais flexivel
            radical_norm = radical_lower.replace("/", "").replace("-", "").replace(".", "").replace("_", "")
            achadas = []
            for k in chaves:
                k_norm = k.lower().replace("/", "").replace("-", "").replace(".", "").replace("_", "")
                if radical_lower in k.lower() or radical_norm in k_norm:
                    achadas.append(k)
            info["chaves_com_radical"] = sorted(achadas)
    except Exception as e:
        info["erro"] = str(e)

    return info


def _converter_messages_para_gemini(messages):
    """
    Converte mensagens OpenAI-style multimodal para o formato Gemini API.
    OpenAI: [{role, content: [{type:text,text:...} | {type:image_url, image_url:{url:data:image/jpeg;base64,...}}]}]
    Gemini: {contents: [{parts: [{text:...} | {inline_data:{mime_type, data}}]}]}
    """
    contents = []
    for msg in messages:
        parts = []
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append({"text": content})
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                tipo = item.get("type", "")
                if tipo == "text":
                    parts.append({"text": item.get("text", "")})
                elif tipo == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        # data:image/jpeg;base64,<b64>
                        try:
                            header, b64 = url.split(",", 1)
                            mime = header.split(";")[0].replace("data:", "")
                            parts.append({"inline_data": {"mime_type": mime, "data": b64}})
                        except Exception:
                            pass
        if parts:
            contents.append({"parts": parts})
    return contents


def _converter_messages_para_anthropic(messages):
    """
    Converte mensagens OpenAI-style multimodal para o formato Anthropic Messages API.
    OpenAI image_url: {url: "data:image/jpeg;base64,..."} -> Anthropic: {type:image, source:{type:base64, media_type, data}}
    """
    novas = []
    for msg in messages:
        role    = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            novas.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue
        novo_content = []
        for item in content:
            if not isinstance(item, dict):
                continue
            tipo = item.get("type", "")
            if tipo == "text":
                novo_content.append({"type": "text", "text": item.get("text", "")})
            elif tipo == "image_url":
                url = item.get("image_url", {}).get("url", "")
                if url.startswith("data:"):
                    try:
                        header, b64 = url.split(",", 1)
                        mime = header.split(";")[0].replace("data:", "")
                        novo_content.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime, "data": b64},
                        })
                    except Exception:
                        pass
        novas.append({"role": role, "content": novo_content})
    return novas


def enviar_completion_http(provedor, modelo_str, messages, api_key="", base_url="",
                           temperature=0.0, max_tokens=4000, timeout=180):
    """
    POST DIRETO ao endpoint nativo do provedor da LLM (sem litellm.completion).

    Estrategia por provedor:
      • gemini    -> POST https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key=KEY
      • anthropic -> POST https://api.anthropic.com/v1/messages (header x-api-key)
      • openai/groq/alibaba/kimi/custom-local -> POST <base>/chat/completions (Bearer KEY)

    Recebe 'messages' no formato OpenAI multimodal e CONVERTE automaticamente
    para o formato nativo do provedor.

    Retorna (ok: bool, dados: dict, mensagem: str).
    dados = {
        "texto":        str,    # resposta textual do modelo
        "tokens_in":    int,    # prompt tokens
        "tokens_out":   int,    # completion tokens
        "tokens_cache": int,    # cache_read_input_tokens (se disponivel)
        "modelo_real":  str,    # nome efetivo enviado ao endpoint
        "endpoint":     str,    # URL chamada
    }
    """
    try:
        import requests
    except ImportError:
        return False, {}, "Biblioteca 'requests' indisponivel."

    if not provedor:
        return False, {}, "Provedor nao informado."
    if not modelo_str:
        return False, {}, "Model String vazia."
    if not messages:
        return False, {}, "messages vazio."

    prov_lower = provedor.lower()

    # ────────────────── GEMINI (Google AI Studio) ──────────────────
    if "gemini" in prov_lower:
        if not api_key:
            return False, {}, "API Key obrigatoria para Gemini."
        modelo_limpo = modelo_str[len("gemini/"):] if modelo_str.startswith("gemini/") else modelo_str
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo_limpo}:generateContent?key={api_key}"
        body = {
            "contents": _converter_messages_para_gemini(messages),
            "generationConfig": {
                "temperature":     float(temperature),
                "maxOutputTokens": int(max_tokens),
                "topP":            1.0,
                "topK":            1,
            },
        }
        try:
            r = requests.post(url, json=body, timeout=timeout)
            if r.status_code != 200:
                return False, {}, f"HTTP {r.status_code}: {r.text[:400]}"
            data = r.json() or {}
            texto = ""
            try:
                texto = data["candidates"][0]["content"]["parts"][0].get("text", "") or ""
            except Exception:
                # Tenta concatenar todas as parts (caso retorne varios chunks)
                try:
                    partes = data["candidates"][0]["content"]["parts"]
                    texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict))
                except Exception:
                    pass
            usage = data.get("usageMetadata", {}) or {}
            finish_reason = ""
            try:
                finish_reason = (data.get("candidates", [{}])[0] or {}).get("finishReason", "") or ""
            except Exception:
                pass
            return True, {
                "texto":         texto,
                "tokens_in":     int(usage.get("promptTokenCount",     0) or 0),
                "tokens_out":    int(usage.get("candidatesTokenCount", 0) or 0),
                "tokens_cache":  int(usage.get("cachedContentTokenCount", 0) or 0),
                "modelo_real":   modelo_limpo,
                "endpoint":      url.split("?")[0],
                "finish_reason": finish_reason,
            }, "ok"
        except Exception as e:
            return False, {}, f"Falha Gemini: {str(e)[:400]}"

    # ────────────────── ANTHROPIC ──────────────────
    if "anthropic" in prov_lower:
        if not api_key:
            return False, {}, "API Key obrigatoria para Anthropic."
        url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        modelo_limpo = modelo_str
        for pref in ("anthropic/",):
            if modelo_limpo.startswith(pref):
                modelo_limpo = modelo_limpo[len(pref):]
                break
        body = {
            "model":      modelo_limpo,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "messages":   _converter_messages_para_anthropic(messages),
        }
        try:
            r = requests.post(
                url,
                headers={
                    "x-api-key":         api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json=body,
                timeout=timeout,
            )
            if r.status_code != 200:
                return False, {}, f"HTTP {r.status_code}: {r.text[:400]}"
            data = r.json() or {}
            texto = ""
            try:
                # content e uma lista de blocos {type, text}
                texto = "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))
            except Exception:
                pass
            usage = data.get("usage", {}) or {}
            finish_reason = data.get("stop_reason", "") or ""
            return True, {
                "texto":         texto,
                "tokens_in":     int(usage.get("input_tokens",  0) or 0),
                "tokens_out":    int(usage.get("output_tokens", 0) or 0),
                "tokens_cache":  int(usage.get("cache_read_input_tokens", 0) or 0),
                "modelo_real":   modelo_limpo,
                "endpoint":      url,
                "finish_reason": finish_reason,
            }, "ok"
        except Exception as e:
            return False, {}, f"Falha Anthropic: {str(e)[:400]}"

    # ────────────────── OpenAI-compatible (openai, groq, alibaba, kimi, custom/local) ──────────────────
    bases_padrao = {
        "openai":  "https://api.openai.com/v1",
        "groq":    "https://api.groq.com/openai/v1",
        "alibaba": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "kimi":    "https://api.moonshot.cn/v1",
    }
    chave_prov = None
    for k in bases_padrao:
        if k in prov_lower:
            chave_prov = k
            break

    url_base = base_url or bases_padrao.get(chave_prov, "")
    if not url_base:
        if "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower:
            url_base = "http://localhost:11434/v1"
        else:
            return False, {}, "Base URL nao configurada para este provedor."

    # Remove prefixos LiteLLM (endpoint nativo nao aceita)
    modelo_limpo = modelo_str
    for prefixo in ("openai/", "groq/", "ollama/"):
        if modelo_limpo.startswith(prefixo):
            modelo_limpo = modelo_limpo[len(prefixo):]
            break

    url = url_base.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model":       modelo_limpo,
        "messages":    messages,   # ja esta em formato OpenAI multimodal
        "temperature": float(temperature),
        "max_tokens":  int(max_tokens),
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=timeout)
        if r.status_code != 200:
            return False, {}, f"HTTP {r.status_code}: {r.text[:400]}"
        data = r.json() or {}
        texto = ""
        try:
            texto = data["choices"][0]["message"].get("content", "") or ""
        except Exception:
            pass
        usage = data.get("usage", {}) or {}
        tokens_cache = 0
        try:
            tokens_cache = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0)
        except Exception:
            pass
        finish_reason = ""
        try:
            finish_reason = (data.get("choices", [{}])[0] or {}).get("finish_reason", "") or ""
        except Exception:
            pass
        return True, {
            "texto":         texto,
            "tokens_in":     int(usage.get("prompt_tokens",     0) or 0),
            "tokens_out":    int(usage.get("completion_tokens", 0) or 0),
            "tokens_cache":  tokens_cache,
            "modelo_real":   modelo_limpo,
            "endpoint":      url,
            "finish_reason": finish_reason,
        }, "ok"
    except Exception as e:
        return False, {}, f"Falha {provedor}: {str(e)[:400]}"


def gerar_resposta(modelo, messages, **kwargs):
    """
    Roteia uma chamada para o LiteLLM, propagando temperatura, max_tokens,
    api_base, api_key, etc. Retorna (response_obj, mensagem_ou_'ok').
    """
    if not litellm:
        return None, "Biblioteca 'litellm' não instalada."
    try:
        resp = litellm.completion(model=modelo, messages=messages, **kwargs)
        return resp, "ok"
    except Exception as e:
        return None, str(e)
