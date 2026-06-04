"""
tests/validar_hybrid.py

Smoke test do run_hybrid testando APENAS o caminho de fallback gracioso
(sem chamar LLM real). Roda em ~1 segundo.

O teste de hybrid COM LLM real fica em tests/test_hybrid_compare.py (arquivo #12),
que precisa de api_key configurada.

Rode na raiz:

    python tests/validar_hybrid.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from innova_bridge.agents.agente1.hybrid import run_hybrid


FIXTURES = ROOT / "tests" / "fixtures"


def main() -> int:
    with open(FIXTURES / "INPUT_INTENSO_formulario.json", encoding="utf-8") as f:
        payload = json.load(f)

    print("=" * 70)
    print("  SMOKE TEST: hybrid.py - caminho de FALLBACK GRACIOSO")
    print("=" * 70)
    print()

    # --- TESTE 1: sem credenciais -> fallback ---
    pai, tele = run_hybrid(payload, provider_key_id=None, validate=False)
    ok1 = (
        tele["fallback_used"]
        and pai
        and "fallback nativo" in pai["meta"]["created_by"]
        and any("Camada fina" in m for m in pai["rationale"]["missing_evidence"])
    )
    print(f"  [{'OK ' if ok1 else 'FAIL'}] Sem creds -> fallback")
    print(f"          fallback_reason: {tele['fallback_reason'][:100]}")
    print(f"          created_by: {pai['meta']['created_by']}")
    print()

    # --- TESTE 2: provider_key_id inexistente ---
    pai, tele = run_hybrid(payload, provider_key_id="provider/inexistente", validate=False)
    ok2 = tele["fallback_used"]
    print(f"  [{'OK ' if ok2 else 'FAIL'}] provider_key_id inexistente -> fallback")
    print(f"          fallback_reason: {tele['fallback_reason'][:100]}")
    print()

    # --- TESTE 3: API key vazia em provider cloud ---
    pai, tele = run_hybrid(
        payload,
        provider_override="gemini",
        model_override="gemini-2.5-flash",
        api_key_override="",
        validate=False,
    )
    ok3 = tele["fallback_used"]
    print(f"  [{'OK ' if ok3 else 'FAIL'}] API key vazia em provider cloud -> fallback")
    print(f"          fallback_reason: {tele['fallback_reason'][:100]}")
    print()

    # --- TESTE 4: PAI estruturalmente valido mesmo em fallback ---
    budget_intenso = pai["adaptation_budget"]
    ok4 = (
        pai["schema_version"] == "PAI_v1.0"
        and budget_intenso["statement_fragmentation"] == 3
        and budget_intenso["language_simplification"] == 3
        and budget_intenso["extra_time_allowed"] is True
        and len(pai["hard_restrictions"]["global"]) == 4
    )
    print(f"  [{'OK ' if ok4 else 'FAIL'}] PAI v1.0 estruturalmente valido em fallback")
    print(f"          budget = ({budget_intenso['statement_fragmentation']}, "
          f"{budget_intenso['language_simplification']}, "
          f"{budget_intenso['content_simplification']}, "
          f"{budget_intenso['metacognitive_hints']}, "
          f"{budget_intenso['visual_support']}, "
          f"{budget_intenso['alternatives_reduction']}, "
          f"{budget_intenso['layout_intensity']}, "
          f"{budget_intenso['command_highlighting']})  extra_time={budget_intenso['extra_time_allowed']}")
    print()

    # --- TESTE 5: telemetria tem todos os campos esperados ---
    expected_keys = {
        "ok", "engine", "modelo", "provedor", "tokens_in", "tokens_out",
        "tokens_cache", "tempo_s", "fallback_used", "fallback_reason", "mensagem",
    }
    ok5 = set(tele.keys()) == expected_keys
    print(f"  [{'OK ' if ok5 else 'FAIL'}] Telemetria tem todos os {len(expected_keys)} campos esperados")
    print(f"          engine={tele['engine']}, tempo_s={tele['tempo_s']}")
    if not ok5:
        print(f"          missing: {expected_keys - set(tele.keys())}")
        print(f"          extra:   {set(tele.keys()) - expected_keys}")

    print()
    print("=" * 70)
    n_ok = sum([ok1, ok2, ok3, ok4, ok5])
    if n_ok == 5:
        print(f"  VEREDITO: 5/5 testes de fallback passaram")
    else:
        print(f"  VEREDITO: {n_ok}/5 testes passaram")
    print("=" * 70)
    return 0 if n_ok == 5 else 1


if __name__ == "__main__":
    sys.exit(main())
