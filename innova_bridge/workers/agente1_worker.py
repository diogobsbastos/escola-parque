"""
innova_bridge/workers/agente1_worker.py

Worker do Agente 1 do SISTEMA DUPLO (web + Python + Supabase).

Fluxo (poll-based, 1 worker local — comecar simples):
  1. Acha 1 secao pronta:
       status='locked' AND agent1_run_id IS NULL AND canonical_response IS NOT NULL
  2. Le o canonical_response (gravado pelo frontend via consolidate.ts) — ja e o
     NEEIInput pronto pro Agente 1, sem adapter.
  3. Le o default do agente em public.agent_configs (engine/model/strict).
  4. Roda router.gerar_pai(...) — mantem o salvamento LOCAL (salvar=True): ADITIVO.
  5. Calcula custo lendo public.model_pricing + system_settings.usd_brl_rate.
  6. Numa UNICA transacao: grava o PAI em public.pais (pais_repo, com supersede +
     status_rule + versao), insere a telemetria em public.agent_run_logs (com
     proveniencia) e carimba questionnaire_sections.agent1_run_id (= "feito").
  7. Heartbeat em public.system_settings['python_worker_heartbeat'].

NAO desativa nada do Python local. O frontend so ENFILEIRA (grava
canonical_response + trava a secao). Este worker consome.

Conexao: usa innova_bridge.db.client (asyncpg, le a DATABASE_URL do BD ativo no
carrossel). RODAR NA MAQUINA DO USUARIO — o sandbox do Cowork nao alcanca o
Supabase pela rede.

Uso:
    python -m innova_bridge.workers.agente1_worker                 # loop continuo
    python -m innova_bridge.workers.agente1_worker --once          # processa 1 e sai
    python -m innova_bridge.workers.agente1_worker --interval 5    # poll a cada 5s
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import time
from datetime import datetime, timezone
from typing import Any, Optional

from innova_bridge.db.client import get_pool
from innova_bridge.repositories import pais_repo


WORKER_VERSION = "agente1_worker_v1.0"
HEARTBEAT_KEY = "python_worker_heartbeat"

# block (questionnaire_block enum) -> discipline_families.id
FAMILY_ID_BY_BLOCK: dict[str, int] = {"exatas": 1, "humanas": 2}

# Quanto tempo (s) ignorar uma secao que acabou de falhar, pra nao martelar.
FAILURE_COOLDOWN_S = 120


# ============================================================================
# Helpers de (de)serializacao — asyncpg devolve jsonb como str por padrao
# ============================================================================

def _as_dict(value: Any) -> dict:
    """Normaliza um campo jsonb que pode vir como dict OU str do asyncpg."""
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value  # type: ignore[return-value]
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {}


def _as_scalar(value: Any) -> Any:
    """Normaliza um jsonb escalar (numero/string) que pode vir como str."""
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


# ============================================================================
# Heartbeat
# ============================================================================

async def write_heartbeat(pool, status: str = "idle", extra: Optional[dict] = None) -> None:
    """Grava/atualiza o heartbeat do worker em system_settings.

    O frontend le isso pra saber se o Python esta no ar (now()-ts < ~60s).
    """
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "version": WORKER_VERSION,
        "status": status,
    }
    if extra:
        payload.update(extra)
    await pool.execute(
        """
        INSERT INTO public.system_settings (key, value, updated_at)
        VALUES ($1, $2::jsonb, now())
        ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = now()
        """,
        HEARTBEAT_KEY, json.dumps(payload),
    )


# ============================================================================
# Config do agente (lida do banco — fonte da verdade = agent_configs)
# ============================================================================

async def read_agent_config(pool, agent_name: str = "profile_builder") -> dict:
    """Le engine/model/strict de public.agent_configs. Defaults seguros se faltar."""
    row = await pool.fetchrow(
        "SELECT engine, model, strict_no_fallback, temperature, max_tokens "
        "FROM public.agent_configs WHERE agent_name = $1::agent_name",
        agent_name,
    )
    if row is None:
        return {"engine": "hybrid", "model": None, "strict_no_fallback": True,
                "temperature": None, "max_tokens": None}
    return {
        "engine": row["engine"] or "hybrid",
        "model": row["model"],
        "strict_no_fallback": bool(row["strict_no_fallback"]),
        "temperature": float(row["temperature"]) if row["temperature"] is not None else None,
        "max_tokens": int(row["max_tokens"]) if row["max_tokens"] is not None else None,
    }


# ============================================================================
# Credenciais da LLM — resolvidas do pool LiteLLM LOCAL (storage_litellm)
# ============================================================================

def resolve_local_creds(model_cfg: Optional[str]) -> Optional[dict]:
    """Acha no pool LiteLLM local o provedor cujo modelo casa com `model_cfg`.

    Ordem de match: exato -> normalizado (sem prefixo 'X/') -> is_active ->
    primeiro do pool. Devolve {provedor, modelo, api_key, base_url} (api_key ja
    decriptada por storage_litellm) ou None.

    Necessario porque o run_hybrid (modo estrito) exige creds diretas, e o
    agent_configs.model pode nao bater 1:1 com a string do pool local
    (ex.: 'models/gemini-2.5-flash' no banco vs 'gemini-2.5-flash' no pool).
    """
    try:
        import storage_litellm as _sl
        pool = _sl.load_ativos()
    except Exception:
        return None
    if not pool:
        return None

    def _norm(m: str) -> str:
        return m.rsplit("/", 1)[-1] if m and "/" in m else (m or "")

    cand = None
    if model_cfg:
        for p in pool:
            if p.get("modelo") == model_cfg:
                cand = p
                break
        if cand is None:
            alvo = _norm(model_cfg)
            for p in pool:
                if _norm(p.get("modelo", "")) == alvo:
                    cand = p
                    break
    if cand is None:
        for p in pool:
            if p.get("is_active"):
                cand = p
                break
    if cand is None:
        cand = pool[0]
    return {
        "provedor": cand.get("provedor", ""),
        "modelo": cand.get("modelo", ""),
        "api_key": cand.get("api_key", "") or "",
        "base_url": cand.get("base_url", "") or None,
    }


# ============================================================================
# Custo — lido de model_pricing + usd_brl_rate (centraliza no banco)
# ============================================================================

async def compute_cost(pool, model: str, t_in: int, t_out: int, t_cache: int) -> tuple[float, float]:
    """Calcula (custo_usd, custo_brl) lendo model_pricing + usd_brl_rate.

    Modelo vazio (native/local) -> (0, 0). Sem linha de preco -> (0, 0) e segue.
    """
    if not model:
        return 0.0, 0.0
    price = await pool.fetchrow(
        """
        SELECT input_price_per_million_usd  AS in_usd,
               output_price_per_million_usd AS out_usd,
               cached_input_price_per_million_usd AS cached_usd
        FROM public.model_pricing
        WHERE regexp_replace(model, '^.*/', '') = regexp_replace($1, '^.*/', '')
          AND effective_until IS NULL
        ORDER BY effective_from DESC
        LIMIT 1
        """,
        model,
    )
    if price is None:
        return 0.0, 0.0
    in_usd = float(price["in_usd"] or 0)
    out_usd = float(price["out_usd"] or 0)
    cached_usd = float(price["cached_usd"] or 0)
    cost_usd = (t_in / 1_000_000) * in_usd \
        + (t_out / 1_000_000) * out_usd \
        + (t_cache / 1_000_000) * cached_usd

    rate_raw = await pool.fetchval(
        "SELECT value FROM public.system_settings WHERE key = 'usd_brl_rate'"
    )
    rate = float(_as_scalar(rate_raw) or 0) or 5.0
    return round(cost_usd, 6), round(cost_usd * rate, 4)


# ============================================================================
# Poll / claim de uma secao pronta
# ============================================================================

async def claim_section(pool, skip_ids: list[str]) -> Optional[dict]:
    """Retorna 1 secao pronta pro Agente 1 (ou None). Ignora ids em cooldown."""
    row = await pool.fetchrow(
        """
        SELECT s.id            AS section_id,
               s.school_id     AS school_id,
               s.block         AS block,
               s.canonical_response AS canonical_response,
               s.locked_by_user_id  AS locked_by_user_id,
               q.student_id    AS student_id,
               q.academic_year AS academic_year
        FROM public.questionnaire_sections s
        JOIN public.questionnaires q ON q.id = s.questionnaire_id
        WHERE s.status = 'locked'
          AND s.agent1_run_id IS NULL
          AND s.canonical_response IS NOT NULL
          AND NOT (s.id = ANY($1::uuid[]))
        ORDER BY s.updated_at ASC
        LIMIT 1
        """,
        skip_ids,
    )
    return dict(row) if row else None


# ============================================================================
# Telemetria — insere em agent_run_logs (dentro da tx do chamador)
# ============================================================================

async def insert_run_log(
    conn,
    *,
    model: str,
    student_id: str,
    family_id: int,
    target_id: Optional[str],
    t_in: int,
    t_out: int,
    t_cache: int,
    cost_usd: float,
    cost_brl: float,
    latency_ms: int,
    status: str,
    prompt_version: Optional[str],
    error_message: Optional[str],
    school_id: str,
    triggered_by_user_id: Optional[str],
    request_source: str = "worker_auto",
) -> str:
    """Insere uma linha em agent_run_logs e devolve o id. agent_name fixo:
    'profile_builder'. request_source vem da origem da submissao."""
    run_id = await conn.fetchval(
        """
        INSERT INTO public.agent_run_logs
            (agent_name, model, student_id, family_id, target_type, target_id,
             input_tokens, output_tokens, cached_input_tokens,
             cost_brl, cost_usd_raw, latency_ms, status, error_message,
             prompt_version, triggered_by_user_id, school_id, request_source)
        VALUES ('profile_builder'::agent_name, $1, $2, $3, 'pai', $4,
                $5, $6, $7, $8, $9, $10, $11::agent_run_status, $12,
                $13, $14, $15, $16)
        RETURNING id
        """,
        model or "", student_id, family_id, target_id,
        int(t_in), int(t_out), int(t_cache),
        cost_brl, cost_usd, int(latency_ms), status, error_message,
        prompt_version, triggered_by_user_id, school_id, request_source,
    )
    return str(run_id)


# ============================================================================
# Processa UMA secao (caminho feliz + erro)
# ============================================================================

async def process_one(pool, skip_ids: list[str]) -> Optional[dict]:
    """Processa 1 secao pronta. Retorna um resumo, ou None se nao havia nenhuma."""
    section = await claim_section(pool, skip_ids)
    if section is None:
        return None

    section_id = str(section["section_id"])
    school_id = str(section["school_id"])
    student_id = str(section["student_id"])
    block = section["block"]
    family_id = FAMILY_ID_BY_BLOCK.get(block)
    canonical = _as_dict(section["canonical_response"])
    triggered_by = (
        _as_dict(canonical.get("meta")).get("submitted_by_user_id")
        or (str(section["locked_by_user_id"]) if section["locked_by_user_id"] else None)
    )
    # Origem da requisicao: vem do canonical.meta.source (ex.: 'web_form' do frontend).
    # Sem meta.source (ex.: seed manual) -> 'worker_auto'.
    req_source = _as_dict(canonical.get("meta")).get("source") or "worker_auto"

    if family_id is None:
        return {"section_id": section_id, "ok": False,
                "error": f"block desconhecido: {block!r}"}

    cfg = await read_agent_config(pool, "profile_builder")
    await write_heartbeat(pool, status="processing", extra={"section_id": section_id})

    # ---- roda o motor (sync) numa thread pra nao travar o event loop ----
    from innova_bridge.agents.agente1.router import gerar_pai

    kwargs: dict[str, Any] = {
        "engine": cfg["engine"],
        "strict_no_fallback": cfg["strict_no_fallback"],
        "salvar": True,    # mantem persistencia LOCAL (aditivo)
        "validar": True,
    }
    # Hybrid/llm exigem credencial: resolve do pool LiteLLM local e passa direto
    # (modo "overrides diretos" do run_hybrid). Native nao precisa de chave.
    creds = resolve_local_creds(cfg["model"]) if cfg["engine"] != "native" else None
    if creds and (creds["api_key"] or creds["base_url"]):
        kwargs["provider_override"] = creds["provedor"]
        kwargs["model_override"] = creds["modelo"]
        kwargs["api_key_override"] = creds["api_key"]
        kwargs["base_url_override"] = creds["base_url"]
    elif cfg["model"]:
        kwargs["model_override"] = cfg["model"]
    if cfg["temperature"] is not None:
        kwargs["temperature_override"] = cfg["temperature"]
    if cfg["max_tokens"] is not None:
        kwargs["max_tokens_override"] = cfg["max_tokens"]

    t0 = time.time()
    try:
        result = await asyncio.to_thread(gerar_pai, canonical, **kwargs)
    except Exception as e:  # noqa: BLE001 — qualquer falha do motor vira run de erro
        result = {"ok": False, "mensagem": f"{type(e).__name__}: {e}",
                  "telemetria_engine": {}, "pai": {}}
    latency_ms = int((time.time() - t0) * 1000)

    tele = result.get("telemetria_engine") or {}
    if cfg["engine"] == "native":
        model_used = "native-deterministic"
    else:
        model_used = tele.get("modelo") or kwargs.get("model_override") or (cfg["model"] or "")
    t_in = int(tele.get("tokens_in", 0) or 0)
    t_out = int(tele.get("tokens_out", 0) or 0)
    t_cache = int(tele.get("tokens_cache", 0) or 0)
    cost_usd, cost_brl = await compute_cost(pool, model_used, t_in, t_out, t_cache)

    # ---- ERRO: loga run de erro, NAO carimba agent1_run_id (retry futuro) ----
    if not result.get("ok") or not result.get("pai"):
        msg = (result.get("mensagem") or "motor retornou PAI vazio")[:1000]
        async with pool.acquire() as conn:
            async with conn.transaction():
                await insert_run_log(
                    conn, model=model_used, student_id=student_id, family_id=family_id,
                    target_id=None, t_in=t_in, t_out=t_out, t_cache=t_cache,
                    cost_usd=cost_usd, cost_brl=cost_brl, latency_ms=latency_ms,
                    status="error", prompt_version=None, error_message=msg,
                    school_id=school_id, triggered_by_user_id=triggered_by,
                    request_source=req_source,
                )
        await write_heartbeat(pool, status="idle")
        return {"section_id": section_id, "ok": False, "error": msg}

    pai = result["pai"]
    generated_by = (pai.get("meta") or {}).get("created_by") or "ProfileBuilder_py"
    status_pai = pais_repo.status_from_pai(pai)

    # ---- SUCESSO: PAI + log + carimbo, tudo atomico ----
    async with pool.acquire() as conn:
        async with conn.transaction():
            superseded = await pais_repo.supersede_vigentes(conn, student_id, family_id)
            version = await pais_repo.next_version(conn, student_id, family_id)
            pai_id = await pais_repo.insert_pai(
                conn, school_id=school_id, student_id=student_id, family_id=family_id,
                section_id=section_id, content=pai, generated_by_agent=generated_by,
                version=version, status=status_pai, created_via=req_source,
            )
            run_id = await insert_run_log(
                conn, model=model_used, student_id=student_id, family_id=family_id,
                target_id=pai_id, t_in=t_in, t_out=t_out, t_cache=t_cache,
                cost_usd=cost_usd, cost_brl=cost_brl, latency_ms=latency_ms,
                status="success", prompt_version=generated_by, error_message=None,
                school_id=school_id, triggered_by_user_id=triggered_by,
                request_source=req_source,
            )
            await conn.execute(
                "UPDATE public.questionnaire_sections "
                "SET agent1_run_id = $1, updated_at = now() WHERE id = $2",
                run_id, section_id,
            )

    await write_heartbeat(pool, status="idle")
    return {
        "section_id": section_id, "ok": True, "pai_id": pai_id, "version": version,
        "status": status_pai, "superseded": superseded, "model": model_used,
        "cost_brl": cost_brl, "latency_ms": latency_ms,
    }


# ============================================================================
# Processa UM upload de CSV (frontend -> Backend Central -> PAI por família)
# ============================================================================

async def claim_upload(pool, skip_ids: list[str]) -> Optional[dict]:
    """Pega 1 upload pendente e marca como 'processing' (atômico). None se não há."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id, school_id, student_id, raw_content, engine, created_by_user_id
                FROM public.questionnaire_uploads
                WHERE status = 'pending'
                  AND NOT (id = ANY($1::uuid[]))
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                skip_ids,
            )
            if row is None:
                return None
            await conn.execute(
                "UPDATE public.questionnaire_uploads SET status='processing' WHERE id=$1",
                row["id"],
            )
            return dict(row)


