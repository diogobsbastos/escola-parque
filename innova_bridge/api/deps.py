"""
innova_bridge/api/deps.py — Dependências FastAPI compartilhadas.

Auth: introspecção GoTrue
  O frontend manda o JWT do usuário no header Authorization: Bearer <token>.
  Chamamos GET /auth/v1/user no GoTrue self-hosted para validar o token e
  obter os dados do usuário — sem precisar expor o JWT_SECRET.

  Para chamadas internas (service-role), o header pode conter o service_role
  JWT diretamente (bypass da verificação de usuário).

Uso nos routers:
    from innova_bridge.api.deps import usuario_autenticado, requer_papel

    @router.get("/...")
    async def endpoint(user=Depends(usuario_autenticado)):
        ...

    @router.post("/...")
    async def endpoint(user=Depends(requer_papel("admin", "coordinator"))):
        ...
"""
from __future__ import annotations

from typing import Dict

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from innova_bridge.config import get_bd_ativo

_bearer = HTTPBearer(auto_error=True)


def _gotrue_url() -> str:
    bd = get_bd_ativo()
    url = (bd.get("supabase_url") or "").rstrip("/")
    if not url:
        raise RuntimeError("BD ativo sem supabase_url — configure no carrossel de Bancos.")
    return url


def _service_role() -> str:
    bd = get_bd_ativo()
    sr = bd.get("service_role") or ""
    if not sr:
        raise RuntimeError("BD ativo sem service_role — configure no carrossel de Bancos.")
    return sr


async def usuario_autenticado(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Dict:
    """
    Valida o JWT via introspecção GoTrue (GET /auth/v1/user).
    Retorna o dict do usuário GoTrue (id, email, role, user_metadata, …).
    Lança HTTP 401 se o token for inválido ou expirado.
    """
    token = creds.credentials
    service_role = _service_role()

    # Chamada interna service-role: bypass
    if token == service_role:
        return {"id": "service-role", "role": "service_role", "email": "internal"}

    try:
        gotrue = _gotrue_url()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{gotrue}/auth/v1/user",
                headers={
                    "apikey":        service_role,
                    "Authorization": f"Bearer {token}",
                },
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Nao foi possivel contatar o GoTrue: {e}",
        )

    if resp.status_code == 200:
        return resp.json()

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalido ou expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def requer_papel(*papeis: str):
    """
    Factory que retorna uma dependencia que verifica se o usuario tem um dos papeis.
    O papel vive em user_metadata.role (como gravado pelo backend_auth.py).
    """
    async def _dep(user: Dict = Depends(usuario_autenticado)) -> Dict:
        meta  = user.get("user_metadata") or {}
        papel = meta.get("role") or user.get("role") or ""
        if papel not in papeis and papel != "service_role":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Papel '{papel}' nao autorizado. Requer: {list(papeis)}",
            )
        return user
    return _dep
