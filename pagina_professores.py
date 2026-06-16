"""
pagina_professores.py - Modulo de Professores (espelho de pagina_alunos).

Estrutura espelhada:
  - Lista geral (toggle SQLite/Supabase BR, filtros, +Novo Professor)
  - Prontuario com 4 tabs:
      * Informacoes
      * Questionario Base (moldes de prova + OCR - FASE C)
      * Perfil Pedagogico
      * Debug

Storage:
  - SQLite local: backend_professores.py (CRUD completo, tabela local)
  - Supabase BR:  innova_bridge.repositories.teachers_repo (le users WHERE role='teacher')
"""
from __future__ import annotations

import streamlit as st
import pandas as pd


# ============================================================================
# Backends - tolerantes a ausencia
# ============================================================================

try:
    import backend_professores as bp
    _BACKEND_OK = True
    _BACKEND_ERR = None
except Exception as _e:
    bp = None
    _BACKEND_OK = False
    _BACKEND_ERR = str(_e)

try:
    from innova_bridge.repositories import teachers_repo
    _SUPABASE_OK = True
    _SUPABASE_ERR = None
except Exception as _e:
    teachers_repo = None
    _SUPABASE_OK = False
    _SUPABASE_ERR = str(_e)

# Backends do sistema antigo (OCR + Moldes) - portados de pagina_alunos.py
import os
import json
import time

try:
    import backend_alunos as bk
except ImportError:
    bk = None

try:
    import backend_molde as bmolde
except ImportError:
    bmolde = None

try:
    import backend_ocr as ocr
except Exception:
    ocr = None

try:
    import rag_sistema as rag
except Exception:
    rag = None

# P1: histórico de OCR no Postgres (dual-write + leitura BD-first)
try:
    import backend_ocr_historico as _ocr_hist
    _OCR_HIST_OK = True
except Exception:
    _ocr_hist = None
    _OCR_HIST_OK = False



# ============================================================================
# Sessao
# ============================================================================

