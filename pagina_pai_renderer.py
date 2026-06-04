"""
pagina_pai_renderer.py - Renderiza PAI v1.0 no Streamlit (tema claro padrao).

Justificativa por Autorizacao: linha com label + intensidade + bolinhas + "?"
com tooltip CSS no hover (sem expander, sem JS).
"""
from __future__ import annotations
import streamlit as st


DIMENSAO_LABELS = {
    "statement_fragmentation":   "Fragmentação de enunciado",
    "language_simplification":   "Simplificação de linguagem",
    "content_simplification":    "Simplificação de conteúdo",
    "metacognitive_hints":       "Dicas metacognitivas",
    "visual_support":            "Suporte visual",
    "alternatives_reduction":    "Redução de alternativas",
    "layout_intensity":          "Layout amplo",
    "command_highlighting":      "Destaque de comando",
}

INTENSIDADE_LABEL = {0: "Não autorizada", 1: "Leve", 2: "Moderada", 3: "Intensa"}

# Restricoes globais hardcoded do schema PAI v1.0 - explicacao PT-BR pra UI.
# Esses 4 codigos sao inviolaveis pelo Agente 2 (Adaptador LLM) em TODO PAI.
GLOBAL_RESTRICTION_LABELS = {
    "do_not_change_evaluated_construct":
        "Nao altera o que a questao mede. Se o original testa interpretacao "
        "de grafico, a adaptada tambem testa interpretacao de grafico.",
    "do_not_provide_answers_in_hints":
        "Dicas guiam o raciocinio, mas nunca entregam a resposta.",
    "do_not_invent_content_not_in_original":
        "Sem alucinacao: nao cria personagens, dados ou contextos que nao "
        "estavam na prova original.",
    "preserve_question_numbering":
        "Mantem a numeracao e ordem das questoes identicas ao original "
        "(correcao paralela e discricao em sala).",
}


