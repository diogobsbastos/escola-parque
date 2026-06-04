"""
verificar_professores_supabase.py
Confirmacao programatica: o que esta REALMENTE gravado em public.users no Supabase BR?

Uso:
    python scripts_verificacao/verificar_professores_supabase.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from innova_bridge.db import get_pool


async def main():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                id::text  AS uuid,
                email,
                full_name,
                active,
                created_at,
                updated_at
            FROM public.users
            WHERE role = 'teacher'
            ORDER BY full_name
        """)

    print(f"\n{'='*100}")
    print(f"  PROFESSORES NO SUPABASE BR (public.users WHERE role='teacher')")
    print(f"{'='*100}\n")

    if not rows:
        print("  Nenhum professor encontrado.")
        return

    print(f"  {'UUID':<12} {'FULL_NAME':<35} {'EMAIL':<30} {'ATIVO':<6} {'UPDATED_AT':<19}")
    print(f"  {'-'*12} {'-'*35} {'-'*30} {'-'*6} {'-'*19}")
    for r in rows:
        uuid_short = r['uuid'][:8] + "..."
        nome = (r['full_name'] or '-')[:35]
        email = (r['email'] or '-')[:30]
        ativo = "SIM" if r['active'] else "NAO"
        upd = str(r['updated_at'])[:19] if r['updated_at'] else "-"
        print(f"  {uuid_short:<12} {nome:<35} {email:<30} {ativo:<6} {upd:<19}")

    print(f"\n  Total: {len(rows)} professor(es)\n")


if __name__ == "__main__":
    asyncio.run(main())
