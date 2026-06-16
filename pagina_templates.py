"""
pagina_templates.py — Seleção do Template do Frontend (Escola Parque V3)
-----------------------------------------------------------------------
Cada template do frontend é uma BRANCH independente do repo
`escola-parque-frontend`. A VPS publica sempre a branch `main`. "Ativar" um
template aponta a `main` para o HEAD da branch escolhida (via API do GitHub) e
a VPS redeploya em ~2 min. O build-gate protege: se o template novo não buildar,
a produção continua no atual.

Token: REUSA a credencial que a VPS já usa (não precisa criar token novo).
Procura em ordem: env GITHUB_TOKEN/GH_TOKEN -> ~/.git-credentials -> URL do
remote dos repos locais. Precisa ter permissão de escrita (Contents: write).
"""

import os
import json

import requests
import streamlit as st

REPO_OWNER = "diogobsbastos"
REPO_FRONT = "escola-parque-frontend"
ESTADO = os.path.join(os.path.dirname(__file__), "_template_ativo.json")

# Locais onde a credencial do GitHub pode já estar na VPS.
_GIT_CRED_PATHS = [
    os.path.expanduser("~/.git-credentials"),
    "/home/ubuntu/.git-credentials",
]
_GIT_CONFIGS = [
    "/home/ubuntu/innova-front/.git/config",
    "/home/ubuntu/escola-parque/.git/config",
]

TEMPLATES = [
    {
        "id": "atual",
        "nome": "Template Atual (v1)",
        "branch": "template-v1-backup",
        "desc": "Template original (Tailwind + Base UI). Estável, é o que rodou até hoje.",
    },
    {
        "id": "novo",
        "nome": "Template Novo (Tailwind + Radix)",
        "branch": "feat/materio-migration",
        "desc": "Migração nova: Base UI removido, stack Tailwind + Radix. Independente do atual.",
    },
]


def _extrair_token_de_url(linha: str) -> str:
    """De 'https://user:token@github.com...' ou 'https://token@github.com...' tira o token."""
    try:
        if "://" in linha and "@" in linha:
            cred = linha.split("://", 1)[1].split("@", 1)[0]
            return cred.split(":")[-1].strip()
    except Exception:
        pass
    return ""


def _token():
    # 1) variável de ambiente
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t.strip()
    # 2) ~/.git-credentials (credential store do git)
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
    # 3) URL do remote nos repos locais (caso o token esteja embutido na URL)
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


def _ler_ativo():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f).get("ativo")
    except Exception:
        return None


def _salvar_ativo(tid):
    try:
        with open(ESTADO, "w", encoding="utf-8") as f:
            json.dump({"ativo": tid}, f)
    except Exception:
        pass


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _branch_head(branch, token):
    r = requests.get(
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_FRONT}/git/ref/heads/{branch}",
        headers=_headers(token), timeout=20,
    )
    return r.json()["object"]["sha"] if r.status_code == 200 else None


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
        _salvar_ativo(template["id"])
        return True, (f"`main` agora aponta para `{template['branch']}` ({sha[:7]}). "
                      "A VPS redeploya em ~2 min — se o build passar.")
    return False, f"GitHub {r.status_code}: {r.text[:200]}"


def render_pagina_templates():
    st.title("🎨 Templates do Frontend")
    st.caption(
        "Escolha qual template do frontend fica ativo. Cada um é independente (uma branch). "
        "Ativar troca a branch publicada — o build-gate protege: se o novo não buildar, "
        "a produção continua no atual."
    )

    ativo = _ler_ativo()

    if not _token():
        st.warning(
            "⚠️ Não localizei a credencial do GitHub que a VPS usa (env / `~/.git-credentials` / "
            "remote). Sem ela o **Ativar** não troca sozinho. Me avise que a gente aponta a página "
            "pro lugar certo da credencial."
        )

    for t in TEMPLATES:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                marca = " ✅ **ATIVO**" if ativo == t["id"] else ""
                st.markdown(f"### {t['nome']}{marca}")
                st.caption(t["desc"])
                st.caption(f"branch: `{t['branch']}`")
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
