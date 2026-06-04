"""
innova_bridge/models/pai.py — Schema do PAI v1.0 (output do Agente 1).
Fiel ao Agente1_ConstrutorDePerfil_v1.2.md.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from .enums import PaiStatus


class PaiApproval(BaseModel):
    status: str = "pending"  # pending | approved | needs_revision | superseded
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    revision_notes_ptbr: Optional[str] = None


class PaiMeta(BaseModel):
    student_id: str
    academic_year: str
    grade_level: str
    age: Optional[int] = None
    created_at: datetime
    created_by: str  # ex: "ProfileBuilderAgent_v1.2"
    source_documents: list[str] = Field(default_factory=list)
    is_neurotypical_path: bool
    has_clinical_report: bool
    approval: PaiApproval = Field(default_factory=PaiApproval)


class PaiNarrative(BaseModel):
    student_summary_ptbr: str
    what_works_ptbr: list[str]
    what_does_not_work_ptbr: list[str] = Field(default_factory=list)
    clinical_summary_operational_ptbr: Optional[str] = None
    aee_recommendations_ptbr: Optional[str] = None


class PaiAdaptationBudget(BaseModel):
    """8 dimensoes 0-3 + tempo extra booleano."""
    statement_fragmentation: int = 0
    language_simplification: int = 0
    content_simplification: int = 0
    metacognitive_hints: int = 0
    visual_support: int = 0
    alternatives_reduction: int = 0
    layout_intensity: int = 0
    command_highlighting: int = 0
    extra_time_allowed: bool = False


class PaiHardRestrictions(BaseModel):
    global_: list[str] = Field(
        default_factory=lambda: [
            "Nao alterar o construto avaliado pela prova",
            "Nao revelar a resposta no enunciado adaptado",
            "Nao simplificar abaixo do nivel minimo aceitavel da serie",
            "Preservar a numeracao e estrutura macro da prova original",
        ],
        alias="global",
    )
    student_specific_ptbr: list[str] = Field(default_factory=list)
    personality_notes_ptbr: Optional[str] = None

    class Config:
        populate_by_name = True


class PaiRationale(BaseModel):
    summary_for_teacher_ptbr: str
    evidence_per_authorization: dict[str, str] = Field(default_factory=dict)
    low_confidence_areas: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class PAI(BaseModel):
    """Plano de Adaptacao Individual v1.0 — saida do Agente 1."""
    schema_version: str = "PAI_v1.0"
    meta: PaiMeta
    narrative: PaiNarrative
    capabilities: dict[str, str] = Field(default_factory=dict)
    barriers: dict = Field(default_factory=dict)
    support_response: dict[str, str] = Field(default_factory=dict)
    adaptation_budget: PaiAdaptationBudget
    hard_restrictions: PaiHardRestrictions
    rationale: PaiRationale
