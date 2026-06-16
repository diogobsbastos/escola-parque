"""
email_sender.py — Motor de envio com FAILOVER (Escola Parque V3)
-----------------------------------------------------------------
Percorre os canais cadastrados em storage_email (ordem de prioridade) e tenta
enviar. Se o canal falha (auth, conexão, timeout), marca status='falhou' e
passa pro PRÓXIMO automaticamente. Para no primeiro que entregar.

Uso típico (no cadastro de logins, reset de senha, avisos):
    from email_sender import enviar_email
    ok, canal, log = enviar_email(
        destinatario="prof@colegio.com",
        assunto="Seu acesso à Escola Parque",
        corpo_html="<h1>Bem-vindo</h1><p>Sua senha provisória...</p>",
    )

Não depende de Streamlit — pode ser chamado por workers/scripts também.
"""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import storage_email


def _html_para_texto(html):
    """Fallback bobo: tira tags pra ter um corpo texto-plano mínimo."""
    import re
    texto = re.sub(r"<br\s*/?>", "\n", html or "", flags=re.IGNORECASE)
    texto = re.sub(r"</p>", "\n\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", "", texto)
    return texto.strip()


def _enviar_via_canal(canal, destinatario, assunto, corpo_html, corpo_texto):
    """Tenta UM envio por UM canal. Levanta exceção em caso de falha."""
    host = canal.get("host")
    porta = int(canal.get("porta", 587) or 587)
    seguranca = (canal.get("seguranca") or "starttls").lower()
    usuario = canal.get("usuario")
    senha = canal.get("senha")
    rem_email = canal.get("remetente_email") or usuario
    rem_nome = canal.get("remetente_nome") or "Escola Parque"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = formataddr((rem_nome, rem_email))
    msg["To"] = destinatario

    texto = corpo_texto or _html_para_texto(corpo_html)
    msg.attach(MIMEText(texto, "plain", "utf-8"))
    msg.attach(MIMEText(corpo_html or texto, "html", "utf-8"))

    contexto = ssl.create_default_context()

    if seguranca == "ssl":
        with smtplib.SMTP_SSL(host, porta, context=contexto, timeout=20) as server:
            server.login(usuario, senha)
            server.sendmail(rem_email, [destinatario], msg.as_string())
    else:  # starttls (default)
        with smtplib.SMTP(host, porta, timeout=20) as server:
            server.ehlo()
            server.starttls(context=contexto)
            server.ehlo()
            server.login(usuario, senha)
            server.sendmail(rem_email, [destinatario], msg.as_string())


def enviar_email(destinatario, assunto, corpo_html, corpo_texto=None, canal_forcado=None):
    """Envia um e-mail com failover entre os canais habilitados.

    Args:
        destinatario:  e-mail de destino.
        assunto:       linha de assunto.
        corpo_html:    corpo em HTML.
        corpo_texto:   (opcional) corpo texto-plano; se ausente, deriva do HTML.
        canal_forcado: (opcional) nome de um canal específico — pula o failover
                       e usa só ele (útil no botão 'Testar envio').

    Returns:
        (ok: bool, canal_usado: str|None, log: list[str])
        log traz uma linha por canal tentado ('OK' ou o erro), pra debug na UI.
    """
    log = []

    if canal_forcado:
        todos = storage_email.load_canais()
        canais = [c for c in todos if (c.get("nome") or "") == canal_forcado]
        if not canais:
            return False, None, [f"Canal '{canal_forcado}' não encontrado."]
    else:
        canais = storage_email.get_canais_ordenados(somente_habilitados=True)

    if not canais:
        return False, None, ["Nenhum canal de e-mail habilitado. Cadastre um em 'Configurar E-mail'."]

    for canal in canais:
        nome = canal.get("nome", "?")
        try:
            _enviar_via_canal(canal, destinatario, assunto, corpo_html, corpo_texto)
            storage_email.update_status(nome, "ativo", f"Envio OK para {destinatario}")
            log.append(f"[{nome}] OK — entregue ao servidor SMTP.")
            return True, nome, log
        except smtplib.SMTPAuthenticationError:
            erro = "Falha de autenticação (usuário/app-password incorretos)."
            storage_email.update_status(nome, "falhou", erro)
            log.append(f"[{nome}] FALHOU — {erro}")
        except Exception as e:  # conexão, timeout, DNS, etc.
            erro = f"{type(e).__name__}: {e}"
            storage_email.update_status(nome, "falhou", erro)
            log.append(f"[{nome}] FALHOU — {erro}")

    return False, None, log
