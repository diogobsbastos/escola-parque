"""
backend_auth.py — Cadastro de usuários COM login (Escola Parque V3)
-------------------------------------------------------------------
Cria contas de acesso de ponta a ponta, tudo na nossa VPS:

  1. Cria o LOGIN no GoTrue (auth.users) via API admin — jeito correto, que
     trata hash de senha, identities e colunas obrigatórias (nada de SQL cru
     no auth.users, que já nos deu dor de cabeça).
  2. Insere/atualiza o public.users (id, email, full_name, role, school_id).
     (No nosso GoTrue self-hosted NÃO há trigger que crie o public.users, então
     fazemos isso aqui explicitamente.)
  3. Faz o vínculo do papel:
       - student  -> student_access (access_type='self')
       - guardian -> student_access (access_type='guardian')
       - aee      -> student_support (acompanha o aluno)
       - teacher/coordinator/admin -> só o public.users (vínculos de turma/
         matéria são feitos nas telas de Associação).
  4. (Opcional) manda o e-mail de boas-vindas com a senha provisória, usando
     os canais configurados em Configurar E-mail (failover).

Config (GoTrue URL + service_role + database_url) vem do BD ATIVO do carrossel
(innova_bridge.config / storage_bancos). Trocar o BD ativo reflete aqui.
"""

from __future__ import annotations

import secrets
from typing import Optional

import requests

from innova_bridge.config import get_bd_ativo
from innova_bridge.db.client import run_async, get_pool

# Papéis válidos (espelha o enum user_role do banco).
PAPEIS_VALIDOS = ("admin", "coordinator", "teacher", "aee", "student", "guardian")

# Rótulos amigáveis pra UI.
PAPEL_LABEL = {
    "admin": "Diretor / Admin do colégio",
    "coordinator": "Coordenação",
    "teacher": "Professor",
    "aee": "Apoio (AEE)",
    "student": "Aluno",
    "guardian": "Responsável",
}


# ════════════════════════════════════════════════════════════════════
# Senha provisória
# ════════════════════════════════════════════════════════════════════
def gerar_senha_provisoria(tamanho: int = 10) -> str:
    """Gera uma senha provisória legível (sem caracteres ambíguos)."""
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    nucleo = "".join(secrets.choice(alfabeto) for _ in range(tamanho))
    # garante ao menos 1 símbolo + 1 dígito (políticas comuns de senha)
    return f"{nucleo}@{secrets.choice('23456789')}"


# ════════════════════════════════════════════════════════════════════
# GoTrue (auth.users) via API admin
# ════════════════════════════════════════════════════════════════════
def _gotrue_base_e_chave():
    """Retorna (base_url_auth, service_role) do BD ativo."""
    bd = get_bd_ativo()
    base = (bd.get("supabase_url") or "").rstrip("/")
    service = bd.get("service_role") or ""
    if not base:
        raise RuntimeError("BD ativo sem supabase_url — configure no carrossel de Bancos.")
    if not service:
        raise RuntimeError("BD ativo sem service_role — configure no carrossel de Bancos.")
    return base, service


def criar_login_gotrue(email: str, senha: str, full_name: str, role: str,
                       school_id: str) -> tuple[bool, Optional[str], str]:
    """Cria o usuário no GoTrue (auth.users). Retorna (ok, user_id, mensagem)."""
    base, service = _gotrue_base_e_chave()
    url = f"{base}/auth/v1/admin/users"
    headers = {
        "apikey": service,
        "Authorization": f"Bearer {service}",
        "Content-Type": "application/json",
    }
    body = {
        "email": email,
        "password": senha,
        "email_confirm": True,  # já confirma — a senha provisória é o acesso
        "user_metadata": {
            "full_name": full_name,
            "role": role,
            "school_id": school_id,
        },
    }
    try:
        r = requests.post(url, json=body, headers=headers, timeout=20)
    except requests.RequestException as e:
        return False, None, f"Erro de rede ao falar com o GoTrue: {type(e).__name__}: {e}"

    if r.status_code in (200, 201):
        data = r.json()
        uid = data.get("id") or (data.get("user") or {}).get("id")
        if not uid:
            return False, None, f"GoTrue criou mas não retornou id. Resposta: {str(data)[:200]}"
        return True, uid, "Login criado no GoTrue."
    if r.status_code in (409, 422):
        return False, None, f"E-mail já existe ou inválido (GoTrue {r.status_code}): {r.text[:200]}"
    return False, None, f"GoTrue retornou {r.status_code}: {r.text[:200]}"


# ════════════════════════════════════════════════════════════════════
# public.users + vínculos (asyncpg)
# ════════════════════════════════════════════════════════════════════
async def _upsert_public_user(pool, user_id, email, full_name, role, school_id):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.users (id, school_id, email, full_name, role, active)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::user_role, true)
            ON CONFLICT (id) DO UPDATE SET
                school_id = EXCLUDED.school_id,
                email     = EXCLUDED.email,
                full_name = EXCLUDED.full_name,
                role      = EXCLUDED.role,
                active    = true,
                updated_at = now()
            """,
            user_id, school_id, email, full_name, role,
        )


async def _vincular_student_access(pool, user_id, student_id, access_type):
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO public.student_access (user_id, student_id, access_type)
               VALUES ($1::uuid, $2::uuid, $3::student_access_type)""",
            user_id, student_id, access_type,
        )


