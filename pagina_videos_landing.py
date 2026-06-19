"""
pagina_videos_landing.py - Gestao dos videos de fundo do hero do site.

Lista os videos cadastrados, faz upload arrastando, insere e deleta. As URLs
publicas alimentam a lista HERO_VIDEO_URLS do Hero.tsx (montagem com crossfade).

- render_conteudo(): so o conteudo (para encaixar numa aba existente).
- render(): wrapper com aba propria (uso standalone).
"""
from __future__ import annotations

import re

import streamlit as st

import backend_storage_videos as bsv


def _slug(nome: str) -> str:
    """Normaliza o nome do arquivo (sem espacos/acentos), preservando extensao."""
    nome = (nome or "").strip().lower()
    nome = nome.replace(" ", "-")
    nome = re.sub(r"[^a-z0-9._-]+", "-", nome)
    nome = nome.strip("-.") or "video"
    if not nome.endswith((".mp4", ".webm")):
        nome += ".mp4"
    return nome


def render_conteudo() -> None:
    """Conteudo da gestao de videos (sem criar abas - para uso dentro de uma aba)."""
    st.subheader("Vídeos de fundo do hero")
    st.caption(
        "Estes vídeos formam a montagem (crossfade automático) no topo do site. "
        "Vão para o bucket público **landing-assets** no Supabase. "
        "Aceita **.mp4 / .webm** até **25 MB** cada."
    )

    try:
        videos = bsv.listar_videos()
    except Exception as e:  # pragma: no cover
        st.error(f"Não consegui falar com o Storage do Supabase: {type(e).__name__} — {e}")
        st.info(
            "Confira se há um BD marcado como EM USO no carrossel "
            "(Configurações → Banco de Dados / Innova V2)."
        )
        with st.expander("Detalhes técnicos"):
            import traceback
            st.code(traceback.format_exc())
        return

    st.markdown("##### ➕ Adicionar vídeos")
    ups = st.file_uploader(
        "Arraste os vídeos aqui (ou clique para escolher)",
        type=["mp4", "webm"],
        accept_multiple_files=True,
        key="vid_uploader",
    )
    if ups:
        if st.button(f"⬆️ Inserir {len(ups)} vídeo(s)", type="primary", use_container_width=True):
            ok, fail = 0, 0
            prog = st.progress(0.0, text="Enviando...")
            for i, f in enumerate(ups):
                try:
                    data = f.getvalue()
                    if len(data) > bsv.MAX_BYTES:
                        mb = len(data) // (1024 * 1024)
                        st.warning(f"'{f.name}' tem {mb} MB (> 25 MB). Pulei — baixe em HD 1080p.")
                        fail += 1
                    else:
                        ct = "video/webm" if f.name.lower().endswith(".webm") else "video/mp4"
                        bsv.upload_video(_slug(f.name), data, ct)
                        ok += 1
                except Exception as e:
                    st.error(f"Erro em '{f.name}': {e}")
                    fail += 1
                prog.progress((i + 1) / len(ups), text=f"{i + 1}/{len(ups)}")
            st.success(f"Concluído: {ok} enviado(s), {fail} com problema.")
            st.rerun()

    st.divider()

    st.markdown(f"##### 🎬 Vídeos cadastrados ({len(videos)})")
    if not videos:
        st.info("Nenhum vídeo ainda. Adicione acima arrastando os arquivos.")
        return

    for v in videos:
        c1, c2 = st.columns([3, 2])
        with c1:
            try:
                st.video(v["url"])
            except Exception:
                st.write("(pré-visualização indisponível)")
        with c2:
            st.markdown(f"**{v['name']}**")
            if v.get("size"):
                mb = round(v["size"] / (1024 * 1024), 1)
                st.caption(f"{mb} MB · {v.get('mimetype', '')}")
            st.code(v["url"], language=None)
            if st.button("🗑️ Deletar", key=f"del_{v['name']}", use_container_width=True):
                try:
                    bsv.deletar_video(v["name"])
                    st.success(f"'{v['name']}' deletado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Falha ao deletar: {e}")
        st.divider()

    with st.expander("ℹ️ Como estes vídeos entram no site"):
        st.write(
            "Copie as URLs acima (ou me avise) para preencher a lista "
            "`HERO_VIDEO_URLS` do `Hero.tsx`. Com 2 ou mais vídeos, o hero "
            "faz a montagem com crossfade automático a cada 7 segundos."
        )


def render() -> None:
    """Wrapper standalone (cria a aba)."""
    aba = st.tabs(["📹 Vídeos da Landing"])[0]
    with aba:
        render_conteudo()
