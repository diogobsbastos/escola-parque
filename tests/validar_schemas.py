"""
tests/validar_schemas.py

Smoke test do `innova_bridge/agents/agente1/schemas.py`:
carrega os 3 fixtures reais e tenta validar com NEEIInput / PaiV1.

Rode na raiz do projeto:

    python tests/validar_schemas.py

Esperado: 4 [OK] sem erros.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"

from innova_bridge.agents.agente1.schemas import (  # noqa: E402
    NEEIInput,
    PaiV1,
    ADAPTATION_BUDGET_DIMENSIONS,
    INTENSITY_TO_INT,
    GLOBAL_RESTRICTIONS,
)


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def validar_entrada(arquivo: str, label: str) -> int:
    """Valida NEEIInput contra um fixture. Retorna 0 se OK, 1 se falhou."""
    try:
        obj = NEEIInput.model_validate(_load(arquivo))
    except Exception as e:
        print(f"  [FAIL] NEEIInput   <- {label}")
        print(f"         {type(e).__name__}: {str(e)[:400]}")
        return 1

    n_caps = sum(
        len(getattr(obj.questionnaire_response.capabilities, g).model_dump())
        for g in (
            "reading_comprehension",
            "writing_production",
            "mathematical_reasoning",
            "executive_functions",
        )
    )
    n_auths = len(obj.questionnaire_response.adaptation_authorizations)
    n_supports = len(obj.questionnaire_response.support_response)
    print(f"  [OK]   NEEIInput   <- {label}")
    print(
        f"         {n_caps} capabilities, {n_auths} authorizations, "
        f"{n_supports} support_response"
    )
    return 0


def validar_saida(arquivo: str, label: str) -> int:
    """Valida PaiV1 contra um fixture. Retorna 0 se OK, 1 se falhou."""
    try:
        pai = PaiV1.model_validate(_load(arquivo))
    except Exception as e:
        print(f"  [FAIL] PaiV1       <- {label}")
        print(f"         {type(e).__name__}: {str(e)[:500]}")
        return 1

    print(f"  [OK]   PaiV1       <- {label}")
    b = pai.adaptation_budget
    print(f"         budget = ({b.statement_fragmentation}, {b.language_simplification}, "
          f"{b.content_simplification}, {b.metacognitive_hints}, "
          f"{b.visual_support}, {b.alternatives_reduction}, "
          f"{b.layout_intensity}, {b.command_highlighting}) extra_time={b.extra_time_allowed}")
    print(f"         hard_restrictions.global: {len(pai.hard_restrictions.global_)} itens "
          f"(esperado: 4)")
    print(f"         rationale.evidence_per_authorization: "
          f"{len(pai.rationale.evidence_per_authorization)} entries")
    return 0


def main() -> int:
    print("=" * 70)
    print("  VALIDACAO Pydantic do schemas.py do agente1/ - FIXTURES REAIS")
    print("=" * 70)
    print()

    falhas = 0
    # Entradas
    falhas += validar_entrada("INPUT_U2_formulario.json",      "U2 (perfil neurotipico)")
    falhas += validar_entrada("INPUT_INTENSO_formulario.json", "INTENSO (perfil U1)")
    falhas += validar_entrada("INPUT_U1_reconstruido.json",    "U1 reconstruido")
    # Saida (golden)
    print()
    falhas += validar_saida("GOLDEN_OUTPUT_U1.json",           "GOLDEN_OUTPUT_U1 (Anthropic)")

    print()
    print("=" * 70)
    print("  Constantes exportadas pelo schemas.py")
    print("=" * 70)
    print(f"  ADAPTATION_BUDGET_DIMENSIONS: {len(ADAPTATION_BUDGET_DIMENSIONS)} dimensoes")
    for i, d in enumerate(ADAPTATION_BUDGET_DIMENSIONS, 1):
        print(f"     {i}. {d}")
    print(f"  INTENSITY_TO_INT: {INTENSITY_TO_INT}")
    print(f"  GLOBAL_RESTRICTIONS: {len(GLOBAL_RESTRICTIONS)} itens")
    for i, r in enumerate(GLOBAL_RESTRICTIONS, 1):
        print(f"     {i}. {r}")

    print()
    print("=" * 70)
    if falhas == 0:
        print(f"  VEREDITO: TODAS as validacoes passaram (0 falhas)")
    else:
        print(f"  VEREDITO: {falhas} validacoes FALHARAM")
    print("=" * 70)
    return falhas


if __name__ == "__main__":
    sys.exit(main())