async def _vincular_student_support(pool, user_id, student_id):
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO public.student_support (student_id, support_user_id)
               VALUES ($1::uuid, $2::uuid)""",
            student_id, user_id,
        )


# ════════════════════════════════════════════════════════════════════
# Leituras pra UI (escolas, alunos, usuários)
# ════════════════════════════════════════════════════════════════════
async def _fetch(pool, sql, *args):
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


def listar_escolas() -> list:
    pool = run_async(get_pool())
    return run_async(_fetch(
        pool, "SELECT id::text, name FROM public.schools ORDER BY name"))


def listar_alunos(school_id: Optional[str] = None) -> list:
    pool = run_async(get_pool())
    if school_id:
        return run_async(_fetch(
            pool,
            """SELECT id::text, code, full_name FROM public.students
               WHERE archived_at IS NULL AND school_id = $1::uuid
               ORDER BY full_name""",
            school_id))
    return run_async(_fetch(
        pool,
        """SELECT id::text, code, full_name FROM public.students
           WHERE archived_at IS NULL ORDER BY full_name"""))


def listar_usuarios() -> list:
    pool = run_async(get_pool())
    return run_async(_fetch(
        pool,
        """SELECT u.id::text, u.email, u.full_name, u.role::text AS role,
                  u.active, s.name AS escola
           FROM public.users u
           LEFT JOIN public.schools s ON s.id = u.school_id
           ORDER BY u.created_at DESC NULLS LAST"""))


# ════════════════════════════════════════════════════════════════════
# Orquestrador: cadastra o usuário COMPLETO
# ════════════════════════════════════════════════════════════════════
def cadastrar_usuario(email: str, full_name: str, role: str, school_id: str,
                      senha: Optional[str] = None,
                      student_id: Optional[str] = None) -> dict:
    """Cria login + public.users + vínculo do papel.

    Retorna dict: {ok, etapa, mensagem, user_id, senha}.
    'etapa' diz onde parou (gotrue/public_users/vinculo/done) pra debug na UI.
    NÃO envia e-mail — quem chama decide (a UI mostra a senha e oferece enviar).
    """
    email = (email or "").strip().lower()
    full_name = (full_name or "").strip()
    if role not in PAPEIS_VALIDOS:
        return {"ok": False, "etapa": "validacao", "mensagem": f"Papel inválido: {role}"}
    if not email or "@" not in email:
        return {"ok": False, "etapa": "validacao", "mensagem": "E-mail inválido."}
    if not full_name:
        return {"ok": False, "etapa": "validacao", "mensagem": "Nome completo é obrigatório."}
    if not school_id:
        return {"ok": False, "etapa": "validacao", "mensagem": "Selecione o colégio."}
    if role in ("student", "guardian") and not student_id:
        return {"ok": False, "etapa": "validacao",
                "mensagem": "Para aluno/responsável, selecione o aluno a vincular."}

    senha = senha or gerar_senha_provisoria()

    # 1) GoTrue
    ok, user_id, msg = criar_login_gotrue(email, senha, full_name, role, school_id)
    if not ok:
        return {"ok": False, "etapa": "gotrue", "mensagem": msg}

    # 2) public.users
    try:
        pool = run_async(get_pool())
        run_async(_upsert_public_user(pool, user_id, email, full_name, role, school_id))
    except Exception as e:
        return {"ok": False, "etapa": "public_users", "user_id": user_id,
                "mensagem": f"Login criado, mas falhou o public.users: {type(e).__name__}: {e}"}

    # 3) vínculo do papel
    try:
        if role == "student":
            run_async(_vincular_student_access(pool, user_id, student_id, "self"))
        elif role == "guardian":
            run_async(_vincular_student_access(pool, user_id, student_id, "guardian"))
        elif role == "aee" and student_id:
            run_async(_vincular_student_support(pool, user_id, student_id))
    except Exception as e:
        return {"ok": True, "etapa": "vinculo", "user_id": user_id, "senha": senha,
                "mensagem": f"Usuário criado, mas o vínculo falhou: {type(e).__name__}: {e}"}

    return {"ok": True, "etapa": "done", "user_id": user_id, "senha": senha,
            "mensagem": "Usuário criado com login."}


# ════════════════════════════════════════════════════════════════════
# E-mail de boas-vindas (usa os canais de Configurar E-mail, com failover)
# ════════════════════════════════════════════════════════════════════
def enviar_boas_vindas(email: str, full_name: str, senha: str,
                       url_login: str = "") -> tuple:
    """Manda a senha provisória pro novo usuário. Retorna (ok, log_resumido)."""
    try:
        from email_sender import enviar_email
    except Exception as e:
        return False, f"email_sender indisponível: {e}"

    link = url_login or "o endereço de acesso da Escola Parque"
    corpo = (
        f"<h2>Bem-vindo(a), {full_name}!</h2>"
        f"<p>Sua conta de acesso à <b>Escola Parque</b> foi criada.</p>"
        f"<p><b>E-mail:</b> {email}<br>"
        f"<b>Senha provisória:</b> {senha}</p>"
        f"<p>Acesse em: {link}</p>"
        f"<p style='color:#666'>Por segurança, troque a senha no primeiro acesso.</p>"
    )
    ok, canal, log = enviar_email(
        destinatario=email,
        assunto="Seu acesso à Escola Parque",
        corpo_html=corpo,
    )
    return ok, (f"Enviado por {canal}" if ok else " | ".join(log))