async def process_one_upload(pool, skip_ids: list[str]) -> Optional[dict]:
    """Processa 1 upload: CSV -> adapter -> motor -> 1 PAI por família (2A)."""
    up = await claim_upload(pool, skip_ids)
    if up is None:
        return None

    upload_id = str(up["id"])
    school_id = str(up["school_id"])
    student_id = str(up["student_id"])
    created_by = str(up["created_by_user_id"]) if up["created_by_user_id"] else None
    raw = up["raw_content"] or ""

    cfg = await read_agent_config(pool, "profile_builder")
    engine = up["engine"] or cfg["engine"]
    await write_heartbeat(pool, status="processing", extra={"upload_id": upload_id})

    # 1) CSV -> canonical (adapter Python existente). source aceita texto cru.
    try:
        from innova_bridge.formularios.adapters.from_neei_v3_0 import (
            csv_to_questionnaire_response,
        )
        canonical = await asyncio.to_thread(csv_to_questionnaire_response, raw, 0)
    except Exception as e:  # noqa: BLE001
        msg = f"parse CSV falhou: {type(e).__name__}: {e}"[:1000]
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE public.questionnaire_uploads "
                "SET status='failed', error_message=$2, processed_at=now() WHERE id=$1",
                up["id"], msg,
            )
        await write_heartbeat(pool, status="idle")
        return {"upload_id": upload_id, "ok": False, "error": msg}

    # 2) Motor (mesma resolução de credencial do fluxo de seção).
    from innova_bridge.agents.agente1.router import gerar_pai

    kwargs: dict[str, Any] = {
        "engine": engine, "strict_no_fallback": cfg["strict_no_fallback"],
        "salvar": True, "validar": True,
    }
    creds = resolve_local_creds(cfg["model"]) if engine != "native" else None
    if creds and (creds["api_key"] or creds["base_url"]):
        kwargs["provider_override"] = creds["provedor"]
        kwargs["model_override"] = creds["modelo"]
        kwargs["api_key_override"] = creds["api_key"]
        kwargs["base_url_override"] = creds["base_url"]
    elif cfg["model"]:
        kwargs["model_override"] = cfg["model"]

    t0 = time.time()
    try:
        result = await asyncio.to_thread(gerar_pai, canonical, **kwargs)
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "mensagem": f"{type(e).__name__}: {e}",
                  "telemetria_engine": {}, "pai": {}}
    latency_ms = int((time.time() - t0) * 1000)

    tele = result.get("telemetria_engine") or {}
    if engine == "native":
        model_used = "native-deterministic"
    else:
        model_used = tele.get("modelo") or kwargs.get("model_override") or (cfg["model"] or "")
    t_in = int(tele.get("tokens_in", 0) or 0)
    t_out = int(tele.get("tokens_out", 0) or 0)
    t_cache = int(tele.get("tokens_cache", 0) or 0)
    cost_usd, cost_brl = await compute_cost(pool, model_used, t_in, t_out, t_cache)

    # ERRO: loga + marca upload failed.
    if not result.get("ok") or not result.get("pai"):
        msg = (result.get("mensagem") or "motor retornou PAI vazio")[:1000]
        async with pool.acquire() as conn:
            async with conn.transaction():
                await insert_run_log(
                    conn, model=model_used, student_id=student_id, family_id=None,
                    target_id=None, t_in=t_in, t_out=t_out, t_cache=t_cache,
                    cost_usd=cost_usd, cost_brl=cost_brl, latency_ms=latency_ms,
                    status="error", prompt_version=None, error_message=msg,
                    school_id=school_id, triggered_by_user_id=created_by,
                    request_source="web_form",
                )
                await conn.execute(
                    "UPDATE public.questionnaire_uploads "
                    "SET status='failed', error_message=$2, processed_at=now() WHERE id=$1",
                    up["id"], msg,
                )
        await write_heartbeat(pool, status="idle")
        return {"upload_id": upload_id, "ok": False, "error": msg}

    pai = result["pai"]
    generated_by = (pai.get("meta") or {}).get("created_by") or "ProfileBuilder_py"
    status_pai = pais_repo.status_from_pai(pai)

    # SUCESSO: 1 PAI ÚNICO (family 1 = Exatas/Matemática, padrão por enquanto) +
    # 1 run log + upload done — tudo atômico.
    # NOTA: NÃO duplicar por família. O Agente 2 lê UM perfil. Se um dia for
    # por família, gerar conteúdo DISTINTO por família (não cópia).
    pai_ids: list[str] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for fam in (1,):
                await pais_repo.supersede_vigentes(conn, student_id, fam)
                ver = await pais_repo.next_version(conn, student_id, fam)
                pid = await pais_repo.insert_pai(
                    conn, school_id=school_id, student_id=student_id, family_id=fam,
                    section_id=None, content=pai, generated_by_agent=generated_by,
                    version=ver, status=status_pai, created_via="web_form",
                )
                pai_ids.append(pid)
            await insert_run_log(
                conn, model=model_used, student_id=student_id, family_id=None,
                target_id=pai_ids[0], t_in=t_in, t_out=t_out, t_cache=t_cache,
                cost_usd=cost_usd, cost_brl=cost_brl, latency_ms=latency_ms,
                status="success", prompt_version=generated_by, error_message=None,
                school_id=school_id, triggered_by_user_id=created_by,
                request_source="web_form",
            )
            await conn.execute(
                "UPDATE public.questionnaire_uploads "
                "SET status='done', processed_at=now(), result_pai_ids=$2 WHERE id=$1",
                up["id"], pai_ids,
            )

    await write_heartbeat(pool, status="idle")
    return {
        "upload_id": upload_id, "ok": True, "pai_ids": pai_ids,
        "model": model_used, "cost_brl": cost_brl, "latency_ms": latency_ms,
    }


