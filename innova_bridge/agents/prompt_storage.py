"""
innova_bridge/agents/prompt_storage.py

Storage de prompts customizaveis por (agente, modelo).

Princípio de design - BLINDAGEM TOTAL:
  1. Default fallback eh SEMPRE o THIN_SYSTEM constante atual.
  2. Se o JSON nao existir, nada quebra - tudo continua usando o default.
  3. Se um modelo nao tiver prompt customizado, usa o default do agente.
  4. Se o agente nao tiver prompt customizado, usa a constante hardcoded.
  5. Errors silenciosos pra nao quebrar a UI - cai pro default.

Estrutura do JSON em disco (agent_prompts.json na raiz do projeto):
    {
      "agente1": {
        "_default_": "...",                       # opcional, sobrescreve THIN_SYSTEM
        "gemini/gemini-2.5-flash": "...",         # opcional, pra este modelo especifico
        "meta-llama/llama-3.3-70b-instruct": "...",
        "claude-sonnet-4-6": "..."
      },
      "agente2": { ... }    # futuro: Adaptador (validator)
    }

API publica:
    get_agent_prompt(agente_id, modelo) -> str
    save_agent_prompt(agente_id, modelo, prompt_text) -> bool
    list_custom_prompts(agente_id) -> dict[modelo -> prompt]
    delete_agent_prompt(agente_id, modelo) -> bool
    get_default_constant(agente_id) -> str    # retorna a constante hardcoded
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


# Caminho do arquivo de storage - raiz do projeto
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ARQUIVO_PROMPTS = ROOT_DIR / "agent_prompts.json"

# Pasta de backups versionados do agent_prompts.json
BACKUPS_DIR = ROOT_DIR / "backups_prompts"


# ============================================================================
# Constantes hardcoded - SEMPRE fallback final
# ============================================================================

def _get_thin_system_constant() -> str:
    """Carrega THIN_SYSTEM do thin_prompt.py - eh a constante atual da spec
    do socio. NAO ALTERAR essa constante - eh a fonte da verdade do default.
    """
    try:
        from innova_bridge.agents.agente1.thin_prompt import THIN_SYSTEM
        return THIN_SYSTEM
    except Exception:
        # Caminho mais seguro: se nao conseguir importar, retorna string vazia
        # (que vai fazer o hybrid usar seu proprio fallback interno)
        return ""


# Mapeia agent_id -> funcao que retorna a constante default daquele agente
_AGENT_DEFAULT_PROVIDERS = {
    "agente1": _get_thin_system_constant,
    # "agente2": _get_adapter_system_constant,  # futuro
}


# ============================================================================
# I/O do JSON
# ============================================================================

def _load_storage() -> dict:
    """Le o arquivo agent_prompts.json. Retorna dict vazio se nao existir
    ou estiver corrompido (defensivo - mesma estrategia do storage_litellm).
    """
    if not ARQUIVO_PROMPTS.exists():
        return {}
    try:
        # Le em bytes pra defender contra null bytes (mesmo bug Windows
        # que vimos no providers_litellm.json)
        with open(ARQUIVO_PROMPTS, "rb") as f:
            raw = f.read()
        if b"\x00" in raw:
            raw = raw.replace(b"\x00", b"")
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return {}
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_storage(data: dict) -> bool:
    """Persiste o dict de prompts em disco. Retorna True/False."""
    try:
        # Garante que o diretorio existe
        ARQUIVO_PROMPTS.parent.mkdir(parents=True, exist_ok=True)
        with open(ARQUIVO_PROMPTS, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


# ============================================================================
# API publica
# ============================================================================

def get_default_constant(agente_id: str) -> str:
    """Retorna a constante hardcoded do agente (ex: THIN_SYSTEM pra agente1).

    Eh o que a UI deveria mostrar como "fonte da verdade" quando o usuario
    clica em "Copiar do Default" ou "Resetar". NAO inclui customizacoes.
    """
    provider = _AGENT_DEFAULT_PROVIDERS.get(agente_id)
    if provider is None:
        return ""
    try:
        return provider() or ""
    except Exception:
        return ""


def get_agent_prompt(agente_id: str, modelo: Optional[str] = None) -> str:
    """Retorna o prompt efetivo pra (agente, modelo).

    Suporta AMBOS os formatos (string legado e dict novo).

    Ordem de prioridade:
      1. Custom por modelo: storage[agente_id][modelo].system_prompt (ou string direto)
      2. Custom default do agente: storage[agente_id]["_default_"]
      3. Constante hardcoded (THIN_SYSTEM, etc)

    Returns:
        String do prompt a usar. NUNCA vazio.
    """
    cfg = get_agent_config(agente_id, modelo)
    custom = cfg.get("system_prompt")
    if isinstance(custom, str) and custom.strip():
        return custom
    return get_default_constant(agente_id)


def save_agent_prompt(agente_id: str, modelo: str, prompt_text: str) -> bool:
    """Salva um prompt customizado pra (agente, modelo).

    Args:
        agente_id: ex "agente1"
        modelo: ex "gemini/gemini-2.5-flash" OR "_default_" pra default do agente
        prompt_text: o texto do prompt. Se vazio/None, remove a customizacao.

    Returns:
        True se salvou, False se falhou.

    Nota: preserva hiperparametros (temperature, max_tokens, etc) se ja existirem
    pro alvo - so atualiza o system_prompt. Pra atualizar tudo junto, usar
    save_agent_config.
    """
    storage = _load_storage()
    if agente_id not in storage or not isinstance(storage[agente_id], dict):
        storage[agente_id] = {}

    if prompt_text is None or not str(prompt_text).strip():
        # Remove a customizacao COMPLETA (prompt + hiperparams)
        storage[agente_id].pop(modelo, None)
        if not storage[agente_id]:
            storage.pop(agente_id, None)
    else:
        # Preserva hiperparams existentes se houver
        existing = storage[agente_id].get(modelo)
        if isinstance(existing, dict):
            existing["system_prompt"] = str(prompt_text)
            storage[agente_id][modelo] = existing
        else:
            # Formato legado (string direto) ou novo - salva como dict
            storage[agente_id][modelo] = {"system_prompt": str(prompt_text)}

    return _save_storage(storage)


# ============================================================================
# NOVO: API de config completa (prompt + hiperparametros)
# ============================================================================

def _normalize_target_to_dict(target) -> dict:
    """Aceita formato legado (string) e novo (dict). Retorna sempre dict."""
    if isinstance(target, str):
        return {"system_prompt": target} if target.strip() else {}
    if isinstance(target, dict):
        return target
    return {}


def get_agent_config(agente_id: str, modelo = None) -> dict:
    """Retorna a CONFIG efetiva pra (agente, modelo).

    Ordem de prioridade:
      1. Custom por modelo
      2. Custom default do agente
      3. Vazio (sistema usa fallbacks)

    Returns:
        dict com chaves opcionais (cada uma None significa "usa default sistema"):
        system_prompt, temperature, max_tokens, force_json.
    """
    storage = _load_storage()
    agente_config = storage.get(agente_id) or {}

    if modelo:
        target = _normalize_target_to_dict(agente_config.get(modelo))
        if target:
            return target

    target_default = _normalize_target_to_dict(agente_config.get("_default_"))
    if target_default:
        return target_default

    return {}


def save_agent_config(agente_id: str, modelo: str, config: dict) -> bool:
    """Salva config completa (prompt + hiperparametros).

    Args:
        agente_id: ex "agente1"
        modelo: ex "gemini/gemini-2.5-flash" OR "_default_"
        config: dict {system_prompt?, temperature?, max_tokens?, force_json?}.
                Chaves None ou invalidas sao removidas.
                Config inteiro vazio = remove a customizacao.
    """
    if not isinstance(config, dict):
        return False

    sanitized = {}
    for k in ("system_prompt", "temperature", "max_tokens", "force_json", "seed", "num_ctx"):
        v = config.get(k)
        if v is None:
            continue
        if k == "system_prompt":
            if not isinstance(v, str) or not v.strip():
                continue
        elif k == "temperature":
            try:
                v = float(v)
                if v < 0.0 or v > 2.0:
                    continue
            except Exception:
                continue
        elif k == "max_tokens":
            try:
                v = int(v)
                if v < 256 or v > 32768:
                    continue
            except Exception:
                continue
        elif k == "force_json":
            if not isinstance(v, bool):
                continue
        elif k == "seed":
            # Aceita int >= 0 ate 2^32 - 1 (range padrao OpenAI/Ollama).
            # 42 eh o classico mas qualquer int do range serve - o que importa
            # eh ser FIXO entre runs (reproducibilidade).
            try:
                v = int(v)
                if v < 0 or v > 4_294_967_295:
                    continue
            except Exception:
                continue
        elif k == "num_ctx":
            # Janela de contexto do Ollama (so aplicado a provedores LOCAIS).
            # Range pratico: 256 a 131072. Maior = mais VRAM.
            try:
                v = int(v)
                if v < 256 or v > 131072:
                    continue
            except Exception:
                continue
        sanitized[k] = v

    storage = _load_storage()
    if agente_id not in storage or not isinstance(storage[agente_id], dict):
        storage[agente_id] = {}

    if not sanitized:
        storage[agente_id].pop(modelo, None)
        if not storage[agente_id]:
            storage.pop(agente_id, None)
    else:
        storage[agente_id][modelo] = sanitized

    # AUTO-BACKUP: cria snapshot antes de gravar (versionamento de prompts).
    # Falha silenciosa - se backup falhar, save continua normal.
    try:
        criar_backup(motivo=f"save_{modelo.replace('/', '_').replace(':', '_')}")
    except Exception:
        pass

    return _save_storage(storage)


def list_custom_configs(agente_id: str) -> dict:
    """Lista todas as configs customizadas (dict completo, retrocompat)."""
    storage = _load_storage()
    config = storage.get(agente_id) or {}
    return {k: _normalize_target_to_dict(v) for k, v in config.items() if v}


def list_custom_prompts(agente_id: str) -> dict:
    """Lista APENAS os system_prompts customizados (compatibilidade UI)."""
    configs = list_custom_configs(agente_id)
    result = {}
    for modelo, cfg in configs.items():
        prompt = cfg.get("system_prompt", "") if isinstance(cfg, dict) else cfg
        if isinstance(prompt, str) and prompt.strip():
            result[modelo] = prompt
    return result


def delete_agent_prompt(agente_id: str, modelo: str) -> bool:
    """Remove customizacao completa (prompt + hiperparametros) de (agente, modelo)."""
    storage = _load_storage()
    if agente_id not in storage or not isinstance(storage[agente_id], dict):
        return True
    storage[agente_id].pop(modelo, None)
    if not storage[agente_id]:
        storage.pop(agente_id, None)
    return _save_storage(storage)


def list_known_agents() -> list:
    """Lista os agentes conhecidos pelo sistema."""
    return [
        {
            "id": "agente1",
            "nome": "Agente 1 - Profile Builder",
            "descricao": "Gera o PAI (Plano de Adaptacao Individual) a partir do questionario NEEI. "
                          "Hybrid: native produz decisoes, LLM fina polishe prosa.",
        },
    ]


# ============================================================================
# SISTEMA DE BACKUP VERSIONADO
# ============================================================================
#
# Cada vez que save_agent_config eh chamado, um snapshot do agent_prompts.json
# eh criado em backups_prompts/. O usuario pode:
#   - Listar todos os backups (listar_backups)
#   - Inspecionar o conteudo de um backup (ler_backup)
#   - Restaurar apenas UM (agente, modelo) de um backup (restaurar_modelo_do_backup)
#   - Restaurar o arquivo INTEIRO de um backup (restaurar_backup_completo)
#   - Excluir backups antigos (excluir_backup)
#
# Nome do arquivo: agent_prompts_YYYYMMDD_HHMMSS.json.bak
# ============================================================================

def _ensure_backups_dir() -> Path:
    """Garante que a pasta de backups existe."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUPS_DIR


