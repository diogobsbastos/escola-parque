"""
innova_bridge/agents/registry.py
CRUD de configuracoes de agentes (Pipeline Profile).

Cada agente tem:
  - id (snake_case unico)
  - agent_type: profile_builder | adapter | validator
  - label (humano)
  - llm_provider (anthropic | google | openai | qwen | ollama)
  - llm_model (ex: claude-3-5-sonnet, gemini-2.5-flash)
  - prompt_version (ex: v1.2)
  - is_default (somente 1 por agent_type)
  - extra_config (dict — temperatura, max_tokens, etc)
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

ARQUIVO_POOL = Path(__file__).resolve().parent.parent.parent / "agents_pool.json"


def _load() -> list[dict]:
    if not ARQUIVO_POOL.exists():
        return _seed_inicial()
    try:
        with open(ARQUIVO_POOL, "r", encoding="utf-8") as f:
            return json.load(f).get("agents", [])
    except Exception:
        return []


def _save(agents: list[dict]) -> None:
    with open(ARQUIVO_POOL, "w", encoding="utf-8") as f:
        json.dump({"agents": agents}, f, indent=2, ensure_ascii=False)


def _seed_inicial() -> list[dict]:
    """Cria pool inicial com 3 agentes default v1.0 (Claude)."""
    agents = [
        {
            "id": "profile_builder_v1_0_claude",
            "agent_type": "profile_builder",
            "label": "Agente 1 v1.0 (Claude Sonnet 4.6)",
            "llm_provider": "anthropic",
            "llm_model": "claude-sonnet-4-6",
            "prompt_version": "v1.2",
            "is_default": True,
            "extra_config": {"temperature": 0.3, "max_tokens": 8000},
        },
        {
            "id": "adapter_v1_0_claude",
            "agent_type": "adapter",
            "label": "Agente 2 v1.0 (placeholder)",
            "llm_provider": "anthropic",
            "llm_model": "claude-sonnet-4-6",
            "prompt_version": "v1.0",
            "is_default": True,
            "extra_config": {"temperature": 0.4, "max_tokens": 12000},
        },
        {
            "id": "validator_v1_0_claude",
            "agent_type": "validator",
            "label": "Agente 3 v1.0 (placeholder)",
            "llm_provider": "anthropic",
            "llm_model": "claude-haiku-4-5-20251001",
            "prompt_version": "v1.0",
            "is_default": True,
            "extra_config": {"temperature": 0.2, "max_tokens": 4000},
        },
    ]
    _save(agents)
    return agents


def listar(agent_type: Optional[str] = None) -> list[dict]:
    """Lista agentes. Filtra por type se especificado."""
    agents = _load()
    if agent_type:
        return [a for a in agents if a.get("agent_type") == agent_type]
    return agents


def get_default(agent_type: str) -> Optional[dict]:
    """Retorna o agente DEFAULT (is_default=True) de cada tipo."""
    for a in _load():
        if a.get("agent_type") == agent_type and a.get("is_default"):
            return a
    return None


def buscar(agent_id: str) -> Optional[dict]:
    for a in _load():
        if a.get("id") == agent_id:
            return a
    return None


def set_default(agent_id: str) -> tuple[bool, str]:
    """Marca um agente como default e desmarca os outros do mesmo tipo."""
    agents = _load()
    alvo = next((a for a in agents if a.get("id") == agent_id), None)
    if not alvo:
        return False, "Agente nao encontrado."
    agent_type = alvo.get("agent_type")
    for a in agents:
        if a.get("agent_type") == agent_type:
            a["is_default"] = (a["id"] == agent_id)
    _save(agents)
    return True, f"Agente '{alvo['label']}' agora e o default de {agent_type}."


def adicionar(agent_dict: dict) -> tuple[bool, str]:
    agents = _load()
    if any(a.get("id") == agent_dict.get("id") for a in agents):
        return False, "Ja existe agente com este id."
    agents.append(agent_dict)
    _save(agents)
    return True, "Agente cadastrado."


def remover(agent_id: str) -> tuple[bool, str]:
    agents = _load()
    alvo = next((a for a in agents if a.get("id") == agent_id), None)
    if not alvo:
        return False, "Agente nao encontrado."
    if alvo.get("is_default"):
        return False, "Nao remova o agente DEFAULT. Defina outro como default primeiro."
    agents = [a for a in agents if a.get("id") != agent_id]
    _save(agents)
    return True, "Agente removido."
