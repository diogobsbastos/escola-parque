"""
═══════════════════════════════════════════════════════════════════════════════
PAGINA_MOLDE.PY v4 — Treinamento de Molde de Prova (Menu de Fases)
═══════════════════════════════════════════════════════════════════════════════
Mudanças v4 (após feedback do usuário):
  • TOPO: menu inteligente com botões de fase
        [📂 Moldes Salvos] [1️⃣ Gabarito] [2️⃣ PDF & Detecção]
        [3️⃣ Calibração]    [4️⃣ Salvar]  [❓ Ajuda]
  • Fluxo gated: Fase 2 só após Fase 1 ter ≥1 frase; Fase 3 só após Fase 2
    ter PDF processado; Fase 4 só após calibração com ao menos 1 quadrado.
  • Fase 1 (Gabarito) ganha UPLOAD de arquivo (JSON/CSV/XLSX/XLS/TXT/MD)
    além de Carregar Padrão / Adicionar / Limpar.
  • Botão ❓ Ajuda — guia do fluxo da versão beta1.
  • Tudo o que já existia (clique de coordenadas, thumbnails, edição,
    persistência) está preservado — só foi reagrupado dentro das fases.
═══════════════════════════════════════════════════════════════════════════════
"""
import os
import time
import hashlib
import streamlit as st

try:
    import cv2
    import numpy as np
    VISAO_OK = True
except ImportError:
    VISAO_OK = False

try:
    from streamlit_image_coordinates import streamlit_image_coordinates
    COMPONENTE_OK = True
except ImportError:
    COMPONENTE_OK = False

from backend_molde import (
    listar_moldes, carregar_molde, salvar_molde, deletar_molde,
    detectar_candidatos_para_molde, garantir_pasta_moldes,
    montar_molde_final, carregar_para_edicao,
    salvar_pdf_referencia, existe_pdf_referencia, molde_pdf_path,
    gabarito_padrao_como_lista, normalizar_gabarito_frases,
    parse_gabarito_arquivo,
    detectar_template_layout,
    _sanitizar_nome_filesystem,
    LISTA_FRASES_GABARITO, SECAO_POR_FRASE, QTD_FRASES_GABARITO,
    DPI_PADRAO,
)


# ═══════════════════════════════════════════════════════════════════════════
# UTILS — ANOTAÇÃO E THUMBNAILS
# ═══════════════════════════════════════════════════════════════════════════
def _anotar_pagina(img_bgr, quadrados_pag, w_largura_max=750):
    """Anota imagem com retângulos numerados. Auto = verde, manual = vermelho."""
    img = img_bgr.copy()
    h_orig, w_orig = img.shape[:2]

    for q in quadrados_pag:
        x = int(q.get("x", 0))
        y = int(q.get("y", 0))
        w = int(q.get("w", 35))
        h = int(q.get("h", 30))
        n = int(q.get("n_global", 0))
        manual = bool(q.get("manual", False))
        cor = (0, 0, 220) if manual else (0, 150, 0)
        cv2.rectangle(img, (x - 3, y - 3), (x + w + 3, y + h + 3), cor, 3)
        label = f"#{n}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        x_lbl = x + w + 10
        y_lbl = y + h // 2 + th // 2
        if x_lbl + tw + 8 > w_orig:
            x_lbl = max(5, x - tw - 14)
        cv2.rectangle(img, (x_lbl - 4, y_lbl - th - 5), (x_lbl + tw + 4, y_lbl + 5),
                      (255, 255, 255), -1)
        cv2.rectangle(img, (x_lbl - 4, y_lbl - th - 5), (x_lbl + tw + 4, y_lbl + 5),
                      cor, 2)
        cv2.putText(img, label, (x_lbl, y_lbl),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, cor, 2, cv2.LINE_AA)

    if w_orig > w_largura_max:
        escala = w_largura_max / w_orig
        novo_w = int(w_orig * escala)
        novo_h = int(h_orig * escala)
        img_resized = cv2.resize(img, (novo_w, novo_h), interpolation=cv2.INTER_AREA)
    else:
        escala = 1.0
        img_resized = img

    img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
    return img_rgb, escala


def _gerar_thumbnail(img_bgr, quadrados_pag, pag_atual, is_atual, largura=140):
    """Thumbnail pequena com indicação visual da página atual e dos quadrados."""
    img = img_bgr.copy()
    h_orig, w_orig = img.shape[:2]
    for q in quadrados_pag:
        cx = int(q["x"] + q.get("w", 35) / 2)
        cy = int(q["y"] + q.get("h", 30) / 2)
        manual = bool(q.get("manual", False))
        cor = (0, 0, 220) if manual else (0, 150, 0)
        cv2.circle(img, (cx, cy), 14, cor, -1)
    if is_atual:
        cv2.rectangle(img, (0, 0), (w_orig - 1, h_orig - 1), (0, 165, 255), 25)
    escala = largura / w_orig
    novo_h = int(h_orig * escala)
    small = cv2.resize(img, (largura, novo_h), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2RGB)


def _converter_clique(click_x, click_y, escala):
    if escala <= 0: escala = 1.0
    return int(click_x / escala), int(click_y / escala)


def _hash_pdf(pdf_bytes):
    return hashlib.md5(pdf_bytes).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════════════════
# VIEWS PRINCIPAIS — list-detail
# ═══════════════════════════════════════════════════════════════════════════
VIEW_LISTA  = "lista"   # home: lista de moldes salvos + botão Novo
VIEW_EDITOR = "editor"  # editor com menu de fases 1-4


def _view_atual() -> str:
    return st.session_state.get("molde_view", VIEW_LISTA)


def _trocar_view(nova_view: str):
    st.session_state["molde_view"] = nova_view


def _limpar_estado_editor():
    """Limpa todo o session_state do editor. Usado ao entrar em 'Novo'
    e ao voltar para a lista após salvar/cancelar."""
    chaves = [
        "molde_candidatos", "molde_descartados", "molde_manuais",
        "molde_paginas", "molde_pdf_path", "molde_ultimo_click",
        "molde_frases_custom", "molde_paginas_editadas", "molde_pdf_hash",
        "molde_em_edicao", "molde_pag_atual", "molde_modo_clique",
        "molde_gabarito_lista", "molde_fase_ativa", "molde_nome",
        "__ver_json_atual__",
    ]
    for k in chaves:
        st.session_state.pop(k, None)


def _entrar_editor_novo():
    """Entra no editor em modo NOVO — limpa tudo e abre na Fase 1 com gabarito padrão."""
    _limpar_estado_editor()
    st.session_state["molde_gabarito_lista"] = gabarito_padrao_como_lista()
    st.session_state["molde_fase_ativa"]     = FASE_GABARITO
    st.session_state["molde_nome"]           = "Prova_Nova"
    _trocar_view(VIEW_EDITOR)


def _voltar_para_lista():
    """Sai do editor sem salvar. Limpa estado e volta para a home."""
    _limpar_estado_editor()
    _trocar_view(VIEW_LISTA)


# ═══════════════════════════════════════════════════════════════════════════
# MENU DE FASES — controla qual seção do EDITOR é renderizada
# ═══════════════════════════════════════════════════════════════════════════
FASE_GABARITO = "gabarito"
FASE_PDF      = "pdf"
FASE_CALIB    = "calib"
FASE_SALVAR   = "salvar"
FASE_AJUDA    = "ajuda"


def _fase_ativa() -> str:
    """Retorna a fase ativa do session_state, com default = gabarito."""
    return st.session_state.get("molde_fase_ativa", FASE_GABARITO)


def _trocar_fase(nova_fase: str):
    """Helper para botões de troca de fase."""
    st.session_state["molde_fase_ativa"] = nova_fase


def _gabarito_pronto() -> bool:
    """True se há pelo menos 1 frase definida no gabarito da sessão."""
    g = st.session_state.get("molde_gabarito_lista", [])
    return any((x.get("frase") or "").strip() for x in g)


def _pdf_pronto() -> bool:
    """True se PDF foi processado (candidatos detectados ou molde em edição)."""
    return "molde_paginas" in st.session_state and bool(st.session_state.get("molde_paginas"))


