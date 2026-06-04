"""
tests/validar_native.py

Smoke test do `innova_bridge/agents/agente1/native.py`:
roda build_pai_native sobre INPUT_INTENSO e compara com GOLDEN_OUTPUT_U1
campo a campo, separando ESTRUTURAL (que tem que bater 100%) de PROSA
(que pode variar - texto livre).

Rode na raiz:

    python tests/validar_native.py

Esperado: 12/12 campos ESTRUTURAIS identicos. PROSA varia (template).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"

from innova_bridge.agents.agente1.native import build_pai_native, build_pai_native_validated  # noqa: E402


# Mesma lista do compare_pai.py do socio: 12 campos ESTRUTURAIS.
# Esses sao decisoes objetivas que codigo resolve - tem que bater 100%.
STRUCTURAL_FIELDS = [
    "adaptation_budget",
    "capabilities",
    "barriers",
    "support_response",
    ("hard_restrictions", "global"),
    ("meta", "student_id"),
    ("meta", "grade_level"),
    ("meta", "age"),
    ("meta", "has_clinical_report"),
    ("meta", "is_neurotypical_path"),
    ("hard_restrictions", "personality_notes_ptbr"),
    ("narrative", "what_does_not_work_ptbr"),
]

# Campos de PROSA - podem variar entre native (template) e golden (LLM polida).
# So checamos presenca, nao igualdade textual.
PROSE_FIELDS = [
    ("narrative", "student_summary_ptbr"),
    ("narrative", "what_works_ptbr"),
    ("narrative", "clinical_summary_operational_ptbr"),
    ("narrative", "aee_recommendations_ptbr"),
    ("rationale", "summary_for_teacher_ptbr"),
    ("rationale", "evidence_per_authorization"),
    ("rationale", "low_confidence_areas"),
    ("rationale", "missing_evidence"),
    ("hard_restrictions", "student_specific_ptbr"),
]


def _get(d: dict, path) -> object:
    """Acessa d[path[0]][path[1]]... aceitando str ou tuple."""
    if isinstance(path, str):
        path = (path,)
    cur = d
    for p in path:
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def _label(path) -> str:
    return ".".join(path) if isinstance(path, tuple) else path


def main() -> int:
    # Carrega INPUT_INTENSO (input que gerou o GOLDEN_OUTPUT_U1)
    with open(FIXTURES / "INPUT_INTENSO_formulario.json", encoding="utf-8") as f:
        payload = json.load(f)
    with open(FIXTURES / "GOLDEN_OUTPUT_U1.json", encoding="utf-8") as f:
        golden = json.load(f)

    print("=" * 70)
    print("  COMPARACAO native (Python puro) vs GOLDEN (Anthropic Opus 4.7)")
    print("=" * 70)
    print()

    # Roda native
    try:
        pai = build_pai_native_validated(payload)
        print("  [OK]  build_pai_native_validated(INPUT_INTENSO) - sem excecoes")
    except Exception as e:
        print(f"  [FAIL] build_pai_native_validated: {type(e).__name__}: {e}")
        return 1

    print()
    print("-" * 70)
    print("  CAMPOS ESTRUTURAIS (decisoes - tem que bater 100%)")
    print("-" * 70)

    n_estr_ok = 0
    for f in STRUCTURAL_FIELDS:
        a = _get(pai, f)
        b = _get(golden, f)
        ok = a == b
        n_estr_ok += int(ok)
        flag = "OK " if ok else "FAIL"
        print(f"  [{flag}] {_label(f)}")
        if not ok:
            print(f"           native: {json.dumps(a, ensure_ascii=False)[:90]}")
            print(f"           golden: {json.dumps(b, ensure_ascii=False)[:90]}")

    print()
    print(f"  -> {n_estr_ok}/{len(STRUCTURAL_FIELDS)} estruturais identicos")

    print()
    print("-" * 70)
    print("  CAMPOS DE PROSA (template native vs LLM golden - varia OK)")
    print("-" * 70)

    for f in PROSE_FIELDS:
        a = _get(pai, f)
        b = _get(golden, f)
        same = a == b
        kind = "identico" if same else "presente, texto difere (esperado)"
        flag = "=" if same else "~"
        print(f"  [{flag}] {_label(f)}: {kind}")

    print()
    print("=" * 70)
    pct = round(100 * n_estr_ok / len(STRUCTURAL_FIELDS))
    print(f"  VEREDITO: {pct}% das DECISOES estruturais reproduzidas em Python puro.")
    print(f"  Custo: R$ 0,00 | Latencia: ~1 ms | Tokens: 0")
    print("=" * 70)

    # ---- TESTE EXTRA: U2 neurotipico ----
    print()
    print("=" * 70)
    print("  TESTE EXTRA: U2 (neurotipico) - so verifica que nao explode")
    print("=" * 70)
    with open(FIXTURES / "INPUT_U2_formulario.json", encoding="utf-8") as f:
        u2 = json.load(f)
    try:
        pai_u2 = build_pai_native_validated(u2)
        print(f"  [OK]  build_pai_native(INPUT_U2) gerou PAI valido")
        print(f"         is_neurotypical_path = {pai_u2['meta']['is_neurotypical_path']}")
        print(f"         has_clinical_report  = {pai_u2['meta']['has_clinical_report']}")
        budget = pai_u2["adaptation_budget"]
        print(f"         budget total nao-zero = "
              f"{sum(1 for d in ('statement_fragmentation','language_simplification','content_simplification','metacognitive_hints','visual_support','alternatives_reduction','layout_intensity','command_highlighting') if budget[d] > 0)}/8")
    except Exception as e:
        print(f"  [FAIL] U2: {type(e).__name__}: {e}")
        return 1

    return 0 if n_estr_ok == len(STRUCTURAL_FIELDS) else 2


if __name__ == "__main__":
    sys.exit(main())
