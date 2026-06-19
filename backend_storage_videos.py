"""
backend_storage_videos.py - Gerencia os videos de fundo da landing na PROPRIA VPS.

Em vez do Storage do Supabase (servico pesado, feito pra Docker), os videos
ficam numa pasta servida pelo Nginx -> simples, duravel, tudo no servidor.

- Pasta no disco: VIDEOS_DIR  (gravada pelo backend Streamlit, que roda como ubuntu)
- URL publica:    PUBLIC_BASE/<arquivo>  (Nginx serve a pasta, mesma origem da landing)

Pre-requisito de infra (uma vez, feito pelo usuario com sudo):
  sudo mkdir -p /var/www/landing-videos
  sudo chown ubuntu:www-data /var/www/landing-videos && sudo chmod 775 /var/www/landing-videos
  + bloco `location /landing-videos/ { alias /var/www/landing-videos/; }` no site Nginx do front
  + sudo nginx -t && sudo systemctl reload nginx
"""
from __future__ import annotations

import os

VIDEOS_DIR = "/var/www/landing-videos"
PUBLIC_BASE = "https://escolaparque-app.duckdns.org/landing-videos"
MAX_BYTES = 25 * 1024 * 1024  # 25 MB
VIDEO_EXTS = (".mp4", ".webm")


def _ensure_dir() -> None:
    os.makedirs(VIDEOS_DIR, exist_ok=True)


def public_url(name: str) -> str:
    return f"{PUBLIC_BASE}/{name}"


def listar_videos() -> list[dict]:
    """Lista os videos da pasta (ordenados por nome)."""
    _ensure_dir()
    out: list[dict] = []
    for name in sorted(os.listdir(VIDEOS_DIR)):
        if not name.lower().endswith(VIDEO_EXTS):
            continue
        p = os.path.join(VIDEOS_DIR, name)
        if not os.path.isfile(p):
            continue
        mt = "video/webm" if name.lower().endswith(".webm") else "video/mp4"
        out.append(
            {
                "name": name,
                "size": os.path.getsize(p),
                "mimetype": mt,
                "url": public_url(name),
            }
        )
    return out


def upload_video(name: str, data: bytes, content_type: str = "video/mp4", upsert: bool = True) -> None:
    """Grava o arquivo na pasta (basename para evitar path traversal)."""
    _ensure_dir()
    name = os.path.basename(name)
    if not name:
        raise RuntimeError("Nome de arquivo inválido.")
    p = os.path.join(VIDEOS_DIR, name)
    if os.path.exists(p) and not upsert:
        raise RuntimeError(f"'{name}' já existe.")
    tmp = p + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, p)  # escrita atomica


def deletar_video(name: str) -> None:
    name = os.path.basename(name)
    p = os.path.join(VIDEOS_DIR, name)
    if os.path.isfile(p):
        os.remove(p)
    else:
        raise RuntimeError(f"'{name}' não encontrado.")