def _calibracao_pronta() -> bool:
    """True se há ao menos 1 quadrado ativo (auto-ativo OU manual)."""
    if not _pdf_pronto():
        return False
    candidatos = st.session_state.get("molde_candidatos", [])
    descartados = st.session_state.get("molde_descartados", set())
    manuais = st.session_state.get("molde_manuais", [])
    ativos = [c for i, c in enumerate(candidatos) if i not in descartados]
    return len(ativos) + len(manuais) > 0


def _renderizar_menu_topo():
    """Barra de botões de fase do EDITOR. Cada botão pula para sua seção.
    Fases bloqueadas por dependência ficam disabled com tooltip explicativo.
    Inclui botão de voltar para a lista (sai do editor)."""
    g_ok    = _gabarito_pronto()
    pdf_ok  = _pdf_pronto()
    calib_ok = _calibracao_pronta()

    fase    = _fase_ativa()
    n_frases = len(st.session_state.get("molde_gabarito_lista", []))
    em_edicao = st.session_state.get("molde_em_edicao")

    # Cabeçalho do editor — mostra modo (Novo/Edição) e botão Voltar
    col_h1, col_h2 = st.columns([5, 1])
    with col_h1:
        if em_edicao:
            # Modo EDIÇÃO: nome do molde existente é IMUTÁVEL aqui (rename é
            # operação separada na lista — evita corromper o link entre o
            # JSON e o PDF físico do molde já salvo).
            st.markdown(f"### ✏️ Editando molde: **{em_edicao}**")
        else:
            # Modo NOVO: cabeçalho com nome EDITÁVEL inline.
            # O text_input é a ÚNICA fonte de edição do nome (removemos o input
            # da Fase 2). O widget gerencia seu próprio estado via session_state
            # da key `molde_nome_input_topo` — Streamlit faz a persistência.
            # Apenas espelhamos o valor digitado em `molde_nome` (canonical lido
            # pela Fase 4 quando chama _salvar_molde_atual).
            _valor_inicial = st.session_state.get("molde_nome", "Prova_Nova")

            ch1, ch2 = st.columns([0.32, 1])
            with ch1:
                st.markdown("### 🆕 Novo molde:")
            with ch2:
                _nome_topo = st.text_input(
                    "Nome do novo molde",
                    value=_valor_inicial,
                    key="molde_nome_input_topo",
                    label_visibility="collapsed",
                    placeholder="Digite o nome do molde…",
                    help=("O nome digitado é normalizado (acentos removidos, "
                          "espaços viram '_') para virar o nome do arquivo no disco."),
                )
                # Espelha o valor do widget no canônico — apenas se mudou,
                # para evitar rerender desnecessário.
                if st.session_state.get("molde_nome") != _nome_topo:
                    st.session_state["molde_nome"] = _nome_topo

                # Preview do nome de arquivo REAL — evita surpresa do tipo
                # "salvei como PROVA GRAVAÇAÕ mas o arquivo virou PROVA_GRAVACAO".
                _nome_safe_preview = _sanitizar_nome_filesystem(_nome_topo or "")
                if _nome_safe_preview and _nome_safe_preview != (_nome_topo or "").strip():
                    st.caption(
                        f"📁 Arquivo no disco: `moldes/{_nome_safe_preview}.json` "
                        f"(acentos/espaços normalizados)"
                    )
                elif _nome_safe_preview:
                    st.caption(f"📁 Arquivo no disco: `moldes/{_nome_safe_preview}.json`")
    with col_h2:
        if st.button("⬅️ Lista", key="btn_voltar_lista",
                      use_container_width=True,
                      help="Sair do editor (descarta o que não foi salvo) e voltar para a lista de moldes."):
            _voltar_para_lista()
            st.rerun()

    # 5 colunas para as fases + ajuda
    c1, c2, c3, c4, c5 = st.columns([1.4, 1.6, 1.4, 1.2, 0.8])

    def _btn(col, key, label, alvo, disabled=False, tip=None, tipo=None):
        with col:
            if st.button(
                label,
                key=key,
                use_container_width=True,
                disabled=disabled,
                help=tip,
                type=(tipo or ("primary" if fase == alvo else "secondary")),
            ):
                _trocar_fase(alvo)
                st.rerun()

    _btn(c1, "fase_btn_gabarito", f"1️⃣ Gabarito ({n_frases})", FASE_GABARITO)
    _btn(c2, "fase_btn_pdf",      "2️⃣ PDF & Detecção",        FASE_PDF,
         disabled=not g_ok,
         tip=("Defina pelo menos 1 frase na Fase 1 antes de subir o PDF."
              if not g_ok else None))
    _btn(c3, "fase_btn_calib",    "3️⃣ Calibração",            FASE_CALIB,
         disabled=not pdf_ok,
         tip=("Suba e detecte o PDF na Fase 2 antes de calibrar."
              if not pdf_ok else None))
    _btn(c4, "fase_btn_salvar",   "4️⃣ Salvar",                FASE_SALVAR,
         disabled=not calib_ok,
         tip=("Calibre pelo menos 1 quadrado antes de salvar."
              if not calib_ok else None))
    _btn(c5, "fase_btn_ajuda",    "❓",                        FASE_AJUDA,
         tip="Como funciona esta página (versão beta 1).")

    # Barra de progresso visual
    etapas = [
        ("Gabarito", g_ok),
        ("PDF",      pdf_ok),
        ("Calib",    calib_ok),
    ]
    feitas = sum(1 for _, ok in etapas if ok)
    st.progress(feitas / len(etapas),
                text=f"Progresso: {feitas}/{len(etapas)} fases concluídas")


