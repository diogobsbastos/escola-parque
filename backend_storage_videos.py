"""
backend_storage_videos.py - Gerencia os videos de fundo da landing no Supabase Storage.

Bucket: landing-assets (publico). Usa o BD ativo do carrossel (mesma fonte do
resto do app): storage_bancos.get_active_bd_decifrado() -> supabase_url + service_role.

API REST de Storage do Supabase:
- listar:  POST {url}/storage/v1/object/list/{bucket}
- upload:  POST {url}/storage/v1/object/{bucket}/{path}   (x-upsert: true p/ sobrescrever)
- deletar: DELETE {url}/storage/v1/object/{bucket}/{path}
- publico: {url}/storage/v1/object/public/{bucket}/{path}
"""
from __future__ import annotations

import requests
import storage_bancos as sb

BUCKET = "landing-assets"
MAX_BYTES = 25 * 1024 * 1024  # 25 MB (limite do bucket)


def _conn() -> tuple[str, str]:
    """Retorna (supabase_url, service_role) do BD ativo, decifrados."""
    bd = sb.get_active_bd_decifrado()
    if not bd:
        raise RuntimeError(
            "Nenhum BD marcado como EM USO no carrossel. "
            "Abra Configuracoes -> Banco de Dados (Innova V2) e ative um."
        )
    url = (bd.get("supabase_url") or "").rstrip("/")
    sr = bd.get("service_role") or ""
    if not url or not sr:
        raise RuntimeError("BD ativo sem supabase_url ou service_role.")
    return url, sr


def _headers(sr: str, content_type: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {sr}", "apikey": sr}
    if content_type:
        h["Content-Type"] = content_type
    return h


def public_url(name: str) -> str:
    url, _ = _conn()
    return f"{url}/storage/v1/object/public/{BUCKET}/{name}"


def listar_videos() -> list[dict]:
    """Lista os objetos do bucket (ignora placeholder de pasta vazia)."""
    url, sr = _conn()
    r = requests.post(
        f"{url}/storage/v1/object/list/{BUCKET}",
        headers=_headers(sr, "application/json"),
        json={
            "prefix": "",
            "limit": 100,
            "offset": 0,
            "sortBy": {"column": "name", "order": "asc"},
        },
        timeout=30,
    )
    r.raise_for_status()
    out: list[dict] = []
    for obj in r.json():
        name = obj.get("name", "")
        if not name or name == ".emptyFolderPlaceholder":
            continue
        meta = obj.get("metadata") or {}
        out.append(
            {
                "name": name,
                "size": meta.get("size"),
                "mimetype": meta.get("mimetype"),
                "url": public_url(name),
            }
        )
    return out


def upload_video(name: str, data: bytes, content_type: str = "video/mp4", upsert: bool = True) -> None:
    url, sr = _conn()
    h = _headers(sr, content_type)
    if upsert:
        h["x-upsert"] = "true"
    r = requests.post(
        f"{url}/storage/v1/object/{BUCKET}/{name}",
        headers=h,
        data=data,
        timeout=180,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Falha no upload ({r.status_code}): {r.text[:300]}")


def deletar_video(name: str) -> None:
    url, sr = _conn()
    r = requests.delete(
        f"{url}/storage/v1/object/{BUCKET}/{name}",
        headers=_headers(sr),
        timeout=30,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"Falha ao deletar ({r.status_code}): {r.text[:300]}")
