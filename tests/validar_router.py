"""
tests/validar_router.py

Smoke test do router.py:
    - Roda gerar_pai(INPUT_INTENSO, engine="native") com salvar=True
    - Verifica path_salvo + metadata_persistencia + log_custo
    - Roda novamente -> deve fazer supersede do v1 + criar v2
    - Testa engine="llm" (delegacao) + engine inexistente

Rode na raiz:

    python tests/validar_router.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Patcha PAIS_GERADOS_DIR pra usar pasta temporaria - evita poluir o disco
from innova_bridge.agents.agente1 import persistence as P  # noqa: E402

TMP_DIR = ROOT / "tests" / "_tmp_router"
if TMP_DIR.exists():
    shutil.rmtree(TMP_DIR)
TMP_DIR.mkdir(parents=True, exist_ok=True)
P.PAIS_GERADOS_DIR = TMP_DIR

from innova_bridge.agents.agente1.router import gerar_pai  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def main() -> int:
    with open(FIXTURES / "INPUT_INTENSO_formulario.json", encoding="utf-8") as f:
        payload = json.load(f)

    print("=" * 70)
    print("  SMOKE TEST router.py - gerar_pai() end-to-end")
    print("=" * 70)
    print()

    # --- TESTE 1: engine=native + salvar -> grava v1 ---
    r1 = gerar_pai(payload, engine="native", salvar=True)
    ok1 = (
        r1["ok"]
        and r1["pai"]
        and r1["metadata_persistencia"] is not None
        and r1["metadata_persistencia"]["versao"] == 1
        and r1["metadata_persistencia"]["status"] == "active"
        and r1["log_custo"] is not None
        and r1["path_salvo"]
    )
    print(f"  [{'OK ' if ok1 else 'FAIL'}] gerar_pai(native, salvar=True)")
    print(f"          versao={r1['metadata_persistencia']['versao']}, "
          f"status={r1['metadata_persistencia']['status']}, "
          f"tempo={r1['tempo_total_s']}s")
    print(f"          log_custo.processo={r1['log_custo']['processo']!r}, "
          f"custo=R$ {r1['log_custo']['custo_brl']}")
    print(f"          mensagem: {r1['mensagem']}")
    print()

    # --- TESTE 2: rodar de novo -> supersede + v2 ---
    r2 = gerar_pai(payload, engine="native", salvar=True)
    ok2 = (
        r2["ok"]
        and r2["metadata_persistencia"]["versao"] == 2
        and len(r2["metadata_persistencia"]["superseded_files"]) == 1
    )
    print(f"  [{'OK ' if ok2 else 'FAIL'}] Re-rodar -> supersede v1 + cria v2")
    print(f"          versao={r2['metadata_persistencia']['versao']}, "
          f"superseded={len(r2['metadata_persistencia']['superseded_files'])} arquivo(s)")
    print()

    # --- TESTE 3: engine="llm" -> delegado ao Molde Antigo ---
    r3 = gerar_pai(payload, engine="llm")
    ok3 = (not r3["ok"]) and ("Molde Antigo" in r3["mensagem"])
    print(f"  [{'OK ' if ok3 else 'FAIL'}] engine='llm' -> delegado ao Molde Antigo (sem chamar nada)")
    print(f"          mensagem: {r3['mensagem'][:80]}")
    print()

    # --- TESTE 4: engine invalido -> mensagem clara ---
    r4 = gerar_pai(payload, engine="xyz")  # type: ignore[arg-type]
    ok4 = (not r4["ok"]) and ("desconhecido" in r4["mensagem"])
    print(f"  [{'OK ' if ok4 else 'FAIL'}] engine='xyz' -> ok=False + mensagem clara")
    print()

    # --- TESTE 5: engine=hybrid sem creds -> usa fallback gracioso do hybrid ---
    r5 = gerar_pai(payload, engine="hybrid", salvar=False)
    # Hybrid fallback nativo eh aceitavel - PAI eh gerado
    ok5 = (
        r5["ok"]
        and r5["pai"]
        and r5["telemetria_engine"].get("fallback_used") is True
    )
    print(f"  [{'OK ' if ok5 else 'FAIL'}] engine='hybrid' sem creds -> fallback gracioso, ok=True")
    print(f"          fallback_used={r5['telemetria_engine'].get('fallback_used')}, "
          f"fallback_reason: {str(r5['telemetria_engine'].get('fallback_reason') or '')[:80]}")
    print()

    # --- TESTE 6: keys do dict de retorno ---
    expected_keys = {
        "ok", "engine", "pai", "telemetria_engine",
        "metadata_persistencia", "log_custo", "path_salvo",
        "tempo_total_s", "mensagem",
    }
    ok6 = set(r1.keys()) == expected_keys
    print(f"  [{'OK ' if ok6 else 'FAIL'}] dict de retorno tem todas as {len(expected_keys)} keys esperadas")
    if not ok6:
        print(f"          missing: {expected_keys - set(r1.keys())}")
        print(f"          extra:   {set(r1.keys()) - expected_keys}")
    print()

    # Limpeza
    shutil.rmtree(TMP_DIR, ignore_errors=True)

    print("=" * 70)
    n_ok = sum([ok1, ok2, ok3, ok4, ok5, ok6])
    if n_ok == 6:
        print(f"  VEREDITO: 6/6 testes passaram - router.py funcional end-to-end")
    else:
        print(f"  VEREDITO: {n_ok}/6 testes passaram")
    print("=" * 70)
    return 0 if n_ok == 6 else 1


if __name__ == "__main__":
    sys.exit(main())
