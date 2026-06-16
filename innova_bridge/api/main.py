"""
innova_bridge/api/main.py — Aplicação FastAPI do Innova Exams / Escola Parque V3.

Porta: 8001 (Streamlit ocupa 8501; LLM gateway outra porta).
Comando de inicialização (systemd / manual):
    uvicorn innova_bridge.api.main:app --host 0.0.0.0 --port 8001

DEPLOY (⚠️ ação manual necessária — uma vez):
  1. Criar o unit systemd `innova-api.service` na VPS apontando para o comando acima.
  2. Adicionar "innova-api" à whitelist do autodeploy.py (lista SERVICOS_WHITELIST).
  3. Adicionar "innova-api" à lista de serviços do VPS MCP.
  A partir daí: editar local → push → auto-deploy, como o resto.
"""
from __future__ import annotations

import time
from typing import Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from innova_bridge.api.routers import formularios as formularios_router
from innova_bridge.api.routers import moldes as moldes_router

# ────────────────────────────────────────────────────────────────
# App
# ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Innova Exams API",
    description=(
        "API de backend do Escola Parque V3 — formulários, schemas NEEI, "
        "perfil pedagógico e auto-correção de provas."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    # Adicione o domínio de produção do frontend aqui quando disponivel
    # "https://innova.escolaparque.com.br",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ────────────────────────────────────────────────────────────────
# Routers
# ────────────────────────────────────────────────────────────────

app.include_router(formularios_router.router, prefix="/api/v1")
app.include_router(moldes_router.router, prefix="/api/v1")

# ────────────────────────────────────────────────────────────────
# Endpoints base
# ────────────────────────────────────────────────────────────────

_START_TIME = time.time()


@app.get("/health", tags=["sistema"])
async def health() -> Dict:
    """Health check — sem autenticação. Útil para o auto-deploy verificar."""
    uptime = int(time.time() - _START_TIME)
    try:
        from innova_bridge.config import get_label_ativo
        bd_label = get_label_ativo()
    except Exception:
        bd_label = "(BD nao configurado)"
    return {
        "status":   "ok",
        "uptime_s": uptime,
        "bd_ativo": bd_label,
        "versao":   app.version,
    }


@app.get("/", tags=["sistema"])
async def root() -> Dict:
    return {"mensagem": "Innova Exams API", "docs": "/docs", "health": "/health"}