def _render_questionario_base_prof(professor_id):
    """Render da tab Questionario Base do Professor.
    Sistema OCR/Molde portado integralmente de pagina_alunos.py (tab_provas).
    Logica preservada; adaptacoes: aluno_id -> professor_id; salvar -> associar_molde."""
    ch, cb = st.columns([3, 1])
    ch.subheader("Questionários Preenchidos")
    
    if 'show_ocr_uploader' not in st.session_state:
        st.session_state.show_ocr_uploader = False

    if cb.button("Novo Questionário", type="primary", use_container_width=True):
        st.session_state.show_ocr_uploader = not st.session_state.show_ocr_uploader
        if not st.session_state.show_ocr_uploader and 'resultado_ocr' in st.session_state:
            del st.session_state['resultado_ocr']
        st.rerun()

    # -----------------------------------------------------------------
    # BLOCO 1: UPLOAD E MOTOR DE OCR (Aparece ao clicar em Novo Questionário)
    # -----------------------------------------------------------------
    if st.session_state.show_ocr_uploader:
        with st.container(border=True):
            st.markdown("#### 📥 Importar Relatório (PDF)")
            st.caption("A IA Vision extrairá os dados visuais baseada na similaridade com o **molde de correção** escolhido.")

            # ─────────────────────────────────────────────────────────
            # SELETOR DE MOLDE — vem ANTES do uploader (gating obrigatório)
            # ─────────────────────────────────────────────────────────
            moldes_disponiveis = []
            if bmolde is not None:
                try:
                    moldes_disponiveis = bmolde.listar_moldes()
                except Exception as e:
                    st.error(f"❌ Falha ao listar moldes: {e}")

            st.markdown("##### 🎓 Molde de correção")
            col_mold, col_btn = st.columns([4, 1.2])

            molde_escolhido = None
            molde_dados     = None

            with col_mold:
                if not moldes_disponiveis:
                    st.error(
                        "🚫 **Nenhum molde cadastrado.** O motor de OCR precisa de um molde "
                        "(lista de frases + coordenadas) para saber o que procurar. "
                        "Clique em **➕ Criar molde** ao lado para treinar o primeiro."
                    )
                else:
                    # Default = último molde usado (persistido na sessão)
                    ultimo = st.session_state.get("ultimo_molde_usado")
                    idx_default = 0
                    if ultimo and ultimo in moldes_disponiveis:
                        idx_default = moldes_disponiveis.index(ultimo)
                    molde_escolhido = st.selectbox(
                        "Escolha o molde da prova",
                        options=moldes_disponiveis,
                        index=idx_default,
                        key="molde_correcao_select",
                        label_visibility="collapsed",
                    )
                    st.session_state["ultimo_molde_usado"] = molde_escolhido

                    # Metadata do molde escolhido
                    try:
                        molde_dados = bmolde.carregar_molde(molde_escolhido)
                    except Exception:
                        molde_dados = None

                    if molde_dados:
                        qtd_frases = molde_dados.get("qtd_frases_gabarito", 0)
                        qtd_quad   = molde_dados.get("qtd_quadrados", 0)
                        completo   = molde_dados.get("completo", False)
                        tem_pdf    = bmolde.existe_pdf_referencia(molde_escolhido)
                        status_emo = "✅" if completo else "⚠️ parcial"
                        pdf_emo    = "📄 PDF referência OK" if tem_pdf else "⚠️ sem PDF"
                        st.success(
                            f"{status_emo} **{molde_escolhido}** · "
                            f"{qtd_frases} frases · {qtd_quad} quadrados · {pdf_emo}"
                        )
                    else:
                        st.error(f"❌ Não consegui ler o molde '{molde_escolhido}'. Treine novamente.")
                        molde_escolhido = None

            with col_btn:
                if st.button("➕ Criar molde", key="btn_criar_molde_atalho",
                              use_container_width=True,
                              help="Abre a Página de Treinamento de Molde para criar um novo."):
                    st.session_state["view_mode"] = "molde"
                    st.rerun()

            st.divider()

            # ─────────────────────────────────────────────────────────
            # UPLOADER + BOTÃO "INICIAR ANÁLISE" (bloqueado sem molde)
            # ─────────────────────────────────────────────────────────
            doc_pdf = st.file_uploader(
                "Selecione o arquivo diagnóstico (escaneado)",
                type=['pdf'], key="ppo_uploader",
                label_visibility="collapsed",
            )

            # Bloqueio: precisa de (a) molde válido escolhido, (b) PDF subido, (c) backend OCR OK
            pode_iniciar = (molde_escolhido is not None) and (doc_pdf is not None) and (ocr is not None)
            if molde_escolhido is None:
                tooltip_btn = "Crie e escolha um molde antes de iniciar a análise."
            elif doc_pdf is None:
                tooltip_btn = "Suba o PDF do aluno antes de iniciar a análise."
            elif ocr is None:
                tooltip_btn = "Backend OCR indisponível — cheque imports."
                # Mostra o erro REAL do import para diagnóstico
                if erro_real_ocr:
                    st.error(f"❌ Falha ao importar backend_ocr.py:\n\n```\n{erro_real_ocr}\n```")
            else:
                tooltip_btn = f"Rodar análise usando o molde {molde_escolhido}."

            if st.button(
                "🚀 Iniciar Análise Pedagógica",
                use_container_width=True,
                type="primary",
                disabled=(not pode_iniciar),
                help=tooltip_btn,
            ):
                with st.status(f"Processando OCR com molde '{molde_escolhido}'...", expanded=True) as status:
                    st.write("Preparando arquivo físico...")
                    caminho_temp = ocr.extrair_texto_pdf(doc_pdf)

                    if str(caminho_temp).startswith("ERRO"):
                        status.update(label="Falha na leitura física", state="error")
                        st.error(caminho_temp)
                    else:
                        st.write(f"Iniciando varredura com molde **{molde_escolhido}**...")
                        analise = ocr.analisar_com_treinamento(caminho_temp, molde_nome=molde_escolhido)

                        if analise.get("sucesso"):
                            # Guarda também o molde usado para gravar junto no JSON do aluno
                            analise["molde_usado"] = molde_escolhido
                            st.session_state['resultado_ocr'] = analise
                            status.update(label="Análise Concluída!", state="complete", expanded=False)
                        else:
                            status.update(label="Falha na análise", state="error")
                            st.error(analise.get("erro"))

        # PREVIEW DA EXTRAÇÃO E BOTÃO DE SALVAR
        if 'resultado_ocr' in st.session_state and st.session_state['resultado_ocr'].get("sucesso"):
            dados = st.session_state['resultado_ocr'].get("dados", {})
            
            st.markdown("<br>", unsafe_allow_html=True)
            with st.container(border=True):
                col_tit, col_salvar = st.columns([3, 1])
                with col_tit:
                    st.markdown("#### 📋 Extração Fidedigna (Pré-visualização)")
                    st.caption("Revise os dados antes de salvar no prontuário do aluno.")
                with col_salvar:
                    if st.button("💾 Salvar no Prontuário", type="primary", use_container_width=True):
                        caminho_cache = f"ocr_cache_{professor_id}.json"

                        # §4.1 — Persiste metadata do molde + telemetria junto com os dados
                        molde_usado = st.session_state['resultado_ocr'].get("molde_usado")
                        telemetria  = st.session_state['resultado_ocr'].get("telemetria") or {}
                        payload_completo = {
                            "_meta": {
                                "molde_usado": molde_usado,
                                "gravado_em":  int(time.time()),
                                "telemetria":  telemetria,
                            },
                            "dados": dados,
                        }
                        # Mantém compatibilidade com o leitor antigo: na raiz fica o dict de seções
                        # (o leitor antigo acessa por categoria direto). Para isso, gravo no formato
                        # legado E embuto _meta como chave especial — o leitor antigo ignora _meta.
                        payload_legado = dict(dados)
                        payload_legado["_meta"] = payload_completo["_meta"]
                        with open(caminho_cache, "w", encoding="utf-8") as f:
                            json.dump(payload_legado, f, ensure_ascii=False, indent=4)

                        # P1 — DUAL-WRITE: grava também no Postgres (histórico imutável).
                        # Falha silenciosa: se o BD não estiver disponível, o disco continua.
                        try:
                            if _OCR_HIST_OK:
                                _ocr_hist.inserir_resultado(
                                    professor_id=str(professor_id),
                                    dados=payload_legado,
                                    molde=molde_usado,
                                )
                        except Exception:
                            pass  # nunca quebra o fluxo principal

                        if bk and hasattr(bk, 'salvar_questionario_aluno'):
                            # CONTEXTO PROFESSOR: em vez de salvar como questionario de aluno,
                                # associamos o molde escolhido a este professor.
                                if bp is not None and molde_escolhido:
                                    try:
                                        prof_id_int = int(professor_id) if str(professor_id).isdigit() else None
                                        if prof_id_int is not None:
                                            bp.associar_molde(prof_id_int, molde_escolhido)
                                    except Exception as _e_assoc:
                                        st.warning(f"Falha ao associar molde: {_e_assoc}")

                        st.success(f"Formulário registrado com sucesso! Molde usado: **{molde_usado}**")
                        st.balloons()
                        time.sleep(2)

                        st.session_state.show_ocr_uploader = False
                        del st.session_state['resultado_ocr']
                        st.rerun()
                
                st.divider()

                for secao, itens in dados.items():
                    if itens:
                        st.markdown(f"**{secao}**")
                        for item in itens:
                            marcado = item.get("marcado", False)
                            pergunta = item.get("pergunta", "")
                            
                            c_check, c_nivel = st.columns([9, 1])
                            with c_check:
                                icone = "☑️" if marcado else "⬜"
                                st.markdown(f"{icone} {pergunta}")
                            with c_nivel:
                                st.caption(f"Nível {4 if marcado else 0}")
                        st.divider()

            with st.expander("💸 Telemetria Financeira (OCR)"):
                st.json(st.session_state['resultado_ocr'].get("telemetria", {}))

    # -----------------------------------------------------------------
    # BLOCO 2: HISTÓRICO SALVO (VISUALIZAÇÃO FIDEDIGNA DEFINITIVA)
    # -----------------------------------------------------------------
    else:
        caminho_cache = f"ocr_cache_{professor_id}.json"

        # P1 — LEITURA BD-FIRST: tenta o Postgres antes do disco.
        # Se não houver registro no BD, cai no arquivo local (fallback).
        dados_salvos = None
        _fonte = "nenhuma"

        if _OCR_HIST_OK:
            try:
                registro_bd = _ocr_hist.ler_mais_recente(str(professor_id))
                if registro_bd is not None:
                    dados_salvos = registro_bd["dados_json"]
                    _fonte = "bd"
            except Exception:
                pass

        if dados_salvos is None and os.path.exists(caminho_cache):
            try:
                with open(caminho_cache, "r", encoding="utf-8") as f:
                    dados_salvos = json.load(f)
                _fonte = "disco"
            except Exception:
                pass

        if dados_salvos is not None:
            with st.container(border=True): # Regra de Ouro 1[cite: 1]
                col_txt, col_tgl = st.columns([4, 1])
                with col_txt:
                    st.markdown("#### 📋 Extração Fidedigna (Questionário Base)")
                    st.caption("Dados extraídos e consolidados no prontuário do aluno.")
                
                # O Toggle agora envolve a Nova Interface
                mostrar_ocr = col_tgl.toggle("Ver Dados Extraídos", value=True, key="tgl_quest_salvo")
                
                if mostrar_ocr:
                    # §4.1 — Mostra molde + telemetria gravados (se houver _meta)
                    meta = dados_salvos.get("_meta") or {}
                    if meta.get("molde_usado"):
                        st.caption(
                            f"🎓 Molde usado: **{meta['molde_usado']}** · "
                            f"gravado em {time.strftime('%d/%m/%Y %H:%M', time.localtime(meta.get('gravado_em', 0)))}"
                        )
                    st.divider()
                    for secao, itens in dados_salvos.items():
                        # Pula a chave de metadados — não é categoria
                        if secao.startswith("_"):
                            continue
                        if not isinstance(itens, list):
                            continue
                        if itens:
                            st.markdown(f"**{secao}**")
                            for item in itens:
                                marcado = item.get("marcado", False)
                                pergunta = item.get("pergunta", "")

                                c_check, c_nivel = st.columns([9, 1])
                                with c_check:
                                    icone = "☑️" if marcado else "⬜"
                                    st.markdown(f"{icone} {pergunta}")
                                with c_nivel:
                                    st.caption(f"Nível {4 if marcado else 0}")
                            st.divider()
        else:
            with st.container(border=True):
                st.info("📌 Nenhum questionário registrado para este aluno. Clique no botão vermelho '**Novo Questionário**' para iniciar a extração óptica via IA.")



