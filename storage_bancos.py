"""
storage_bancos.py — Carrossel de Bancos de Dados (Supabase pool).

Análogo cirúrgico do storage_gemini.py, mas para o domínio de BDs Supabase.
Cada banco cadastrado vira um "card" no painel de Configurações, com
status visual e ações (ativar / editar / remover / ping).

PERSISTÊNCIA:
  - Arquivo `bancos_pool.json` na raiz do projeto.
  - Campos sensíveis (anon_key, service_role, database_url, db_password)
    são criptografados com Fernet via utils_cripto antes de gravar.
  - Quem lê o BD em runtime usa `get_active_bd_decifrado()`, que devolve
    o dict pronto pra conectar (com campos já decifrados).

ESTADOS DOS BANCOS:
  - 'active'        🔵 Em uso (o is_primary=True ATIVO)
  - 'reserve'       🟢 Disponível como reserva
  - 'offline'       🔴 Falhou no último ping
  - 'untested'      ⚪ Cadastrado mas sem ping desde o boot

BOOTSTRAP:
  - Função `bootstrap_do_br_credentials()` importa automaticamente o
    arquivo `br-credentials.json` (do projeto Innova V2) se ele existir
    em qualquer um dos caminhos conhecidos. Roda 1 vez só (idempotente).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import requests

from utils_cripto import encriptar, decriptar, mascarar

# ============================================================================
# Constantes
# ============================================================================

ARQUIVO_POOL = "bancos_pool.json"
PING_TIMEOUT_S = 4  # tempo máximo de resposta antes de marcar offline
CAMPOS_SENSIVEIS = ("anon_key", "service_role", "database_url", "db_password")

# Caminhos onde procuramos o br-credentials.json pra bootstrap automático.
# A ordem importa: o primeiro que existir vence.
CAMINHOS_BR_CREDS_CONHECIDOS = (
    "br-credentials.json",
    "Migração BD/innova-v2-python-handoff-v2/backups/migration-2026-05-26/br-credentials.json",
    "Migração BD/br-credentials.json",
)


# ============================================================================
# Persistência crua (raw I/O — campos sensíveis em texto cifrado)
# ============================================================================

def _caminho_pool() -> Path:
    """Caminho absoluto do bancos_pool.json (ancorado neste módulo)."""
    return Path(__file__).resolve().parent / ARQUIVO_POOL


def load_pool() -> list[dict]:
    """Carrega a lista de bancos. Retorna [] se o arquivo não existir."""
    caminho = _caminho_pool()
    if not caminho.exists():
        return []
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("bancos", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_pool(pool: list[dict]) -> None:
    """Grava a lista de bancos no disco (sobrescreve)."""
    caminho = _caminho_pool()
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"bancos": pool}, f, indent=2, ensure_ascii=False)


# ============================================================================
# Helpers internos
# ============================================================================

def _encriptar_campos(bd: dict) -> dict:
    """Devolve uma cópia do dict com os campos sensíveis cifrados."""
    saida = dict(bd)
    for campo in CAMPOS_SENSIVEIS:
        valor = saida.get(campo, "")
        # Só re-encripta se for texto puro (sem o prefixo do Fernet 'gAAAA').
        # Isso evita encriptar 2x se a UI chamar save em sequência.
        if valor and not str(valor).startswith("gAAAA"):
            saida[campo] = encriptar(str(valor))
    return saida


def _decriptar_campos(bd: dict) -> dict:
    """Devolve uma cópia do dict com os campos sensíveis decifrados."""
    saida = dict(bd)
    for campo in CAMPOS_SENSIVEIS:
        token = saida.get(campo, "")
        if token:
            saida[campo] = decriptar(str(token))
    return saida


def _novo_id() -> str:
    """Gera um id curto pra novo banco (ex.: 'bd_a1b2c3d4')."""
    return f"bd_{uuid.uuid4().hex[:8]}"


def _agora_iso() -> str:
    """Timestamp ISO local, sem microsegundos (legível)."""
    from datetime import datetime
    return datetime.now().replace(microsecond=0).isoformat()


# ============================================================================
# API pública — leitura
# ============================================================================

def listar_bancos(decifrar_para_ui: bool = True) -> list[dict]:
    """Lista todos os bancos cadastrados.

    Se `decifrar_para_ui=True` (default), retorna os campos sensíveis
    em texto puro — usado pelo formulário de Editar.
    Se `False`, retorna como está em disco (cifrado).
    """
    pool = load_pool()
    if not decifrar_para_ui:
        return pool
    return [_decriptar_campos(bd) for bd in pool]


def buscar_bd(bd_id: str, decifrar: bool = True) -> Optional[dict]:
    """Retorna o BD por id, ou None se não existir."""
    for bd in load_pool():
        if bd.get("id") == bd_id:
            return _decriptar_campos(bd) if decifrar else bd
    return None


def get_active_bd_decifrado() -> Optional[dict]:
    """Retorna o BD marcado como `is_primary=True` E `status='active'`.

    Esse é o método que o resto do sistema (futuro innova_bridge/db/client.py)
    chama pra montar a connection string em runtime.
    Retorna None se nenhum banco ativo for encontrado.
    """
    pool = load_pool()
    for bd in pool:
        if bd.get("is_primary") and bd.get("status") == "active":
            return _decriptar_campos(bd)
    # fallback: qualquer ativo
    for bd in pool:
        if bd.get("status") == "active":
            return _decriptar_campos(bd)
    return None


# ============================================================================
# API pública — escrita (CRUD)
# ============================================================================

def adicionar_banco(
    label: str,
    project_id: str,
    region: str,
    supabase_url: str,
    anon_key: str = "",
    service_role: str = "",
    database_url: str = "",
    db_password: str = "",
    tornar_primary: bool = False,
) -> tuple[bool, str, Optional[str]]:
    """Cadastra um novo banco. Retorna (ok, mensagem, novo_id)."""
    if not label or not supabase_url:
        return False, "Label e Supabase URL são obrigatórios.", None

    pool = load_pool()

    # Evita duplicar mesmo project_id
    if any(bd.get("project_id") == project_id for bd in pool if project_id):
        return False, f"Já existe um banco cadastrado com project_id '{project_id}'.", None

    novo = {
        "id": _novo_id(),
        "label": label,
        "project_id": project_id,
        "region": region,
        "supabase_url": supabase_url.rstrip("/"),
        "anon_key": anon_key,
        "service_role": service_role,
        "database_url": database_url,
        "db_password": db_password,
        "is_primary": False,
        "status": "untested",
        "last_ping_ms": None,
        "last_ping_at": None,
        "added_at": _agora_iso(),
    }

    novo = _encriptar_campos(novo)
    pool.append(novo)

    # Se for o primeiro banco do pool, ele já vira o ativo principal.
    if len(pool) == 1 or tornar_primary:
        for bd in pool:
            bd["is_primary"] = (bd["id"] == novo["id"])
        # garante que o novo principal está ativo
        for bd in pool:
            if bd["id"] == novo["id"]:
                bd["status"] = "active"

    save_pool(pool)
    return True, f"Banco '{label}' cadastrado com sucesso.", novo["id"]


def atualizar_banco(bd_id: str, campos: dict) -> tuple[bool, str]:
    """Atualiza um banco existente. Só campos enviados são alterados.

    Campos sensíveis enviados em texto puro serão re-encriptados.
    Campo sensível enviado como "" significa "manter o valor atual".
    """
    pool = load_pool()
    alvo = None
    for bd in pool:
        if bd.get("id") == bd_id:
            alvo = bd
            break
    if not alvo:
        return False, "Banco não encontrado."

    # aplica somente os campos enviados (preserva sensíveis vazios)
    for k, v in campos.items():
        if k in CAMPOS_SENSIVEIS:
            if v:  # só atualiza sensível se veio valor
                alvo[k] = v
        else:
            alvo[k] = v

    # marca como untested ao mexer em qualquer credencial sensível
    if any(k in CAMPOS_SENSIVEIS for k in campos):
        alvo["status"] = "untested"
        alvo["last_ping_ms"] = None

    # encripta o que precisar
    alvo_cif = _encriptar_campos(alvo)
    for i, bd in enumerate(pool):
        if bd.get("id") == bd_id:
            pool[i] = alvo_cif
            break

    save_pool(pool)
    return True, "Banco atualizado."


def remover_banco(bd_id: str) -> tuple[bool, str]:
    """Remove um banco do pool. Bloqueia remoção do ativo principal."""
    pool = load_pool()
    alvo = next((bd for bd in pool if bd.get("id") == bd_id), None)
    if not alvo:
        return False, "Banco não encontrado."
    if alvo.get("is_primary"):
        return False, "Não dá pra remover o banco que está EM USO. Ative outro primeiro."

    pool = [bd for bd in pool if bd.get("id") != bd_id]
    save_pool(pool)
    return True, "Banco removido."


def ativar_banco(bd_id: str) -> tuple[bool, str]:
    """Promove um banco a is_primary=True e marca os outros como reserva."""
    pool = load_pool()
    alvo = next((bd for bd in pool if bd.get("id") == bd_id), None)
    if not alvo:
        return False, "Banco não encontrado."

    for bd in pool:
        if bd["id"] == bd_id:
            bd["is_primary"] = True
            bd["status"] = "active"
        else:
            bd["is_primary"] = False
            # quem era 'active' vira 'reserve'; quem era 'offline' continua offline
            if bd.get("status") == "active":
                bd["status"] = "reserve"

    save_pool(pool)
    return True, f"Banco '{alvo.get('label')}' agora é o EM USO."


def marcar_offline(bd_id: str) -> None:
    """Marca um banco como offline (usado pelo ping ou por falha em runtime)."""
    pool = load_pool()
    for bd in pool:
        if bd.get("id") == bd_id:
            bd["status"] = "offline"
    save_pool(pool)


def marcar_status(bd_id: str, status: str, ping_ms: Optional[int] = None) -> None:
    """Atualiza status (active/reserve/offline/untested) e opcionalmente o ping."""
    pool = load_pool()
    for bd in pool:
        if bd.get("id") == bd_id:
            bd["status"] = status
            if ping_ms is not None:
                bd["last_ping_ms"] = ping_ms
                bd["last_ping_at"] = _agora_iso()
    save_pool(pool)


# ============================================================================
# Ping / health check
# ============================================================================

def testar_ping(bd_id: str) -> tuple[bool, str, Optional[int]]:
    """Faz um HEAD no endpoint REST do Supabase pra medir latência.

    Não precisa do password do BD nem de asyncpg — usa só a anon_key
    e o supabase_url. Se a resposta vier OK em <PING_TIMEOUT_S, marca como ativo.
    Retorna (ok, mensagem, latência_ms).
    """
    bd = buscar_bd(bd_id, decifrar=True)
    if not bd:
        return False, "Banco não encontrado.", None

    url = f"{bd['supabase_url']}/rest/v1/"
    headers = {
        "apikey": bd.get("anon_key", ""),
        "Authorization": f"Bearer {bd.get('anon_key', '')}",
    }
    inicio = time.perf_counter()
    try:
        resp = requests.head(url, headers=headers, timeout=PING_TIMEOUT_S)
        latencia_ms = int((time.perf_counter() - inicio) * 1000)
        # 200 ou 401 (sem permissão) ambos indicam que o projeto está vivo.
        # 404/5xx ou exceção indicam problema real.
        if resp.status_code < 500:
            # se este BD era o ativo principal, mantém active; senão reserve.
            novo_status = "active" if bd.get("is_primary") else "reserve"
            marcar_status(bd_id, novo_status, latencia_ms)
            return True, f"Conexão OK em {latencia_ms} ms (HTTP {resp.status_code})", latencia_ms
        else:
            marcar_offline(bd_id)
            return False, f"Servidor retornou HTTP {resp.status_code}.", latencia_ms
    except requests.exceptions.Timeout:
        marcar_offline(bd_id)
        return False, f"Timeout após {PING_TIMEOUT_S}s.", None
    except requests.exceptions.RequestException as e:
        marcar_offline(bd_id)
        return False, f"Erro de rede: {type(e).__name__}", None


# ============================================================================
# Diagnostico de rede (DNS, TCP, TLS, HTTP warm)
# ============================================================================

def diagnostico_rede_supabase(bd_id: str, n_pings: int = 5) -> dict:
    """Mede separadamente cada componente da latencia ate o Supabase.

    Retorna dict com:
      - dns_ms:        tempo de resolucao DNS do hostname
      - tcp_ms:        tempo de conexao TCP pura (sem TLS)
      - tls_ms:        tempo de handshake TLS (mede session quente)
      - http_first_ms: 1o ping HTTP (inclui DNS+TCP+TLS+HEAD)
      - http_warm_ms:  lista dos pings 2..N (session reaproveitada)
      - http_avg_warm: media dos pings warm
      - http_min_warm: minimo dos pings warm
      - http_max_warm: maximo dos pings warm
      - host:          hostname pingado
      - erros:         lista de erros encontrados
    """
    import socket
    import ssl
    from urllib.parse import urlparse

    bd = buscar_bd(bd_id, decifrar=True)
    if not bd:
        return {"erro": "Banco nao encontrado"}

    url = bd.get("supabase_url", "")
    if not url:
        return {"erro": "Supabase URL vazia"}

    parsed = urlparse(url)
    host = parsed.hostname
    porta = parsed.port or (443 if parsed.scheme == "https" else 80)

    resultado = {
        "host": host,
        "porta": porta,
        "dns_ms": None,
        "tcp_ms": None,
        "tls_ms": None,
        "http_first_ms": None,
        "http_warm_ms": [],
        "http_avg_warm": None,
        "http_min_warm": None,
        "http_max_warm": None,
        "erros": [],
    }

    # ── 1) DNS lookup ──
    try:
        t0 = time.perf_counter()
        ip = socket.gethostbyname(host)
        resultado["dns_ms"] = int((time.perf_counter() - t0) * 1000)
        resultado["resolved_ip"] = ip
    except Exception as e:
        resultado["erros"].append(f"DNS falhou: {e}")
        return resultado

    # ── 2) TCP connect puro (sem TLS) ──
    try:
        t0 = time.perf_counter()
        s = socket.create_connection((host, porta), timeout=5)
        resultado["tcp_ms"] = int((time.perf_counter() - t0) * 1000)
        s.close()
    except Exception as e:
        resultado["erros"].append(f"TCP falhou: {e}")
        return resultado

    # ── 3) TLS handshake (TCP + handshake) ──
    try:
        ctx = ssl.create_default_context()
        t0 = time.perf_counter()
        with socket.create_connection((host, porta), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls_sock:
                pass  # handshake completo
        # Subtraimos o TCP medido antes pra isolar o TLS
        total_tls_ms = int((time.perf_counter() - t0) * 1000)
        resultado["tls_ms"] = max(0, total_tls_ms - (resultado["tcp_ms"] or 0))
    except Exception as e:
        resultado["erros"].append(f"TLS falhou: {e}")

    # ── 4) Pings HTTP em sequencia com session reaproveitada ──
    rest_url = f"{url.rstrip('/')}/rest/v1/"
    headers = {
        "apikey": bd.get("anon_key", ""),
        "Authorization": f"Bearer {bd.get('anon_key', '')}",
    }

    try:
        with requests.Session() as sess:
            # Primeiro ping (frio - inclui DNS/TCP/TLS)
            t0 = time.perf_counter()
            sess.head(rest_url, headers=headers, timeout=5)
            resultado["http_first_ms"] = int((time.perf_counter() - t0) * 1000)

            # Pings subsequentes (warm - reusa conexao TCP+TLS)
            for _ in range(max(1, n_pings - 1)):
                t1 = time.perf_counter()
                sess.head(rest_url, headers=headers, timeout=5)
                ms = int((time.perf_counter() - t1) * 1000)
                resultado["http_warm_ms"].append(ms)
    except Exception as e:
        resultado["erros"].append(f"HTTP falhou: {e}")

    # Estatisticas dos pings warm
    if resultado["http_warm_ms"]:
        lst = resultado["http_warm_ms"]
        resultado["http_avg_warm"] = int(sum(lst) / len(lst))
        resultado["http_min_warm"] = min(lst)
        resultado["http_max_warm"] = max(lst)

    return resultado


# ============================================================================
# Bootstrap — importa br-credentials.json automaticamente
# ============================================================================

def bootstrap_do_br_credentials(forcar: bool = False) -> tuple[bool, str]:
    """Procura `br-credentials.json` em caminhos conhecidos e importa.

    Idempotente: se o pool já tem o mesmo project_id, não importa de novo
    (a menos que forcar=True, que sobrescreve).
    """
    base = Path(__file__).resolve().parent
    encontrado = None
    for relativo in CAMINHOS_BR_CREDS_CONHECIDOS:
        caminho = base / relativo
        if caminho.exists():
            encontrado = caminho
            break

    if not encontrado:
        return False, "Arquivo br-credentials.json não encontrado em nenhum caminho conhecido."

    try:
        with open(encontrado, "r", encoding="utf-8") as f:
            creds = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, f"Falha ao ler {encontrado.name}: {e}"

    project_id = creds.get("project_id", "")
    if not project_id:
        return False, f"Arquivo {encontrado.name} sem 'project_id' — formato inesperado."

    pool = load_pool()
    ja_existe = any(bd.get("project_id") == project_id for bd in pool)

    if ja_existe and not forcar:
        return False, f"Já existe um banco cadastrado com project_id '{project_id}'. Use Editar."

    if ja_existe and forcar:
        # remove o antigo antes de re-adicionar
        pool = [bd for bd in pool if bd.get("project_id") != project_id]
        save_pool(pool)

    ok, msg, novo_id = adicionar_banco(
        label=creds.get("name", "Importado do br-credentials"),
        project_id=project_id,
        region=creds.get("region", ""),
        supabase_url=creds.get("supabase_url", ""),
        anon_key=creds.get("anon_key", ""),
        service_role=creds.get("service_role", ""),
        database_url=creds.get("database_url", ""),
        db_password=creds.get("db_password", ""),
        tornar_primary=(len(load_pool()) == 0),  # primeiro do pool vira ativo
    )

    if ok:
        return True, f"Banco '{creds.get('name')}' importado de {encontrado.name}."
    return False, msg


# ============================================================================
# Helpers visuais (consumidos pela página Streamlit)
# ============================================================================

def emoji_status(status: str) -> str:
    """Mapeia status técnico → emoji visual."""
    return {
        "active": "🔵",
        "reserve": "🟢",
        "offline": "🔴",
        "untested": "⚪",
    }.get(status, "⚪")


def label_status(status: str) -> str:
    """Mapeia status técnico → label PT-BR."""
    return {
        "active": "EM USO",
        "reserve": "DISPONÍVEL (Reserva)",
        "offline": "OFFLINE",
        "untested": "NÃO TESTADO",
    }.get(status, "DESCONHECIDO")


def bandeira_regiao(region: str) -> str:
    """Mapeia região AWS → bandeira (visual no card)."""
    if not region:
        return "🌐"
    r = region.lower()
    if "sa-east" in r:
        return "🇧🇷"
    if "us-east" in r or "us-west" in r:
        return "🇺🇸"
    if "eu-" in r:
        return "🇪🇺"
    if "ap-" in r:
        return "🌏"
    return "🌐"


def cor_latencia(ms: Optional[int]) -> str:
    """Devolve um indicador visual de qualidade de latência."""
    if ms is None:
        return "⚪"
    if ms < 50:
        return "🟢"
    if ms < 150:
        return "🟡"
    return "🔴"


def mascarar_credencial(token: str) -> str:
    """Reexporta o mascarador do utils_cripto (conveniência)."""
    return mascarar(token)


def arquivo_pool_existe() -> bool:
    """True se o bancos_pool.json já foi criado."""
    return _caminho_pool().exists()