def criar_backup(motivo: str = "auto") -> Optional[str]:
    """Cria snapshot timestamped do agent_prompts.json.

    Args:
        motivo: "auto" (default), "manual", "pre_restore", "save_<modelo>", etc.
                Aparece no nome do arquivo apenas como contexto.

    Returns:
        Nome do arquivo criado (ex: "agent_prompts_20260531_184500.json.bak"),
        ou None se o agent_prompts.json nao existir ou copia falhar.

    Defensivo - NUNCA quebra a chamada principal mesmo se backup falhar.
    """
    if not ARQUIVO_PROMPTS.exists():
        return None
    try:
        import shutil
        from datetime import datetime
        _ensure_backups_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = f"agent_prompts_{ts}.json.bak"
        destino = BACKUPS_DIR / nome
        # Se ja existe (clicou Salvar 2x no mesmo segundo), nao sobrescreve
        if destino.exists():
            return destino.name  # Idempotente
        shutil.copy2(ARQUIVO_PROMPTS, destino)
        return nome
    except Exception:
        return None


def listar_backups() -> list:
    """Lista todos os backups disponiveis, mais recentes primeiro.

    Returns:
        Lista de dicts:
            {
                "filename": str,
                "size_bytes": int,
                "mtime": float (timestamp Unix),
                "num_agentes": int,
                "num_modelos": int (total em todos os agentes),
                "modelos_lista": list[str] (nomes dos modelos no backup),
            }
    """
    _ensure_backups_dir()
    out = []
    for f in sorted(BACKUPS_DIR.glob("*.json.bak"),
                    key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = f.stat()
            raw = f.read_bytes()
            if b"\x00" in raw:
                raw = raw.replace(b"\x00", b"")
            content = json.loads(raw.decode("utf-8", errors="replace"))
            agentes = list(content.keys()) if isinstance(content, dict) else []
            modelos_lista = []
            num_modelos = 0
            if isinstance(content, dict):
                for ag_id, ag_cfg in content.items():
                    if isinstance(ag_cfg, dict):
                        for modelo_nome in ag_cfg.keys():
                            num_modelos += 1
                            modelos_lista.append(f"{ag_id}::{modelo_nome}")
            out.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
                "num_agentes": len(agentes),
                "num_modelos": num_modelos,
                "modelos_lista": modelos_lista,
            })
        except Exception:
            # Backup corrompido - inclui mesmo assim mas com info minima
            try:
                stat = f.stat()
                out.append({
                    "filename": f.name,
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                    "num_agentes": 0,
                    "num_modelos": 0,
                    "modelos_lista": [],
                    "corrupted": True,
                })
            except Exception:
                continue
    return out


