"""
backend_usuarios_admin.py — Edição e reset de senha de usuários (admin).
-----------------------------------------------------------------------
Complementa backend_auth.py (que CRIA usuários). Aqui:
  - atualizar_usuario(): edita nome / papel / colégio / ativo
  - resetar_senha():     define uma NOVA senha no GoTrue (a antiga é hash,
                         não dá pra recuperar — só substituir)

Tudo no GoTrue self-hosted (API admin) + public.users do BD ativo do carrossel.
Reaproveita helpers de backend_auth (base/chave do GoTrue, gerador de senha).
"""

from __future__ import annotations

from typing import Optional

import requests

from innova_bridge.db.client import run_async, get_pool
import backend_auth as auth

# Papéis aceitos na edição. Inclui super_admin (existe no enum e é usado pelo
# frontend), além dos papéis "normais" do backend_auth.
PAPEIS_EDITAVEIS = tuple(auth.PAPEIS_VALIDOS) + ("super_admin",)


def _admin_headers():
    """(base_url, headers) pra API admin do GoTrue do BD ativo."""
    base, service = auth._gotrue_base_e_chave()
    return base, {
        "apikey": service,
        "Authorization": f"Bearer {service}",
        "Content-Type": "application/json",
    }


# ════════════════════════════════════════════════════════════════════
# Editar dados do usuário
# ════════════════════════════════════════════════════════════════════
async def _update_public_user(pool, user_id, full_name, role, school_id, active):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE public.users
               SET full_name  = $2,
                   role       = $3::user_role,
                   school_id  = $4::uuid,
                   active     = $5,
                   updated_at = now()
             WHERE id = $1::uuid
            """,
            user_id, full_name, role, school_id, active,
        )


def atualizar_usuario(user_id: str, full_name: str, role: str,
                      school_id: str, active: bool) -> dict:
    """Atualiza nome/papel/colégio/ativo. Retorna {ok, mensagem}."""
    full_name = (full_name or "").strip()
    if role not in PAPEIS_EDITAVEIS:
        return {"ok": False, "mensagem": f"Papel inválido: {role}"}
    if not full_name:
        return {"ok": False, "mensagem": "Nome completo é obrigatório."}
    if not school_id:
        return {"ok": False, "mensagem": "Selecione o colégio."}

    # 1) public.users — fonte de verdade do app
    try:
        pool = run_async(get_pool())
        run_async(_update_public_user(pool, user_id, full_name, role, school_id, active))
    except Exception as e:
        return {"ok": False, "mensagem": f"Falha no public.users: {type(e).__name__}: {e}"}

    # 2) GoTrue user_metadata — mantém role/school em sincronia (best-effort)
    try:
        base, headers = _admin_headers()
        requests.put(
            f"{base}/auth/v1/admin/users/{user_id}",
            json={"user_metadata": {"full_name": full_name, "role": role, "school_id": school_id}},
            headers=headers, timeout=20,
        )
    except Exception:
        pass  # não bloqueia: o app lê de public.users

    return {"ok": True, "mensagem": "Usuário atualizado."}


# ════════════════════════════════════════════════════════════════════
# Resetar / renovar senha
# ════════════════════════════════════════════════════════════════════
def resetar_senha(user_id: str, nova_senha: Optional[str] = None) -> dict:
    """Define uma nova senha no GoTrue. Retorna {ok, senha, mensagem}.

    A senha ANTIGA não é recuperável (é hash). Esta função SUBSTITUI por uma
    nova (gerada se não vier explícita).
    """
    nova_senha = nova_senha or auth.gerar_senha_provisoria()
    try:
        base, headers = _admin_headers()
        r = requests.put(
            f"{base}/auth/v1/admin/users/{user_id}",
            json={"password": nova_senha},
            headers=headers, timeout=20,
        )
    except requests.RequestException as e:
        return {"ok": False, "mensagem": f"Erro de rede com o GoTrue: {type(e).__name__}: {e}"}

    if r.status_code in (200, 201):
        return {"ok": True, "senha": nova_senha, "mensagem": "Senha redefinida."}
    return {"ok": False, "mensagem": f"GoTrue retornou {r.status_code}: {r.text[:200]}"}
