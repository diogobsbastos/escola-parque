"""
innova_bridge/api/routers/formularios.py — Endpoints de schemas de formularios.

Endpoints:
  GET  /schemas             Lista todos os schemas (id, nome, versao, ativo, n_fields).
  GET  /schemas/ativo       Retorna o schema marcado como ativo (canonical completo).
  GET  /schemas/{id}        Retorna um schema pelo id (canonical completo).
  POST /schemas             Cria ou atualiza um schema (upsert por nome).
  PUT  /schemas/{id}/activate  Ativa um schema (desativa o anterior na mesma tx).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

import backend_formularios as bf
from innova_bridge.api.deps import requer_papel, usuario_autenticado

router = APIRouter(prefix="/schemas", tags=["formularios"])

# ─────────────────────────────────────────────────────────────────────────────
# Modelos Pydantic
# ─────────────────────────────────────────────────────────────────────────────

class SchemaResumo(BaseModel):
    id:           Optional[int]
    nome:         str
    versao:       str
    ativo:        bool
    n_fields:     int
    titulo:       str
    produzido_em: str

    class Config:
        from_attributes = True


class SchemaCompleto(SchemaResumo):
    canonical: Dict[str, Any]


class SalvarSchemaPayload(BaseModel):
    nome:   str = Field(..., description="Identificador unico (ex: neei_v2_1)")
    dados:  Dict[str, Any] = Field(..., description="Conteudo completo do schema (mapping + value_maps + metadados)")


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[SchemaResumo])
async def listar_schemas(
    _user: Dict = Depends(usuario_autenticado),
):
    """Lista todos os schemas disponiveis. Qualquer usuario autenticado."""
    schemas = bf.listar_schemas()
    return [
        SchemaResumo(
            id=sc.get("id"),
            nome=sc["nome"],
            versao=sc["versao"],
            ativo=sc.get("ativo", False),
            n_fields=sc.get("n_fields", 0),
            titulo=sc.get("titulo", sc["nome"]),
            produzido_em=sc.get("produzido_em", "-"),
        )
        for sc in schemas
    ]


@router.get("/ativo", response_model=SchemaCompleto)
async def obter_schema_ativo(
    _user: Dict = Depends(usuario_autenticado),
):
    """Retorna o schema atualmente ativo com canonical completo."""
    sc = bf.schema_ativo()
    if not sc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum schema ativo encontrado.",
        )
    return SchemaCompleto(
        id=sc.get("id"),
        nome=sc["nome"],
        versao=sc["versao"],
        ativo=sc.get("ativo", True),
        n_fields=sc.get("n_fields", 0),
        titulo=sc.get("titulo", sc["nome"]),
        produzido_em=sc.get("produzido_em", "-"),
        canonical=sc.get("canonical", {}),
    )


@router.get("/{schema_id}", response_model=SchemaCompleto)
async def obter_schema(
    schema_id: int,
    _user: Dict = Depends(usuario_autenticado),
):
    """Retorna um schema pelo id numerico com canonical completo."""
    schemas = bf.listar_schemas()
    sc = next((s for s in schemas if s.get("id") == schema_id), None)
    if not sc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schema id={schema_id} nao encontrado.",
        )
    sc_completo = bf.carregar_schema(sc["nome"])
    if not sc_completo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Schema encontrado na lista mas falhou ao carregar.")
    return SchemaCompleto(
        id=sc_completo.get("id"),
        nome=sc_completo["nome"],
        versao=sc_completo["versao"],
        ativo=sc_completo.get("ativo", False),
        n_fields=sc_completo.get("n_fields", 0),
        titulo=sc_completo.get("titulo", sc_completo["nome"]),
        produzido_em=sc_completo.get("produzido_em", "-"),
        canonical=sc_completo.get("canonical", {}),
    )


@router.post("", response_model=Dict, status_code=status.HTTP_201_CREATED)
async def criar_ou_atualizar_schema(
    payload: SalvarSchemaPayload,
    _user: Dict = Depends(requer_papel("admin", "coordinator")),
):
    """
    Cria ou atualiza (upsert por nome) um schema.
    Requer papel admin ou coordinator.
    NAO altera o flag ativo — use PUT /{id}/activate para isso.
    """
    resultado = bf.salvar_schema(payload.nome, payload.dados)
    if not resultado["ok"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=resultado["mensagem"],
        )
    return resultado


@router.put("/{schema_id}/activate", response_model=Dict)
async def ativar_schema(
    schema_id: int,
    _user: Dict = Depends(requer_papel("admin", "coordinator")),
):
    """
    Ativa um schema (desativa o anterior na mesma transacao).
    Requer papel admin ou coordinator.
    """
    resultado = bf.ativar_schema(schema_id)
    if not resultado["ok"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=resultado["mensagem"],
        )
    return resultado
