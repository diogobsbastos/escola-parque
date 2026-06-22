"""
pagina_login_google.py — Painel "Login com Google (OAuth)" (Escola Parque V3)
------------------------------------------------------------------------------
Permite ao admin configurar o OAuth do Google no GoTrue sem tocar no servidor.
Lê e escreve /home/ubuntu/gotrue.env (upsert linha a linha) e reinicia o GoTrue
via systemctl.

Para o botão de restart funcionar em 1 clique, o usuário ubuntu precisa de:
    ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart gotrue
em /etc/sudoers.d/gotrue-restart (ou equivalente).
"""

import subprocess
import streamlit as st

_GOTRUE_ENV_PATH = "/home/ubuntu/gotrue.env"
_DEFAULT_REDIRECT = "https://escolaparque-app.duckdns.org/auth/v1/callback"
_JS_ORIGIN = "https://escolaparque-app.duckdns.org"

# Chaves que gerenciamos
_KEY_ENABLED = "GOTRUE_EXTERNAL_GOOGLE_ENABLED"
_KEY_CLIENT_ID = "GOTRUE_EXTERNAL_GOOGLE_CLIENT_ID"
_KEY_SECRET = "GOTRUE_EXTERNAL_GOOGLE_SECRET"
_KEY_REDIRECT = "GOTRUE_EXTERNAL_GOOGLE_REDIRECT_URI"

# Chaves do gotrue.env usadas para derivar a Redirect URI quando não configurada
_URL_KEYS = [
    "GOTRUE_API_EXTERNAL_URL",
    "GOTRUE_EXTERNAL_URL",
    "GOTRUE_SITE_URL",
]


def _parse_gotrue_env(path: str) -> dict:
    """Lê o arquivo gotrue.env e retorna um dict {CHAVE: valor}.
    Ignora linhas comentadas (#) e linhas sem '='.
    Retorna dict vazio em caso de erro."""
    resultado = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.rstrip("\n")
                if linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                resultado[chave.strip()] = valor.strip()
    except Exception:
        pass
    return resultado


def _upsert_gotrue_env(path: str, updates: dict) -> tuple[bool, str]:
    """Faz upsert das chaves em `updates` no arquivo `path`.
    Para cada chave: se a linha já existe, substitui; senão, acrescenta ao final.
    Retorna (True, "") em caso de sucesso, (False, mensagem_erro) em caso de falha."""
    try:
        # Lê conteúdo atual
        try:
            with open(path, "r", encoding="utf-8") as f:
                linhas = f.readlines()
        except FileNotFoundError:
            linhas = []

        chaves_atualizadas = set()
        novas_linhas = []
        for linha in linhas:
            stripped = linha.rstrip("\n")
            if "=" in stripped and not stripped.startswith("#"):
                chave = stripped.partition("=")[0].strip()
                if chave in updates:
                    # Substitui a linha
                    novas_linhas.append(f"{chave}={updates[chave]}\n")
                    chaves_atualizadas.add(chave)
                    continue
            novas_linhas.append(linha)

        # Acrescenta chaves que não existiam
        for chave, valor in updates.items():
            if chave not in chaves_atualizadas:
                novas_linhas.append(f"{chave}={valor}\n")

        with open(path, "w", encoding="utf-8") as f:
            f.writelines(novas_linhas)

        return True, ""
    except PermissionError:
        return False, f"Sem permissão para escrever em {path}. O usuário do Streamlit precisa ter acesso de escrita ao arquivo."
    except Exception as e:
        return False, str(e)


def _restart_gotrue() -> tuple[bool, str]:
    """Tenta reiniciar o serviço GoTrue via sudo systemctl.
    Retorna (sucesso, mensagem)."""
    try:
        resultado = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", "gotrue"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if resultado.returncode == 0:
            return True, ""
        stderr = (resultado.stderr or "").strip()
        return False, stderr
    except subprocess.TimeoutExpired:
        return False, "Timeout ao tentar reiniciar o GoTrue (30s)."
    except FileNotFoundError:
        return False, "Comando 'sudo' não encontrado no PATH do Streamlit."
    except Exception as e:
        return False, str(e)