# ═══════════════════════════════════════════════════════════════════════════
# FASE: AJUDA (beta1)
# ═══════════════════════════════════════════════════════════════════════════
def _renderizar_fase_ajuda():
    st.markdown("## ❓ Como funciona — Treinamento de Molde · versão **beta 1**")
    st.markdown(
        """
        Esta página serve para **treinar um molde** de uma variante de prova.
        Um molde guarda as **coordenadas exatas** dos checkboxes e a **lista de frases**
        que cada checkbox representa. Uma vez treinado, o sistema processa
        automaticamente qualquer prova nova com o mesmo layout.

        O fluxo está dividido em **4 fases sequenciais**:

        ### 1️⃣ Gabarito de Frases
        Defina **quais frases** existem nesta prova. Você pode:
        - 📥 **Carregar Padrão** — 46 frases canônicas (Escola Parque V3).
        - 📤 **Upload de gabarito** — subir um arquivo `.json`, `.csv`, `.xlsx`, `.xls`,
          `.txt` ou `.md` com sua própria lista. Útil para outras variantes
          (Português, TDAH adaptado, etc.).
        - ➕ **Adicionar / editar / remover** manualmente.

        A **ordem importa**: a 1ª frase será vinculada ao 1º quadrado da prova,
        a 2ª ao 2º, e assim por diante. Esse vínculo é editável depois.

        ### 2️⃣ PDF & Detecção
        Dê um **nome ao molde** (ex.: `Prova_Padrao_Mat_6ano`), suba o **PDF da prova**
        e clique em **Detectar candidatos**. O motor de visão (template matching +
        filtros) propõe automaticamente os quadrados de cada página.

        ### 3️⃣ Calibração
        Aqui você refina o resultado:
        - **Clique** em um checkbox **faltando** → adiciona manual (vermelho).
        - **Clique** em um quadrado **errado** → descarta.
        - Para cada quadrado, escolha a **frase** correspondente.

        O contador `✅ / N` reflete quantos quadrados ativos você tem versus
        quantas frases definidas na Fase 1.

        ### 4️⃣ Salvar
        Quando o número de quadrados bater com o de frases, salve o molde como
        **COMPLETO**. Ou salve **PARCIAL** se quiser continuar depois — o PDF
        de referência fica gravado junto.

        ---
        ### 🛣️ Roadmap (próximas versões)
        - **beta 2**: detecção automática de gabarito (LLM lê o próprio PDF e propõe a lista).
        - **beta 3**: importação em lote (zip de moldes) + galeria de variantes.
        - **beta 4**: alinhamento por âncoras fiduciais — provas escaneadas levemente
          desalinhadas serão reposicionadas automaticamente.
        """
    )
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        if st.button("⬅️ Voltar para Gabarito", use_container_width=True):
            _trocar_fase(FASE_GABARITO)
            st.rerun()
    with col_v2:
        if st.button("📂 Voltar para a Lista de Moldes", use_container_width=True):
            _voltar_para_lista()
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# VIEW: LISTAGEM HOME (lista + botão Novo + Editar/Deletar)
# ═══════════════════════════════════════════════════════════════════════════
def _renderizar_listagem_home():
    """Página inicial: mostra os moldes cadastrados e oferece criar um novo.
    O menu de fases (Gabarito/PDF/Calibração/Salvar) NÃO aparece aqui —
    aparece apenas dentro do editor, ao clicar em ➕ Novo ou ✏️ Editar."""

    # ── CABEÇALHO COM CTA ──
    col_titulo, col_novo, col_ajuda = st.columns([4, 1.4, 0.8])
    with col_titulo:
        st.markdown("## 📂 Moldes cadastrados")
        st.caption(f"📁 Pasta: `{os.path.abspath('moldes')}`")
    with col_novo:
        if st.button("➕ Novo Molde", key="btn_novo_molde",
                      type="primary", use_container_width=True,
                      help="Criar um novo molde do zero — abre o editor na Fase 1."):
            _entrar_editor_novo()
            st.rerun()
    with col_ajuda:
        if st.button("❓", key="btn_ajuda_home",
                      use_container_width=True,
                      help="Como funciona — versão beta 1."):
            # Entra no editor já em modo ajuda (mantém gabarito padrão pronto)
            _entrar_editor_novo()
            _trocar_fase(FASE_AJUDA)
            st.rerun()

    st.divider()

    moldes_existentes = listar_moldes()
    if not moldes_existentes:
        st.info(
            "🆕 **Nenhum molde cadastrado ainda.**  \n\n"
            "Clique em **➕ Novo Molde** acima para começar. Você irá:  \n"
            "1️⃣ Definir as frases do gabarito  \n"
            "2️⃣ Subir o PDF da prova  \n"
            "3️⃣ Calibrar as coordenadas dos checkboxes  \n"
            "4️⃣ Salvar"
        )
        return

    st.markdown(f"**{len(moldes_existentes)} molde(s) cadastrado(s)**")

    # Cabeçalho compacto — apenas 1 linha
    h1, h2, h3, h4, h5 = st.columns([4.5, 0.9, 1.4, 0.7, 0.7])
    with h1: st.caption("Molde")
    with h2: st.caption("Status")
    with h3: st.caption("Quad/Frases")
    with h4: st.caption("Editar")
    with h5: st.caption("Del")

    # ── Linhas em UMA LINHA cada, SEM captions extras, SEM divider entre itens
    for nm in moldes_existentes:
        dados    = carregar_molde(nm)
        qtd      = (dados or {}).get("qtd_quadrados", 0) if dados else 0
        qtd_g    = (dados or {}).get("qtd_frases_gabarito", 0) if dados else 0
        completo = (dados or {}).get("completo", False)
        tem_pdf  = existe_pdf_referencia(nm)
        pdf_emo    = "📄" if tem_pdf else "⚠️"
        status_emo = "✅" if completo else "⚠️"

        col_n, col_s, col_t, col_e, col_d = st.columns([4.5, 0.9, 1.4, 0.7, 0.7])
        with col_n:
            st.markdown(f"{pdf_emo} **{nm}**")
        with col_s:
            st.markdown(status_emo)
        with col_t:
            st.markdown(f"`{qtd}/{qtd_g}`")
        with col_e:
            if st.button("✏️", key=f"editar_{nm}",
                          help=f"Editar {nm} — carrega molde + PDF",
                          use_container_width=True, disabled=(not tem_pdf)):
                resultado = carregar_para_edicao(nm)
                if "erro" in resultado:
                    st.error(f"❌ {resultado['erro']}")
                else:
                    _limpar_estado_editor()
                    st.session_state["molde_nome"]              = nm
                    st.session_state["molde_em_edicao"]         = nm
                    st.session_state["molde_pdf_path"]          = resultado["pdf_path"]
                    st.session_state["molde_paginas"]           = resultado["paginas"]
                    st.session_state["molde_candidatos"]        = []
                    st.session_state["molde_descartados"]       = set()
                    st.session_state["molde_manuais"]           = resultado["quadrados"]
                    for q in st.session_state["molde_manuais"]:
                        q["manual"] = True
                    st.session_state["molde_ultimo_click"]      = {}
                    st.session_state["molde_frases_custom"]     = resultado["frases"]
                    st.session_state["molde_paginas_editadas"]  = set()
                    st.session_state["molde_pag_atual"]         = 0
                    molde_dados = resultado.get("molde") or {}
                    gabarito_do_json = molde_dados.get("gabarito_frases")
                    if gabarito_do_json:
                        st.session_state["molde_gabarito_lista"] = normalizar_gabarito_frases(gabarito_do_json)
                    else:
                        st.session_state["molde_gabarito_lista"] = gabarito_padrao_como_lista()
                    st.session_state["molde_fase_ativa"] = FASE_CALIB
                    _trocar_view(VIEW_EDITOR)
                    st.rerun()
        with col_d:
            if st.button("🗑️", key=f"del_{nm}",
                          help=f"Deletar {nm} (JSON + PDF)",
                          use_container_width=True):
                deletar_molde(nm)
                st.rerun()

    st.caption(
        "Legenda: 📄 com PDF · ⚠️ sem PDF · ✅ completo · ⚠️ parcial · "
        "`Quad/Frases` = quadrados calibrados / frases no gabarito."
    )


