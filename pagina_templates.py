"""
pagina_templates.py — Seleção do Template do Frontend (Escola Parque V3)
-----------------------------------------------------------------------
Cada template do frontend é uma BRANCH independente do repo
`escola-parque-frontend`. A VPS publica sempre a branch `main`. "Ativar" um
template aponta a `main` para o HEAD da branch escolhida (via API do GitHub) e
a VPS redeploya em ~2 min. O build-gate protege: se o template novo não buildar,
a produção continua no atual.

O template ATIVO é detectado comparando o HEAD da `main` com o HEAD de cada
branch — fonte de verdade real (não depende de arquivo local).

Token: REUSA a credencial que a VPS já usa (env GITHUB_TOKEN/GH_TOKEN ->
~/.git-credentials -> URL do remote dos repos locais). Precisa de Contents:write.

Cores por template: persistidas em `_template_cores.json` ao lado deste arquivo
e aplicadas em `public.schools.brand_primary` / `brand_primary_dark` via
innova_bridge.db.client (mesmo padrão de backend_auth.py).
"""

import json
import os

import requests
import streamlit as st

from innova_bridge.db.client import get_pool, run_async

REPO_OWNER = "diogobsbastos"
REPO_FRONT = "escola-parque-frontend"

_GIT_CRED_PATHS = [
    os.path.expanduser("~/.git-credentials"),
    "/home/ubuntu/.git-credentials",
]
_GIT_CONFIGS = [
    "/home/ubuntu/innova-front/.git/config",
    "/home/ubuntu/escola-parque/.git/config",
]

# Arquivo JSON ao lado deste módulo
_CORES_JSON = os.path.join(os.path.dirname(__file__), "_template_cores.json")

TEMPLATES = [
    {
        "id": "antigo",
        "nome": "Template Antigo",
        "branch": "template-antigo",
        "desc": "O original da Escola Parque (burgundy + Base UI). Estável.",
        "cor_editavel": False,
    },
    {
        "id": "intermediario",
        "nome": "Template Intermediário",
        "branch": "template-intermediario",
        "desc": "Materio feito no chat: Tailwind + Radix, claro/roxo. O 'novo' que construímos juntos.",
        "cor_editavel": True,
        "cor_default_light": "#8C57FF",
        "cor_default_dark": "#9E95F5",
    },
    {
        "id": "claude-design",
        "nome": "Template Claude Design",
        "branch": "template-claude-design",
        "desc": "Tudo do Claude Design: paleta magenta por modo, login-v1 e editor de cores por colégio.",
        "cor_editavel": True,
        "cor_default_light": "#911256",
        "cor_default_dark": "#D14C84",
    },
]


# ====================================================================
# Persistência de cores (_template_cores.json)
# ====================================================================

