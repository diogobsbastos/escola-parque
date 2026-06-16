"""
═══════════════════════════════════════════════════════════════════════════════
BACKEND_FORMULARIOS.PY — Gerenciamento de schemas declarativos de formulários
═══════════════════════════════════════════════════════════════════════════════
Camada de dados para pagina_formularios.py e para a API FastAPI (/schemas).

Substitui a lógica inline de _listar_schemas() que vivia em pagina_formularios.py
e elimina o bug de "schema ativo = primeiro arquivo da lista".

Fonte de verdade: tabela public.formularios_schemas no Postgres.
Fallback: disco (innova_bridge/formularios/schemas/*.json) se o BD estiver vazio
          ou inacessível — garante que o Streamlit não quebre durante a transição.

Funções públicas (mesma assinatura esperada pela UI e pela API):
  listar_schemas()             → List[Dict]   (inclui campo 'ativo')
  carregar_schema(nome)        → Optional[Dict]
  salvar_schema(nome, dados)   → Dict {ok, id, mensagem}
  ativar_schema(id_ou_nome)    → Dict {ok, mensagem}
  schema_ativo()               → Optional[Dict]
  migrar_disco_para_bd()       → Dict {migrados, ignorados, erros}
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Caminho dos schemas em disco (fallback / migração)
SCHEMAS_DIR = Path(__file__).resolve().parent / "innova_bridge" / "formularios" / "schemas"

# ─────────────────────────────────────────────────────────────────────────────
# Importação lazy do pool asyncpg (mesmo padrão do resto do projeto)
# ─────────────────────────────────────────────────────────────────────────────

def _run(coro):
    """Executa coroutine no event loop singleton do innova_bridge."""
    try:
        from innova_bridge.db.client import run_async
        return run_async(coro)
    except Exception as e:
        raise RuntimeError(f"innova_bridge não disponível: {e}") from e


def _get_pool():
    try:
        from innova_bridge.db.client import run_async, get_pool
        return run_async(get_pool())
    except Exception as e:
        raise RuntimeError(f"Pool de BD indisponível: {e}") from e


# ─────────────────────────────────────────────────────────────────────────────
# Camada asyncpg (privada)
# ─────────────────────────────────────────────────────────────────────────────

async def _bd_listar(pool) -> List[Dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, nome, versao, canonical, ativo,
                   criado_em, atualizado_em
            FROM public.formularios_schemas
            ORDER BY ativo DESC, criado_em ASC
            """
        )
    return [dict(r) for r in rows]


async def _bd_carregar(pool, nome: str) -> Optional[Dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, nome, versao, canonical, ativo, criado_em, atualizado_em "
            "FROM public.formularios_schemas WHERE nome = $1",
            nome,
        )
    return dict(row) if row else None


async def _bd_schema_ativo(pool) -> Optional[Dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, nome, versao, canonical, ativo, criado_em, atualizado_em "
            "FROM public.formularios_schemas WHERE ativo = TRUE LIMIT 1"
        )
    return dict(row) if row else None


async def _bd_upsert(pool, nome: str, versao: str, canonical: dict,
                     ativo: bool = False) -> int:
    """Insere ou atualiza. Retorna o id do registro."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO public.formularios_schemas (nome, versao, canonical, ativo)
            VALUES ($1, $2, $3::jsonb, $4)
            ON CONFLICT (nome) DO UPDATE SET
                versao        = EXCLUDED.versao,
                canonical     = EXCLUDED.canonical,
                atualizado_em = NOW()
            RETURNING id
            """,
            nome, versao, json.dumps(canonical, ensure_ascii=False), ativo,
        )
    return row["id"]