def ler_backup(filename: str) -> Optional[dict]:
    """Le o conteudo completo de UM backup especifico.

    Returns:
        dict do backup, ou None se nao encontrar/falhar parse.
    """
    if not filename or "/" in filename or "\\" in filename:
        # Defesa basica contra path traversal
        return None
    _ensure_backups_dir()
    path = BACKUPS_DIR / filename
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
        if b"\x00" in raw:
            raw = raw.replace(b"\x00", b"")
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None


def restaurar_modelo_do_backup(filename: str, agente_id: str,
                                  modelo: str) -> bool:
    """Restaura a config de UM (agente, modelo) especifico vindo de um backup.

    NAO mexe nos outros modelos do agent_prompts.json atual.
    Cria backup automatico do estado atual antes (pre_restore) pra
    permitir desfazer.

    Returns:
        True se restaurou, False se backup nao tem essa (agente, modelo).
    """
    backup_content = ler_backup(filename)
    if not isinstance(backup_content, dict):
        return False
    target_agente = backup_content.get(agente_id)
    if not isinstance(target_agente, dict):
        return False
    target_modelo = target_agente.get(modelo)
    if target_modelo is None:
        return False

    # Backup do estado atual antes de modificar
    criar_backup(motivo="pre_restore_modelo")

    # Carrega atual, sobrescreve so esse (agente, modelo), salva
    atual = _load_storage()
    if agente_id not in atual or not isinstance(atual[agente_id], dict):
        atual[agente_id] = {}
    atual[agente_id][modelo] = target_modelo
    return _save_storage(atual)


