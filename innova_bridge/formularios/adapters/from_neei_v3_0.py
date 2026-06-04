"""
innova_bridge/formularios/adapters/from_neei_v3_0.py

Adapter NEEI v3.0 - produz o formato NESTED esperado pelo Molde Novo
(router.gerar_pai do agente1/).

Suporta 2 modos:

  MODO 1 - FIXTURE (operacional JA, sem CSV)
      carregar_fixture("U1_intenso" | "U2_neurotipico" | "U1_reconstruido")
      Le um dos 3 fixtures de tests/fixtures/ direto pra payload.

  MODO 2 - CSV (stub - aguarda neei_v3_0.json da task #44)
      csv_to_questionnaire_response(csv_path, linha=0)
      Por enquanto levanta NotImplementedError com instrucao clara.

Output dos 2 modos: dict {questionnaire_response, laudo_summary, historical_data}
                   pronto pra router.gerar_pai().

Persistencia:
    innova_bridge/formularios/responses_v3/{aluno_id}_NEEI_v3_0_{source}_{ts}.json
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


# ============================================================================
# Paths
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent.parent.parent
RESPONSES_V3_DIR = BASE_DIR / "formularios" / "responses_v3"

# Fixtures vivem em <projeto>/tests/fixtures/ (pasta da raiz, ja existente)
_PROJECT_ROOT = BASE_DIR.parent
FIXTURES_DIR = _PROJECT_ROOT / "tests" / "fixtures"

# Fixtures cadastrados manualmente - id -> filename + label amigavel
FIXTURES_DISPONIVEIS: dict[str, dict[str, str]] = {
    "U1_intenso": {
        "filename": "INPUT_INTENSO_formulario.json",
        "label": "U1 - perfil INTENSO (com laudo TEA s2, autorizacoes Intensa/Moderada)",
        "is_neurotypical": False,
    },
    "U2_neurotipico": {
        "filename": "INPUT_U2_formulario.json",
        "label": "U2 - perfil NEUROTIPICO (sem laudo, autorizacoes Leve)",
        "is_neurotypical": True,
    },
    "U1_reconstruido": {
        "filename": "INPUT_U1_reconstruido.json",
        "label": "U1 - reconstruido a partir do GOLDEN (alvo de benchmark)",
        "is_neurotypical": False,
    },
}


# ============================================================================
# Helpers
# ============================================================================

def _garantir_pasta_responses() -> None:
    RESPONSES_V3_DIR.mkdir(parents=True, exist_ok=True)


def _sanitizar_aluno_id(aluno_id: str) -> str:
    """Remove caracteres problematicos pra nome de arquivo."""
    proibidos = {"/", "\\", ":", "*", "?", '"', "<", ">", "|", " "}
    return "".join("_" if c in proibidos else c for c in aluno_id) or "UNKNOWN"


# ============================================================================
# MODO 1 - FIXTURES (operacional)
# ============================================================================

def listar_fixtures_disponiveis() -> list[dict]:
    """Lista os fixtures pre-cadastrados pra UI mostrar como opcoes.

    Returns:
        Lista de dicts com {id, label, filename, is_neurotypical, available}.
        `available=False` se o arquivo nao existe no disco.
    """
    resultado = []
    for fid, meta in FIXTURES_DISPONIVEIS.items():
        arq = FIXTURES_DIR / meta["filename"]
        resultado.append({
            "id": fid,
            "label": meta["label"],
            "filename": meta["filename"],
            "is_neurotypical": meta["is_neurotypical"],
            "available": arq.exists(),
            "path": str(arq) if arq.exists() else None,
        })
    return resultado


def carregar_fixture(fixture_id: str) -> dict:
    """Carrega um dos fixtures pre-cadastrados.

    Args:
        fixture_id: "U1_intenso" | "U2_neurotipico" | "U1_reconstruido"

    Returns:
        dict ja no formato esperado pelo agente1.router.gerar_pai():
        {questionnaire_response, laudo_summary, historical_data}.

    Raises:
        ValueError: fixture_id desconhecido.
        FileNotFoundError: arquivo nao existe (pasta tests/fixtures/ vazia).
    """
    if fixture_id not in FIXTURES_DISPONIVEIS:
        raise ValueError(
            f"Fixture {fixture_id!r} nao existe. "
            f"Disponiveis: {list(FIXTURES_DISPONIVEIS)}"
        )
    arquivo = FIXTURES_DIR / FIXTURES_DISPONIVEIS[fixture_id]["filename"]
    if not arquivo.exists():
        raise FileNotFoundError(
            f"Fixture nao encontrado em disco: {arquivo}. "
            "Verifique que tests/fixtures/ contem o arquivo."
        )
    with open(arquivo, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# MODO 2 - CSV do Google Forms (NEEI v2.0/v3.0) -> canonical
# ============================================================================
#
# Adapter FIEL: a camada ESTRUTURAL (capacidades 2.x, suportes 4.1, autorizacoes
# 5.1, tempo 5.2, flag de laudo) mapeia 1:1 pros enums canonicos; a PROSA (1.1,
# 1.4, 1.5, personalidade, barreiras, AEE) passa LITERAL - a palavra real da
# professora (nada de reescrita no dado de entrada). Validado reproduzindo a
# camada estrutural de INPUT_INTENSO_formulario.json a partir do CSV real.

import csv as _csv
import io as _io
import re as _re

_CAP_MAP = {"realiza sem suporte": "without_support", "realiza com apoio": "with_support", "não realiza": "cannot"}
_SUP_MAP = {"sim, sozinho": "yes_alone", "sim, com apoio": "yes_with_support", "não": "no", "não testado": "not_tested"}
_INT_MAP = {"não autorizada": "not_authorized", "não autorizar": "not_authorized", "leve": "light", "moderada": "moderate", "intensa": "intense"}

_READING = [("lê textos curtos", "short_texts"), ("ideia principal", "main_idea"), ("linguagem direta e literal", "literal_language"), ("linguagem figurada", "figurative_language"), ("localiza o comando", "command_localization"), ("3 frases ou mais", "long_statements"), ("múltiplos comandos", "multi_command_statements")]
_WRITING = [("escreve palavras simples", "simple_words"), ("frases bem organizadas", "organized_sentences"), ("espaço delimitado", "spatial_organization"), ("escrita legível", "legibility_endurance"), ("textos curtos com clareza", "short_texts_clarity"), ("correções e revisões", "self_revision")]
_MATH = [("reconhece os números e suas posições", "place_value"), ("com números pequenos", "small_number_operations"), ("com números grandes", "large_number_operations"), ("interpreta problemas matemáticos escritos", "word_problem_interpretation"), ("múltiplas etapas", "multi_step_problems"), ("frações simples", "simple_fractions"), ("tabelas e gráficos", "table_graph_reading"), ("conceitos não concretos", "abstract_concepts")]
_EXEC = [("atenção em uma tarefa por mais de 20", "sustained_attention_20min"), ("distrações ambientais", "distraction_resistance"), ("sem precisar de comando externo", "task_initiation"), ("persiste em tarefa difícil", "task_persistence"), ("sequência de passos", "step_organization"), ("memória de trabalho", "working_memory_load"), ("muda de estratégia", "strategy_flexibility"), ("monitora os próprios erros", "self_monitoring")]
_SUPPORT = [("exemplo resolvido", "worked_example_before"), ("fragmentado em passos", "fragmented_statement"), ("vocabulário do enunciado é simplificado", "simplified_vocabulary"), ("números do problema são reduzidos", "smaller_numbers"), ("recebe tempo adicional", "extra_time"), ("ambiente silencioso ou separado", "isolated_environment"), ("quadriculado ou linhas-guia", "grid_lines"), ("há suporte visual", "visual_support"), ("dica metacognitiva", "metacognitive_hint"), ("número de alternativas", "fewer_alternatives")]
_AUTH = [("fragmentação de enunciado", "statement_fragmentation"), ("simplificação de linguagem", "language_simplification"), ("simplificação de conteúdo", "content_simplification"), ("dicas metacognitivas", "metacognitive_hints"), ("inclusão de suporte visual", "visual_support"), ("redução do número de alternativas", "alternatives_reduction"), ("ajuste de layout", "layout_intensity"), ("destaque do comando", "command_highlighting")]
_BARRIERS = [("3.a", "language_comprehension"), ("3.b", "attention_executive"), ("3.c", "working_memory"), ("3.d", "writing_production"), ("3.e", "visual_spatial"), ("3.f", "math_specific")]

_NONE_TOKENS = {"não há restrições", "não há", "nenhuma", "nenhum", "não", "n/a", "-", "não há laudo", ""}


def _norm_txt(s):
    return (s or "").strip()

def _low(s):
    return _norm_txt(s).lower()

def _none_if_empty(s):
    t = _norm_txt(s)
    return None if _low(t) in _NONE_TOKENS else t

def _split_barrier(s):
    t = _norm_txt(s)
    return [p.strip() for p in t.split(";") if p.strip()] if t else []

def _normalize_grade(s):
    sl = _low(s)
    m = _re.search(r"(\d+)\s*[ªa]?\s*série", sl)
    if m:
        return f"{m.group(1)}_serie_em"
    m = _re.search(r"(\d+)\s*[ºo]?\s*ano", sl)
    if m:
        return f"{m.group(1)}_ano_ef"
    return _norm_txt(s)

def _col(row, needle):
    nl = needle.lower()
    for k, v in row.items():
        if k and nl in k.lower():
            return v
    return None

def _col_prefixo(row, prefixo, label):
    """Acha a coluna cujo header contem o prefixo da secao E o label do item."""
    pl, ll = prefixo.lower(), label.lower()
    for k, v in row.items():
        if k and pl in k.lower() and ll in k.lower():
            return v
    return None

def _ler_linhas(source) -> list:
    """Le CSV de path, bytes, file-like (st.file_uploader) ou texto cru."""
    if hasattr(source, "read"):
        raw = source.read()
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).decode("utf-8-sig")
        f = _io.StringIO(raw)
    elif isinstance(source, (bytes, bytearray)):
        f = _io.StringIO(bytes(source).decode("utf-8-sig"))
    elif isinstance(source, str) and "\n" in source:
        f = _io.StringIO(source)
    else:
        f = open(source, encoding="utf-8-sig")
    try:
        return list(_csv.DictReader(f))
    finally:
        try:
            f.close()
        except Exception:
            pass


def listar_respostas_csv(source) -> list:
    """Resumo das respostas no CSV (pra UI escolher qual linha rodar)."""
    out = []
    for i, row in enumerate(_ler_linhas(source)):
        ident_id = _norm_txt(_col(row, "ID anonimizado")) or _norm_txt(_col(row, "Nome ou ID"))
        out.append({
            "linha": i,
            "student_id": ident_id or f"linha {i}",
            "age": _norm_txt(_col(row, "Idade")),
            "grade_level": _normalize_grade(_col(row, "Ano / série")),
            "teacher_name": _norm_txt(_col(row, "Professor(a) responsável")),
            "has_laudo": "existe" in _low(_col(row, "1.2 Existe laudo")),
        })
    return out


def csv_to_questionnaire_response(source, linha: int = 0) -> dict:
    """Converte UMA linha do CSV do Google Forms (NEEI v2.0/v3.0) no canonical
    {questionnaire_response, laudo_summary, historical_data} pronto pro
    router.gerar_pai() / run_hybrid().

    Args:
        source: path do CSV, bytes, file-like (st.file_uploader) ou texto cru.
        linha:  indice da resposta (0 = primeira linha de dados).

    FIEL: estrutura -> enums canonicos; prosa -> texto LITERAL da professora.
    """
    rows = _ler_linhas(source)
    if not rows:
        raise ValueError("CSV vazio ou sem linhas de resposta.")
    if linha < 0 or linha >= len(rows):
        raise IndexError(f"linha {linha} fora do intervalo (0..{len(rows) - 1}).")
    row = rows[linha]

    ident = {
        "student_id": _norm_txt(_col(row, "ID anonimizado")) or _norm_txt(_col(row, "Nome ou ID")),
        "age": int(_re.sub(r"\D", "", _norm_txt(_col(row, "Idade"))) or 0),
        "grade_level": _normalize_grade(_col(row, "Ano / série")),
        "fill_date": _norm_txt(_col(row, "Data de preenchimento")),
        "teacher_name": _norm_txt(_col(row, "Professor(a) responsável")),
        "aee_professional_name": _none_if_empty(_col(row, "Profissional do AEE")),
    }

    laudo_raw = _low(_col(row, "1.2 Existe laudo"))
    has_report = ("existe" in laudo_raw) or laudo_raw.startswith("sim")
    char = {
        "student_summary": _norm_txt(_col(row, "1.1 Resumo")),
        "has_clinical_report": has_report,
        "clinical_summary": _none_if_empty(_col(row, "1.2.1")) if has_report else None,
        "current_supports": _norm_txt(_col(row, "1.3 Quais suportes")),
        "what_works": _norm_txt(_col(row, "1.4 O que FUNCIONA")),
        "what_did_not_work": _none_if_empty(_col(row, "1.5 O que")),
    }

    def _cap(label2field, prefixo):
        return {field: _CAP_MAP.get(_low(_col_prefixo(row, prefixo, label)), None)
                for label, field in label2field}

    capabilities = {
        "reading_comprehension": _cap(_READING, "2.A"),
        "writing_production": _cap(_WRITING, "2.B"),
        "mathematical_reasoning": _cap(_MATH, "2.C"),
        "executive_functions": _cap(_EXEC, "2.D"),
    }

    barriers = {field: _split_barrier(_col(row, pref)) for pref, field in _BARRIERS}
    barriers["other_observations"] = _none_if_empty(_col(row, "3.G"))

    support_response = [
        {"support_type": st, "response": _SUP_MAP.get(_low(_col_prefixo(row, "4.1", label)), "not_tested")}
        for label, st in _SUPPORT
    ]

    authorizations = [
        {"dimension": dim, "intensity": _INT_MAP.get(_low(_col_prefixo(row, "5.1", label)), "not_authorized")}
        for label, dim in _AUTH
    ]

    extra_time = "sim" in _low(_col(row, "5.2 Tempo adicional"))
    filled_jointly = bool(ident["aee_professional_name"])

    qr = {
        "identification": ident,
        "characterization": char,
        "capabilities": capabilities,
        "barriers": barriers,
        "support_response": support_response,
        "adaptation_authorizations": authorizations,
        "extra_time_authorized": extra_time,
        "specific_restrictions": _none_if_empty(_col(row, "6.1 Há restrições")),
        "personality_notes": _none_if_empty(_col(row, "6.2 Há aspectos")),
        "aee_observations": {
            "specific_strategies": _none_if_empty(_col(row, "7.1 Estratégias")),
            "material_resources": _none_if_empty(_col(row, "7.2 Recursos")),
            "other": _none_if_empty(_col(row, "7.3 Outras")),
        },
        "fill_metadata": {
            "filled_jointly": filled_jointly,
            "justification": (
                f"Questionário preenchido em conjunto pela professora regente "
                f"({ident['teacher_name']}) e pelo AEE ({ident['aee_professional_name']})."
            ) if filled_jointly else None,
        },
    }
    return {
        "questionnaire_response": qr,
        "laudo_summary": char["clinical_summary"],
        "historical_data": None,
    }


# ============================================================================
# Persistencia (responses_v3/)
# ============================================================================

def salvar_response_v3(
    aluno_id: str,
    response_dict: dict,
    source_label: str = "fixture",
) -> Path:
    """Grava o response NEEI v3.0 em innova_bridge/formularios/responses_v3/.

    Args:
        aluno_id: id do aluno (sera sanitizado pra nome de arquivo).
        response_dict: payload completo {questionnaire_response, ...}.
        source_label: como veio ("fixture", "csv", "manual"). So pra audit trail.

    Returns:
        Path do arquivo salvo.
    """
    _garantir_pasta_responses()
    aluno_safe = _sanitizar_aluno_id(aluno_id)
    # Sanitiza source_label tambem - caso a UI passe a label completa do
    # fixture (que pode ter /, \, parens, espacos), o Windows quebra ao montar
    # o Path. Truncamos em 40 chars pra nao gerar nome de arquivo gigante.
    source_safe = _sanitizar_aluno_id(source_label or "fixture")[:40] or "fixture"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"{aluno_safe}_NEEI_v3_0_{source_safe}_{ts}.json"
    destino = RESPONSES_V3_DIR / nome

    # Carimba metadado de origem sem mexer no payload original
    data_to_save = dict(response_dict)
    meta_pers = dict(data_to_save.get("_meta_persistencia") or {})
    meta_pers.update({
        "aluno_id": aluno_id,
        "source": source_label,
        "saved_at": datetime.now().isoformat(),
        "filename": nome,
    })
    data_to_save["_meta_persistencia"] = meta_pers

    with open(destino, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    return destino


def listar_responses_v3_do_aluno(aluno_id: str) -> list[dict]:
    """Lista responses v3 ja gravadas pra este aluno (mais recente primeiro)."""
    if not RESPONSES_V3_DIR.exists():
        return []
    aluno_safe = _sanitizar_aluno_id(aluno_id)
    encontrados: list[dict] = []
    for arq in sorted(RESPONSES_V3_DIR.glob(f"{aluno_safe}_NEEI_v3_0_*.json"), reverse=True):
        try:
            stat = arq.stat()
            with open(arq, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        meta_pers = data.get("_meta_persistencia") or {}
        qr = data.get("questionnaire_response") or {}
        ident = qr.get("identification") or {}
        char = qr.get("characterization") or {}
        encontrados.append({
            "path": str(arq),
            "filename": arq.name,
            "aluno_id": aluno_id,
            "source": meta_pers.get("source", "?"),
            "saved_at": meta_pers.get("saved_at", "?"),
            "size_kb": round(stat.st_size / 1024, 1),
            "student_id_in_response": ident.get("student_id", "?"),
            "has_clinical_report": bool(char.get("has_clinical_report", False)),
            "fill_date": ident.get("fill_date", "?"),
        })
    return encontrados


def carregar_response_v3(path: str) -> dict:
    """Le um response v3 do disco. Levanta se nao existir/invalido."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Remove o metadado de persistencia antes de devolver - ele NAO faz parte
    # do contrato esperado por agente1.router.gerar_pai()
        data = {k: v for k, v in data.items() if k != "_meta_persistencia"}
    return data


__all__ = [
    "carregar_fixture",
    "listar_fixtures_disponiveis",
    "csv_to_questionnaire_response",
    "listar_respostas_csv",
    "salvar_response_v3",
    "listar_responses_v3_do_aluno",
    "carregar_response_v3",
    "FIXTURES_DISPONIVEIS",
    "FIXTURES_DIR",
    "RESPONSES_V3_DIR",
]
