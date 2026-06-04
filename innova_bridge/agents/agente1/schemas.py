"""
innova_bridge/agents/agente1/schemas.py

Schemas Pydantic do Agente 1 (Construtor de PAI) - MOLDE NOVO.
Espelha LITERALMENTE as secoes 2 (entrada NEEI) e 3 (saida PAI v1.0)
do documento `ESPEC_COMPLETA_Agente1_Python.md`.

Por que existe se ja temos `innova_bridge/models/pai.py` e canonical.py?
Porque o MOLDE NOVO usa o formato nested do socio (innova-v2/react)
em vez do nosso `CanonicalQuestionnaire` (dict-flat). Os dois moldes
convivem - cada um com seu schema.

Validacao: testar carregando os 3 fixtures de `tests/fixtures/`:
  - INPUT_U2_formulario.json     (perfil neurotipico)
  - INPUT_INTENSO_formulario.json (perfil intenso, U1)
  - GOLDEN_OUTPUT_U1.json         (PAI de referencia Anthropic)

Principios honrados:
  - As 8 dimensoes do adaptation_budget tem NOMES FIXOS (Literal types)
  - intensity / capability level / support response usam Literal restrito
  - Pydantic V2 syntax (model_validate, model_dump)
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# Enums tipados (literais) - source of truth para os 4 vocabularios fechados
# ============================================================================

# Capacidades (Parte 2) - 4 niveis
CapabilityLevel = Literal[
    "without_support",
    "with_support",
    "cannot",
    "not_observed",
]

# Resposta a suporte (Parte 4.1) - 4 niveis
SupportResponseLevel = Literal[
    "yes_alone",
    "yes_with_support",
    "no",
    "not_tested",
]

# Intensidade autorizada (Parte 5.1) - 4 niveis
AuthorizationIntensity = Literal[
    "not_authorized",
    "light",
    "moderate",
    "intense",
]

# Status do PAI (governança)
PaiStatus = Literal["pending", "active", "needs_review", "approved", "rejected", "superseded"]


# ============================================================================
# ENTRADA NEEI (questionnaire_response) - secao 2 da spec
# ============================================================================

class NEEIIdentification(BaseModel):
    """Parte 0 - identificacao do estudante e contexto do preenchimento."""
    model_config = ConfigDict(extra="allow")

    student_id: str
    age: int = Field(ge=0)
    grade_level: str
    fill_date: str  # "DD/MM/AAAA"
    teacher_name: str
    aee_professional_name: Optional[str] = None


class NEEICharacterization(BaseModel):
    """Parte 1 - caracterizacao textual do estudante."""
    model_config = ConfigDict(extra="allow")

    student_summary: str
    has_clinical_report: bool
    clinical_summary: Optional[str] = None
    current_supports: str
    what_works: str
    what_did_not_work: Optional[str] = None


class NEEICapabilityReadingComprehension(BaseModel):
    """Parte 2.A - 7 itens de leitura/compreensao."""
    model_config = ConfigDict(extra="allow")

    short_texts: CapabilityLevel
    main_idea: CapabilityLevel
    literal_language: CapabilityLevel
    figurative_language: CapabilityLevel
    command_localization: CapabilityLevel
    long_statements: CapabilityLevel
    multi_command_statements: CapabilityLevel


class NEEICapabilityWritingProduction(BaseModel):
    """Parte 2.B - 6 itens de producao escrita."""
    model_config = ConfigDict(extra="allow")

    simple_words: CapabilityLevel
    organized_sentences: CapabilityLevel
    spatial_organization: CapabilityLevel
    legibility_endurance: CapabilityLevel
    short_texts_clarity: CapabilityLevel
    self_revision: CapabilityLevel


class NEEICapabilityMathematicalReasoning(BaseModel):
    """Parte 2.C - 8 itens de raciocinio matematico."""
    model_config = ConfigDict(extra="allow")

    place_value: CapabilityLevel
    small_number_operations: CapabilityLevel
    large_number_operations: CapabilityLevel
    word_problem_interpretation: CapabilityLevel
    multi_step_problems: CapabilityLevel
    simple_fractions: CapabilityLevel
    table_graph_reading: CapabilityLevel
    abstract_concepts: CapabilityLevel


class NEEICapabilityExecutiveFunctions(BaseModel):
    """Parte 2.D - 8 itens de funcoes executivas."""
    model_config = ConfigDict(extra="allow")

    sustained_attention_20min: CapabilityLevel
    distraction_resistance: CapabilityLevel
    task_initiation: CapabilityLevel
    task_persistence: CapabilityLevel
    step_organization: CapabilityLevel
    working_memory_load: CapabilityLevel
    strategy_flexibility: CapabilityLevel
    self_monitoring: CapabilityLevel


class NEEICapabilities(BaseModel):
    """Parte 2 - 4 grupos de capacidades."""
    model_config = ConfigDict(extra="allow")

    reading_comprehension: NEEICapabilityReadingComprehension
    writing_production: NEEICapabilityWritingProduction
    mathematical_reasoning: NEEICapabilityMathematicalReasoning
    executive_functions: NEEICapabilityExecutiveFunctions


class NEEIBarriers(BaseModel):
    """Parte 3 - 6 listas de barreiras em PT-BR + texto livre."""
    model_config = ConfigDict(extra="allow")

    language_comprehension: list[str] = Field(default_factory=list)
    attention_executive: list[str] = Field(default_factory=list)
    working_memory: list[str] = Field(default_factory=list)
    writing_production: list[str] = Field(default_factory=list)
    visual_spatial: list[str] = Field(default_factory=list)
    math_specific: list[str] = Field(default_factory=list)
    other_observations: Optional[str] = None


class NEEISupportResponseItem(BaseModel):
    """Parte 4.1 - resposta a um tipo de suporte."""
    model_config = ConfigDict(extra="allow")

    support_type: str
    response: SupportResponseLevel


class NEEIAdaptationAuthorization(BaseModel):
    """Parte 5.1 - autorizacao por dimensao (A DECISAO)."""
    model_config = ConfigDict(extra="allow")

    dimension: Literal[
        "statement_fragmentation",
        "language_simplification",
        "content_simplification",
        "metacognitive_hints",
        "visual_support",
        "alternatives_reduction",
        "layout_intensity",
        "command_highlighting",
    ]
    intensity: AuthorizationIntensity


class NEEIAeeObservations(BaseModel):
    """Parte 7 - observacoes do AEE."""
    model_config = ConfigDict(extra="allow")

    specific_strategies: Optional[str] = None
    material_resources: Optional[str] = None
    other: Optional[str] = None


class NEEIFillMetadata(BaseModel):
    """Metadado de preenchimento do formulario."""
    model_config = ConfigDict(extra="allow")

    filled_jointly: bool
    justification: Optional[str] = None


class NEEIQuestionnaireResponse(BaseModel):
    """A resposta completa do questionario NEEI v2/v3."""
    model_config = ConfigDict(extra="allow")

    identification: NEEIIdentification
    characterization: NEEICharacterization
    capabilities: NEEICapabilities
    barriers: NEEIBarriers
    support_response: list[NEEISupportResponseItem]
    adaptation_authorizations: list[NEEIAdaptationAuthorization]
    extra_time_authorized: bool
    specific_restrictions: Optional[str] = None
    personality_notes: Optional[str] = None
    aee_observations: NEEIAeeObservations
    fill_metadata: NEEIFillMetadata


class NEEIInput(BaseModel):
    """
    Objeto raiz que o Agente 1 consome.
    Fonte: secao 2 do ESPEC_COMPLETA_Agente1_Python.md.
    """
    model_config = ConfigDict(extra="allow")

    questionnaire_response: NEEIQuestionnaireResponse
    laudo_summary: Optional[str] = None
    historical_data: Optional[dict] = None  # Aberto pra evoluir no F3.5+


# ============================================================================
# SAIDA PAI v1.0 - secao 3 da spec
# ============================================================================

class PaiApproval(BaseModel):
    """Subbloco de aprovacao humana."""
    model_config = ConfigDict(extra="allow")

    status: PaiStatus = "pending"
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None  # ISO timestamp
    revision_notes_ptbr: Optional[str] = None


class PaiMeta(BaseModel):
    """Identificacao + autoria + aprovacao do PAI."""
    model_config = ConfigDict(extra="allow")

    student_id: str
    academic_year: str
    grade_level: str
    age: Optional[int] = None
    fill_date: Optional[str] = None
    teacher_name: Optional[str] = None
    aee_professional_name: Optional[str] = None
    created_at: str  # ISO timestamp
    created_by: str  # ex: "ProfileBuilderNative_v1.0" | "ProfileBuilderHibrido_v2.0"
    source_documents: list[str] = Field(default_factory=list)
    is_neurotypical_path: bool
    has_clinical_report: bool
    approval: Optional[PaiApproval] = None


class PaiNarrative(BaseModel):
    """Resumos qualitativos PT-BR. Arrays onde a spec exige arrays."""
    model_config = ConfigDict(extra="allow")

    student_summary_ptbr: str
    what_works_ptbr: list[str] = Field(min_length=1)  # spec: >=1
    what_does_not_work_ptbr: list[str] = Field(default_factory=list)
    clinical_summary_operational_ptbr: Optional[str] = None
    aee_recommendations_ptbr: Optional[str] = None


class PaiAdaptationBudget(BaseModel):
    """
    8 dimensoes 0-3 + tempo extra booleano.
    NOMES FIXOS - o Agente 2 indexa por eles. Nunca renomear.
    """
    model_config = ConfigDict(extra="forbid")  # bloqueia campos desconhecidos!

    statement_fragmentation: int = Field(ge=0, le=3)
    language_simplification: int = Field(ge=0, le=3)
    content_simplification: int = Field(ge=0, le=3)
    metacognitive_hints: int = Field(ge=0, le=3)
    visual_support: int = Field(ge=0, le=3)
    alternatives_reduction: int = Field(ge=0, le=3)
    layout_intensity: int = Field(ge=0, le=3)
    command_highlighting: int = Field(ge=0, le=3)
    extra_time_allowed: bool


class PaiHardRestrictions(BaseModel):
    """Restricoes globais (constante) + especificas + notas de personalidade.

    `global` eh palavra reservada do Python - usamos `global_` no Pydantic
    com alias="global" pra ler/escrever o JSON com a chave certa.
    `populate_by_name=True` permite ambos os nomes na entrada.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    # Spec define 4 constantes - validamos exatamente 4 strings
    global_: list[str] = Field(
        default_factory=list,
        alias="global",
        min_length=4,
        max_length=4,
    )
    student_specific_ptbr: list[str] = Field(default_factory=list)
    personality_notes_ptbr: Optional[str] = None