def restaurar_backup_completo(filename: str) -> bool:
    """Restaura o agent_prompts.json INTEIRO de um backup (overwrite).

    Antes de sobrescrever, cria backup automatico do estado atual
    (pre_restore_completo) pra permitir desfazer.

    Returns:
        True se restaurou, False se backup invalido.
    """
    backup_content = ler_backup(filename)
    if not isinstance(backup_content, dict):
        return False
    # Backup do estado atual antes de sobrescrever
    criar_backup(motivo="pre_restore_completo")
    return _save_storage(backup_content)


def excluir_backup(filename: str) -> bool:
    """Apaga um arquivo de backup.

    Returns:
        True se apagou (ou se ja nao existia), False se falhou.
    """
    if not filename or "/" in filename or "\\" in filename:
        return False
    _ensure_backups_dir()
    path = BACKUPS_DIR / filename
    if not path.exists():
        return True
    try:
        path.unlink()
        return True
    except Exception:
        return False


__all__ = [
    "get_agent_prompt",
    "save_agent_prompt",
    "list_custom_prompts",
    "delete_agent_prompt",
    "list_known_agents",
    "get_default_constant",
    "ARQUIVO_PROMPTS",
    "BACKUPS_DIR",
    "get_agent_config",
    "save_agent_config",
    "list_custom_configs",
    # Sistema de backup
    "criar_backup",
    "listar_backups",
    "ler_backup",
    "restaurar_modelo_do_backup",
    "restaurar_backup_completo",
    "excluir_backup",
]