# ============================================================================
# Loop principal
# ============================================================================

async def run(once: bool = False, interval: float = 10.0) -> None:
    pool = await get_pool()
    cooldown: dict[str, float] = {}  # section_id -> timestamp ate quando ignorar
    print(f"[{WORKER_VERSION}] iniciado. once={once} interval={interval}s")
    await write_heartbeat(pool, status="idle")

    while True:
        now = time.time()
        skip = [sid for sid, until in cooldown.items() if until > now]

        try:
            res = await process_one(pool, skip)            # seções (canonical_response)
            if res is None:
                res = await process_one_upload(pool, skip)  # uploads de CSV (Google)
        except Exception as e:  # noqa: BLE001 — loop nao pode morrer
            print(f"[worker] erro inesperado no ciclo: {type(e).__name__}: {e}")
            res = {"ok": False, "error": str(e)}

        if res is None:
            if once:
                print("[worker] nada pendente. saindo (--once).")
                break
        elif res.get("ok"):
            if res.get("section_id"):
                print(f"[worker] OK secao={res['section_id']} PAI={res['pai_id']} "
                      f"v{res['version']} ({res['status']}) "
                      f"R$ {res['cost_brl']:.4f} {res['latency_ms']}ms")
            else:
                print(f"[worker] OK upload={res['upload_id']} "
                      f"PAIs={','.join(res.get('pai_ids', []))} "
                      f"modelo={res.get('model')} R$ {res['cost_brl']:.4f} {res['latency_ms']}ms")
            if once:
                break
        else:
            jid = res.get("section_id") or res.get("upload_id")
            if jid:
                cooldown[jid] = time.time() + FAILURE_COOLDOWN_S
                print(f"[worker] FALHA {jid}: {res.get('error')} "
                      f"(cooldown {FAILURE_COOLDOWN_S}s)")
            if once:
                break

        await write_heartbeat(pool, status="idle")
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker do Agente 1 (Supabase poll).")
    parser.add_argument("--once", action="store_true", help="processa 1 e sai")
    parser.add_argument("--interval", type=float, default=10.0, help="segundos entre polls")
    args = parser.parse_args()
    asyncio.run(run(once=args.once, interval=args.interval))


if __name__ == "__main__":
    main()