async def _bd_ativar(pool, schema_id: int) -> None:
    """
    Ativa um schema e desativa todos os outros na mesma transação.
    Necessário por causa do índice único parcial (ativo=TRUE só pode aparecer uma vez).
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1) rebaixa o atual (se houver) — evita colisão no índice parcial
            await conn.execute(
                "UPDATE public.formularios_schemas SET ativo = FALSE WHERE ativo = TRUE"
            )
            # 2) ativa o novo
            await conn.execute(
                "UPDATE public.formularios_schemas SET ativo = TRUE, atualizado_em = NOW() "
                "WHERE id = $1",
                schema_id,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de disco (fallback / migração)
# ─────────────────────────────────────────────────────────────────────────────

def _listar_disco() -> List[Dict]:
    """Lista schemas disponíveis em disco. Retorna lista de dicts com metadados."""
    if not SCHEMAS_DIR.exists():
        return []
    resultado = []
    for arq in sorted(SCHEMAS_DIR.glob("*.json")):
        if arq.name == "__init__.py":
            continue
        try:
            data = json.loads(arq.read_text(encoding="utf-8"))
            resultado.append({
                "id":           None,
                "nome":         arq.stem,
                "versao":       data.get("schema_version", arq.stem),
                "canonical":    data,
                "ativo":        False,   # disco não tem flag real; será corrigido na migração
                "n_fields":     len(data.get("mapping", {})),
                "titulo":       data.get("title", arq.stem),
                "produzido_em": data.get("produced_at", "-"),
                "_fonte":       "disco",
            })
        except Exception as e:
            logger.warning("Erro lendo schema '%s': %s", arq.name, e)
    return resultado


def _enriquecer(row: dict) -> dict:
    """Adiciona campos derivados ao dict vindo do BD (n_fields, titulo, etc.)."""
    canonical = row.get("canonical") or {}
    if isinstance(canonical, str):
        try:
            canonical = json.loads(canonical)
        except Exception:
            canonical = {}
    row["canonical"] = canonical
    row["n_fields"]     = len(canonical.get("mapping", {}))
    row["titulo"]       = canonical.get("title", row.get("nome", "-"))
    row["produzido_em"] = canonical.get("produced_at", "-")
    row["_fonte"]       = "bd"
    return row


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────

def listar_schemas() -> List[Dict]:
    """
    Lista todos os schemas. BD-first; fallback para disco se BD vazio ou falhar.
    Garante que haja sempre ao menos um schema marcado 'ativo' (o primeiro do disco
    se vier do fallback).
    """
    try:
        pool = _get_pool()
        rows = _run(_bd_listar(pool))
        if rows:
            return [_enriquecer(dict(r)) for r in rows]
        # BD vazio → tenta migrar automaticamente e relista
        resultado = migrar_disco_para_bd()
        if resultado["migrados"] > 0:
            rows = _run(_bd_listar(pool))
            if rows:
                return [_enriquecer(dict(r)) for r in rows]
    except Exception as e:
        logger.warning("listar_schemas: BD indisponível, usando disco. (%s)", e)

    # Fallback disco
    schemas = _listar_disco()
    if schemas:
        schemas[0]["ativo"] = True   # simula o comportamento antigo para a UI
    return schemas


def carregar_schema(nome: str) -> Optional[Dict]:
    """
    Carrega um schema pelo nome (sem extensão). BD-first, fallback disco.
    """
    try:
        pool = _get_pool()
        row = _run(_bd_carregar(pool, nome))
        if row:
            return _enriquecer(dict(row))
    except Exception as e:
        logger.warning("carregar_schema '%s': BD falhou, usando disco. (%s)", nome, e)

    # Fallback disco
    arq = SCHEMAS_DIR / f"{nome}.json"
    if arq.exists():
        try:
            data = json.loads(arq.read_text(encoding="utf-8"))
            return {
                "id": None, "nome": nome,
                "versao": data.get("schema_version", nome),
                "canonical": data, "ativo": False,
                "n_fields": len(data.get("mapping", {})),
                "titulo": data.get("title", nome),
                "produzido_em": data.get("produced_at", "-"),
                "_fonte": "disco",
            }
        except Exception as e:
            logger.error("carregar_schema '%s' disco: %s", nome, e)
    return None


def schema_ativo() -> Optional[Dict]:
    """Retorna o schema marcado como ativo. None se nenhum."""
    try:
        pool = _get_pool()
        row = _run(_bd_schema_ativo(pool))
        if row:
            return _enriquecer(dict(row))
    except Exception as e:
        logger.warning("schema_ativo: BD falhou. (%s)", e)

    # Fallback: primeiro do disco
    schemas = _listar_disco()
    if schemas:
        schemas[0]["ativo"] = True
        return schemas[0]
    return None


def salvar_schema(nome: str, dados: dict) -> Dict:
    """
    Salva (upsert) um schema no BD. NÃO altera o flag ativo.
    Retorna {ok, id, mensagem}.
    """
    nome = nome.strip()
    if not nome:
        return {"ok": False, "id": None, "mensagem": "Nome inválido."}
    if not dados:
        return {"ok": False, "id": None, "mensagem": "Dados vazios."}

    versao  = dados.get("schema_version") or nome
    # canonical = o dict completo (mapping + value_maps + metadados)
    canonical = dados

    try:
        pool = _get_pool()
        schema_id = _run(_bd_upsert(pool, nome, versao, canonical))
        return {"ok": True, "id": schema_id,
                "mensagem": f"Schema '{nome}' salvo (id={schema_id})."}
    except Exception as e:
        logger.error("salvar_schema '%s': %s", nome, e)
        return {"ok": False, "id": None, "mensagem": f"Erro ao salvar: {e}"}


def ativar_schema(id_ou_nome) -> Dict:
    """
    Marca um schema como ativo (desativa o anterior na mesma transação).
    Aceita int (id) ou str (nome).
    Retorna {ok, mensagem}.
    """
    try:
        pool = _get_pool()

        # Resolve id se recebeu nome
        if isinstance(id_ou_nome, str):
            row = _run(_bd_carregar(pool, id_ou_nome))
            if not row:
                return {"ok": False, "mensagem": f"Schema '{id_ou_nome}' não encontrado."}
            schema_id = row["id"]
        else:
            schema_id = int(id_ou_nome)

        _run(_bd_ativar(pool, schema_id))
        return {"ok": True, "mensagem": f"Schema id={schema_id} ativado."}
    except Exception as e:
        logger.error("ativar_schema '%s': %s", id_ou_nome, e)
        return {"ok": False, "mensagem": f"Erro ao ativar: {e}"}


def migrar_disco_para_bd() -> Dict:
    """
    Importa todos os schemas de disco para o BD.
    - Usa ON CONFLICT(nome) DO UPDATE → idempotente.
    - O neei_v2_0 (único schema atual) é marcado ativo=TRUE.
    - Schemas adicionais entram como ativo=FALSE.
    Retorna {migrados, ignorados, erros, detalhes}.
    """
    schemas_disco = _listar_disco()
    if not schemas_disco:
        return {"migrados": 0, "ignorados": 0, "erros": 0,
                "detalhes": ["Nenhum schema encontrado em disco."]}

    try:
        pool = _get_pool()
    except Exception as e:
        return {"migrados": 0, "ignorados": 0, "erros": 1,
                "detalhes": [f"BD indisponível: {e}"]}

    # Verifica se já há schemas no BD
    bd_atual = _run(_bd_listar(pool))
    nomes_bd = {r["nome"] for r in bd_atual}

    migrados = ignorados = erros = 0
    detalhes: List[str] = []

    # Determina qual schema deve ser ativo: se já houver ativo no BD, mantém.
    # Caso contrário, marca o primeiro do disco (neei_v2_0) como ativo.
    ha_ativo_no_bd = any(r["ativo"] for r in bd_atual)
    primeiro_nome  = schemas_disco[0]["nome"] if schemas_disco else None

    for sc in schemas_disco:
        nome      = sc["nome"]
        canonical = sc["canonical"]
        versao    = sc["versao"]
        # Marca ativo somente se: BD não tem nenhum ativo E é o primeiro da lista
        marcar_ativo = (not ha_ativo_no_bd) and (nome == primeiro_nome)

        try:
            schema_id = _run(_bd_upsert(pool, nome, versao, canonical, ativo=marcar_ativo))
            if marcar_ativo:
                # Garante que o índice parcial seja respeitado (rebaixa outros se existirem)
                _run(_bd_ativar(pool, schema_id))
            migrados += 1
            flag = " [ATIVO]" if marcar_ativo else ""
            detalhes.append(f"✅ '{nome}' → id={schema_id}{flag}")
        except Exception as e:
            erros += 1
            detalhes.append(f"❌ '{nome}': {e}")

    return {
        "migrados":  migrados,
        "ignorados": ignorados,
        "erros":     erros,
        "detalhes":  detalhes,
    }
