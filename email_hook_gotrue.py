"""
email_hook_gotrue.py — Serviço HTTP para GoTrue Send Email Hook (Innova Exams / Escola Parque V3)
=====================================================================================================
Este serviço recebe o webhook do GoTrue quando ele precisa enviar e-mails de autenticação
(recovery, signup, magiclink, invite, email_change, reauthentication) e os despacha através
do motor de e-mail dinâmico do backend (email_sender.py + canais_email.json com failover).

Requisitos:
    fastapi, uvicorn[standard]  — já estão no requirements.txt do projeto.

Como rodar (manualmente, para teste):
    GOTRUE_SEND_EMAIL_HOOK_SECRET=<seu_secret_base64> \\
        uvicorn email_hook_gotrue:app --host 127.0.0.1 --port 8502

Para produção, use o unit systemd 'escolaparque-emailhook.service' descrito no RUNBOOK.

Variáveis de ambiente:
    GOTRUE_SEND_EMAIL_HOOK_SECRET  (obrigatório)
        O mesmo valor configurado no GoTrue como GOTRUE_HOOK_SEND_EMAIL_SECRETS=v1,whsec_<secret>.
        Aqui informe APENAS a parte base64 (sem o prefixo 'whsec_'), OU o valor completo
        'whsec_<base64>' — o código aceita os dois formatos.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import textwrap
from urllib.parse import quote as url_quote, urlparse, parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("email_hook_gotrue")

# ---------------------------------------------------------------------------
# Importa o motor de e-mail do backend (mesmo diretório / PYTHONPATH)
# ---------------------------------------------------------------------------
try:
    from email_sender import enviar_email  # noqa: E402
except ImportError as exc:
    logger.error(
        "Não foi possível importar email_sender.py. "
        "Certifique-se de rodar este serviço a partir do diretório /home/ubuntu/escola-parque. "
        "Erro original: %s",
        exc,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="GoTrue Send Email Hook — Innova Exams",
    description="Recebe o webhook de e-mail do GoTrue e envia via motor de e-mail dinâmico.",
    version="1.1.0",
)

# ---------------------------------------------------------------------------
# Helpers de assinatura (Standard Webhooks — hmac-sha256)
# ---------------------------------------------------------------------------

def _carregar_secret() -> bytes:
    """
    Lê GOTRUE_SEND_EMAIL_HOOK_SECRET e retorna os bytes brutos do segredo.
    Aceita:
      - Só a parte base64:  'abc123=='
      - Com prefixo whsec_:  'whsec_abc123=='
    """
    raw = os.environ.get("GOTRUE_SEND_EMAIL_HOOK_SECRET", "").strip()
    if not raw:
        raise RuntimeError(
            "Variável de ambiente GOTRUE_SEND_EMAIL_HOOK_SECRET não definida. "
            "O serviço não pode validar assinaturas sem ela."
        )
    if raw.startswith("whsec_"):
        raw = raw[len("whsec_"):]
    return base64.b64decode(raw)


def _verificar_assinatura(secret_bytes: bytes, webhook_id: str, webhook_timestamp: str, raw_body: bytes, signature_header: str) -> bool:
    """
    Verifica a assinatura Standard Webhooks.

    Mensagem assinada:  "{webhook-id}.{webhook-timestamp}.{raw_body_str}"
    O header 'webhook-signature' pode conter múltiplas assinaturas separadas por espaço:
        v1,<base64sig1> v1,<base64sig2>
    Basta que UMA delas bata.
    """
    msg_to_sign = f"{webhook_id}.{webhook_timestamp}.".encode() + raw_body
    expected_bytes = hmac.new(secret_bytes, msg_to_sign, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(expected_bytes).decode()

    # Compara com cada assinatura recebida
    for token in signature_header.split():
        # formato: v1,<base64>
        parts = token.split(",", 1)
        if len(parts) != 2:
            continue
        _version, received_b64 = parts
        try:
            received_bytes = base64.b64decode(received_b64)
        except Exception:
            continue
        if hmac.compare_digest(expected_bytes, received_bytes):
            return True

    return False


# ---------------------------------------------------------------------------
# Helper: montar URL de verificação apontando para o frontend Next.js
# ---------------------------------------------------------------------------

def _montar_verification_url(
    site_url: str,
    token_hash: str,
    email_action_type: str,
    redirect_to: str,
) -> str:
    """
    Monta a URL de verificação apontando para a rota do frontend Next.js
    /auth/confirm, que chama supabase.auth.verifyOtp({ token_hash, type })
    e redireciona o usuário para o destino final.

    Formato:
        {base}/auth/confirm
            ?token_hash={token_hash}
            &type={email_action_type}
            &next={next_path}

    A base é derivada como scheme://host de site_url (ou redirect_to como
    fallback), descartando qualquer path (ex.: /auth/v1) que o GoTrue possa
    incluir no site_url. Isso evita URLs duplicadas como /auth/v1/auth/confirm.

    O parâmetro `next` é extraído do `redirect_to` recebido pelo GoTrue:
      - Se redirect_to vier com ?next=/alguma/rota, extrai esse valor.
      - Se redirect_to for uma URL do próprio site (ex.: https://dominio.com/app/foo),
        extrai o path (/app/foo).
      - Caso contrário, usa /app/configuracoes/senha (padrão para recovery).
    """
    next_path = "/app/configuracoes/senha"  # padrão seguro

    if redirect_to:
        try:
            parsed = urlparse(redirect_to)
            # Tenta extrair ?next= do próprio redirect_to
            qs = parse_qs(parsed.query)
            if "next" in qs:
                next_path = qs["next"][0]
            elif parsed.path and parsed.path not in ("/", ""):
                # Usa o path da URL como destino final
                next_path = parsed.path
                if parsed.query:
                    next_path += "?" + parsed.query
        except Exception:
            pass  # mantém o padrão

    # Deriva base como scheme://host, descartando qualquer path que venha no
    # site_url (ex.: GoTrue envia https://dominio.com/auth/v1 — queremos só
    # https://dominio.com para não duplicar o path na URL final).
    _src = site_url or redirect_to or ""
    _p = urlparse(_src)
    if _p.scheme and _p.netloc:
        base = _p.scheme + "://" + _p.netloc
    else:
        base = site_url.rstrip("/")

    # Calculamos os valores encoded em variáveis para evitar barras invertidas
    # dentro de expressões f-string (SyntaxError no Python 3.10).
    next_safe_chars = "/:@!$&'()*+,;="
    tok_encoded = url_quote(token_hash, safe="")
    type_encoded = url_quote(email_action_type, safe="")
    next_encoded = url_quote(next_path, safe=next_safe_chars)
    url = (
        f"{base}/auth/confirm"
        f"?token_hash={tok_encoded}"
        f"&type={type_encoded}"
        f"&next={next_encoded}"
    )
    return url


# ---------------------------------------------------------------------------
# Templates de e-mail por tipo de ação
# ---------------------------------------------------------------------------

_CONFIGS_POR_TIPO = {
    "recovery": {
        "assunto": "Innova Exams — Redefinir sua senha",
        "titulo": "Redefinir sua senha",
        "intro": "Recebemos uma solicitação para redefinir a senha da sua conta <strong>Innova Exams</strong>.",
        "botao": "Redefinir senha",
        "aviso": "Se você não solicitou a redefinição de senha, ignore este e-mail. Sua senha permanece a mesma.",
    },
    "signup": {
        "assunto": "Innova Exams — Confirme seu cadastro",
        "titulo": "Bem-vindo ao Innova Exams!",
        "intro": "Obrigado por se cadastrar. Clique no botão abaixo para confirmar seu endereço de e-mail e ativar sua conta.",
        "botao": "Confirmar e-mail",
        "aviso": "Se você não criou esta conta, ignore este e-mail.",
    },
    "magiclink": {
        "assunto": "Innova Exams — Seu link de acesso",
        "titulo": "Acesse sua conta",
        "intro": "Use o botão abaixo para entrar na sua conta <strong>Innova Exams</strong> sem precisar de senha. O link expira em 60 minutos.",
        "botao": "Entrar agora",
        "aviso": "Se você não solicitou este acesso, ignore este e-mail.",
    },
    "invite": {
        "assunto": "Innova Exams — Você foi convidado",
        "titulo": "Convite para o Innova Exams",
        "intro": "Você foi convidado a criar uma conta no <strong>Innova Exams</strong>. Clique no botão abaixo para aceitar o convite e definir sua senha.",
        "botao": "Aceitar convite",
        "aviso": "Se você não esperava este convite, pode ignorar este e-mail com segurança.",
    },
    "email_change": {
        "assunto": "Innova Exams — Confirme seu novo e-mail",
        "titulo": "Confirmar alteração de e-mail",
        "intro": "Recebemos uma solicitação para alterar o e-mail da sua conta <strong>Innova Exams</strong>. Clique no botão para confirmar o novo endereço.",
        "botao": "Confirmar novo e-mail",
        "aviso": "Se você não solicitou esta alteração, ignore este e-mail e entre em contato com o suporte.",
    },
    "reauthentication": {
        "assunto": "Innova Exams — Código de reautenticação",
        "titulo": "Código de verificação",
        "intro": "Use o código abaixo para confirmar sua identidade no <strong>Innova Exams</strong>.",
        "botao": "Verificar identidade",
        "aviso": "Se você não solicitou este código, ignore este e-mail.",
    },
}

_FALLBACK_CONFIG = {
    "assunto": "Innova Exams — Ação necessária",
    "titulo": "Ação necessária na sua conta",
    "intro": "Clique no botão abaixo para continuar.",
    "botao": "Continuar",
    "aviso": "Se você não solicitou esta ação, ignore este e-mail.",
}


def _montar_corpo_html(
    cfg: dict,
    verification_url: str,
    token_otp: str | None,
    email_action_type: str,
) -> str:
    """
    Gera o corpo HTML do e-mail.
    Para 'reauthentication', exibe o token OTP em destaque além do botão.
    """
    otp_block = ""
    if email_action_type == "reauthentication" and token_otp:
        otp_block = f"""
        <tr>
          <td style="padding: 12px 40px 0; text-align: center;">
            <p style="margin: 0 0 6px; color: #555; font-size: 14px;">Seu código:</p>
            <p style="margin: 0; font-size: 36px; font-weight: bold; letter-spacing: 8px;
                       color: #1a56db; font-family: monospace;">{token_otp}</p>
          </td>
        </tr>"""

    return textwrap.dedent(f"""\
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{cfg['assunto']}</title>
    </head>
    <body style="margin: 0; padding: 0; background-color: #f4f6f9; font-family: Arial, sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f6f9; padding: 32px 0;">
        <tr>
          <td align="center">
            <table width="600" cellpadding="0" cellspacing="0"
                   style="background: #ffffff; border-radius: 8px;
                          box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow: hidden;">

              <!-- Cabeçalho -->
              <tr>
                <td style="background: #1a56db; padding: 28px 40px; text-align: center;">
                  <h1 style="margin: 0; color: #ffffff; font-size: 22px; font-weight: 700;
                             letter-spacing: 1px;">Innova Exams</h1>
                </td>
              </tr>

              <!-- Corpo -->
              <tr>
                <td style="padding: 36px 40px 20px;">
                  <h2 style="margin: 0 0 16px; color: #1a1a2e; font-size: 20px;">{cfg['titulo']}</h2>
                  <p style="margin: 0 0 24px; color: #444; font-size: 15px; line-height: 1.6;">
                    {cfg['intro']}
                  </p>
                </td>
              </tr>

              {otp_block}

              <!-- Botão -->
              <tr>
                <td style="padding: 0 40px 28px; text-align: center;">
                  <a href="{verification_url}"
                     style="display: inline-block; padding: 14px 36px;
                            background-color: #1a56db; color: #ffffff;
                            text-decoration: none; border-radius: 6px;
                            font-size: 16px; font-weight: 600;">
                    {cfg['botao']}
                  </a>
                </td>
              </tr>

              <!-- Link texto (fallback) -->
              <tr>
                <td style="padding: 0 40px 12px; text-align: center;">
                  <p style="margin: 0; color: #888; font-size: 12px;">Ou copie e cole este link no navegador:</p>
                  <p style="margin: 4px 0 0; word-break: break-all;">
                    <a href="{verification_url}" style="color: #1a56db; font-size: 12px;">{verification_url}</a>
                  </p>
                </td>
              </tr>

              <!-- Aviso -->
              <tr>
                <td style="padding: 16px 40px 32px;">
                  <p style="margin: 0; color: #888; font-size: 13px; line-height: 1.5;">
                    {cfg['aviso']}
                  </p>
                </td>
              </tr>

              <!-- Rodapé -->
              <tr>
                <td style="background: #f4f6f9; padding: 18px 40px; text-align: center;
                           border-top: 1px solid #e8ecf0;">
                  <p style="margin: 0; color: #aaa; font-size: 12px;">
                    &copy; 2025 Innova Exams &mdash; Escola Parque
                  </p>
                </td>
              </tr>

            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Verificação de saúde do serviço."""
    return {"status": "ok", "service": "email_hook_gotrue"}


@app.post("/hook/send-email")
async def hook_send_email(request: Request) -> Response:
    """
    Endpoint receptor do GoTrue Send Email Hook.

    Fluxo:
    1. Lê body raw.
    2. Valida assinatura HMAC-SHA256 (Standard Webhooks).
    3. Parseia JSON e extrai user + email_data.
    4. Monta URL de verificação apontando para /auth/confirm do frontend Next.js.
    5. Envia via email_sender.enviar_email (com failover).
    6. Responde 200 {} em sucesso.
    """
    # --- 1. Ler body ---
    raw_body = await request.body()

    # --- 2. Verificar assinatura ---
    webhook_id = request.headers.get("webhook-id", "")
    webhook_timestamp = request.headers.get("webhook-timestamp", "")
    webhook_signature = request.headers.get("webhook-signature", "")

    if not all([webhook_id, webhook_timestamp, webhook_signature]):
        logger.warning("Requisição sem headers de assinatura Standard Webhooks — rejeitada.")
        return JSONResponse(status_code=401, content={"error": "Missing webhook signature headers"})

    try:
        secret_bytes = _carregar_secret()
    except RuntimeError as exc:
        logger.error("Erro ao carregar secret: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})

    if not _verificar_assinatura(secret_bytes, webhook_id, webhook_timestamp, raw_body, webhook_signature):
        logger.warning(
            "Assinatura inválida — webhook_id=%s timestamp=%s",
            webhook_id,
            webhook_timestamp,
        )
        return JSONResponse(status_code=401, content={"error": "Invalid webhook signature"})

    # --- 3. Parsear payload ---
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        logger.error("Payload JSON inválido: %s", exc)
        return JSONResponse(status_code=400, content={"error": "Invalid JSON payload"})

    user = payload.get("user", {})
    email_data = payload.get("email_data", {})

    # Destinatário: para email_change usa new_email; caso contrário usa email
    email_action_type = email_data.get("email_action_type", "")
    destinatario = user.get("new_email") or user.get("email", "")

    if not destinatario:
        logger.error("Payload sem e-mail de destinatário. user=%s", user)
        return JSONResponse(status_code=400, content={"error": "Missing recipient email in payload"})

    token_hash = email_data.get("token_hash", "")
    token_otp = email_data.get("token", "")
    redirect_to = email_data.get("redirect_to", "")
    site_url = email_data.get("site_url", "").rstrip("/")

    # --- 4. Montar URL de verificação → rota /auth/confirm do frontend Next.js ---
    # A rota /auth/confirm chama supabase.auth.verifyOtp({ token_hash, type })
    # e redireciona para `next` após verificação bem-sucedida.
    # Isso evita o 404 causado pelo link antigo /auth/v1/verify que caía no Next.js.
    verification_url = _montar_verification_url(
        site_url=site_url,
        token_hash=token_hash,
        email_action_type=email_action_type,
        redirect_to=redirect_to,
    )

    logger.info(
        "URL de verificação montada: tipo='%s' url='%s'",
        email_action_type,
        verification_url,
    )

    # --- 4b. Selecionar config de texto e montar HTML ---
    cfg = _CONFIGS_POR_TIPO.get(email_action_type, _FALLBACK_CONFIG)
    corpo_html = _montar_corpo_html(cfg, verification_url, token_otp, email_action_type)
    assunto = cfg["assunto"]

    # --- 5. Enviar via motor de e-mail ---
    logger.info(
        "Enviando e-mail tipo='%s' para='%s' via motor de e-mail com failover.",
        email_action_type,
        destinatario,
    )
    try:
        ok, canal_usado, log_envio = enviar_email(
            destinatario=destinatario,
            assunto=assunto,
            corpo_html=corpo_html,
        )
    except Exception as exc:
        logger.exception("Excessão inesperada ao chamar enviar_email: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": f"Unexpected error in email_sender: {exc}"},
        )

    if not ok:
        logger.error(
            "Todos os canais falharam ao enviar e-mail tipo='%s' para='%s'. Log: %s",
            email_action_type,
            destinatario,
            log_envio,
        )
        return JSONResponse(
            status_code=500,
            content={"error": "All email channels failed", "detail": log_envio},
        )

    logger.info(
        "E-mail tipo='%s' enviado com sucesso via canal='%s' para='%s'.",
        email_action_type,
        canal_usado,
        destinatario,
    )
    return JSONResponse(status_code=200, content={})