def _init_state() -> None:
    st.session_state.setdefault("professor_em_visualizacao", None)
    st.session_state.setdefault("origem_dados_prof", "SQLite (local)")
    st.session_state.setdefault("show_form_novo_prof", False)


# ============================================================================
# Origem dos dados
# ============================================================================

def _origem_dados() -> str:
    return st.session_state.get("origem_dados_prof", "SQLite (local)")


def _render_toggle_origem() -> None:
    """Radio pra alternar entre SQLite local e Supabase BR."""
    opcoes = ["SQLite (local)"]
    if _SUPABASE_OK:
        opcoes.append("Supabase BR (Innova V2)")

    if len(opcoes) == 1:
        st.caption("📦 Origem: **SQLite local** (Supabase indisponivel).")
        return

    col_t, col_info = st.columns([2, 5])
    with col_t:
        novo = st.radio(
            "Origem dos dados",
            opcoes,
            index=opcoes.index(_origem_dados()) if _origem_dados() in opcoes else 0,
            horizontal=True,
            label_visibility="collapsed",
            key="radio_origem_prof",
        )
        if novo != st.session_state.get("origem_dados_prof"):
            st.session_state["origem_dados_prof"] = novo
            st.rerun()
    with col_info:
        if _origem_dados().startswith("Supabase"):
            st.caption("☁️ Lendo `users WHERE role='teacher'` do Supabase BR (sa-east-1).")
        else:
            st.caption("💾 SQLite local (`banco_professores.db`).")


