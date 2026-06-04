"""
innova_bridge/models/enums.py
Os 12 enums oficiais do Supabase Innova V2, tipados em Python.
Fonte: SUPABASE_SCHEMA.md (handoff).
"""
from __future__ import annotations
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    COORDINATOR = "coordinator"
    TEACHER = "teacher"
    AEE = "aee"


class DisciplineFamilyType(str, Enum):
    LOGICAL_MATHEMATICAL = "logical_mathematical"
    TEXTUAL_INTERPRETIVE = "textual_interpretive"


class PaiStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    NEEDS_REVIEW = "needs_review"
    SUPERSEDED = "superseded"


class AdaptedExamStatus(str, Enum):
    GENERATING = "generating"
    PENDING_VALIDATION = "pending_validation"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class ValidatorVerdict(str, Enum):
    PASS = "PASS"
    PASS_WITH_NOTES = "PASS_WITH_NOTES"
    PATCH = "PATCH"
    FULL_RERUN = "FULL_RERUN"


class AgentName(str, Enum):
    PROFILE_BUILDER = "profile_builder"
    ADAPTER = "adapter"
    VALIDATOR = "validator"


class AgentRunStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class PaiReviewAction(str, Enum):
    APPROVED = "approved"
    REQUESTED_ADJUSTMENT = "requested_adjustment"


class QuestionnaireBlock(str, Enum):
    EXATAS = "exatas"
    HUMANAS = "humanas"


class QuestionnaireSectionStatus(str, Enum):
    DRAFT = "draft"
    AEE_READY = "aee_ready"
    LOCKED = "locked"
    SUPERSEDED = "superseded"


class QuestionnaireRole(str, Enum):
    REGENTE = "regente"
    AEE = "aee"


class LlmProvider(str, Enum):
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    QWEN = "qwen"
    MOONSHOT = "moonshot"
    OPENAI = "openai"


# Enums INTERNOS do canonical (escalas dos questionarios)
class CapabilityLevel(str, Enum):
    """Escala da Parte 2 do NEEI: Realiza sem suporte / com apoio / nao realiza / nao observado."""
    WITHOUT_SUPPORT = "without_support"
    WITH_SUPPORT = "with_support"
    CANNOT = "cannot"
    NOT_OBSERVED = "not_observed"


class SupportResponse(str, Enum):
    """Escala da Parte 4 do NEEI: Sim sozinho / Sim com apoio / Nao / Nao testado."""
    YES_ALONE = "yes_alone"
    YES_WITH_SUPPORT = "yes_with_support"
    NO = "no"
    NOT_TESTED = "not_tested"


class AuthorizationIntensity(str, Enum):
    """Escala da Parte 5 do NEEI: Nao autorizar / Leve / Moderada / Intensa."""
    NOT_AUTHORIZED = "not_authorized"
    LIGHT = "light"
    MODERATE = "moderate"
    INTENSE = "intense"
