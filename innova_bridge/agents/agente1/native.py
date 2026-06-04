"""
innova_bridge/agents/agente1/native.py

Motor 1.0 DETERMINISTICO (zero LLM, R$ 0.00, ~1ms).

Porta exata de `benchmark_pai/py/profile_builder.py` do socio, com 2 ajustes:
  1. Reaproveita constantes/tipos de `.schemas` (single source of truth).
  2. Validacao opcional via `build_pai_native_validated()` que passa pelo PaiV1.

Tese central (reforcada na secao 4 da ESPEC_COMPLETA):
    O orcamento de adaptacao eh decidido pelo HUMANO na Parte 5.1.
    O agente apenas mapeia enum->inteiro e copia campos.

Resultado validado pelo socio: 12/12 decisoes estruturais identicas ao
golden Anthropic, custo R$ 0.00 vs R$ 0.73 da LLM completa.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .schemas import (
    ADAPTATION_BUDGET_DIMENSIONS,
    GLOBAL_RESTRICTIONS,
    INTENSITY_TO_INT,
    INT_TO_INTENSITY_PTBR,
    PaiV1,
)


# ============================================================================
# Constantes especificas do Native (labels PT-BR + chaves de barreiras)
# ============================================================================

# Labels PT-BR das 8 dimensoes - usado no template do summary_for_teacher_ptbr.
DIM_LABEL_PTBR: dict[str, str] = {
    "statement_fragmentation": "Fragmentação de enunciado",
    "language_simplification": "Simplificação de linguagem",
    "content_simplification": "Simplificação de conteúdo",
    "metacognitive_hints": "Dicas metacognitivas",
    "visual_support": "Suporte visual",
    "alternatives_reduction": "Redução de alternativas",
    "layout_intensity": "Layout amplo",
    "command_highlighting": "Destaque de comando",
}

# 29 chaves canonicas de barreiras em snake_case - keys do PAI.barriers.
ALL_BARRIER_KEYS: tuple[str, ...] = (
    # language_comprehension
    "long_statements",
    "command_confusion",
    "needs_rereading",
    "figurative_language_difficulty",
    "needs_command_highlight",
    "multiple_instructions_loss",
    # attention_executive
    "easy_distraction",
    "focus_decay",
    "impulsive_response",
    "slow_initiation",
    "answer_organization",
    "multi_step_loss",
    # working_memory
    "working_memory_overload",
    "instruction_forgetting",
    "improves_with_reconsultation",
    # writing_production
    "slow_writing",
    "motor_fatigue",
    "writing_spatial_disorganization",
    "time_pressure_loss",
    # visual_spatial
    "dense_table_loss",
    "alignment_errors",
    "spatial_disorganization_general",
    # math_specific
    "math_sign_confusion",
    "number_inversion",
    "number_order_swap",
    "calculation_layout_difficulty",
    "math_problem_interpretation_difficulty",
    "improves_with_visual_organization",
    "errors_by_disorganization_not_knowledge",
)

# Mapa: rotulo PT-BR (como vem no input) -> chave snake_case canonica.
# Fonte literal: benchmark_pai/py/profile_builder.py do socio.
BARRIER_LABEL_TO_KEY: dict[str, str] = {
    "Perde-se em enunciados longos": "long_statements",
    "Confunde o que é pedido pelo comando": "command_confusion",
    "Precisa reler várias vezes para entender": "needs_rereading",
    "Tem dificuldade com linguagem figurada": "figurative_language_difficulty",
    "Compreende melhor quando o comando está em destaque": "needs_command_highlight",
    "Perde-se quando há múltiplas instruções na mesma questão": "multiple_instructions_loss",
    "Distrai-se com facilidade": "easy_distraction",
    "Foco diminui ao longo da prova": "focus_decay",
    "Responde de forma impulsiva, sem reler": "impulsive_response",
    "Demora a começar": "slow_initiation",
    "Tem dificuldade em organizar a resposta": "answer_organization",
    "Perde-se em etapas de tarefas longas": "multi_step_loss",
    "Sobrecarrega memória de trabalho": "working_memory_overload",
    "Esquece instruções dadas há pouco": "instruction_forgetting",
    "Melhora quando pode reconsultar o enunciado": "improves_with_reconsultation",
    "Escreve devagar": "slow_writing",
    "Sente fadiga motora ao escrever": "motor_fatigue",
    "Desorganiza a escrita no espaço": "writing_spatial_disorganization",
    "Perde-se sob pressão de tempo": "time_pressure_loss",
    "Perde-se em tabelas e gráficos densos": "dense_table_loss",
    "Erra por desalinhamento": "alignment_errors",
    "Tem desorganização espacial generalizada": "spatial_disorganization_general",
    "Confunde sinais (+/−/×/÷)": "math_sign_confusion",
    "Inverte algarismos (e.g., 21 ↔ 12)": "number_inversion",
    "Troca a ordem dos números na conta": "number_order_swap",
    "Dificuldade em montar a conta no papel": "calculation_layout_difficulty",
    "Dificuldade em interpretar problemas matemáticos": "math_problem_interpretation_difficulty",
    "Melhora com organização visual (grades, espaçamento)": "improves_with_visual_organization",
    "Erra por desorganização (não por desconhecimento)": "errors_by_disorganization_not_knowledge",
}


# ============================================================================
# Helpers privados
# ============================================================================

def _split_list(text: str | None) -> list[str]:
    """Quebra texto livre por linha (\\n) e por ponto-e-virgula em itens limpos.

    Usado pra what_works/what_did_not_work onde a professora escreve em prosa.
    """
    if not text:
        return []
    parts = [
        p.strip().rstrip(".").strip()
        for chunk in text.split("\n")
        for p in chunk.split(";")
    ]
    return [p for p in parts if p]


def _iso_date(fill_date: str | None) -> str:
    """'15/05/2026' -> '2026-05-15'. Devolve o original se falhar."""
    if not fill_date:
        return ""
    try:
        d, m, y = fill_date.split("/")
        return f"{y}-{int(m):02d}-{int(d):02d}"
    except (ValueError, AttributeError):
        return fill_date


def _build_barriers(raw_barriers: dict) -> dict[str, Any]:
    """Constroi dict flat de booleans a partir das 6 listas PT-BR.

    Para cada barreira que aparece em qualquer lista do input, marca True.
    Todas as outras 29 chaves canonicas ficam False (presenca completa).
    other_observations_ptbr no fim (passthrough).
    """
    out: dict[str, Any] = {k: False for k in ALL_BARRIER_KEYS}
    for category, items in (raw_barriers or {}).items():
        if category == "other_observations" or not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, bool):
                continue
            # Aceita tanto chave canonica (snake_case) quanto rotulo PT-BR
            key = item if item in out else BARRIER_LABEL_TO_KEY.get(item)
            if key:
                out[key] = True
    out["other_observations_ptbr"] = raw_barriers.get("other_observations")
    return out


# ============================================================================
# API publica
# ============================================================================

def build_pai_native(payload: dict | Any) -> dict:
    """Motor Nativo 1.0: NEEIInput -> PAI v1.0 (dict).

    Args:
        payload: dict cru OU instancia NEEIInput (sera convertida).
                 Espera estrutura {questionnaire_response, laudo_summary, historical_data}.

    Returns:
        dict PAI v1.0 (NAO valida com Pydantic - use build_pai_native_validated
        se quiser garantia de schema). Custo R$ 0.00, latencia ~1ms.

    Regras honradas:
        - INTENSITY_TO_INT mapping (intense=3, moderate=2, light=1, not_authorized=0)
        - extra_time_authorized: bool top-level vira budget.extra_time_allowed
        - GLOBAL_RESTRICTIONS constante de 4 itens (nunca LLM gera)
        - low_confidence_areas = [] sempre (status real eh decidido pelo hybrid/llm)
        - missing_evidence inclui historico se historical_data is None
    """
    # Aceita NEEIInput tambem (caller pode ter validado antes)
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()

    qr = payload["questionnaire_response"]
    ident = qr["identification"]
    char = qr["characterization"]
    has_laudo = bool(char["has_clinical_report"])

    # --- 1) ADAPTATION_BUDGET (a peca-chave) ---
    # As autorizacoes vem como lista [{dimension, intensity}, ...]
    # Convertemos pra dict e mapeamos pra int.
    auth = {a["dimension"]: a["intensity"] for a in qr["adaptation_authorizations"]}
    budget: dict[str, Any] = {
        dim: INTENSITY_TO_INT.get(auth.get(dim, "not_authorized"), 0)
        for dim in ADAPTATION_BUDGET_DIMENSIONS
    }
    budget["extra_time_allowed"] = bool(qr.get("extra_time_authorized", False))

    # --- 2) SUPPORT_RESPONSE: lista -> dict ---
    support_response = {s["support_type"]: s["response"] for s in qr["support_response"]}

    # --- 3) SUMMARY_FOR_TEACHER_PTBR: template deterministico ---
    teacher_first = (ident.get("teacher_name") or "Professor(a)").split()[0]
    intense  = [DIM_LABEL_PTBR[d] for d in ADAPTATION_BUDGET_DIMENSIONS if budget[d] == 3]
    moderate = [DIM_LABEL_PTBR[d] for d in ADAPTATION_BUDGET_DIMENSIONS if budget[d] == 2]
    light    = [DIM_LABEL_PTBR[d] for d in ADAPTATION_BUDGET_DIMENSIONS if budget[d] == 1]

    summary_parts = [
        f"{teacher_first}, este PAI transcreve as autorizações marcadas no questionário "
        f"(Parte 5.1). O orçamento reflete exatamente o que foi autorizado — nenhuma "
        f"intensidade foi elevada acima do permitido."
    ]
    if intense:
        summary_parts.append(f"Intensidade Intensa em: {', '.join(intense)}.")
    if moderate:
        summary_parts.append(f"Intensidade Moderada em: {', '.join(moderate)}.")
    if light:
        summary_parts.append(f"Intensidade Leve em: {', '.join(light)}.")
    if not (intense or moderate or light):
        summary_parts.append("Nenhuma adaptação autorizada — perfil de autonomia plena.")
    summary_parts.append(
        "O Validador deve preservar SEMPRE o construto avaliado: simplificar a forma, "
        "nunca a matéria."
    )
    if qr.get("personality_notes"):
        summary_parts.append(f"Atenção à personalidade: {qr['personality_notes']}")

    # --- 4) EVIDENCE_PER_AUTHORIZATION: template por dimensao ativa ---
    evidence: dict[str, dict] = {}
    for dim in ADAPTATION_BUDGET_DIMENSIONS:
        value = budget[dim]
        if value == 0:
            continue
        evidence[dim] = {
            "intensity": value,
            "ptbr": (
                f"Intensidade {INT_TO_INTENSITY_PTBR[value]} autorizada na Parte 5.1 "
                "do questionário. Orçamento transcrito diretamente da autorização "
                "do(a) docente/AEE."
            ),
        }

    # --- 5) STUDENT_SPECIFIC_PTBR: restricoes + diretriz AEE ---
    student_specific: list[str] = []
    if qr.get("specific_restrictions"):
        student_specific.append(qr["specific_restrictions"])
    else:
        student_specific.append(
            "Não há restrições específicas marcadas pela professora (Parte 6.1)."
        )
    aee = qr.get("aee_observations") or {}
    if aee.get("specific_strategies"):
        student_specific.append(f"Diretriz do AEE: {aee['specific_strategies']}")

    # --- 6) AEE_RECOMMENDATIONS_PTBR: consolidacao ---
    aee_reco: list[str] = []
    if aee.get("specific_strategies"):
        aee_reco.append(f"Estratégias: {aee['specific_strategies']}")
    if aee.get("material_resources"):
        aee_reco.append(f"Recursos materiais: {aee['material_resources']}")
    if aee.get("other"):
        aee_reco.append(aee["other"])
    aee_reco_text = " ".join(aee_reco) if aee_reco else "Sem recomendações específicas do AEE."

    # --- 7) MISSING_EVIDENCE: gap analysis (basico) ---
    missing_evidence: list[str] = []
    if payload.get("historical_data") is None:
        missing_evidence.append(
            "Histórico de provas adaptadas anteriores ainda não está disponível "
            "(primeira execução). Após a primeira prova adaptada, recomenda-se marcar "
            "quais adaptações foram úteis para refinar o PAI."
        )

    # --- 8) MONTAGEM FINAL ---
    pai: dict[str, Any] = {
        "schema_version": "PAI_v1.0",
        "meta": {
            "student_id": ident["student_id"],
            "academic_year": _iso_date(ident.get("fill_date"))[:4] or "",
            "grade_level": ident["grade_level"],
            "age": ident["age"],
            "fill_date": ident.get("fill_date"),
            "teacher_name": ident.get("teacher_name"),
            "aee_professional_name": ident.get("aee_professional_name"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "ProfileBuilderNative_v1.0",
            "source_documents": [
                f"Questionario_NEEI_v2_resposta_"
                f"{ident['student_id']}_{_iso_date(ident.get('fill_date'))}"
            ],
            "is_neurotypical_path": not has_laudo,
            "has_clinical_report": has_laudo,
        },
        "narrative": {
            "student_summary_ptbr": char["student_summary"],
            "what_works_ptbr": _split_list(char.get("what_works")) or ["—"],
            "what_does_not_work_ptbr": _split_list(char.get("what_did_not_work")),
            "clinical_summary_operational_ptbr": (
                char.get("clinical_summary") if has_laudo else None
            ),
            "aee_recommendations_ptbr": aee_reco_text,
        },
        "capabilities": qr["capabilities"],
        "barriers": _build_barriers(qr.get("barriers", {})),
        "support_response": support_response,
        "adaptation_budget": budget,
        "hard_restrictions": {
            "global": list(GLOBAL_RESTRICTIONS),
            "student_specific_ptbr": student_specific,
            "personality_notes_ptbr": qr.get("personality_notes"),
        },
        "rationale": {
            "summary_for_teacher_ptbr": " ".join(summary_parts),
            "evidence_per_authorization": evidence,
            "low_confidence_areas": [],
            "missing_evidence": missing_evidence,
        },
    }
    return pai


def build_pai_native_validated(payload: dict | Any) -> dict:
    """Igual a build_pai_native, mas valida o resultado contra PaiV1 Pydantic.

    Levanta pydantic.ValidationError se o dict gerado nao for valido.
    Use quando voce quer garantia ao salvar/usar downstream.
    """
    pai_dict = build_pai_native(payload)
    PaiV1.model_validate(pai_dict)
    return pai_dict


__all__ = [
    "build_pai_native",
    "build_pai_native_validated",
    "DIM_LABEL_PTBR",
    "ALL_BARRIER_KEYS",
    "BARRIER_LABEL_TO_KEY",
]