def _carregar_cores() -> dict:
    """Lê _template_cores.json; retorna {} se não existir ou for inválido."""
    try:
        with open(_CORES_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _salvar_cores_json(template_id: str, light: str, dark: str) -> None:
    """Persiste as cores de um template no JSON."""
    dados = _carregar_cores()
    dados[template_id] = {"light": light, "dark": dark}
    with open(_CORES_JSON, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def _cores_template(template: dict) -> tuple[str, str]:
    """Retorna (light, dark) salvas para o template, ou os defaults."""
    dados = _carregar_cores()
    salvas = dados.get(template["id"], {})
    light = salvas.get("light") or template.get("cor_default_light", "#8C57FF")
    dark = salvas.get("dark") or template.get("cor_default_dark", "#9E95F5")
    return light, dark


# ====================================================================
# Aplicar cores no banco (public.schools)
# ====================================================================

async def _aplicar_cores_banco_async(light: str, dark: str) -> None:
    """UPDATE em todas as escolas — há essencialmente uma (Escola Parque)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.schools SET brand_primary = $1, brand_primary_dark = $2",
            light, dark,
        )


def _aplicar_cores_banco(light: str, dark: str) -> tuple[bool, str]:
    """Wrapper síncrono para _aplicar_cores_banco_async. Retorna (ok, msg)."""
    try:
        run_async(_aplicar_cores_banco_async(light, dark))
        return True, "Cores aplicadas no banco."
    except Exception as e:
        return False, f"Banco: {type(e).__name__}: {e}"


# ====================================================================
# Token / credenciais do GitHub
# ====================================================================

def _extrair_token_de_url(linha: str) -> str:
    try:
        if "://" in linha and "@" in linha:
            cred = linha.split("://", 1)[1].split("@", 1)[0]
            return cred.split(":")[-1].strip()
    except Exception:
        pass
    return ""


def _token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t.strip()
    for p in _GIT_CRED_PATHS:
        try:
            with open(p, encoding="utf-8") as f:
                for linha in f:
                    if "github.com" in linha:
                        tok = _extrair_token_de_url(linha.strip())
                        if tok:
                            return tok
        except Exception:
            continue
    for cfg in _GIT_CONFIGS:
        try:
            with open(cfg, encoding="utf-8") as f:
                for linha in f:
                    linha = linha.strip()
                    if linha.startswith("url") and "github.com" in linha:
                        tok = _extrair_token_de_url(linha)
                        if tok:
                            return tok
        except Exception:
            continue
    return ""


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _branch_head(branch, token):
    try:
        r = requests.get(
            f"https://api.github.com/repos/{REPO_OWNER}/{REPO_FRONT}/git/ref/heads/{branch}",
            headers=_headers(token), timeout=20,
        )
        return r.json()["object"]["sha"] if r.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=30, show_spinner=False)
def _estado(_token_hash):
    """Retorna (id_ativo, main_sha, {branch: sha}). Cacheado 30s p/ não bater na API a cada rerun."""
    token = _token()
    if not token:
        return None, None, {}
    main_sha = _branch_head("main", token)
    mapa = {t["branch"]: _branch_head(t["branch"], token) for t in TEMPLATES}
    ativo = None
    if main_sha:
        for t in TEMPLATES:
            if mapa.get(t["branch"]) == main_sha:
                ativo = t["id"]
                break
    return ativo, main_sha, mapa


def _ativar(template):
    token = _token()
    if not token:
        return False, "Não encontrei credencial do GitHub na VPS (env, ~/.git-credentials ou remote)."
    sha = _branch_head(template["branch"], token)
    if not sha:
        return False, f"Não encontrei a branch `{template['branch']}` (ou o token não tem acesso)."
    r = requests.patch(
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_FRONT}/git/refs/heads/main",
        headers=_headers(token), json={"sha": sha, "force": True}, timeout=20,
    )
    if r.status_code in (200, 201):
        _estado.clear()
        # Aplica as cores do template ativado no banco (se editável)
        if template.get("cor_editavel"):
            light, dark = _cores_template(template)
            ok_cor, msg_cor = _aplicar_cores_banco(light, dark)
            cor_info = f" Cores aplicadas ({light} / {dark})." if ok_cor else f" ⚠️ {msg_cor}"
        else:
            cor_info = ""
        return True, (
            f"`main` agora aponta para `{template['branch']}` ({sha[:7]}). "
            "A VPS redeploya em ~2 min — se o build passar."
            + cor_info
        )
    return False, f"GitHub {r.status_code}: {r.text[:200]}"


# ====================================================================
# Render
# ====================================================================

def _render_templates_conteudo():
    st.title("🎨 Templates do Frontend")
    st.caption(
        "Escolha qual template do frontend fica ativo. Cada um é independente (uma branch). "
        "Ativar troca a branch publicada — o build-gate protege: se o novo não buildar, "
        "a produção continua no atual."
    )

    tem_token = bool(_token())
    if not tem_token:
        st.warning("⚠️ Não localizei a credencial do GitHub que a VPS usa. Me avise que eu aponto a página pro lugar certo.")

    ativo, main_sha, mapa = _estado(tem_token)
    if main_sha:
        st.caption(f"`main` está em `{main_sha[:7]}`" + (" — nenhum template casado exatamente" if not ativo else ""))

    if st.button("🔄 Recarregar estado", use_container_width=False):
        _estado.clear()
        st.rerun()

    for t in TEMPLATES:
        with st.container(border=True):
            # -- Linha 1: titulo + botao Ativar --
            c1, c2 = st.columns([4, 1])
            with c1:
                marca = " ✅ **ATIVO**" if ativo == t["id"] else ""
                st.markdown(f"### {t['nome']}{marca}")
                st.caption(t["desc"])
                _sha = mapa.get(t["branch"])
                st.caption(f"branch: `{t['branch']}`" + (f" · `{_sha[:7]}`" if _sha else ""))
            with c2:
                st.write("")
                st.write("")
                if ativo == t["id"]:
                    st.button("Ativo", key=f"tpl_{t['id']}", disabled=True, use_container_width=True)
                elif st.button("Ativar", key=f"tpl_{t['id']}", type="primary", use_container_width=True):
                    ok, msg = _ativar(t)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            # -- Linha 2: editor de cor (apenas Intermediario e Claude Design) --
            if t.get("cor_editavel"):
                st.divider()
                light_saved, dark_saved = _cores_template(t)

                cc1, cc2, cc3 = st.columns([2, 2, 1])
                with cc1:
                    nova_light = st.color_picker(
                        "Cor base · fundo claro",
                        value=light_saved,
                        key=f"cor_light_{t['id']}",
                    )
                with cc2:
                    nova_dark = st.color_picker(
                        "Cor base · fundo escuro",
                        value=dark_saved,
                        key=f"cor_dark_{t['id']}",
                    )
                with cc3:
                    st.write("")
                    st.write("")
                    if st.button("Salvar cores", key=f"salvar_cores_{t['id']}", use_container_width=True):
                        try:
                            _salvar_cores_json(t["id"], nova_light, nova_dark)
                            ok_banco, msg_banco = _aplicar_cores_banco(nova_light, nova_dark)
                            if ok_banco:
                                st.success(f"Cores salvas e aplicadas no banco ({nova_light} / {nova_dark}).")
                            else:
                                st.warning(f"Cores salvas no JSON, mas falhou no banco: {msg_banco}")
                        except Exception as e:
                            st.error(f"Erro ao salvar cores: {type(e).__name__}: {e}")


def render_pagina_templates():
    """Area Templates: aba do seletor de template + aba de Videos da Landing."""
    _tab_tpl, _tab_vid = st.tabs(["🎨 Templates do Frontend", "📹 Vídeos da Landing"])
    with _tab_tpl:
        _render_templates_conteudo()
    with _tab_vid:
        try:
            import pagina_videos_landing
            pagina_videos_landing.render_conteudo()
        except Exception as _e_vid:
            st.error(f"Falha ao carregar Vídeos da Landing: {type(_e_vid).__name__} — {_e_vid}")
            import traceback
            with st.expander("Traceback"):
                st.code(traceback.format_exc())