def render_pagina_login_google():
    st.markdown("## 🔐 Login com Google (OAuth)")
    st.caption(
        "Configure as credenciais OAuth do Google para habilitar o login social "
        "no GoTrue (Supabase Auth). As alterações são escritas em "
        f"`{_GOTRUE_ENV_PATH}` e o serviço é reiniciado automaticamente."
    )

    # ── Leitura do estado atual ──────────────────────────────────────────────
    env = _parse_gotrue_env(_GOTRUE_ENV_PATH)
    if not env:
        st.warning(
            f"Não foi possível ler `{_GOTRUE_ENV_PATH}` (arquivo ausente ou sem permissão). "
            "Os campos ficarão em branco — preencha e salve normalmente."
        )

    atual_enabled = env.get(_KEY_ENABLED, "false").lower() == "true"
    atual_client_id = env.get(_KEY_CLIENT_ID, "")
    atual_secret = env.get(_KEY_SECRET, "")

    # Derivação da Redirect URI
    atual_redirect = env.get(_KEY_REDIRECT, "")
    if not atual_redirect:
        for url_key in _URL_KEYS:
            base = env.get(url_key, "").rstrip("/")
            if base:
                atual_redirect = base + "/callback"
                break
    if not atual_redirect:
        atual_redirect = _DEFAULT_REDIRECT

    # ── Instruções para o Google Cloud Console ───────────────────────────────
    with st.expander("📖 Onde criar as credenciais no Google Cloud (passo a passo)", expanded=False):
        st.markdown(
            "1. Acesse o **Google Cloud Console** pelo botão abaixo.\n"
            "2. Selecione (ou crie) um projeto.\n"
            "3. Vá em **APIs & Serviços → Credenciais → Criar credencial → ID do cliente OAuth 2.0**.\n"
            "4. Tipo de aplicativo: **Aplicativo da Web**.\n"
            "5. Em **Origens JavaScript autorizadas**, adicione:\n"
            f"   - `{_JS_ORIGIN}`\n"
            f"6. Em **URIs de redirecionamento autorizados**, adicione:\n"
            f"   - `{atual_redirect}`\n"
            "7. Copie o **Client ID** e o **Client Secret** e cole nos campos abaixo."
        )
        st.link_button(
            "🔗 Abrir Google Cloud Console — Credenciais",
            "https://console.cloud.google.com/apis/credentials",
            use_container_width=True,
        )

    # ── Valores para copiar ──────────────────────────────────────────────────
    st.markdown("#### Valores para cadastrar no Google Cloud")
    col_a, col_b = st.columns(2)
    with col_a:
        st.text_input(
            "Redirect URI autorizado (copie este valor)",
            value=atual_redirect,
            disabled=True,
            key="_google_redirect_display",
        )
    with col_b:
        st.text_input(
            "Origem JavaScript autorizada (copie este valor)",
            value=_JS_ORIGIN,
            disabled=True,
            key="_google_jsorigin_display",
        )

    st.divider()

    # ── Formulário de configuração ───────────────────────────────────────────
    st.markdown("#### Configuração OAuth")

    habilitado = st.checkbox(
        "Habilitar login com Google",
        value=atual_enabled,
        key="google_oauth_habilitado",
    )

    client_id = st.text_input(
        "Google Client ID",
        value=atual_client_id,
        placeholder="123456789012-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.apps.googleusercontent.com",
        key="google_oauth_client_id",
    )

    # Secret: se já existe no arquivo, mostra placeholder em vez do valor real
    secret_placeholder = "(mantém o valor atual — deixe em branco para não alterar)" if atual_secret else ""
    client_secret = st.text_input(
        "Google Client Secret",
        value="",
        placeholder=secret_placeholder or "Cole o Client Secret aqui",
        type="password",
        key="google_oauth_client_secret",
    )

    redirect_uri = st.text_input(
        "Redirect URI",
        value=atual_redirect,
        key="google_oauth_redirect_uri",
    )

    st.divider()

    # ── Botão salvar ─────────────────────────────────────────────────────────
    if st.button("💾 Salvar e aplicar (reinicia o GoTrue)", type="primary", use_container_width=True):
        # Monta as atualizações
        updates = {
            _KEY_ENABLED: "true" if habilitado else "false",
            _KEY_CLIENT_ID: client_id.strip(),
            _KEY_REDIRECT: redirect_uri.strip(),
        }

        # Secret: só atualiza se o usuário preencheu algo
        secret_valor = client_secret.strip()
        if secret_valor:
            updates[_KEY_SECRET] = secret_valor
        elif not atual_secret:
            # Não havia secret e o campo ficou vazio — avisa mas não bloqueia
            st.warning(
                "O campo Client Secret está vazio e não havia valor anterior. "
                "O GoTrue será reiniciado, mas o login com Google provavelmente não funcionará sem o secret."
            )

        # Escreve o arquivo
        ok_env, erro_env = _upsert_gotrue_env(_GOTRUE_ENV_PATH, updates)
        if not ok_env:
            st.error(f"Falha ao salvar `{_GOTRUE_ENV_PATH}`: {erro_env}")
            return

        # Reinicia o GoTrue
        ok_restart, stderr_restart = _restart_gotrue()
        if ok_restart:
            st.success(
                "✅ Configuração salva e GoTrue reiniciado com sucesso! "
                "O login com Google já deve estar ativo."
            )
        else:
            st.warning(
                f"⚠️ As configurações foram salvas em `{_GOTRUE_ENV_PATH}`, "
                "mas **não foi possível reiniciar o GoTrue automaticamente**.\n\n"
                f"Erro: `{stderr_restart}`\n\n"
                "Execute manualmente na VPS:"
            )
            st.code("sudo systemctl restart gotrue", language="bash")

    # ── Status atual (informativo) ───────────────────────────────────────────
    st.divider()
    st.markdown("#### Estado atual lido do arquivo")
    if env:
        col1, col2 = st.columns(2)
        with col1:
            status_label = "🟢 Habilitado" if atual_enabled else "🔴 Desabilitado"
            st.metric("Status Google OAuth", status_label)
            st.caption(f"Client ID: `{atual_client_id or '(não configurado)'}` ")
        with col2:
            st.caption(f"Redirect URI: `{env.get(_KEY_REDIRECT, '(não configurado)')}`")
            st.caption(f"Secret: {'`(configurado)`' if atual_secret else '`(não configurado)`'}")
    else:
        st.info(f"Arquivo `{_GOTRUE_ENV_PATH}` não encontrado ou ilegível.")