# ═══════════════════════════════════════════════════════════════════════════
# FASE 1: GABARITO DE FRASES (editor + upload)
# ═══════════════════════════════════════════════════════════════════════════
def _renderizar_fase_gabarito():
    st.markdown("## 1️⃣ Gabarito de Frases")
    st.caption(
        "Defina aqui as frases que o sistema deve identificar nesta variante de prova. "
        "**A ordem importa**: a 1ª frase vincula ao Q1, 2ª ao Q2, etc. "
        "Esse vínculo pode ser ajustado depois, na Fase 3."
    )

    if "molde_gabarito_lista" not in st.session_state:
        st.session_state["molde_gabarito_lista"] = gabarito_padrao_como_lista()
    gabarito_atual = st.session_state["molde_gabarito_lista"]

    # ── BARRA DE AÇÕES ──
    col_a1, col_a2, col_a3, col_a4 = st.columns([2, 2, 2, 2])
    with col_a1:
        if st.button("📥 Carregar padrão (46)", use_container_width=True,
                      help="Substitui a lista atual pelo gabarito padrão de 46 frases."):
            st.session_state["molde_gabarito_lista"] = gabarito_padrao_como_lista()
            st.rerun()
    with col_a2:
        if st.button("➕ Adicionar frase", use_container_width=True, type="primary"):
            novo_id = len(gabarito_atual) + 1
            st.session_state["molde_gabarito_lista"].append({
                "id": novo_id, "frase": "", "secao": "",
            })
            st.rerun()
    with col_a3:
        if st.button("🗑️ Limpar tudo", use_container_width=True,
                      help="Remove todas as frases (cuidado!)"):
            st.session_state["molde_gabarito_lista"] = []
            st.rerun()
    with col_a4:
        avancar_disabled = not _gabarito_pronto()
        if st.button("➡️ Ir para Fase 2", use_container_width=True,
                      disabled=avancar_disabled, type="primary",
                      help=("Adicione ao menos 1 frase para avançar."
                            if avancar_disabled else "Avança para PDF & Detecção.")):
            _trocar_fase(FASE_PDF)
            st.rerun()

    # ── UPLOAD DE GABARITO (.json/.csv/.xlsx/.xls/.txt/.md) ──
    with st.expander("📤 Importar gabarito de arquivo (`.json`, `.csv`, `.xlsx`, `.xls`, `.txt`, `.md`)",
                      expanded=False):
        st.caption(
            "Suba uma lista de frases pronta. Formatos aceitos:\n\n"
            "- **JSON**: lista de strings `[\"frase1\", \"frase2\"]` OU lista de dicts "
            "`[{\"frase\":\"...\", \"secao\":\"...\"}]` OU dicionário "
            "`{\"Seção A\": [\"...\"], \"Seção B\": [\"...\"]}`.\n"
            "- **CSV**: colunas `Frase` e (opcional) `Secao`. Aceita sem cabeçalho.\n"
            "- **XLSX / XLS**: planilha Excel. Lê a **primeira aba**. Mesma semântica "
            "do CSV — colunas `Frase` e (opcional) `Secao`. Sem cabeçalho: coluna A = frase, "
            "coluna B = seção. Suporte a `.xls` legado requer o pacote `xlrd`.\n"
            "- **TXT / MD**: uma frase por linha. Marcadores `-`, `*`, `1.` são removidos."
        )
        # Chave DINÂMICA controlada por counter — quando o usuário aperta
        # "Limpar arquivo", incrementamos o counter, o Streamlit cria um
        # widget NOVO e descarta o anterior (com qualquer arquivo agarrado,
        # mesmo rejeitado por extensão). Padrão consagrado da comunidade.
        _upl_counter = st.session_state.get("upload_gabarito_counter", 0)
        _upl_key     = f"upload_gabarito_arq_{_upl_counter}"
        arq_gab = st.file_uploader(
            "Arquivo de gabarito",
            type=["json", "csv", "xlsx", "xls", "txt", "md"],
            key=_upl_key,
            accept_multiple_files=False,
        )
        # Botão Limpar — sempre habilitado quando algum arquivo está no widget,
        # mesmo que o Streamlit tenha rejeitado por extensão errada.
        col_clear, _col_clear_sp = st.columns([1.4, 4])
        with col_clear:
            if st.button("🗑️ Limpar arquivo",
                          key=f"btn_limpar_upload_{_upl_counter}",
                          help="Remove o arquivo selecionado e libera o uploader."):
                st.session_state["upload_gabarito_counter"] = _upl_counter + 1
                st.rerun()

        col_u1, col_u2 = st.columns([1, 1])
        with col_u1:
            modo_import = st.radio(
                "Modo de importação",
                options=["substituir", "anexar"],
                format_func=lambda m: ("🔄 Substituir lista atual"
                                        if m == "substituir"
                                        else "📎 Anexar ao final"),
                horizontal=True,
                key="upload_gabarito_modo",
            )
        with col_u2:
            if st.button("📥 Importar agora", use_container_width=True,
                          disabled=(arq_gab is None), type="primary"):
                if arq_gab is None:
                    st.warning("Selecione um arquivo primeiro.")
                else:
                    conteudo = arq_gab.getvalue()
                    ok, lista, msg = parse_gabarito_arquivo(conteudo, arq_gab.name)
                    if not ok:
                        st.error(f"❌ {msg}")
                    else:
                        if modo_import == "substituir":
                            st.session_state["molde_gabarito_lista"] = lista
                        else:
                            atual = st.session_state.get("molde_gabarito_lista", [])
                            combinada = atual + lista
                            # Renumera IDs
                            for i, item in enumerate(combinada, start=1):
                                item["id"] = i
                            st.session_state["molde_gabarito_lista"] = combinada
                        st.success(f"✅ {msg}")
                        st.rerun()

    st.divider()

    # ── LISTA EDITÁVEL ──
    st.markdown(f"### 📜 Frases definidas — **{len(gabarito_atual)}**")
    if not gabarito_atual:
        st.warning("⚠️ Nenhuma frase definida. Use **📥 Carregar padrão**, **📤 Importar** "
                   "ou **➕ Adicionar**.")
        return

    for idx_g, g in enumerate(list(gabarito_atual)):
        cQ, cFrase, cSec, cDel = st.columns([0.5, 5, 2.5, 0.5])
        with cQ:
            st.markdown(f"**Q{idx_g+1}**")
        with cFrase:
            nova_frase = st.text_input(
                "Frase",
                value=g.get("frase", ""),
                key=f"gab_frase_{idx_g}",
                label_visibility="collapsed",
            )
            if nova_frase != g.get("frase"):
                st.session_state["molde_gabarito_lista"][idx_g]["frase"] = nova_frase
        with cSec:
            secao_atual = g.get("secao", "")
            nova_secao = st.text_input(
                "Seção",
                value=secao_atual,
                key=f"gab_secao_{idx_g}",
                placeholder="(opcional)",
                label_visibility="collapsed",
            )
            if nova_secao != secao_atual:
                st.session_state["molde_gabarito_lista"][idx_g]["secao"] = nova_secao
        with cDel:
            if st.button("🗑️", key=f"gab_del_{idx_g}", help="Remover esta frase"):
                st.session_state["molde_gabarito_lista"].pop(idx_g)
                for j, gg in enumerate(st.session_state["molde_gabarito_lista"]):
                    gg["id"] = j + 1
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# FASE 2: PDF & DETECÇÃO
# ═══════════════════════════════════════════════════════════════════════════
def _renderizar_fase_pdf():
    st.markdown("## 2️⃣ PDF & Detecção")
    st.caption(
        "Dê um nome ao molde, suba o PDF da prova e detecte os candidatos automaticamente."
    )

    # ─────────────────────────────────────────────────────────────────────
    # 1) CARD VERDE no TOPO — quando JÁ existe PDF carregado (edição ou
    #    detecção anterior nesta sessão). Mostra metadata e oferece avançar.
    # ─────────────────────────────────────────────────────────────────────
    if _pdf_pronto():
        n_paginas = len(st.session_state.get("molde_paginas", {}))
        n_cand    = len(st.session_state.get("molde_candidatos", []))
        n_manuais = len(st.session_state.get("molde_manuais", []))
        pdf_path  = st.session_state.get("molde_pdf_path", "")
        em_edicao = st.session_state.get("molde_em_edicao")
        nome_arq  = os.path.basename(pdf_path) if pdf_path else "(sem path)"

        if em_edicao:
            # Modo EDIÇÃO de molde salvo — não precisa redetectar
            st.success(
                f"✅ **PDF de referência já carregado** — `{nome_arq}`  \n"
                f"📄 {n_paginas} página(s) · ✋ {n_manuais} quadrado(s) calibrados anteriormente · "
                f"🤖 {n_cand} candidato(s) auto  \n"
                f"_Você está **editando** o molde **{em_edicao}**. "
                f"Não é necessário subir o PDF de novo — vá direto para a Fase 3._"
            )
        else:
            # Detecção feita nesta sessão (molde novo)
            st.success(
                f"✅ **PDF processado nesta sessão** — `{nome_arq}`  \n"
                f"📄 {n_paginas} página(s) · 🤖 {n_cand} candidato(s) detectado(s) automaticamente"
            )

        col_p1, col_p2 = st.columns([2, 1])
        with col_p1:
            if st.button("➡️ Ir para Fase 3 — Calibração",
                          type="primary", use_container_width=True,
                          key="btn_avancar_calib_topo"):
                _trocar_fase(FASE_CALIB)
                st.rerun()
        with col_p2:
            if st.button("🔄 Trocar / Re-detectar PDF",
                          use_container_width=True,
                          help="Apaga o PDF atual desta sessão e libera novo upload abaixo. "
                               "(NÃO apaga o JSON salvo no disco.)",
                          key="btn_trocar_pdf"):
                for k in ["molde_candidatos", "molde_descartados", "molde_manuais",
                          "molde_paginas", "molde_pdf_path", "molde_ultimo_click",
                          "molde_frases_custom", "molde_paginas_editadas",
                          "molde_pdf_hash"]:
                    st.session_state.pop(k, None)
                # Sai do modo edição (vai virar um molde NOVO com mesmo nome)
                st.session_state.pop("molde_em_edicao", None)
                st.warning("PDF anterior descartado. Suba um novo PDF abaixo.")
                st.rerun()

        st.divider()

    # ─────────────────────────────────────────────────────────────────────
    # 2) UPLOAD DO PDF + DETECTAR
    # (o NOME do molde é definido APENAS no cabeçalho do topo da página,
    #  que é persistente entre todas as fases — não duplicamos aqui.)
    # ─────────────────────────────────────────────────────────────────────
    nome_molde = (st.session_state.get("molde_nome") or "Prova_Nova").strip() or "Prova_Nova"
    st.session_state["molde_nome"] = nome_molde  # mantém canônico atualizado

    _nome_safe_f2 = _sanitizar_nome_filesystem(nome_molde)
    if _nome_safe_f2 != nome_molde:
        st.caption(
            f"📛 Nome do molde: **`{nome_molde}`** → arquivo no disco: "
            f"`moldes/{_nome_safe_f2}.json` (acentos/espaços normalizados). "
            f"Edite no topo da página se quiser mudar."
        )
    else:
        st.caption(
            f"📛 Nome do molde: **`{nome_molde}`** — arquivo: "
            f"`moldes/{_nome_safe_f2}.json`. Edite no topo para alterar."
        )

    label_uploader = ("PDF da prova (substituir o atual)"
                      if _pdf_pronto() else "PDF da prova")
    pdf_uploaded = st.file_uploader(
        label_uploader,
        type=["pdf"],
        key="molde_pdf_upload",
    )

    if st.button("🔍 Detectar candidatos no PDF",
                 type="primary",
                 use_container_width=True,
                 disabled=(pdf_uploaded is None)):
        if pdf_uploaded is None:
            st.error("Faça upload de um PDF primeiro.")
        else:
            pdf_bytes = pdf_uploaded.getbuffer()
            hash_atual = _hash_pdf(bytes(pdf_bytes))

            pdf_temp = os.path.join(garantir_pasta_moldes(), f"_tmp_{int(time.time())}.pdf")
            with open(pdf_temp, "wb") as f:
                f.write(pdf_bytes)

            with st.spinner("Detectando candidatos via template matching..."):
                resultado = detectar_candidatos_para_molde(pdf_temp)

            if "erro" in resultado:
                st.error(f"❌ {resultado['erro']}")
            else:
                hash_anterior = st.session_state.get("molde_pdf_hash")
                if hash_atual != hash_anterior:
                    st.session_state["molde_pdf_hash"]      = hash_atual
                    st.session_state["molde_pdf_path"]      = pdf_temp
                    st.session_state["molde_paginas"]       = resultado["paginas_imagens"]
                    st.session_state["molde_candidatos"]    = resultado["candidatos"]
                    st.session_state["molde_descartados"]   = set()
                    st.session_state["molde_manuais"]       = []
                    st.session_state["molde_ultimo_click"]  = {}
                    st.session_state["molde_frases_custom"] = {}
                    st.session_state["molde_paginas_editadas"] = set()
                    st.session_state["molde_pag_atual"]     = 0
                    st.success(f"✅ {len(resultado['candidatos'])} candidatos em "
                               f"{resultado['qtd_paginas']} páginas. "
                               f"Pulando para Fase 3 (Calibração).")
                else:
                    st.info("📄 Mesmo PDF — preservando estado anterior.")
                _trocar_fase(FASE_CALIB)
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# FASE 3: CALIBRAÇÃO
# ═══════════════════════════════════════════════════════════════════════════
def _renderizar_fase_calibracao():
    st.markdown("## 3️⃣ Calibração")

    candidatos      = st.session_state["molde_candidatos"]
    descartados     = st.session_state["molde_descartados"]
    manuais         = st.session_state["molde_manuais"]
    paginas         = st.session_state["molde_paginas"]
    frases_custom   = st.session_state.get("molde_frases_custom", {})
    pags_editadas   = st.session_state.get("molde_paginas_editadas", set())
    ultimo_click_dict = st.session_state.get("molde_ultimo_click", {})
    gabarito_atual  = st.session_state.get("molde_gabarito_lista", [])

    # Lista de quadrados ATIVOS
    ativos_detectados = [c for i, c in enumerate(candidatos) if i not in descartados]
    todos_ativos      = list(ativos_detectados) + list(manuais)
    todos_ativos.sort(key=lambda c: (c["pag"], c["y"], c["x"]))
    for n, q in enumerate(todos_ativos):
        q["n_global"] = n + 1

    qtd_ativos = len(todos_ativos)
    qtd_alvo   = len(gabarito_atual)
    lista_frases_disponiveis = [g["frase"] for g in gabarito_atual]
    mapa_frase_para_secao    = {g["frase"]: g.get("secao", "") for g in gabarito_atual}

    em_edicao = st.session_state.get("molde_em_edicao")
    if em_edicao:
        st.info(f"✏️ **MODO EDIÇÃO** — editando molde existente: **{em_edicao}**. "
                f"Salvar sobrescreve o JSON e o PDF de referência.")

    # ── HEADER DE STATUS ──
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("📦 Detec.", len(candidatos))
    col_m2.metric("❌ Desc.", len(descartados))
    col_m3.metric("➕ Manuais", len(manuais))
    delta = qtd_ativos - qtd_alvo
    col_m4.metric(f"✅ / {qtd_alvo}", qtd_ativos,
                  delta=delta if delta != 0 else None,
                  delta_color="inverse" if delta != 0 else "off")

    completo = (qtd_ativos == qtd_alvo) and (qtd_alvo > 0)

    # Banner de status
    if qtd_alvo == 0:
        st.error("⚠️ Sem gabarito! Volte para a Fase 1 e defina ao menos 1 frase.")
    elif completo:
        st.success(f"🎯 PERFEITO! {qtd_ativos}/{qtd_alvo} — molde COMPLETO.")
    elif qtd_ativos < qtd_alvo:
        st.warning(f"⚠️ Faltam {qtd_alvo - qtd_ativos}. Pode salvar PARCIAL e continuar depois.")
    else:
        st.warning(f"⚠️ {qtd_ativos - qtd_alvo} a mais. Descartar os errados ou salvar mesmo assim.")

    col_ir_salvar, col_resetar = st.columns([2, 1])
    with col_ir_salvar:
        if st.button("➡️ Ir para Fase 4 — Salvar",
                      type="primary", use_container_width=True,
                      disabled=(qtd_ativos == 0)):
            _trocar_fase(FASE_SALVAR)
            st.rerun()
    with col_resetar:
        if st.button("🔄 Resetar calibração", use_container_width=True,
                      help="Limpa toda a calibração atual (mantém gabarito de frases)"):
            for k in ["molde_candidatos", "molde_descartados", "molde_manuais",
                      "molde_paginas", "molde_pdf_path", "molde_ultimo_click",
                      "molde_frases_custom", "molde_paginas_editadas",
                      "molde_pdf_hash", "molde_em_edicao"]:
                st.session_state.pop(k, None)
            _trocar_fase(FASE_PDF)
            st.rerun()

    st.divider()

    # ─────────────────────────────────────────────────────────────────────
    # LAYOUT 2 COLUNAS: LATERAL (thumbs à esquerda) + PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────
    col_lateral, col_principal = st.columns([1, 4])

    paginas_disponiveis = sorted(paginas.keys())
    pag_atual = st.session_state.get("molde_pag_atual", paginas_disponiveis[0])
    if pag_atual not in paginas_disponiveis:
        pag_atual = paginas_disponiveis[0]
        st.session_state["molde_pag_atual"] = pag_atual

    with col_lateral:
        st.markdown("##### 📑 Páginas")
        for npag in paginas_disponiveis:
            quadrados_pag_t = [q for q in todos_ativos if q["pag"] == npag]
            qtd_pag = len(quadrados_pag_t)
            foi_editada = npag in pags_editadas
            is_atual = (npag == pag_atual)

            if qtd_pag == 0:
                emoji_status = "⏳"
            elif foi_editada:
                emoji_status = "✏️"
            else:
                emoji_status = "🤖"

            estilo_label = f"**{emoji_status} Pag {npag+1}** — {qtd_pag}"
            if is_atual:
                estilo_label = f"👉 {estilo_label}"
            st.markdown(estilo_label)

            thumb = _gerar_thumbnail(paginas[npag], quadrados_pag_t, pag_atual, is_atual, largura=130)
            click_thumb = streamlit_image_coordinates(
                thumb, key=f"thumb_pag{npag}", width=130,
            )
            if click_thumb is not None:
                ultimo_thumb_key = f"thumb_{npag}"
                click_tuple = (int(click_thumb["x"]), int(click_thumb["y"]))
                if ultimo_click_dict.get(ultimo_thumb_key) != click_tuple:
                    ultimo_click_dict[ultimo_thumb_key] = click_tuple
                    st.session_state["molde_ultimo_click"] = ultimo_click_dict
                    if npag != pag_atual:
                        st.session_state["molde_pag_atual"] = npag
                        st.rerun()

    with col_principal:
        st.markdown(f"### 📄 Página {pag_atual+1}")

        modo = st.radio(
            "🖱️ Modo de clique",
            options=["adicionar", "descartar"],
            format_func=lambda m: ("🟢 Adicionar quadrado (clique onde está faltando)"
                                    if m == "adicionar"
                                    else "🔴 Descartar quadrado (clique em cima do errado)"),
            horizontal=True,
            index=0 if st.session_state.get("molde_modo_clique", "adicionar") == "adicionar" else 1,
            key=f"radio_modo_pag{pag_atual}",
        )
        st.session_state["molde_modo_clique"] = modo

        img_pag_bgr = paginas[pag_atual]
        h_orig, w_orig = img_pag_bgr.shape[:2]
        quadrados_pag = [q for q in todos_ativos if q["pag"] == pag_atual]

        img_rgb, escala = _anotar_pagina(img_pag_bgr, quadrados_pag, w_largura_max=750)

        st.caption(
            f"Orig: **{w_orig}×{h_orig}** · escala: **{escala:.1%}** · "
            f"VERDE = detectado · VERMELHO = manual"
        )

        click = streamlit_image_coordinates(
            img_rgb,
            key=f"img_clique_pag{pag_atual}",
            width=img_rgb.shape[1],
        )

        if click is not None:
            ultimo_click_pag_key = f"main_{pag_atual}"
            click_tuple = (int(click["x"]), int(click["y"]))
            if ultimo_click_dict.get(ultimo_click_pag_key) != click_tuple:
                ultimo_click_dict[ultimo_click_pag_key] = click_tuple
                st.session_state["molde_ultimo_click"] = ultimo_click_dict

                click_x_resized, click_y_resized = click_tuple
                x_orig, y_orig = _converter_clique(click_x_resized, click_y_resized, escala)

                if modo == "adicionar":
                    W_PAD, H_PAD = 35, 30
                    novo = {
                        "pag":    int(pag_atual),
                        "x":      int(x_orig - W_PAD // 2),
                        "y":      int(y_orig - H_PAD // 2),
                        "w":      W_PAD,
                        "h":      H_PAD,
                        "score":  1.0,
                        "stddev": 0.0,
                        "manual": True,
                    }
                    st.session_state["molde_manuais"].append(novo)
                    st.session_state["molde_paginas_editadas"].add(pag_atual)
                    st.success(f"➕ Quadrado adicionado em ({x_orig}, {y_orig})")
                    st.rerun()
                else:
                    melhor_idx = None
                    melhor_dist = 10**9
                    melhor_eh_manual = False
                    for i, c in enumerate(candidatos):
                        if c["pag"] != pag_atual: continue
                        if i in descartados: continue
                        cx = c["x"] + c["w"]/2
                        cy = c["y"] + c["h"]/2
                        dist = (cx - x_orig)**2 + (cy - y_orig)**2
                        if dist < melhor_dist:
                            melhor_dist = dist
                            melhor_idx  = i
                            melhor_eh_manual = False
                    for j, c in enumerate(manuais):
                        if c["pag"] != pag_atual: continue
                        cx = c["x"] + c["w"]/2
                        cy = c["y"] + c["h"]/2
                        dist = (cx - x_orig)**2 + (cy - y_orig)**2
                        if dist < melhor_dist:
                            melhor_dist = dist
                            melhor_idx  = j
                            melhor_eh_manual = True

                    if melhor_idx is not None and melhor_dist < 80**2:
                        if melhor_eh_manual:
                            st.session_state["molde_manuais"].pop(melhor_idx)
                        else:
                            st.session_state["molde_descartados"].add(melhor_idx)
                        st.session_state["molde_paginas_editadas"].add(pag_atual)
                        st.warning(f"🗑️ Quadrado descartado perto de ({x_orig}, {y_orig})")
                        st.rerun()
                    else:
                        st.error(f"❌ Nenhum quadrado próximo de ({x_orig}, {y_orig}).")

        with st.expander(f"📋 Quadrados desta página ({len(quadrados_pag)}) — editar frase associada",
                          expanded=False):
            if not quadrados_pag:
                st.info("Nenhum quadrado nesta página. Use **Adicionar** para criar.")
            else:
                for q in quadrados_pag:
                    n = q["n_global"]
                    origem = "✋ manual" if q.get("manual") else "🤖 auto"
                    if not lista_frases_disponiveis:
                        with st.container(border=True):
                            st.warning(f"#{n} — Defina frases na Fase 1 primeiro.")
                        continue

                    frase_default_idx = (n - 1) if (n - 1) < len(lista_frases_disponiveis) else 0
                    frase_custom = frases_custom.get(str(n))
                    if frase_custom and frase_custom in lista_frases_disponiveis:
                        idx_frase = lista_frases_disponiveis.index(frase_custom)
                    else:
                        idx_frase = frase_default_idx if n <= len(lista_frases_disponiveis) else 0

                    with st.container(border=True):
                        cN, cI, cF, cD = st.columns([1, 2, 5, 1])
                        with cN:
                            st.markdown(f"### #{n}")
                            st.caption(origem)
                        with cI:
                            st.markdown(f"📍 ({q['x']}, {q['y']})")
                            st.caption(f"{q['w']}×{q['h']} px")
                        with cF:
                            nova_frase = st.selectbox(
                                "Frase",
                                options=lista_frases_disponiveis,
                                index=idx_frase,
                                key=f"frase_q{n}_pag{pag_atual}",
                                label_visibility="collapsed",
                            )
                            st.session_state["molde_frases_custom"][str(n)] = nova_frase
                            secao = mapa_frase_para_secao.get(nova_frase, "")
                            st.caption(f"🏷️ {secao}" if secao else "🏷️ (sem seção)")
                        with cD:
                            if q.get("manual"):
                                idx_m = None
                                for j, mm in enumerate(manuais):
                                    if mm["x"] == q["x"] and mm["y"] == q["y"] and mm["pag"] == q["pag"]:
                                        idx_m = j; break
                                if st.button("🗑️", key=f"del_man_q{n}", help="Remover"):
                                    if idx_m is not None:
                                        st.session_state["molde_manuais"].pop(idx_m)
                                        st.session_state["molde_paginas_editadas"].add(pag_atual)
                                        st.rerun()
                            else:
                                idx_c = None
                                for i, c in enumerate(candidatos):
                                    if (c["pag"] == q["pag"] and c["x"] == q["x"]
                                        and c["y"] == q["y"] and c["w"] == q["w"]):
                                        idx_c = i; break
                                if st.button("🗑️", key=f"desc_q{n}", help="Descartar"):
                                    if idx_c is not None:
                                        st.session_state["molde_descartados"].add(idx_c)
                                        st.session_state["molde_paginas_editadas"].add(pag_atual)
                                        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# FASE 4: SALVAR
# ═══════════════════════════════════════════════════════════════════════════
def _renderizar_fase_salvar():
    st.markdown("## 4️⃣ Salvar Molde")

    candidatos      = st.session_state.get("molde_candidatos", [])
    descartados     = st.session_state.get("molde_descartados", set())
    manuais         = st.session_state.get("molde_manuais", [])
    paginas         = st.session_state.get("molde_paginas", {})
    pdf_path        = st.session_state.get("molde_pdf_path", "")
    frases_custom   = st.session_state.get("molde_frases_custom", {})
    gabarito_atual  = st.session_state.get("molde_gabarito_lista", [])
    nome_molde      = st.session_state.get("molde_nome", "Prova_Padrao_Mat_6ano")

    ativos_detectados = [c for i, c in enumerate(candidatos) if i not in descartados]
    todos_ativos      = list(ativos_detectados) + list(manuais)
    todos_ativos.sort(key=lambda c: (c["pag"], c["y"], c["x"]))
    for n, q in enumerate(todos_ativos):
        q["n_global"] = n + 1

    qtd_ativos = len(todos_ativos)
    qtd_alvo   = len(gabarito_atual)
    completo   = (qtd_ativos == qtd_alvo) and (qtd_alvo > 0)

    st.markdown("### 📊 Resumo do molde")
    col_r1, col_r2, col_r3, col_r4 = st.columns(4)
    col_r1.metric("📝 Frases (Fase 1)", qtd_alvo)
    col_r2.metric("📦 Quadrados ativos", qtd_ativos)
    col_r3.metric("📄 Páginas", len(paginas))
    col_r4.metric("Status", "COMPLETO ✅" if completo else "PARCIAL ⚠️")

    st.markdown(f"**Nome do molde:** `{nome_molde}`")
    em_edicao = st.session_state.get("molde_em_edicao")
    if em_edicao:
        st.info(f"✏️ **MODO EDIÇÃO** — vai sobrescrever **{em_edicao}** (JSON + PDF de referência).")

    if completo:
        st.success(f"🎯 PERFEITO! {qtd_ativos}/{qtd_alvo} — pronto para salvar como COMPLETO.")
    elif qtd_ativos < qtd_alvo:
        st.warning(f"⚠️ Faltam {qtd_alvo - qtd_ativos}. Pode salvar PARCIAL e continuar depois.")
    else:
        st.warning(f"⚠️ {qtd_ativos - qtd_alvo} quadrado(s) a mais que frases — salve mesmo assim ou volte à Fase 3 para descartar.")

    # ─────────────────────────────────────────────────────────────────────
    # SELETOR DE TEMPLATE DE LAYOUT (calibrado 2026-05-25)
    # Define como o motor OCR vai cortar/enviar cada fatia ao LLM.
    # Autodetecta com base na disposição dos quadrados; usuário pode sobrescrever.
    # ─────────────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 🧩 Template de Layout (motor OCR)")

    _layout_sugerido = detectar_template_layout(
        todos_ativos,
        {int(p): {"h": img.shape[0], "w": img.shape[1]} for p, img in paginas.items()}
    )
    _layout_options = {
        "multipla_escolha_esquerda":
            "🎯 Esquerda (recomendado para questionários) — crop estreito, ~89% menos tokens, mais rápido e mais preciso com Gemini",
        "hibrido_sem_corte":
            "📐 Híbrido — full-width (legado), use só se a prova tiver checkboxes em colunas variáveis ou layout misto",
    }
    _layout_keys = list(_layout_options.keys())
    _layout_idx_sugerido = _layout_keys.index(_layout_sugerido)
    template_layout_escolhido = st.selectbox(
        "Layout do crop horizontal — escolha o que faz o motor OCR enxergar",
        options=_layout_keys,
        format_func=lambda k: _layout_options[k],
        index=_layout_idx_sugerido,
        key="molde_template_layout_selector",
        help=("Sugestão automática baseada na disposição dos quadrados detectados. "
              "Você pode sobrescrever se souber que sua prova tem layout especial."),
    )
    if template_layout_escolhido == _layout_sugerido:
        st.caption(f"✨ Auto-sugerido pela disposição dos {len(todos_ativos)} quadrados.")
    else:
        st.caption(f"⚠️ Override manual — autodetecção sugeriu `{_layout_sugerido}`.")

    st.divider()

    col_b1, col_b2, col_b3 = st.columns([2, 1, 1])
    with col_b1:
        label_save = "💾 Salvar COMPLETO" if completo else "💾 Salvar PARCIAL"
        if st.button(label_save, type="primary", use_container_width=True):
            _salvar_molde_atual(nome_molde, pdf_path, paginas, todos_ativos,
                                frases_custom, completo,
                                template_layout=template_layout_escolhido)
    with col_b2:
        if st.button("⬅️ Voltar à Calibração", use_container_width=True):
            _trocar_fase(FASE_CALIB)
            st.rerun()
    with col_b3:
        ver_json = st.toggle("👁️ Ver JSON", value=False, help="Preview do JSON antes de salvar")

    if ver_json:
        with st.expander("📜 JSON do molde atual (preview)", expanded=True):
            dimensoes_preview = {}
            for npag_i, img_i in paginas.items():
                h_i, w_i = img_i.shape[:2]
                dimensoes_preview[int(npag_i)] = {"h": int(h_i), "w": int(w_i)}
            preview = montar_molde_final(
                nome=nome_molde,
                fonte_pdf=pdf_path,
                quadrados_ordenados=todos_ativos,
                dimensoes_pag=dimensoes_preview,
                dpi=DPI_PADRAO,
                gabarito_frases=gabarito_atual,
            )
            preview["completo"] = bool(completo)
            mapa_frase_secao = {g["frase"]: g.get("secao", "") for g in gabarito_atual}
            for pag_str_p, pag_data_p in preview["paginas"].items():
                for q_p in pag_data_p["quadrados"]:
                    nid = q_p["id"]
                    if str(nid) in frases_custom:
                        q_p["frase"] = frases_custom[str(nid)]
                        q_p["secao"] = mapa_frase_secao.get(frases_custom[str(nid)], "")
            st.json(preview)


# ═══════════════════════════════════════════════════════════════════════════
# UI PRINCIPAL — LIST-DETAIL DISPATCHER
# ═══════════════════════════════════════════════════════════════════════════
def renderizar():
    st.title("🎓 Treinamento de Molde de Prova")
    st.caption(
        "Calibre **uma vez** o gabarito de coordenadas. "
        "Provas futuras com o mesmo layout serão processadas automaticamente."
    )

    if not VISAO_OK:
        st.error("❌ OpenCV/PyMuPDF/NumPy ausentes. Rode: `pip install opencv-python pymupdf numpy`")
        return
    if not COMPONENTE_OK:
        st.error("❌ Pacote 'streamlit-image-coordinates' ausente. Rode: `pip install streamlit-image-coordinates`")
        return

    garantir_pasta_moldes()

    view = _view_atual()

    if view == VIEW_LISTA:
        _renderizar_listagem_home()
        return

    # ── VIEW = EDITOR ──
    if "molde_gabarito_lista" not in st.session_state:
        st.session_state["molde_gabarito_lista"] = gabarito_padrao_como_lista()

    _renderizar_menu_topo()
    st.divider()

    fase = _fase_ativa()

    if fase == FASE_GABARITO:
        _renderizar_fase_gabarito()
    elif fase == FASE_PDF:
        _renderizar_fase_pdf()
    elif fase == FASE_CALIB:
        if not _pdf_pronto():
            st.warning("⚠️ Suba e detecte um PDF na Fase 2 antes de calibrar.")
            if st.button("⬅️ Voltar para Fase 2"):
                _trocar_fase(FASE_PDF)
                st.rerun()
        else:
            _renderizar_fase_calibracao()
    elif fase == FASE_SALVAR:
        if not _calibracao_pronta():
            st.warning("⚠️ Calibre ao menos 1 quadrado na Fase 3 antes de salvar.")
            if st.button("⬅️ Voltar para Fase 3"):
                _trocar_fase(FASE_CALIB)
                st.rerun()
        else:
            _renderizar_fase_salvar()
    elif fase == FASE_AJUDA:
        _renderizar_fase_ajuda()
    else:
        _renderizar_fase_gabarito()


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: SALVAR MOLDE
# ═══════════════════════════════════════════════════════════════════════════
def _salvar_molde_atual(nome_molde, pdf_path, paginas, todos_ativos,
                         frases_custom, completo, template_layout=None):
    """Salva o molde atual em moldes/<nome>.json + COPIA o PDF para moldes/<nome>.pdf.
    Usa o GABARITO DINÂMICO do session_state["molde_gabarito_lista"].

    template_layout: 'multipla_escolha_esquerda' (default, Esquerda) ou
                     'hibrido_sem_corte' (full-width, legado). Se None,
                     a autodetecção do montar_molde_final decide."""

    # ═══════════════════════════════════════════════════════════════════
    # INSTRUMENTAÇÃO FORENSE — para diagnosticar "molde salvou mas sumiu"
    # ═══════════════════════════════════════════════════════════════════
    with st.expander("🔬 Diagnóstico do salvamento (clique para abrir)",
                      expanded=False):
        try:
            from backend_molde import (
                _sanitizar_nome_filesystem as _san_fs,
                molde_path as _mp,
                molde_pdf_path as _mpp,
                PASTA_MOLDES as _pasta_const,
                garantir_pasta_moldes as _garantir,
            )
            _cwd = os.getcwd()
            _pasta_abs = _garantir()
            _arquivos_antes = sorted(os.listdir(_pasta_abs))
            _qtd_json_antes = len([f for f in _arquivos_antes if f.endswith(".json")])

            st.code(
                f"NOME RECEBIDO       : {nome_molde!r}\n"
                f"NOME SANITIZADO     : {_san_fs(nome_molde)!r}\n"
                f"PATH JSON ESPERADO  : {_mp(nome_molde)}\n"
                f"PATH PDF ESPERADO   : {_mpp(nome_molde)}\n"
                f"PASTA_MOLDES const  : {_pasta_const!r}\n"
                f"PASTA ABSOLUTA      : {_pasta_abs}\n"
                f"CWD (cwd)           : {_cwd}\n"
                f"PASTA EXISTE        : {os.path.exists(_pasta_abs)}\n"
                f"PASTA ESCREVÍVEL    : {os.access(_pasta_abs, os.W_OK)}\n"
                f"JSON na pasta ANTES : {_qtd_json_antes}\n"
                f"ARQUIVOS NA PASTA   : {len(_arquivos_antes)}",
                language="text"
            )
            st.session_state["_diag_qtd_json_antes"] = _qtd_json_antes
            st.session_state["_diag_arquivos_antes"] = _arquivos_antes
            st.session_state["_diag_pasta_abs"] = _pasta_abs
        except Exception as _e:
            import traceback as _tb
            st.error(f"⚠️ Falha no diagnóstico pré-save: {_e}")
            st.code(_tb.format_exc(), language="text")

    dimensoes = {}
    for npag, img in paginas.items():
        h, w = img.shape[:2]
        dimensoes[int(npag)] = {"h": int(h), "w": int(w)}

    gabarito_lista = st.session_state.get("molde_gabarito_lista", [])
    mapa_frase_secao = {g["frase"]: g.get("secao", "") for g in gabarito_lista}

    molde = montar_molde_final(
        nome=nome_molde,
        fonte_pdf=pdf_path,
        quadrados_ordenados=todos_ativos,
        dimensoes_pag=dimensoes,
        dpi=DPI_PADRAO,
        gabarito_frases=gabarito_lista,
        template_layout=template_layout,
    )
    molde["completo"] = bool(completo)

    for pag_str, pag_data in molde["paginas"].items():
        for q in pag_data["quadrados"]:
            n = q["id"]
            if str(n) in frases_custom:
                frase_escolhida = frases_custom[str(n)]
                q["frase"] = frase_escolhida
                q["secao"] = mapa_frase_secao.get(frase_escolhida, "")
                for g in gabarito_lista:
                    if g["frase"] == frase_escolhida:
                        q["frase_id"] = g["id"]
                        break

    ok_json, msg_json, path_json_abs = salvar_molde(nome_molde, molde)
    st.code(f"📂 JSON: {path_json_abs}", language="bash")

    if ok_json:
        if completo:
            st.balloons()
            st.success(f"✅ JSON {nome_molde} salvo COMPLETO — {msg_json}")
        else:
            st.info(f"💾 JSON {nome_molde} salvo PARCIAL — {msg_json}")
    else:
        st.error(f"❌ FALHA AO SALVAR JSON: {msg_json}")
        st.error(f"Path tentado: {path_json_abs}")
        pasta = os.path.dirname(path_json_abs)
        st.info(f"Pasta de destino existe? {os.path.exists(pasta)}")
        st.info(f"Pasta tem permissão de escrita? {os.access(pasta, os.W_OK)}")
        return

    if pdf_path and os.path.exists(pdf_path):
        ok_pdf, msg_pdf, path_pdf_abs = salvar_pdf_referencia(nome_molde, pdf_path)
        st.code(f"📂 PDF ref: {path_pdf_abs}", language="bash")
        if ok_pdf:
            st.success(f"✅ PDF de referência copiado — {msg_pdf}")
        else:
            st.warning(f"⚠️ JSON salvo OK, mas falhou ao copiar PDF: {msg_pdf}")
    else:
        st.warning(f"⚠️ PDF original não localizado em {pdf_path} — molde salvo SEM PDF.")

    try:
        with open(path_json_abs, "r", encoding="utf-8") as f:
            import json as _json
            conteudo = _json.load(f)
            st.success(f"🔍 Verificação OK · {conteudo.get('qtd_quadrados', 0)} quadrados · "
                       f"{conteudo.get('qtd_frases_gabarito', 0)} frases no gabarito")
    except Exception as e:
        st.warning(f"⚠️ Salvou mas não conseguiu reler o arquivo: {e}")

    # ═══ INSTRUMENTAÇÃO FORENSE PÓS-SALVE ═══
    with st.expander("🔬 Diagnóstico PÓS-salvamento (clique para abrir)",
                      expanded=False):
        try:
            _pasta_abs = st.session_state.get("_diag_pasta_abs", os.path.abspath("moldes"))
            _arquivos_depois = sorted(os.listdir(_pasta_abs))
            _qtd_json_depois = len([f for f in _arquivos_depois if f.endswith(".json")])
            _qtd_antes = st.session_state.get("_diag_qtd_json_antes", 0)
            _arquivos_antes = st.session_state.get("_diag_arquivos_antes", [])
            _novos = sorted(set(_arquivos_depois) - set(_arquivos_antes))

            st.code(
                f"JSON antes  : {_qtd_antes}\n"
                f"JSON depois : {_qtd_json_depois}\n"
                f"Delta JSON  : {_qtd_json_depois - _qtd_antes}\n"
                f"NOVOS ARQUIVOS NESTA SESSÃO: {_novos}\n"
                f"PATH ESPERADO existe? {os.path.exists(path_json_abs)}\n"
                f"PATH ESPERADO tamanho: "
                f"{os.path.getsize(path_json_abs) if os.path.exists(path_json_abs) else 'N/A'}",
                language="text"
            )
            if not _novos:
                st.error(
                    "🚨 NENHUM arquivo novo apareceu na pasta! "
                    "O salvamento provavelmente ABORTOU sem exception visível. "
                    "Manda esse diagnóstico pro Claude."
                )
            elif any(n.endswith(".json") for n in _novos):
                st.success(f"✅ Arquivo(s) JSON aparecido(s): {[n for n in _novos if n.endswith('.json')]}")
        except Exception as _e:
            import traceback as _tb
            st.error(f"⚠️ Falha no diagnóstico pós-save: {_e}")
            st.code(_tb.format_exc(), language="text")

    st.divider()
    col_pos1, col_pos2 = st.columns(2)
    with col_pos1:
        if st.button("📂 Voltar para a Lista de Moldes",
                      key="btn_pos_salvar_lista",
                      type="primary", use_container_width=True):
            _voltar_para_lista()
            st.rerun()
    with col_pos2:
        if st.button("✏️ Continuar editando este molde",
                      key="btn_pos_salvar_continuar",
                      use_container_width=True):
            st.session_state["molde_em_edicao"] = nome_molde
            _trocar_fase(FASE_CALIB)
            st.rerun()