def _buscar_lista_prof() -> pd.DataFrame:
    if _origem_dados().startswith("Supabase") and _SUPABASE_OK:
        return teachers_repo.listar_professores_supabase()
    if _BACKEND_OK:
        return bp.buscar_lista_professores()
    return pd.DataFrame()


def _obter_detalhes_prof(prof_id) -> dict | None:
    if _origem_dados().startswith("Supabase") and _SUPABASE_OK:
        return teachers_repo.obter_detalhes_professor_supabase(str(prof_id))
    if _BACKEND_OK:
        return bp.obter_detalhes_professor(prof_id)
    return None


# ============================================================================
# Form de cadastro
# ============================================================================

@st.dialog("Novo Professor")
def _modal_novo_professor():
    if not _BACKEND_OK:
        st.error("backend_professores nao carregado.")
        return
    apelido = st.text_input("Apelido / como chama na escola *", placeholder="Ex.: Prof. Marcelo")
    nome_completo = st.text_input("Nome completo", placeholder="Marcelo da Silva Santos")
    col1, col2 = st.columns(2)
    with col1:
        email = st.text_input("Email", placeholder="marcelo@escolaparque.local")
        materia = st.text_input("Materia principal", placeholder="Matematica")
    with col2:
        turmas = st.text_input("Turmas responsavel", placeholder="U1, U2, 1601")

    if st.button("Cadastrar", type="primary", use_container_width=True):
        if not apelido.strip():
            st.error("Apelido eh obrigatorio.")
            return
        try:
            novo_id = bp.criar_professor(
                apelido=apelido.strip(),
                nome_completo=nome_completo.strip(),
                email=email.strip(),
                materia=materia.strip(),
                turmas=turmas.strip(),
            )
            st.success(f"✅ Professor cadastrado! ID anonimo: `{novo_id}`")
            st.balloons()
            st.session_state["show_form_novo_prof"] = False
            st.rerun()
        except Exception as e:
            st.error(f"Falha ao cadastrar: {e}")


