"""
innova_bridge/agents/profile_builder.py - Agente 1 (Profile Builder).

Orquestra a chamada LLM que transforma:
    CANONICAL (Pydantic) -> PAI v1.0 (Pydantic)

Pipeline:
    canonical_dict (entrada)
      -> monta input JSON conforme spec do Agente1_ConstrutorDePerfil_v1.2
      -> le system prompt de prompts/profile_builder_v1_2.md
      -> pega agent default do registry (profile_builder)
      -> chama backend_litellm.enviar_completion_http
      -> parseia o output JSON
      -> valida com Pydantic PAI
      -> salva em innova_bridge/formularios/pais_gerados/
      -> registra custo via funcoes_fla.registrar_consumo
      -> retorna (pai_dict, telemetria)

Custo estimado por execucao (Claude Sonnet 4.6, temp 0.3, max 8000 tokens):
    ~R$ 3-5 por aluno. Executar 1x por ano por aluno.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Caminho base do innova_bridge
BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
PAIS_GERADOS_DIR = BASE_DIR / "formularios" / "pais_gerados"


# ============================================================================
# Helpers
# ============================================================================

def _carregar_system_prompt(versao: str = "v1.2") -> str:
    """Le o system prompt do arquivo .md, normalizando para passar ao LLM."""
    arq = PROMPTS_DIR / f"profile_builder_{versao.replace('.', '_')}.md"
    if not arq.exists():
        raise FileNotFoundError(f"System prompt nao encontrado: {arq}")
    return arq.read_text(encoding="utf-8")


def _garantir_pasta_pais() -> None:
    PAIS_GERADOS_DIR.mkdir(parents=True, exist_ok=True)


def _montar_input_json(canonical_dict: dict,
                        laudo_summary: Optional[str] = None,
                        historical: Optional[dict] = None) -> dict:
    """Monta o input que o Agente 1 espera receber (conforme spec)."""
    return {
        "questionnaire_response": canonical_dict,
        "laudo_summary": laudo_summary,
        "historical_data": historical,
    }


def _extrair_json_da_resposta(texto: str) -> dict:
    """LLMs as vezes envolvem JSON em markdown fences ou prosa. Extrai o JSON."""
    texto = texto.strip()
    # Remove markdown fences se houver
    if texto.startswith("```"):
        # Pega bloco interno
        match = re.search(r"```(?:json)?\s*(.*?)```", texto, re.DOTALL)
        if match:
            texto = match.group(1).strip()
    # Se ainda nao parsea, tenta achar o primeiro { ate o ultimo }
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        primeiro = texto.find("{")
        ultimo = texto.rfind("}")
        if primeiro >= 0 and ultimo > primeiro:
            return json.loads(texto[primeiro:ultimo + 1])
        raise


def _validar_pai_pydantic(pai_dict: dict) -> tuple[bool, str]:
    """Valida o dict contra o schema PAI v1.0. Retorna (ok, mensagem)."""
    try:
        from innova_bridge.models.pai import PAI
        PAI.model_validate(pai_dict)
        return True, "PAI valido segundo Pydantic v1.0"
    except Exception as e:
        return False, f"Pydantic invalidou PAI: {type(e).__name__} - {e}"


def _salvar_pai_local(pai_dict: dict, aluno_id: str) -> Path:
    """Salva o PAI gerado em pais_gerados/{aluno_id}_PAI_v1_0_{timestamp}.json."""
    _garantir_pasta_pais()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"{aluno_id}_PAI_v1_0_{timestamp}.json"
    destino = PAIS_GERADOS_DIR / nome
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(pai_dict, f, ensure_ascii=False, indent=2)
    return destino


# ============================================================================
# API publica
# ============================================================================

def build_pai(canonical_dict: dict,
              laudo_summary: Optional[str] = None,
              historical: Optional[dict] = None,
              agent_id_override: Optional[str] = None,
              provider_override: Optional[str] = None,
              model_override: Optional[str] = None,
              temperature_override: Optional[float] = None,
              max_tokens_override: Optional[int] = None,
              salvar: bool = True) -> tuple[dict, dict]:
    """Dispara o Agente 1: canonical -> PAI v1.0.

    3 modos de selecao do LLM (em ordem de prioridade):
      1. provider_override + model_override -> usa direto, sem registry
      2. agent_id_override -> busca o agent especifico no registry
      3. (default) -> usa o agent default do registry (profile_builder)

    Args:
        canonical_dict: dict do canonical (saida do adapter NEEI)
        laudo_summary: PT-BR opcional, sintese operacional do laudo
        historical: PAIs anteriores deste aluno (opcional)
        agent_id_override: forca um agent_id especifico (None = usa default)
        provider_override: forca um provedor especifico (ex: "gemini", "anthropic")
        model_override: forca um modelo especifico (ex: "gemini/gemini-2.5-flash")
        temperature_override: forca temperatura (None = usa do agent ou 0.3)
        max_tokens_override: forca max tokens (None = usa do agent ou 8000)
        salvar: se True, persiste em pais_gerados/

    Returns:
        (pai_dict, telemetria) onde telemetria tem:
            {ok, tokens_in, tokens_out, tokens_cache, custo_brl, tempo_s,
             modelo, provedor, agent_id, arquivo_salvo, mensagem}
    """
    t0 = time.time()
    telemetria = {
        "ok": False,
        "tokens_in": 0, "tokens_out": 0, "tokens_cache": 0,
        "custo_brl": 0.0, "tempo_s": 0.0,
        "modelo": "?", "provedor": "?", "agent_id": "?",
        "arquivo_salvo": None,
        "mensagem": "",
    }

    # 1) Resolve o LLM a usar (3 modos)
    agent = None
    prompt_version = "v1.2"

    if provider_override and model_override:
        # Modo direto - bypass total do registry
        provedor = provider_override
        modelo = model_override
        temperatura = temperature_override if temperature_override is not None else 0.3
        max_tokens = max_tokens_override if max_tokens_override is not None else 8000
        telemetria["agent_id"] = f"override:{provedor}:{modelo}"
    else:
        # Modo registry (default ou agent_id_override)
        try:
            from innova_bridge.agents import registry
            if agent_id_override:
                agent = registry.buscar(agent_id_override)
                if agent is None:
                    telemetria["mensagem"] = f"agent_id '{agent_id_override}' nao encontrado"
                    return {}, telemetria
            else:
                agent = registry.get_default("profile_builder")
                if agent is None:
                    telemetria["mensagem"] = "Nenhum profile_builder default no registry"
                    return {}, telemetria
        except Exception as e:
            telemetria["mensagem"] = f"Erro carregando registry: {e}"
            return {}, telemetria

        provedor = agent.get("llm_provider", "anthropic")
        modelo = agent.get("llm_model", "claude-sonnet-4-6")
        extra = agent.get("extra_config", {}) or {}
        temperatura = float(extra.get("temperature", 0.3))
        max_tokens = int(extra.get("max_tokens", 8000))
        prompt_version = agent.get("prompt_version", "v1.2")
        telemetria["agent_id"] = agent.get("id", "?")

    # Permite override mesmo no modo registry
    if temperature_override is not None:
        temperatura = float(temperature_override)
    if max_tokens_override is not None:
        max_tokens = int(max_tokens_override)

    telemetria["modelo"] = modelo
    telemetria["provedor"] = provedor

    # 2) Carrega system prompt
    try:
        system_prompt = _carregar_system_prompt(prompt_version)
    except FileNotFoundError as e:
        telemetria["mensagem"] = str(e)
        return {}, telemetria

    # 3) Monta input + messages
    user_input = _montar_input_json(canonical_dict, laudo_summary, historical)
    user_message_text = (
        "Generate the PAI v1.0 for this student based on the structured input below. "
        "Return ONLY the JSON, no extra commentary.\n\n"
        + json.dumps(user_input, ensure_ascii=False, indent=2)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message_text},
    ]

    # 4) Dispara LLM via backend_litellm
    try:
        from backend_litellm import enviar_completion_http
        from funcoes_fla import load_key, registrar_consumo, calcular_custo_brl
    except ImportError as e:
        telemetria["mensagem"] = f"Imports falharam: {e}"
        return {}, telemetria

    # Busca API key: 1o tenta providers_litellm (mais novo), depois keys.json (legacy)
    api_key = ""
    base_url = ""
    try:
        import storage_litellm as _sl
        for p in _sl.load_ativos():
            if p.get("modelo") == modelo and p.get("api_key"):
                api_key = p.get("api_key", "")
                base_url = p.get("base_url", "") or ""
                break
    except Exception:
        pass
    if not api_key:
        api_key = load_key(provider=provedor) or ""
    if not api_key:
        telemetria["mensagem"] = (
            f"API key vazia pro modelo '{modelo}' (provedor '{provedor}'). "
            "Cadastre em Configuracoes -> LiteLLM."
        )
        return {}, telemetria

    ok, dados, msg = enviar_completion_http(
        provedor=provedor,
        modelo_str=modelo,
        messages=messages,
        api_key=api_key,
        base_url=base_url,
        temperature=temperatura,
        max_tokens=max_tokens,
        timeout=180,
    )
    if not ok:
        telemetria["mensagem"] = f"LLM falhou: {msg}"
        return {}, telemetria

    texto_resposta = dados.get("texto", "")
    telemetria["tokens_in"] = int(dados.get("tokens_in", 0))
    telemetria["tokens_out"] = int(dados.get("tokens_out", 0))
    telemetria["tokens_cache"] = int(dados.get("tokens_cache", 0))

    # 5) Parsea JSON
    try:
        pai_dict = _extrair_json_da_resposta(texto_resposta)
    except Exception as e:
        telemetria["mensagem"] = f"Falha parseando JSON do LLM: {e}"
        telemetria["resposta_bruta"] = texto_resposta[:500]
        return {}, telemetria

    # 6) Valida com Pydantic
    pai_valido, msg_valid = _validar_pai_pydantic(pai_dict)
    if not pai_valido:
        telemetria["mensagem"] = msg_valid
        # Retorna pai_dict mesmo invalido pra inspecao
        return pai_dict, telemetria

    # 7) Salva local
    aluno_id = pai_dict.get("meta", {}).get("student_id", "UNKNOWN")
    if salvar:
        try:
            destino = _salvar_pai_local(pai_dict, aluno_id)
            telemetria["arquivo_salvo"] = str(destino)
        except Exception as e:
            telemetria["mensagem"] = f"Falha salvando local: {e}"
            return pai_dict, telemetria

    # 8) Registra custo
    custo_brl = calcular_custo_brl(modelo, telemetria["tokens_in"], telemetria["tokens_out"])
    telemetria["custo_brl"] = float(custo_brl)
    tempo = time.time() - t0
    telemetria["tempo_s"] = round(tempo, 2)
    try:
        registrar_consumo(
            processo=f"Agente1_ProfileBuilder ({modelo})",
            modelo=modelo,
            total_tokens=telemetria["tokens_in"] + telemetria["tokens_out"],
            custo_brl=custo_brl,
            tempo_execucao=tempo,
            provedor=provedor,
            tokens_in=telemetria["tokens_in"],
            tokens_out=telemetria["tokens_out"],
            tokens_cache=telemetria["tokens_cache"],
        )
    except Exception as e:
        # Telemetria nao deve falhar a operacao toda
        telemetria["mensagem"] = f"PAI OK, mas registro de custo falhou: {e}"
        return pai_dict, telemetria

    telemetria["ok"] = True
    telemetria["mensagem"] = "PAI gerado, validado e salvo com sucesso."
    return pai_dict, telemetria


def _is_localhost_base_url(base_url: str) -> bool:
    """Detecta se a base_url aponta pra maquina local (Ollama, vLLM, LM Studio).

    Distincao crucial: o provedor "custom/local" do nosso sistema eh polivalente:
      - http://localhost:11434/v1     -> Ollama real (gratis)
      - https://openrouter.ai/api/v1  -> OpenRouter (PAGO!)
      - https://api.deepseek.com      -> DeepSeek (PAGO!)
    O label nao pode mais assumir "gratis" so pelo nome do provedor.
    """
    if not base_url:
        return False
    bu = base_url.lower()
    return any(h in bu for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1"))


def _formatar_label_modelo(prov: str, modelo: str, is_local: bool, custos: dict,
                            base_url: str = "") -> str:
    """Label amigavel pro dropdown: [TIPO] modelo (custo/1M).

    Regras revisadas (apos descobrir provedores cloud cadastrados como custom/local):
      - [LOCAL] so se a base_url for localhost/127 (Ollama de verdade).
      - [CLOUD] em todos os outros casos, INCLUSIVE custom/local com base_url
        externa (OpenRouter, DeepSeek, etc).
      - Sufixo "- gratis" so se for local-real OU custos cadastrados = 0.
      - Caso contrario, mostra preco USD/1M cadastrado.
    """
    modelo_curto = modelo.split("/")[-1] if "/" in modelo else modelo
    custo_in = float(custos.get("in_usd_1M", 0.0))
    custo_out = float(custos.get("out_usd_1M", 0.0))

    # Local REAL = localhost. Custom/local apontando pra cloud nao eh "local".
    is_local_real = is_local and _is_localhost_base_url(base_url)
    tipo = "LOCAL" if is_local_real else "CLOUD"

    if is_local_real or (custo_in == 0 and custo_out == 0):
        custo_txt = " - gratis"
    else:
        custo_txt = f" - ${custo_in:.2f}/${custo_out:.2f} por 1M"
    return f"[{tipo}] {modelo_curto}{custo_txt}"


def listar_modelos_disponiveis() -> list[dict]:
    """Lista TODOS os modelos LLM disponiveis pra benchmark do Agente 1.

    Combina:
      - providers_litellm.json (storage_litellm.load_providers)
      - keys.json legado (so gemini)

    Um modelo eh "executavel" se:
      - Tem api_key SET (cloud: gemini, anthropic, openai, ...)
      - OU eh local/ollama com base_url SET (LLM local nao precisa de auth)

    Retorna lista de dicts com:
        {provider, model, label, has_key, is_local, is_executable,
         in_usd_1M, out_usd_1M, is_active}
    """
    modelos = []
    try:
        import storage_litellm as _sl
        # IMPORTANTE: load_ativos() filtra apenas_precos=True - bate exatamente
        # com o que a UI "Provedores Configurados" mostra (4 hoje, 5 amanha etc).
        for p in _sl.load_ativos():
            prov = p.get("provedor", "?")
            modelo = p.get("modelo", "?")
            api_key = p.get("api_key", "")
            base_url = p.get("base_url", "")
            has_api_key = bool(api_key)
            has_base_url = bool(base_url)
            # Heuristica do nome do provedor (pra dispatch correto no providers.py)
            prov_lower = prov.lower()
            is_local_provider = (
                "custom" in prov_lower or
                "local" in prov_lower or
                "ollama" in prov_lower or
                "vllm" in prov_lower
            )
            # MAS um provider "custom/local" pode estar apontando pra cloud
            # (ex: OpenRouter). Pra UX correta no dropdown, distinguimos:
            #   is_local_real = roda em localhost mesmo
            is_local_real = is_local_provider and _is_localhost_base_url(base_url)
            # Executavel se: cloud com api_key OU local com base_url
            is_executable = has_api_key or (is_local_provider and has_base_url)
            custos = p.get("custos") or {}
            modelos.append({
                "provider": prov,
                "model": modelo,
                "base_url": base_url,
                # has_key mantido pra retrocompatibilidade; semantica = "executavel"
                "has_key": is_executable,
                # is_local reflete a REALIDADE (roda em localhost), nao so o nome.
                # Importante pra UI nao mostrar "gratis" pra OpenRouter pago.
                "is_local": is_local_real,
                "is_executable": is_executable,
                "is_active": bool(p.get("is_active", False)),
                "in_usd_1M": float(custos.get("in_usd_1M", 0.0)),
                "out_usd_1M": float(custos.get("out_usd_1M", 0.0)),
                "label": _formatar_label_modelo(prov, modelo, is_local_provider,
                                                 custos, base_url=base_url),
                "source": "providers_litellm",
            })
    except Exception:
        pass

    return modelos


def listar_pais_do_aluno(aluno_id: str) -> list[dict]:
    """Retorna lista de PAIs ja gerados para esse aluno (mais recente primeiro)."""
    if not PAIS_GERADOS_DIR.exists():
        return []
    encontrados = []
    for arq in sorted(PAIS_GERADOS_DIR.glob(f"{aluno_id}_PAI_*.json"), reverse=True):
        try:
            stat = arq.stat()
            with open(arq, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("meta", {})
            encontrados.append({
                "path": str(arq),
                "filename": arq.name,
                "schema_version": data.get("schema_version", "?"),
                "academic_year": meta.get("academic_year", "?"),
                "created_at": meta.get("created_at", "?"),
                "created_by": meta.get("created_by", "?"),
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "approval_status": meta.get("approval", {}).get("status", "pending"),
            })
        except Exception:
            pass
    return encontrados
