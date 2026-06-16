"""
backend_usuarios_admin.py — Edição e reset de senha de usuários (admin).
-----------------------------------------------------------------------
Complementa backend_auth.py (que CRIA usuários). Aqui:
  - atualizar_usuario(): edita nome / papel / colégio / ativo
  - resetar_senha():     define uma NOVA senha no GoTrue (a antiga é hash,
                         não dá pra recuperar — só substituir)

IMPORTANTE (nginx 405): o nginx público só repassa GET/POST nas rotas admin do
GoTrue — o PUT volta 405. Como ESTE backend roda na MESMA VPS do GoTrue, falamos
direto com o GoTrue na porta interna (127.0.0.1:9999), pulando o nginx. Internamente
o GoTrue serve os caminhos SEM o prefixo /auth/v1 (ele vê /admin/users/{id}, /user...).
Mantemos o público como fallback.
"""

from __future__ import annotations

from typing import Optional

import requests

from innova_bridge.db.client import run_async, get_pool
import backend_auth as auth

# Papéis aceitos na edição. Inclui super_admin (existe no enum e é usado pelo
# frontend), além dos papéis "normais" do backend_auth.
PAPEIS_EDITAVEIS = tuple(auth.PAPEIS_VALIDOS) + ("super_admin",)

# Porta interna padrão do GoTrue self-hosted.
GOTRUE_INTERNO = "http://127.0.0.1:9999"


def _headers():
    _base, service = auth._gotrue_base_e_chave()
    return {
        "apikey": service,
        "Authorization": f"Bearer {service}",
        "Content-Type": "application/json",
    }


def _gotrue_admin_put(rel_path: str, payload: dict):
    """PUT numa rota admin do GoTrue. rel_path ex.: 'admin/users/<id>'.

    Tenta primeiro o GoTrue INTERNO (sem nginx, caminho sem /auth/v1); se não
    rolar, cai pro público (com /auth/v1). Retorna (ok, response|None, erro_str|None).
    """
    headers = _headers()
    base, _service = auth._gotrue_base_e_chave()
    candidatos = [
        ("interno", f"{GOTRUE_INTERNO}/{rel_path}"),
        ("publico", f"{base}/auth/v1/{rel_path}"),
    ]
    erros = []
    for nome, url in candidatos:
        try:
            r = requests.put(url, json=payload, headers=headers, timeout=15)
        except requests.RequestException as e:
            erros.append(f"{nome}: rede {type(e).__name__}")
            continue
        if r.status_code in (200, 201):
            return True, r, None
        erros.append(f"{nome}: HTTP {r.status_code} {r.text[:100]}")
    return False, None, " | ".join(erros)


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
    _ok, _r, _err = _gotrue_admin_put(
        f"admin/users/{user_id}",
        {"user_metadata": {"full_name": full_name, "role": role, "school_id": school_id}},
    )
    # Não bloqueia: o app lê de public.users. Mas avisa se a sincronia falhou.
    if not _ok:
        return {"ok": True, "mensagem": f"Usuário atualizado (metadata do GoTrue não sincronizou: {_err})."}

    return {"ok": True, "mensagem": "Usuário atualizado."}


# ════════════════════════════════════════════════════════════════════
# Resetar / renovar senha
# ════════════════════════════════════════════════════════════════════
def resetar_senha(user_id: str, nova_senha: Optional[str] = None) -> dict:
    """Define uma nova senha no GoTrue. Retorna {ok, senha, mensagem}."""
    nova_senha = nova_senha or auth.gerar_senha_provisoria()
    ok, _r, err = _gotrue_admin_put(f"admin/users/{user_id}", {"password": nova_senha})
    if ok:
        return {"ok": True, "senha": nova_senha, "mensagem": "Senha redefinida."}
    return {"ok": False, "mensagem": f"GoTrue não aceitou o PUT. {err}"}
