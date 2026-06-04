"""
innova_bridge/formularios/adapters/from_neei_v2_0.py
Adapter: CSV exportado do Google Forms (NEEI v2.0) -> CanonicalQuestionnaire.

USO:
    from innova_bridge.formularios.adapters.from_neei_v2_0 import csv_to_canonical
    canonical = csv_to_canonical("path/to/respostas.csv", linha=0)
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Optional

from innova_bridge.models.canonical import (
    CanonicalQuestionnaire, CanonicalMeta, CanonicalCharacterization,
    CanonicalCapabilities, CanonicalBarriers, CanonicalSupportResponse,
    CanonicalAuthorizations, CanonicalRestrictions, CanonicalAeeObservations,
)
from innova_bridge.models.enums import (
    CapabilityLevel, SupportResponse, AuthorizationIntensity,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "neei_v2_0.json"


def _load_schema() -> dict:
    """Carrega o schema declarativo do NEEI v2.0."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _map_value(raw: str, value_map: dict) -> Optional[str]:
    """Tenta mapear valor PT-BR para enum EN. Aceita variantes com/sem acento."""
    if raw is None:
        return None
    raw_stripped = raw.strip()
    if raw_stripped in value_map:
        return value_map[raw_stripped]
    # Tenta com normalizacao (sem acento)
    import unicodedata
    raw_no_accent = unicodedata.normalize("NFKD", raw_stripped).encode("ascii", "ignore").decode("ascii")
    for k, v in value_map.items():
        k_no_accent = unicodedata.normalize("NFKD", k).encode("ascii", "ignore").decode("ascii")
        if k_no_accent == raw_no_accent:
            return v
    return None


def csv_to_canonical(csv_path: str | Path, linha: int = 0) -> CanonicalQuestionnaire:
    """Le UMA linha de resposta do CSV (linha=0 = primeira resposta) e retorna canonical."""
    schema = _load_schema()
    mapping: dict[str, str] = schema["mapping"]
    value_maps: dict[str, dict] = schema["value_maps"]

    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if linha >= len(rows):
        raise IndexError(f"CSV tem {len(rows)} linhas, mas pediram linha {linha}")

    row = rows[linha]

    # Pre-computa lookup de colunas normalizadas (sem acento) -> coluna real do CSV
    import unicodedata as _ud
    def _norm(s: str) -> str:
        return _ud.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower().strip()
    col_lookup = {_norm(c): c for c in row.keys()}

    def get(field_id: str) -> str:
        col_esperada = mapping.get(field_id)
        if col_esperada is None:
            return ""
        # tenta match exato primeiro
        if col_esperada in row:
            return row[col_esperada].strip()
        # fallback: fuzzy match por normalizacao de acentos
        col_real = col_lookup.get(_norm(col_esperada))
        if col_real:
            return row[col_real].strip()
        return ""

    # ─── META ───
    has_clinical_raw = get("characterization.has_clinical_report_raw")
    has_clinical = value_maps["has_clinical_report"].get(has_clinical_raw, False)

    extra_time_raw = get("auth_extra_time_raw")
    extra_time = value_maps["extra_time"].get(extra_time_raw, False)

    meta = CanonicalMeta(
        student_id=get("meta.student_id") or "UNKNOWN",
        academic_year="2026",  # TODO: extrair de meta.grade_level se houver
        grade_level=get("meta.grade_level") or "-",
        age=int(get("meta.age")) if get("meta.age").isdigit() else None,
        fill_date=get("meta.fill_date"),
        teacher_name=get("meta.teacher_name") or "-",
        aee_professional_name=get("meta.aee_professional_name") or None,
        schema_version="NEEI_v2.0",
    )

    # ─── CHARACTERIZATION ───
    characterization = CanonicalCharacterization(
        student_summary=get("characterization.student_summary"),
        has_clinical_report=has_clinical,
        clinical_summary=get("characterization.clinical_summary") or None,
        current_supports=get("characterization.current_supports"),
        what_works=get("characterization.what_works"),
        what_did_not_work=get("characterization.what_did_not_work") or None,
    )

    # ─── CAPABILITIES (todos field_ids comecam com "capability_") ───
    cap_items = {}
    for field_id in mapping:
        if field_id.startswith("capability_"):
            raw = get(field_id)
            mapped = _map_value(raw, value_maps["capability"])
            if mapped:
                cap_items[field_id] = CapabilityLevel(mapped)
    capabilities = CanonicalCapabilities(items=cap_items)

    # ─── BARRIERS (cada secao 3.A-3.F vem como string com ; separado) ───
    barrier_flags = {}
    for field_id in mapping:
        if field_id.startswith("barriers_3") and field_id.endswith("_raw"):
            raw = get(field_id)
            if raw:
                # Cada item separado por ; vira flag true
                items = [x.strip() for x in raw.split(";") if x.strip()]
                secao = field_id.replace("barriers_", "").replace("_raw", "")
                for item in items:
                    # field_id: barrier_{secao}_{slug}
                    slug = item.lower().replace(" ", "_").replace(",", "")[:50]
                    key = f"barrier_{secao}_{slug}"
                    barrier_flags[key] = True
    other_text = get("barriers_3g_other_text") or None
    barriers = CanonicalBarriers(flags=barrier_flags, other_observations=other_text)

    # ─── SUPPORT RESPONSE ───
    sup_items = {}
    for field_id in mapping:
        if field_id.startswith("support_4_"):
            raw = get(field_id)
            mapped = _map_value(raw, value_maps["support"])
            if mapped:
                sup_items[field_id] = SupportResponse(mapped)
    support_response = CanonicalSupportResponse(items=sup_items)

    # ─── AUTHORIZATIONS ───
    auth_intens = {}
    for field_id in mapping:
        if field_id.startswith("auth_") and field_id != "auth_extra_time_raw":
            raw = get(field_id)
            mapped = _map_value(raw, value_maps["authorization"])
            if mapped:
                auth_intens[field_id] = AuthorizationIntensity(mapped)
    authorizations = CanonicalAuthorizations(
        intensities=auth_intens,
        extra_time_allowed=extra_time,
    )

    # ─── RESTRICTIONS ───
    restrictions = CanonicalRestrictions(
        specific_restrictions=get("restrictions.specific_restrictions") or None,
        personality_notes=get("restrictions.personality_notes") or None,
    )

    # ─── AEE OBSERVATIONS ───
    aee = CanonicalAeeObservations(
        specific_strategies=get("aee.specific_strategies") or None,
        material_resources=get("aee.material_resources") or None,
        other=get("aee.other") or None,
    )

    return CanonicalQuestionnaire(
        meta=meta,
        characterization=characterization,
        capabilities=capabilities,
        barriers=barriers,
        support_response=support_response,
        authorizations=authorizations,
        restrictions=restrictions,
        aee_observations=aee,
    )