class PaiEvidencePerAuthorization(BaseModel):
    """Subitem de rationale.evidence_per_authorization.

    Spec: dict[dimensao] = {intensity:int, ptbr:str}
    """
    model_config = ConfigDict(extra="allow")

    intensity: int = Field(ge=0, le=3)
    ptbr: str


class PaiRationale(BaseModel):
    """Justificativa pra professora ler em 5 min."""
    model_config = ConfigDict(extra="allow")

    summary_for_teacher_ptbr: str
    evidence_per_authorization: dict[str, PaiEvidencePerAuthorization] = Field(default_factory=dict)
    low_confidence_areas: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class PaiV1(BaseModel):
    """
    Plano de Adaptacao Individual v1.0 - SAIDA do Agente 1.

    Esse schema vale pra QUALQUER engine (native, hybrid, llm).
    A unica diferenca entre engines eh quem preenche `rationale` -
    nativo usa template, hibrido pede a uma LLM fina, llm pede tudo.
    """
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["PAI_v1.0"] = "PAI_v1.0"
    meta: PaiMeta
    narrative: PaiNarrative
    capabilities: dict  # passthrough do input (4 grupos nested)
    barriers: dict  # flat dict de bools + other_observations_ptbr
    support_response: dict[str, SupportResponseLevel]  # lista -> dict
    adaptation_budget: PaiAdaptationBudget
    hard_restrictions: PaiHardRestrictions
    rationale: PaiRationale


