"""
innova_bridge/agents/agente1/persistence.py

Persistencia local de PAIs + governanca (status rule + supersede).

Secao 7 da ESPEC:
  - Status do PAI: `active` se rationale.low_confidence_areas vazio;
                   senao `needs_review`.
  - 1 PAI vigente por (aluno, familia): ao gravar um novo, SUPERSEDE TODOS os
    anteriores cujo status in {active, needs_review} (regra 4 da secao 12 -
    eh um bug corrigido pegar apenas `active`).
  - Versao = ultima + 1.
  - meta.created_by: distingue origem ("ProfileBuilderNative_v1.0",
    "ProfileBuilderHibrido_v2.0", "ProfileBuilderAgent_<versao>").

Storage: arquivos JSON em innova_bridge/formularios/pais_gerados/.
   Nome: {aluno_id}_PAI_v1_0_v{N}_{YYYYMMDD_HHMMSS}.json

(O Supabase BR fica pra F3.5 conforme decisao 4.3 = Caminho A.)
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent.parent
PAIS_GERADOS_DIR = BASE_DIR / "formularios" / "pais_gerados"


# ============================================================================
# Status rule
# ============================================================================

def aplicar_status_rule(pai: dict) -> str:
    """Decide o status do PAI baseado em low_confidence_areas.

    Regra 3 da secao 12 da ESPEC:
        low_confidence_areas vazio -> 'active'
        senao                       -> 'needs_review'

    NAO inventar baixa confianca quando questionario eh coerente
    (criterio espelhado no THIN_SYSTEM).
    """
    low = pai.get("rationale", {}).get("low_confidence_areas") or []
    return "active" if not low else "needs_review"


def carimbar_status(pai: dict, status: Optional[str] = None) -> dict:
    """Aplica status_rule e carimba em meta.approval.status.

    Args:
        pai: dict PAI v1.0.
        status: forca um status especifico (None = usa aplicar_status_rule).

    Returns:
        novo dict com meta.approval.status definido (NAO muta o original).
    """
    status_efetivo = status or aplicar_status_rule(pai)
    new_approval = dict(pai.get("meta", {}).get("approval") or {})
    new_approval["status"] = status_efetivo
    return {
        **pai,
        "meta": {
            **pai["meta"],
            "approval": new_approval,
        },
    }


# ============================================================================
# Naming + parsing de arquivo
# ============================================================================

# Regex pra reconhecer arquivos PAI gerados: {aluno_id}_PAI_v1_0_v{N}_{TIMESTAMP}.json
_PAI_FILENAME_RE = re.compile(
    r"^(?P<aluno>.+?)_PAI_v1_0_v(?P<versao>\d+)_(?P<ts>\d{8}_\d{6})\.json$"
)


def _parse_pai_filename(arq: Path) -> Optional[dict]:
    """Extrai aluno_id, versao, timestamp do nome de arquivo. None se nao bater."""
    m = _PAI_FILENAME_RE.match(arq.name)
    if not m:
        return None
    return {
        "path": str(arq),
        "filename": arq.name,
        "aluno_id": m.group("aluno"),
        "versao": int(m.group("versao")),
        "timestamp": m.group("ts"),
    }


def _nome_arquivo_pai(aluno_id: str, versao: int, ts: Optional[str] = None) -> str:
    """{aluno_id}_PAI_v1_0_v{N}_{YYYYMMDD_HHMMSS}.json"""
    ts_efetivo = ts or datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{aluno_id}_PAI_v1_0_v{versao}_{ts_efetivo}.json"


# ============================================================================
# Listagens
# ============================================================================

def _garantir_pasta() -> None:
    PAIS_GERADOS_DIR.mkdir(parents=True, exist_ok=True)


def listar_pais_do_aluno(aluno_id: str) -> list[dict]:
    """Lista TODOS os PAIs (vigentes + superseded) do aluno.

    Returns:
        Lista de dicts com {path, filename, aluno_id, versao, timestamp,
        status, created_by, has_clinical_report}, ordenada por versao desc.
    """
    if not PAIS_GERADOS_DIR.exists():
        return []
    resultado: list[dict] = []
    for arq in PAIS_GERADOS_DIR.glob(f"{aluno_id}_PAI_v1_0_v*.json"):
        meta = _parse_pai_filename(arq)
        if not meta:
            continue
        # Le dados pra enriquecer
        try:
            with open(arq, "r", encoding="utf-8") as f:
                pai = json.load(f)
        except Exception:
            continue
        pai_meta = pai.get("meta", {}) if isinstance(pai, dict) else {}
        approval = pai_meta.get("approval") or {}
        resultado.append({
            **meta,
            "status": approval.get("status", "?"),
            "created_by": pai_meta.get("created_by", "?"),
            "has_clinical_report": pai_meta.get("has_clinical_report"),
            "academic_year": pai_meta.get("academic_year", "?"),
        })
    resultado.sort(key=lambda d: d["versao"], reverse=True)
    return resultado


def listar_pais_vigentes(aluno_id: str) -> list[dict]:
    """Lista APENAS os PAIs com status active ou needs_review."""
    return [
        p for p in listar_pais_do_aluno(aluno_id)
        if p["status"] in ("active", "needs_review")
    ]


def carregar_pai_mais_recente(aluno_id: str) -> Optional[dict]:
    """Retorna o PAI vigente mais recente do aluno (dict completo). None se vazio."""
    vigentes = listar_pais_vigentes(aluno_id)
    if not vigentes:
        # Fallback: tenta qualquer PAI mais recente, mesmo superseded
        todos = listar_pais_do_aluno(aluno_id)
        if not todos:
            return None
        path = todos[0]["path"]
    else:
        path = vigentes[0]["path"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def proxima_versao(aluno_id: str) -> int:
    """Retorna a proxima versao incremental disponivel para o aluno."""
    todos = listar_pais_do_aluno(aluno_id)
    if not todos:
        return 1
    return max(p["versao"] for p in todos) + 1


# ============================================================================
# Supersede
# ============================================================================

def supersede_anteriores(aluno_id: str) -> list[str]:
    """Marca como 'superseded' TODOS os PAIs do aluno cujo status estiver
    em {active, needs_review}.

    Regra 4 da secao 12 (BUG corrigido no Innova: NAO pega so 'active',
    senao acumula 2 PAIs vigentes e confunde o Agente 2).

    Returns:
        Lista de paths dos arquivos modificados.
    """
    modificados: list[str] = []
    for p in listar_pais_vigentes(aluno_id):
        path = Path(p["path"])
        try:
            with open(path, "r", encoding="utf-8") as f:
                pai = json.load(f)
        except Exception:
            continue
        if not isinstance(pai, dict):
            continue
        meta = pai.setdefault("meta", {})
        approval = meta.setdefault("approval", {})
        approval["status"] = "superseded"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(pai, f, ensure_ascii=False, indent=2)
            modificados.append(str(path))
        except Exception:
            pass
    return modificados


# ============================================================================
# API publica: salvar_pai (com supersede + status_rule + versionamento)
# ============================================================================

def salvar_pai(
    pai: dict,
    *,
    aluno_id_override: Optional[str] = None,
    fazer_supersede: bool = True,
) -> tuple[Path, dict]:
    """Persiste PAI v1.0 com governanca completa.

    Pipeline:
        1. Aplica status_rule (low_confidence_areas vazio -> active)
        2. Faz supersede dos PAIs anteriores vigentes (active + needs_review)
        3. Calcula proxima versao
        4. Grava em pais_gerados/{aluno_id}_PAI_v1_0_v{N}_{TIMESTAMP}.json

    Args:
        pai: dict PAI v1.0 (geralmente vindo de build_pai_native ou run_hybrid).
        aluno_id_override: forca um aluno_id (None = pega de pai.meta.student_id).
        fazer_supersede: se False, pula o supersede (uso em testes).

    Returns:
        (path_salvo, metadata) onde metadata = {
            "aluno_id": str,
            "versao": int,
            "status": "active" | "needs_review",
            "timestamp": "YYYYMMDD_HHMMSS",
            "superseded_files": list[str],
            "filename": str,
        }
    """
    _garantir_pasta()

    aluno_id = aluno_id_override or pai.get("meta", {}).get("student_id")
    if not aluno_id:
        raise ValueError("salvar_pai: aluno_id ausente (forneca via override ou meta.student_id)")

    # 1) Status rule
    pai_com_status = carimbar_status(pai)
    status_efetivo = pai_com_status["meta"]["approval"]["status"]

    # 2) Supersede dos vigentes anteriores
    superseded_files: list[str] = []
    if fazer_supersede:
        superseded_files = supersede_anteriores(aluno_id)

    # 3) Versionamento
    versao = proxima_versao(aluno_id)

    # 4) Gravacao
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = _nome_arquivo_pai(aluno_id, versao, ts)
    destino = PAIS_GERADOS_DIR / nome

    with open(destino, "w", encoding="utf-8") as f:
        json.dump(pai_com_status, f, ensure_ascii=False, indent=2)

    metadata = {
        "aluno_id": aluno_id,
        "versao": versao,
        "status": status_efetivo,
        "timestamp": ts,
        "filename": nome,
        "superseded_files": superseded_files,
    }
    return destino, metadata


__all__ = [
    "salvar_pai",
    "aplicar_status_rule",
    "carimbar_status",
    "supersede_anteriores",
    "listar_pais_do_aluno",
    "listar_pais_vigentes",
    "carregar_pai_mais_recente",
    "proxima_versao",
    "PAIS_GERADOS_DIR",
]