def _bolinhas(intensidade: int) -> str:
    cor_ativa = "#e3a008"
    cor_inativa = "#e0e0e0"
    bolas = []
    for i in range(3):
        cor = cor_ativa if i < intensidade else cor_inativa
        bolas.append(
            f'<span style="display:inline-block; width:22px; height:9px; '
            f'background:{cor}; border-radius:999px; margin:0 2px;"></span>'
        )
    return "".join(bolas)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .pai-badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 0.72em;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-right: 6px;
            border: 1px solid;
        }
        .pai-badge-purple { background: #f3eaff; color: #6b35c4; border-color: #d4b8ff; }
        .pai-badge-gray   { background: #f5f5f5; color: #555;    border-color: #d6d6d6; }
        .pai-badge-green  { background: #e9f9ee; color: #1e8a3d; border-color: #a8e0bc; }

        .pai-titulo {
            font-family: Georgia, "Times New Roman", serif;
            font-style: italic;
            font-size: 1.6rem;
            color: #b8800a;
            margin: 10px 0 4px 0;
            font-weight: 600;
        }
        .pai-meta-line {
            font-size: 0.82em;
            color: #888;
            margin-bottom: 14px;
        }

        .pai-section-h {
            font-size: 0.78em;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #333;
            margin: 4px 0 10px 0;
        }

        .pai-dim-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #fafafa;
            border: 1px solid #e6e6e6;
            padding: 12px 14px;
            border-radius: 8px;
            margin-bottom: 8px;
        }
        .pai-dim-label { font-size: 0.95em; font-weight: 600; color: #222; }
        .pai-dim-intens { font-size: 0.78em; color: #888; margin-top: 2px; }

        .pai-resumo-pro {
            background: #fffaf0;
            border: 1px solid #f0d896;
            border-left: 4px solid #e3a008;
            border-radius: 8px;
            padding: 14px 18px;
            font-size: 0.93em;
            line-height: 1.6;
            color: #3a2820;
        }
        .pai-resumo-h {
            font-size: 0.72em;
            font-weight: 700;
            letter-spacing: 0.08em;
            color: #b8800a;
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        .pai-restricao-code {
            font-family: "Courier New", monospace;
            font-size: 0.82em;
            background: #f5f5f5;
            padding: 3px 8px;
            border-radius: 4px;
            color: #333;
            border: 1px solid #e0e0e0;
        }

        .pai-narr-subtitle {
            font-size: 0.72em;
            color: #999;
            margin-left: 6px;
            font-weight: 400;
            text-transform: none;
        }

        .pai-just-wrapper {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .pai-just-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            background: #fafafa;
            border: 1px solid #e6e6e6;
            padding: 12px 14px;
            border-radius: 8px;
        }
        .pai-just-label {
            font-size: 0.95em;
            font-weight: 600;
            color: #222;
            flex: 1;
        }
        .pai-just-right {
            display: flex;
            align-items: center;
            gap: 14px;
            white-space: nowrap;
        }
        .pai-just-intens {
            font-size: 0.78em;
            color: #888;
            font-weight: 500;
            min-width: 90px;
            text-align: right;
        }
        .pai-just-help {
            position: relative;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #fff;
            border: 1px solid #d0a04a;
            color: #b8800a;
            font-size: 0.7em;
            font-weight: 800;
            font-family: Georgia, serif;
            cursor: help;
            margin-left: 4px;
            user-select: none;
        }
        .pai-just-help:hover {
            background: #b8800a;
            color: #fff;
        }
        .pai-just-help .pai-just-tip {
            visibility: hidden;
            opacity: 0;
            position: absolute;
            bottom: 130%;
            right: -8px;
            transform: translateY(4px);
            width: 360px;
            max-width: 80vw;
            background: #fffaf0;
            color: #3a2820;
            border: 1px solid #f0d896;
            border-left: 4px solid #e3a008;
            border-radius: 8px;
            padding: 12px 14px;
            font-size: 0.82em;
            font-weight: 400;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.55;
            text-align: left;
            white-space: normal;
            box-shadow: 0 6px 20px rgba(0,0,0,0.15);
            z-index: 9999;
            transition: opacity 0.15s ease, transform 0.15s ease;
            pointer-events: none;
        }
        .pai-just-help:hover .pai-just-tip,
        .pai-just-help:focus .pai-just-tip {
            visibility: visible;
            opacity: 1;
            transform: translateY(0);
        }
        .pai-just-help .pai-just-tip::after {
            content: "";
            position: absolute;
            top: 100%;
            right: 12px;
            border-width: 6px;
            border-style: solid;
            border-color: #f0d896 transparent transparent transparent;
        }

        /* MODIFIER: tooltip aparece EMBAIXO do "?" (pra nao bater no menu/header) */
        .pai-just-help--down .pai-just-tip {
            top: 130%;
            bottom: auto;
            left: -8px;
            right: auto;
            transform: translateY(-4px);
        }
        .pai-just-help--down:hover .pai-just-tip,
        .pai-just-help--down:focus .pai-just-tip {
            transform: translateY(0);
        }
        /* setinha apontando pra CIMA (pro "?") */
        .pai-just-help--down .pai-just-tip::after {
            top: auto;
            bottom: 100%;
            left: 12px;
            right: auto;
            border-color: transparent transparent #f0d896 transparent;
        }
        /* z-index turbinado pra ficar acima do sidebar do Streamlit */
        .pai-just-help .pai-just-tip { z-index: 2147483647 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_badges_e_titulo(pai: dict) -> None:
    meta = pai.get("meta", {})
    approval = meta.get("approval", {})
    has_laudo = meta.get("has_clinical_report", False)
    status = approval.get("status", "pending")
    family = pai.get("family_label", "EXATAS")
    versao = f"v{meta.get('version', 1)}"

    status_map = {
        "active":       ("Ativo",     "pai-badge-green"),
        "approved":     ("Aprovado",  "pai-badge-green"),
        "pending":      ("Pendente",  "pai-badge-gray"),
        "draft":        ("Rascunho",  "pai-badge-gray"),
        "needs_review": ("Revisar",   "pai-badge-gray"),
    }
    status_txt, status_cls = status_map.get(status, ("—", "pai-badge-gray"))

    badges = (
        f'<div style="margin-bottom: 6px;">'
        f'<span class="pai-badge pai-badge-purple">{family}</span>'
        f'<span class="pai-badge pai-badge-gray">{versao}</span>'
        f'<span class="pai-badge {status_cls}">● {status_txt}</span>'
    )
    if has_laudo:
        badges += '<span class="pai-badge pai-badge-gray">Com laudo</span>'
    badges += '</div>'

    created_by = meta.get("created_by", "ProfileBuilderAgent")
    created_at = meta.get("created_at", "")
    data_fmt = created_at[:10] if created_at else "—"

    st.markdown(
        badges +
        f'<div class="pai-titulo">Plano de Adaptação Individual</div>'
        f'<div class="pai-meta-line">Gerado por <code>{created_by}</code> em {data_fmt}</div>',
        unsafe_allow_html=True,
    )


def _render_orcamento(pai: dict) -> None:
    budget = pai.get("adaptation_budget", {})
    with st.container(border=True):
        st.markdown('<div class="pai-section-h">Orçamento de Adaptação</div>', unsafe_allow_html=True)
        dims = list(DIMENSAO_LABELS.keys())
        cols = st.columns(2)
        for i, dim_key in enumerate(dims):
            col = cols[i % 2]
            intens = budget.get(dim_key, 0)
            label = DIMENSAO_LABELS.get(dim_key, dim_key)
            intens_txt = INTENSIDADE_LABEL.get(intens, "—")
            with col:
                st.markdown(
                    f'<div class="pai-dim-row">'
                    f'<div>'
                    f'<div class="pai-dim-label">{label}</div>'
                    f'<div class="pai-dim-intens">{intens_txt}</div>'
                    f'</div>'
                    f'<div>{_bolinhas(intens)}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        extra = budget.get("extra_time_allowed", False)
        if extra:
            st.markdown(
                '<div class="pai-dim-row" style="margin-top:10px; background:#e9f9ee; border-color:#a8e0bc;">'
                '<div style="color:#1e8a3d; font-weight:600;">✓ Tempo adicional autorizado</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="pai-dim-row" style="margin-top:10px; background:#fff0f0; border-color:#f4c4c4;">'
                '<div style="color:#a82828; font-weight:600;">✗ Tempo adicional NÃO autorizado</div>'
                '</div>',
                unsafe_allow_html=True,
            )


def _render_justificativa(pai: dict) -> None:
    rationale = pai.get("rationale", {})
    with st.container(border=True):
        st.markdown('<div class="pai-section-h">Justificativa</div>', unsafe_allow_html=True)

        resumo = rationale.get("summary_for_teacher_ptbr", "")
        if resumo:
            st.markdown(
                f'<div class="pai-resumo-pro">'
                f'<div class="pai-resumo-h">Resumo para a Professora</div>'
                f'{resumo}'
                f'</div>',
                unsafe_allow_html=True,
            )

        evidencias = rationale.get("evidence_per_authorization", {})
        if evidencias:
            st.markdown('<div class="pai-section-h" style="margin-top:18px;">Justificativa por Autorização</div>', unsafe_allow_html=True)
            budget = pai.get("adaptation_budget", {})

            linhas_html = ['<div class="pai-just-wrapper">']
            for dim_key, evid in evidencias.items():
                label = DIMENSAO_LABELS.get(dim_key, dim_key)
                intens = budget.get(dim_key, 0)
                intens_txt = INTENSIDADE_LABEL.get(intens, "—")
                texto = evid.get("ptbr", str(evid)) if isinstance(evid, dict) else str(evid)
                texto_safe = (
                    str(texto)
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("\n", "<br>")
                )
                linhas_html.append(
                    f'<div class="pai-just-row">'
                    f'<div class="pai-just-label">{label}</div>'
                    f'<div class="pai-just-right">'
                    f'<span class="pai-just-intens">{intens_txt}</span>'
                    f'{_bolinhas(intens)}'
                    f'<span class="pai-just-help" tabindex="0">?'
                    f'<span class="pai-just-tip">{texto_safe}</span>'
                    f'</span>'
                    f'</div>'
                    f'</div>'
                )
            linhas_html.append('</div>')
            st.markdown("".join(linhas_html), unsafe_allow_html=True)

        low_conf = rationale.get("low_confidence_areas", [])
        if low_conf:
            st.markdown('<div class="pai-section-h" style="margin-top:18px;">⊘ Áreas de Baixa Confiança</div>', unsafe_allow_html=True)
            for it in low_conf:
                st.markdown(f"- <span style='font-size:0.9em;'>{it}</span>", unsafe_allow_html=True)

        missing = rationale.get("missing_evidence", [])
        if missing:
            st.markdown('<div class="pai-section-h" style="margin-top:14px;">✦ Evidências que ainda Faltam</div>', unsafe_allow_html=True)
            for it in missing:
                st.markdown(f"- <span style='font-size:0.9em;'>{it}</span>", unsafe_allow_html=True)


def _render_restricoes(pai: dict) -> None:
    hr = pai.get("hard_restrictions", {})
    with st.container(border=True):
        st.markdown('<div class="pai-section-h">Restrições</div>', unsafe_allow_html=True)

        globais = hr.get("global", []) or hr.get("global_", [])
        if globais:
            # Cabecalho da secao
            st.markdown(
                '<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">'
                '<span style="font-size:0.78em; font-weight:700; color:#666;">'
                'GLOBAIS (aplicadas a todos os PAIs)</span>'
                f'<span style="font-size:0.72em; color:#999;">'
                f'· {len(globais)} regras do schema PAI v1.0</span>'
                '</div>',
                unsafe_allow_html=True,
            )

            # Lista os 4 textos em PT-BR diretamente (sem tooltip). Bate com
            # o padrao do Anthropic do socio (PAI U5): cada regra como bullet
            # visivel - melhor pra professora ler do que esconder em tooltip.
            for g in globais:
                explicacao = GLOBAL_RESTRICTION_LABELS.get(
                    g, "Restricao global do schema PAI v1.0."
                )
                st.markdown(
                    f'<div style="font-size:0.9em; line-height:1.55; color:#3a2820; '
                    f'margin: 2px 0 8px 14px; position:relative;">'
                    f'<span style="position:absolute; left:-12px; top:0; color:#e3a008;">•</span>'
                    f'{explicacao}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        espec = hr.get("student_specific_ptbr", [])
        if espec:
            st.markdown('<div style="font-size:0.78em; font-weight:700; color:#666; margin:14px 0 6px 0;">ESPECÍFICAS DESTE ESTUDANTE</div>', unsafe_allow_html=True)
            for e in espec:
                st.markdown(f"- <span style='font-size:0.9em;'>{e}</span>", unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:0.88em; color:#888; margin-top:8px;">- Não há restrições específicas marcadas pela professora (Parte 6.1).</div>', unsafe_allow_html=True)

        person = hr.get("personality_notes_ptbr")
        if person:
            st.markdown('<div style="font-size:0.78em; font-weight:700; color:#666; margin:14px 0 6px 0;">NOTAS DE PERSONALIDADE</div>', unsafe_allow_html=True)
            st.markdown(f'<div style="font-size:0.9em; line-height:1.6; color:#333;">{person}</div>', unsafe_allow_html=True)


def _render_narrativa(pai: dict) -> None:
    narr = pai.get("narrative", {})
    with st.container(border=True):
        st.markdown('<div class="pai-section-h">Narrativa do Estudante</div>', unsafe_allow_html=True)

        blocos = [
            ("Resumo do Estudante", narr.get("student_summary_ptbr"), "Parte 1.1"),
            ("O que Funciona",      narr.get("what_works_ptbr"),      "Parte 1.4"),
            ("O que Não Funcionou", narr.get("what_does_not_work_ptbr"), "Parte 1.5"),
            ("Síntese Operacional do Laudo", narr.get("clinical_summary_operational_ptbr"), "Parte 1.2.1"),
            ("Recomendações do AEE", narr.get("aee_recommendations_ptbr"), "Parte 7"),
        ]

        for titulo, valor, parte in blocos:
            if not valor:
                continue
            st.markdown(
                f'<div style="font-size:0.82em; font-weight:700; color:#b8800a; margin:14px 0 6px 0;">'
                f'{titulo.upper()}<span class="pai-narr-subtitle">· {parte}</span></div>',
                unsafe_allow_html=True,
            )
            if isinstance(valor, list):
                for item in valor:
                    st.markdown(f"- <span style='font-size:0.9em;'>{item}</span>", unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="font-size:0.9em; line-height:1.6; color:#333;">{valor}</div>', unsafe_allow_html=True)


def render_pai_view(pai: dict) -> None:
    if not pai:
        st.info("Nenhum PAI disponível para este aluno ainda.")
        return
    _inject_css()
    _render_badges_e_titulo(pai)
    _render_orcamento(pai)
    _render_justificativa(pai)
    _render_restricoes(pai)
    _render_narrativa(pai)


def render_pai_view_from_fixture(student_code: str = "U1") -> None:
    import json
    from pathlib import Path
    fixture_path = Path(__file__).resolve().parent / "Migração BD" / "innova-v2-python-handoff-v2" / "docs" / f"PAI_aluno_{student_code}_2026.json"
    if not fixture_path.exists():
        st.warning(f"PAI fixture nao encontrado: {fixture_path.name}")
        return
    with open(fixture_path, "r", encoding="utf-8") as f:
        pai = json.load(f)
    render_pai_view(pai)