# ============================================================================
# Helpers publicos pra outros modulos do agente1/
# ============================================================================

# Lista canonica das 8 dimensoes do adaptation_budget (ordem da spec).
# Usado pelo native.py pra iterar e pelo Agente 2 pra indexar.
ADAPTATION_BUDGET_DIMENSIONS: tuple[str, ...] = (
    "statement_fragmentation",
    "language_simplification",
    "content_simplification",
    "metacognitive_hints",
    "visual_support",
    "alternatives_reduction",
    "layout_intensity",
    "command_highlighting",
)


# Mapa intensity (string) -> int (escala 0-3 do budget).
# E mapa inverso pra labels PT-BR (debug/log).
INTENSITY_TO_INT: dict[str, int] = {
    "not_authorized": 0,
    "light": 1,
    "moderate": 2,
    "intense": 3,
}

INT_TO_INTENSITY_PTBR: dict[int, str] = {
    0: "Nao autorizada",
    1: "Leve",
    2: "Moderada",
    3: "Intensa",
}


# Restricoes globais hardcoded (constantes - nunca LLM gera).
GLOBAL_RESTRICTIONS: tuple[str, ...] = (
    "do_not_change_evaluated_construct",
    "do_not_provide_answers_in_hints",
    "do_not_invent_content_not_in_original",
    "preserve_question_numbering",
)


__all__ = [
    # Entradas
    "NEEIInput",
    "NEEIQuestionnaireResponse",
    "NEEIIdentification",
    "NEEICharacterization",
    "NEEICapabilities",
    "NEEICapabilityReadingComprehension",
    "NEEICapabilityWritingProduction",
    "NEEICapabilityMathematicalReasoning",
    "NEEICapabilityExecutiveFunctions",
    "NEEIBarriers",
    "NEEISupportResponseItem",
    "NEEIAdaptationAuthorization",
    "NEEIAeeObservations",
    "NEEIFillMetadata",
    # Saidas
    "PaiV1",
    "PaiMeta",
    "PaiApproval",
    "PaiNarrative",
    "PaiAdaptationBudget",
    "PaiHardRestrictions",
    "PaiEvidencePerAuthorization",
    "PaiRationale",
    # Tipos
    "CapabilityLevel",
    "SupportResponseLevel",
    "AuthorizationIntensity",
    "PaiStatus",
    # Constantes
    "ADAPTATION_BUDGET_DIMENSIONS",
    "INTENSITY_TO_INT",
    "INT_TO_INTENSITY_PTBR",
    "GLOBAL_RESTRICTIONS",
]