@st.dialog("Novo Professor (Supabase BR)")
def _modal_novo_professor_supabase():
    """Cadastro via Auth Admin API + envio automatico de email de reset."""
    if not _SUPABASE_OK:
        st.error("teachers_repo nao disponivel.")
        return

    st.caption(
        "O professor sera criado no Auth do Supabase com **senha temporaria** + "
        "receberá email automaticamente pra definir a propria senha."
    )

    # Lista escolas pro dropdown
    try:
        escolas = teachers_repo.listar_escolas_supabase()
    except Exception as e:
        st.error(f"Falha ao listar escolas: {e}")
        return

    if not escolas:
        st.warning("Nenhuma escola cadastrada em public.schools. Cadastre uma antes.")
        return

    col1, col2 = st.columns(2)
    with col1:
        email = st.text_input("Email *", placeholder="prof.marcelo@escola.com")
        full_name = st.text_input("Nome completo *", placeholder="Marcelo da Silva Santos")
    with col2:
        opcoes_escola = {e["name"]: e["uuid"] for e in escolas}
        escola_nome = st.selectbox("Escola *", list(opcoes_escola.keys()))
        school_id = opcoes_escola.get(escola_nome)

    st.info(
        "💡 **Modelo de primeiro acesso:** o backend cria o professor com senha demo. "
        "O professor depois usa o **fluxo de 'Esqueci minha senha' no frontend (React)** "
        "pra definir sua propria senha. O backend NAO dispara emails."
    )

    if st.button("Cadastrar", type="primary", use_container_width=True):
        if not email.strip() or "@" not in email:
            st.error("Email invalido.")
            return
        if not full_name.strip():
            st.error("Nome completo eh obrigatorio.")
            return
        if not school_id:
            st.error("Escola eh obrigatoria.")
            return

        senha_demo = teachers_repo.gerar_senha_temporaria()

        with st.spinner("Criando professor no Supabase Auth..."):
            ok, msg = teachers_repo.criar_professor_supabase(
                email=email.strip(),
                password=senha_demo,
                full_name=full_name.strip(),
                school_id=school_id,
            )

        if not ok:
            st.error(f"❌ Falha no cadastro: {msg}")
            return

        st.success(f"✅ {msg}")

        # Destaca a senha demo - admin precisa passar pro professor por canal seguro
        with st.container(border=True):
            st.markdown("##### 🔐 Credenciais de primeiro acesso")
            st.markdown(
                f"**Email:** `{email.strip()}`\n\n"
                f"**Senha demo:** `{senha_demo}`"
            )
            st.warning(
                "⚠️ Anote AGORA - apos fechar este modal a senha NAO sera mais visivel.\n\n"
                "Passe estas credenciais ao professor por canal seguro (WhatsApp, "
                "presencialmente). Ele usara pra fazer o primeiro login e depois "
                "trocar a senha pelo proprio fluxo do frontend."
            )

        st.balloons()
# ============================================================================
# Lista geral
# ============================================================================

