"""
innova_bridge/models/canonical.py
Schema CANONICO UNICO de questionario pedagogico.
Todos os adapters (Google Forms, Form Proprio, PDF OCR) convergem aqui.
field_ids sao ESTAVEIS — nunca mudam mesmo se texto da pergunta mudar.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

from .enums import CapabilityLevel, SupportResponse, AuthorizationIntensity


class CanonicalMeta(BaseModel):
    """Metadados de quem/quando/qual versao do questionario."""
    student_id: str
    school_id: Optional[str] = None
    academic_year: str
    grade_level: str
    age: Optional[int] = None
    fill_date: str
    teacher_name: str
    aee_professional_name: Optional[str] = None
    schema_version: str  # ex: "NEEI_v2.0"


class CanonicalCharacterization(BaseModel):
    """Parte 1 do NEEI — narrativas de texto livre."""
    student_summary: str
    has_clinical_report: bool
    clinical_summary: Optional[str] = None
    current_supports: str
    what_works: str
    what_did_not_work: Optional[str] = None


class CanonicalCapabilities(BaseModel):
    """Parte 2 — campos dinamicos por field_id estavel.

    Usa dict pra permitir field_ids opcionais entre formularios.
    Exemplo: {"capability_2a_01": "with_support", "capability_2c_05": "cannot"}
    """
    items: dict[str, CapabilityLevel] = Field(default_factory=dict)


class CanonicalBarriers(BaseModel):
    """Parte 3 — barreiras checkbox (true/false) + texto livre opcional."""
    flags: dict[str, bool] = Field(default_factory=dict)
    other_observations: Optional[str] = None


class CanonicalSupportResponse(BaseModel):
    """Parte 4 — resposta a suportes."""
    items: dict[str, SupportResponse] = Field(default_factory=dict)


class CanonicalAuthorizations(BaseModel):
    """Parte 5 — autorizacoes de adaptacao."""
    intensities: dict[str, AuthorizationIntensity] = Field(default_factory=dict)
    extra_time_allowed: bool = False


class CanonicalRestrictions(BaseModel):
    """Parte 6 — restricoes."""
    specific_restrictions: Optional[str] = None
    personality_notes: Optional[str] = None


class CanonicalAeeObservations(BaseModel):
    """Parte 7 — observacoes do AEE."""
    specific_strategies: Optional[str] = None
    material_resources: Optional[str] = None
    other: Optional[str] = None


class CanonicalQuestionnaire(BaseModel):
    """O CANONICO COMPLETO — input do Agente 1.

    Independente de qual formulario gerou (Google Forms, Form Proprio, PDF),
    o Agente 1 sempre recebe este formato.
    """
    meta: CanonicalMeta
    characterization: CanonicalCharacterization
    capabilities: CanonicalCapabilities
    barriers: CanonicalBarriers
    support_response: CanonicalSupportResponse
    authorizations: CanonicalAuthorizations
    restrictions: CanonicalRestrictions
    aee_observations: CanonicalAeeObservations