def _render_lista_geral_professores() -> None:
    # Cabecalho
    col_titulo, col_origem = st.columns([3, 2])
    with col_titulo:
        st.title("Professores")
        st.caption(
            "Lista do corpo docente. Use o filtro de materia e o campo de busca "
            "para encontrar rapidamente. Cada professor mantem seu acervo de moldes."
        )
    with col_origem:
        st.markdown("<br>", unsafe_allow_html=True)
        _render_toggle_origem()

    origem = "supabase" if _origem_dados().startswith("Supabase") else "sqlite"

    if origem == "sqlite" and not _BACKEND_OK:
        st.error(f"Backend de professores (SQLite) inoperante: {_BACKEND_ERR}")
        return
    if origem == "supabase" and not _SUPABASE_OK:
        st.error(f"Adapter Supabase indisponivel: {_SUPABASE_ERR}")
        return

    try:
        df = _buscar_lista_prof()
    except Exception as e:
        st.error(f"Falha ao buscar professores ({origem}): **{type(e).__name__}** - {e}")
        import traceback as _tb
        with st.expander("Ver traceback"):
            st.code(_tb.format_exc())
        return

    # Barra de ferramentas (busca + materia + novo)
    col_busca, col_materia, col_novo = st.columns([3, 2, 1.2])

    with col_busca:
        busca = st.text_input(
            "Buscar por nome",
            placeholder="Digite ao menos 2 letras",
            key="profs_filtro_busca",
        )

    with col_materia:
        if not df.empty and "materia" in df.columns:
            mat_unicas = sorted([m for m in df["materia"].dropna().unique() if m and m != "-"])
        else:
            mat_unicas = []
        opcoes_mat = ["Todas as materias"] + mat_unicas
        mat_sel = st.selectbox(
            "Materia",
            opcoes_mat,
            key="profs_filtro_materia",
        )

    with col_novo:
        st.markdown("<br>", unsafe_allow_html=True)
        # Cadastro disponivel em ambas as origens (cada uma usa modal apropriado)
        cad_disabled = False
        if origem == "sqlite" and not _BACKEND_OK:
            cad_disabled = True
        if origem == "supabase" and not _SUPABASE_OK:
            cad_disabled = True

        if st.button(
            "+ Novo Professor",
            key="btn_novo_prof_topo",
            type="primary",
            use_container_width=True,
            disabled=cad_disabled,
            help="Cadastra no SQLite local ou no Supabase BR (com email de reset automatico)."
                 if not cad_disabled else "Backend nao disponivel.",
        ):
            if origem == "supabase":
                _modal_novo_professor_supabase()
            else:
                _modal_novo_professor()

    # Aplica filtros
    total_antes = len(df)
    if busca and len(busca) >= 2:
        df = df[df["apelido"].str.contains(busca, case=False, na=False)]
    if mat_sel and mat_sel != "Todas as materias":
        df = df[df["materia"] == mat_sel]
    total_depois = len(df)

    if df.empty:
        if total_antes == 0:
            st.info("Nenhum professor cadastrado. Clique em **+ Novo Professor** para comecar.")
        else:
            st.warning(f"Nenhum professor encontrado com os filtros ({total_antes} no total).")
        return

    # Caption de status
    if total_depois < total_antes:
        st.caption(f":material/group: **{total_depois} de {total_antes}** professor(es) - filtros aplicados - origem: `{origem}`")
    else:
        st.caption(f":material/group: **{total_antes} professor(es) cadastrado(s)** - origem: `{origem}`")

    # CSS da tabela (espelhado do template Alunos, prefixo .profs-)
    st.markdown(
        """
        <style>
        .profs-cell {
            padding: 8px 4px;
            font-size: 0.92em;
            border-bottom: 1px solid #e6e6e6;
            min-height: 38px;
            display: flex;
            align-items: center;
        }
        .profs-cell-alt { background: #fafafa; }
        .profs-badge-ativo {
            display: inline-block;
            background: #e8f5e9;
            color: #1e7e34;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.82em;
            font-weight: 500;
        }
        .profs-badge-inativo {
            display: inline-block;
            background: #f5f5f5;
            color: #999;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.82em;
        }
        .profs-badge-mat {
            display: inline-block;
            background: #eef3fb;
            color: #1f4e79;
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 0.85em;
            font-weight: 500;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .profs-header {
            font-weight: 700;
            font-size: 0.78em;
            color: #555;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 2px solid #999;
            padding-bottom: 8px;
            padding-top: 4px;
        }
        .profs-id-mono {
            font-family: "Courier New", monospace;
            font-size: 0.78em;
            color: #888;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Larguras: ID, NOME, EMAIL, MATERIA, TURMAS, STATUS, CADASTRO, ACAO
    larguras = [0.7, 1.6, 1.6, 1.1, 0.8, 0.7, 0.9, 0.5]
    labels   = ["ID", "Nome", "Email", "Materia", "Turmas", "Status", "Cadastro", ""]

    with st.container(border=True):
        # Cabecalho
        hcols = st.columns(larguras)
        for col, text in zip(hcols, labels):
            if text:
                col.markdown(f"<div class='profs-header'>{text}</div>",
                             unsafe_allow_html=True)
            else:
                col.markdown("<div class='profs-header' style='border-bottom:none;'>&nbsp;</div>",
                             unsafe_allow_html=True)

        # Linhas
        for i, (_, row) in enumerate(df.iterrows()):
            cells = st.columns(larguras)
            cell_class = "profs-cell" + (" profs-cell-alt" if i % 2 else "")

            ativo = bool(row.get("ativo", True))
            status_html = (
                "<span class='profs-badge-ativo'>ATIVO</span>" if ativo
                else "<span class='profs-badge-inativo'>INATIVO</span>"
            )

            id_str = str(row.get("id", "-"))
            # Pra UUID, mostra apenas os 8 primeiros chars + ...
            if len(id_str) > 12:
                id_display = f"<span class='profs-id-mono'>{id_str[:8]}...</span>"
            else:
                id_display = f"#{id_str}"

            apelido = row.get("apelido", "-") or "-"
            email = row.get("email", "-") or "-"
            materia = str(row.get("materia", "-") or "-")
            turmas = str(row.get("turmas", row.get("turmas_responsavel", "-")) or "-")
            cadastro = str(row.get("cadastro", row.get("data_cadastro", "-")) or "-")

            mat_html = f"<span class='profs-badge-mat'>{materia}</span>" if materia != "-" else "-"

            cells[0].markdown(f"<div class='{cell_class}'>{id_display}</div>", unsafe_allow_html=True)
            cells[1].markdown(f"<div class='{cell_class}'><b>{apelido}</b></div>", unsafe_allow_html=True)
            cells[2].markdown(f"<div class='{cell_class}' style='font-size:0.82em; color:#666;'>{email}</div>", unsafe_allow_html=True)
            cells[3].markdown(f"<div class='{cell_class}'>{mat_html}</div>", unsafe_allow_html=True)
            cells[4].markdown(f"<div class='{cell_class}'>{turmas}</div>", unsafe_allow_html=True)
            cells[5].markdown(f"<div class='{cell_class}'>{status_html}</div>", unsafe_allow_html=True)
            cells[6].markdown(f"<div class='{cell_class}'>{cadastro}</div>", unsafe_allow_html=True)
            with cells[7]:
                with st.container(key=f"bd-entrar-prof-{id_str}"):
                    if st.button(
                        "🔍",
                        key=f"open_prof_{id_str}",
                        help=f"Abrir prontuario de {apelido}",
                    ):
                        st.session_state["professor_em_visualizacao"] = id_str
                        st.rerun()



# ============================================================================
# Prontuario do Professor (4 tabs)
# ============================================================================

def _render_prontuario_professor(professor_id) -> None:
    detalhes = _obter_detalhes_prof(professor_id)

    # Detecta se origem eh Supabase (uuid) ou SQLite (int)
    is_supabase = _origem_dados().startswith("Supabase")
    uuid_str = str(professor_id) if is_supabase else None

    col_back, col_titulo = st.columns([1, 5])
    with col_back:
        if st.button("← Voltar", use_container_width=True, key="btn_back_prof"):
            st.session_state["professor_em_visualizacao"] = None
            st.session_state.pop("editando_prof", None)
            st.rerun()
    with col_titulo:
        if detalhes:
            nome = detalhes.get("apelido") or detalhes.get("full_name") or str(professor_id)
            st.markdown(
                f"### Professor: {nome} - "
                f"<small style='color:#888;'>{detalhes.get('email','-')}</small>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"### Professor: {professor_id} (nao encontrado)")

    st.divider()

    tab_info, tab_quest, tab_ppo, tab_debug = st.tabs(
        ["Informações", "Questionário Base", "Perfil Pedagógico", "Relatório IA (Debug)"]
    )

    with tab_info:
        col_titulo_info, col_edit = st.columns([4, 1])
        with col_titulo_info:
            st.markdown("##### Informacoes do Professor")
        with col_edit:
            modo_edicao = st.session_state.get("editando_prof") == str(professor_id)
            if not modo_edicao:
                if st.button("✏️ Editar", use_container_width=True, key=f"btn_edit_{professor_id}"):
                    st.session_state["editando_prof"] = str(professor_id)
                    st.rerun()

        if not detalhes:
            st.error("Detalhes nao encontrados.")
        else:
            modo_edicao = st.session_state.get("editando_prof") == str(professor_id)

            with st.container(border=True):
                nome_atual = detalhes.get("apelido", "") or detalhes.get("full_name", "")
                email_atual = detalhes.get("email", "") or "-"
                ativo_atual = bool(detalhes.get("ativo", detalhes.get("active", True)))
                materia_atual = str(detalhes.get("materia", "") or detalhes.get("materias_list", "") or "-")
                turmas_atual = str(detalhes.get("turmas_responsavel", "") or detalhes.get("turmas_list", "") or "-")

                if modo_edicao and is_supabase:
                    # MODO EDICAO (Supabase)
                    st.info(
                        "🛡️ **Edicao no Supabase BR.** Apenas `full_name` e `active` podem ser "
                        "alterados via Streamlit. Email e turmas/materias sao gerenciados pelo "
                        "Innova V2 (auth.users / class_teacher_subjects)."
                    )
                    c1, c2 = st.columns(2)
                    novo_nome = c1.text_input("Nome (full_name)", value=nome_atual, key=f"ed_nome_{professor_id}")
                    novo_ativo = c2.toggle("Ativo", value=ativo_atual, key=f"ed_ativo_{professor_id}")
                    c1.text_input("Email", value=email_atual, disabled=True,
                                  help="Email vem de auth.users - edite no painel Auth do Supabase.")
                    c2.text_input("Materia", value=materia_atual, disabled=True,
                                  help="Materias gerenciadas via class_teacher_subjects (Innova V2).")
                    c1.text_input("Turmas", value=turmas_atual, disabled=True)

                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("💾 Salvar alteracoes", type="primary", use_container_width=True,
                                     key=f"btn_save_{professor_id}"):
                            try:
                                from innova_bridge.repositories import teachers_repo
                                ok = teachers_repo.atualizar_professor_supabase(
                                    uuid_str=uuid_str,
                                    full_name=novo_nome.strip() if novo_nome != nome_atual else None,
                                    active=novo_ativo if novo_ativo != ativo_atual else None,
                                )
                                if ok:
                                    st.success("✅ Atualizado no Supabase BR.")
                                    st.session_state.pop("editando_prof", None)
                                    st.rerun()
                                else:
                                    st.warning("Nenhuma mudanca detectada (ou falha silenciosa).")
                            except Exception as e:
                                st.error(f"Falha: {e}")
                    with bc2:
                        if st.button("❌ Cancelar", use_container_width=True,
                                     key=f"btn_cancel_{professor_id}"):
                            st.session_state.pop("editando_prof", None)
                            st.rerun()

                elif modo_edicao and not is_supabase:
                    # MODO EDICAO (SQLite local)
                    c1, c2 = st.columns(2)
                    novo_nome = c1.text_input("Apelido", value=nome_atual, key=f"ed_nome_l_{professor_id}")
                    novo_email = c2.text_input("Email", value=email_atual if email_atual != "-" else "", key=f"ed_email_l_{professor_id}")
                    novo_mat = c1.text_input("Materia", value=materia_atual if materia_atual != "-" else "", key=f"ed_mat_l_{professor_id}")
                    novos_turmas = c2.text_input("Turmas", value=turmas_atual if turmas_atual != "-" else "", key=f"ed_turm_l_{professor_id}")
                    novo_ativo = st.toggle("Ativo", value=ativo_atual, key=f"ed_ativo_l_{professor_id}")

                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("💾 Salvar", type="primary", use_container_width=True,
                                     key=f"btn_save_l_{professor_id}"):
                            try:
                                bp.atualizar_professor(
                                    int(professor_id),
                                    apelido=novo_nome.strip(),
                                    email=novo_email.strip(),
                                    materia=novo_mat.strip(),
                                    turmas_responsavel=novos_turmas.strip(),
                                    ativo=1 if novo_ativo else 0,
                                )
                                st.success("✅ Atualizado localmente.")
                                st.session_state.pop("editando_prof", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Falha: {e}")
                    with bc2:
                        if st.button("❌ Cancelar", use_container_width=True,
                                     key=f"btn_cancel_l_{professor_id}"):
                            st.session_state.pop("editando_prof", None)
                            st.rerun()
                else:
                    # MODO VISUALIZACAO
                    c1, c2 = st.columns(2)
                    c1.text_input("Nome", value=nome_atual, disabled=True, key=f"vw_nome_{professor_id}")
                    c2.text_input("Email", value=email_atual, disabled=True, key=f"vw_email_{professor_id}")
                    c1.text_input("Materia", value=materia_atual, disabled=True, key=f"vw_mat_{professor_id}")
                    c2.text_input("Turmas", value=turmas_atual, disabled=True, key=f"vw_turm_{professor_id}")
                    c1.text_input("Status", value="Ativo" if ativo_atual else "Inativo", disabled=True, key=f"vw_at_{professor_id}")
                    if detalhes.get("data_cadastro") or detalhes.get("created_at"):
                        cad = detalhes.get("data_cadastro") or str(detalhes.get("created_at", ""))[:10]
                        c2.text_input("Cadastrado em", value=str(cad), disabled=True, key=f"vw_cad_{professor_id}")

    with tab_quest:
        _render_questionario_base_prof(professor_id)

    with tab_ppo:
        st.markdown("##### Perfil Pedagogico do Professor")
        st.info(
            "🚧 **Em construcao**: estilo de avaliacao, frequencia de adaptacoes solicitadas, "
            "materias predominantes."
        )

    with tab_debug:
        st.markdown("##### Debug")
        if detalhes:
            with st.expander("JSON raw"):
                st.json(detalhes)



# ============================================================================
# API publica
# ============================================================================

def render_pagina_professores() -> None:
    """Roteador principal - chamado pelo app.py quando view_mode == 'professores'."""
    _init_state()

    if st.session_state.get("professor_em_visualizacao"):
        _render_prontuario_professor(st.session_state["professor_em_visualizacao"])
    else:
        _render_lista_geral_professores()
