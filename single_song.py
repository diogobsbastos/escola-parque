import streamlit as st
import time 
import os
from funcoes_lab import (
    extrair_resumo_tecnico, 
    criar_nova_versao,
    extrair_conteudo_inteligente,
    salvar_no_historico,
    carregar_historico,
    baixar_audio_youtube,
    analisar_original_com_mestre, 
    traduzir_texto_existente,
    load_key
)

# --- LISTA MESTRE DE IDIOMAS ---
LISTA_IDIOMAS = ["PT-BR (Brasil)", "PT-AO (Angola)", "PT-MZ (Moçambique)", "PT-PT (Portugal)", "Inglês", "Espanhol", "Francês"]

# --- ATUALIZAÇÃO: Importando o novo motor blindado ---
try:
    from fabrica_video import renderizar_video_com_texto
except ImportError:
    renderizar_video_com_texto = None

# --- FUNÇÃO DO POP-UP (MODAL) ---
@st.dialog("🎬 Estúdio de Vídeo & Visual", width="large")
def abrir_modal_video(index_versao, versao_dados, url_audio_original):
    st.caption(f"Trabalhando na versão: **{versao_dados['tema']}**")
    
    col_vis, col_vid = st.columns(2, gap="medium")
    
    # --- COLUNA 1: PROMPT VISUAL (MIDJOURNEY) ---
    with col_vis:
        st.markdown("##### 🎨 Prompt Visual (Capa/Fundo)")
        st.info("Copie este comando para gerar a imagem de fundo em IAs como Midjourney ou Flux.")
        
        # Tenta pegar o prompt visual separado. Se for versão antiga, avisa.
        p_vis = versao_dados.get('prompt_visual', None)
        if not p_vis:
            p_vis = "⚠️ Esta é uma versão antiga. O prompt visual separado não está disponível.\nUse o prompt musical como base ou crie uma nova versão."
            
        st.code(p_vis, language="text")

    # --- COLUNA 2: RENDERIZADOR DE VÍDEO ---
    with col_vid:
        st.markdown("##### 🎥 Renderizar Vídeo Vertical")
        bg_file = st.file_uploader("Upload do Fundo (Vídeo MP4 ou Imagem JPG/PNG):", type=['mp4', 'jpg', 'png'])
        
        # --- [NOVO] PREVIEW IMEDIATO ---
        if bg_file:
            st.caption("👁️ Pré-visualização:")
            if bg_file.type.startswith('image'):
                st.image(bg_file, caption="Fundo Carregado", use_container_width=True)
            elif bg_file.type.startswith('video'):
                st.video(bg_file)
        # -------------------------------
        
        if st.button("🚀 Renderizar Agora", type="primary", use_container_width=True):
            # Validação do Motor
            if not renderizar_video_com_texto:
                st.error("ERRO CRÍTICO: 'fabrica_video.py' não encontrado ou 'moviepy' não instalado.")
                st.code("pip install moviepy==1.0.3 decorator==4.4.2 imageio-ffmpeg")
            else:
                # Define caminhos
                nome_safe = f"video_v{index_versao}_{int(time.time())}.mp4"
                path_out = os.path.abspath(nome_safe)
                
                status = st.status("Iniciando produção...", expanded=True)
                
                # 1. Baixar Áudio Original (Cache rápido)
                status.write("📥 Obtendo áudio da base...")
                
                # --- [ACRESCENTADO] Tratamento para áudios locais ---
                if url_audio_original.startswith("upload_"):
                    status.error("⚠️ Este projeto foi criado a partir de um arquivo local. O áudio temporário não está mais disponível para download automático.")
                    d_audio = None
                else:
                    d_audio = baixar_audio_youtube(url_audio_original)
                # ----------------------------------------------------
                
                if d_audio:
                    # 2. Preparar Fundo
                    path_bg = None
                    if bg_file:
                        path_bg = f"temp_bg_{index_versao}.mp4"
                        with open(path_bg, "wb") as f: f.write(bg_file.getbuffer())
                    
                    # 3. Renderizar (USANDO A NOVA FUNÇÃO COM CALLBACK HÍBRIDO)
                    status.write("⚙️ Conectando ao motor de vídeo...")
                    
                    # --- [ALTERAÇÃO] CONFIGURAÇÃO DA BARRA ---
                    barra_progresso = status.empty()
                    prog_bar = barra_progresso.progress(0, text="Aguardando motor...")

                    def callback_hibrido(dados):
                        if isinstance(dados, (int, float)):
                            # Se for número, atualiza a barra
                            pct = int(dados)
                            prog_bar.progress(pct, text=f"🚀 Renderizando: {pct}%")
                        else:
                            # Se for texto, escreve no log
                            status.write(dados)
                    
                    sucesso, msg = renderizar_video_com_texto(
                        audio_path=d_audio['arquivo'], 
                        texto_overlay=versao_dados['letra'], 
                        fundo_path=path_bg, 
                        output_path=path_out,
                        callback_progresso=callback_hibrido  # <--- Usa a função inteligente
                    )
                    
                    if sucesso:
                        prog_bar.progress(100, text="✅ 100% Concluído!")
                        status.update(label="Vídeo Renderizado com Sucesso!", state="complete", expanded=False)
                        st.balloons()
                        st.success("✅ Vídeo pronto para download!")
                        st.video(path_out)
                        
                        with open(path_out, "rb") as fv:
                            st.download_button("⬇️ Baixar MP4 (9:16)", fv, file_name=nome_safe)
                    else:
                        status.update(label="Falha na Renderização", state="error")
                        st.error(f"Erro: {msg}")
                    
                    # 4. Limpeza de arquivos temporários
                    try: 
                        os.remove(d_audio['arquivo'])
                        if path_bg: os.remove(path_bg)
                    except: pass
                else:
                    status.update(label="Erro no Processamento", state="error")
                    st.error("Não foi possível acessar o áudio para renderização.")

# --- FUNÇÃO PRINCIPAL DA ABA ---
def render_single_song_tab(api_key: str, modelo_ia: str = "gemini-1.5-flash"): 
# --- LOGICA DE IMPORTAÇÃO DO RADAR ---
    link_pre_definido = ""
    if 'pacote_radar' in st.session_state:
        pacote = st.session_state['pacote_radar']
        link_pre_definido = pacote.get('link', '')
        # Opcional: Mostrar aviso
        st.toast(f"Importado do Radar: {pacote['titulo']}")
        # Limpa para não ficar voltando
        del st.session_state['pacote_radar']

    """
    Renderiza toda a lógica da aba MÚSICA INDIVIDUAL.
    """
    
    # MODO 1: PROJETO CARREGADO DO HISTÓRICO
    if st.session_state.get('projeto_ativo'):
        proj = st.session_state['projeto_ativo']
        url_atual = st.session_state['url_ativa']
        
        # --- LÓGICA DE DADOS (SEPARAÇÃO LETRA vs SCRIPT) ---
        letra_display = proj.get('letra_original', '')
        script_display = proj.get('prompt_tecnico', None)
        
        # Verifica se é projeto antigo (sem script separado)
        is_old_project = False
        if not script_display:
            is_old_project = True
            script_display = "⚠️ PROJETO ANTIGO DETECTADO.\n\nPara separar o Script Técnico da Letra e habilitar todas as funções novas, vá em 'Iniciar Novo Projeto' e cole o link desta música novamente.\nIsso forçará uma atualização da análise."

        # Tenta extrair BPM/Estilo do lugar certo
        try:
            texto_para_analise = script_display if not is_old_project else letra_display
            estilo_ref, bpm_ref = extrair_resumo_tecnico(texto_para_analise)
        except Exception:
            estilo_ref, bpm_ref = 'N/A', 'N/A'
        
        # Cabeçalho do Projeto
        c_img, c_info = st.columns([1, 4])
        with c_img: 
            if proj.get('thumb'): st.image(proj['thumb'])
        with c_info:
            st.subheader(proj['titulo'])
            st.caption(f"🔗 Base: {url_atual}")
            st.caption(f"🧠 Modelo Ativo: **{modelo_ia}**")

        # Abas internas
        t_base, t_criacao, t_versoes = st.tabs(["📜 Base & Tradução", "✨ Criar Versão", "💾 Histórico de Versões"])
        
        # ABA 1: BASE (Visualização Limpa)
        with t_base: 
            col_orig, col_trad = st.columns(2)
            
            with col_orig:
                st.markdown("##### 🇺🇸 Original (Letra Limpa)")
                st.text_area("Original", letra_display, height=500, label_visibility="collapsed")
            
            with col_trad:
                st.markdown("##### 🌍 Tradução Literal")
                # -- [NOVO] SELETOR DE REGIÃO PARA TRADUÇÃO --
                regiao_trad = st.selectbox("Idioma de Tradução:", LISTA_IDIOMAS, key="sel_trad")
                
                if 'traducao_literal' in proj:
                    st.text_area("Tradução", proj['traducao_literal'], height=500, label_visibility="collapsed")
                else:
                    st.warning("⚠️ Sem tradução salva.")
                    
                if st.button("🔄 Gerar Tradução Agora", use_container_width=True):
                    with st.spinner(f"Traduzindo para {regiao_trad}..."):
                        trad_nova = traduzir_texto_existente(api_key, letra_display, modelo_escolhido=modelo_ia, regiao=regiao_trad)
                        proj['traducao_literal'] = trad_nova
                        salvar_no_historico(url_atual, proj)
                        st.rerun()

            st.divider()
            st.subheader("📋 Script Técnico (Suno/Udio)")
            st.caption("Prompt Musical em Inglês (Genre, Instruments, Vibe, BPM).")
            st.text_area("Script Completo", value=script_display, height=250)
            
        # ABA 2: CRIAÇÃO (Focada em Compositor)
        with t_criacao:
            st.info(f"🎤 **ESTILO BASE:** {estilo_ref} | **BPM:** {bpm_ref}", icon="🔎")
            
            # -- [NOVO] SELETOR DE REGIÃO PARA COMPOSIÇÃO --
            regiao_criacao = st.selectbox("Mercado Alvo (Regionalidade):", LISTA_IDIOMAS)
            tema = st.text_input("Tema da Nova Versão:", "Resposta da mulher, superada")
            
            usar_base = st.checkbox(
                "📚 Usar Base de Conhecimento (Perfil DUDA)", 
                value=True, 
                help="Se marcado, a IA imita o estilo da Duda. Se desmarcado, cria livremente."
            )
            
            if st.button("⚡ GERAR VERSÃO INÉDITA", type="primary", use_container_width=True):
                if not api_key:
                    st.error("Sem chave API configurada.")
                else:
                    with st.spinner(f"Compondo letra em {regiao_criacao} com {modelo_ia}..."):
                        # Chama a função que retorna o texto bruto, passando a região
                        raw_res = criar_nova_versao(
                            api_key, 
                            letra_display, 
                            tema,
                            modelo_escolhido=modelo_ia,
                            usar_treino=usar_base,
                            regiao=regiao_criacao
                        )
                        # Extrai as 3 partes: Letra, Prompt Suno, Prompt Visual
                        letra_final, prompt_suno, prompt_visual = extrair_conteudo_inteligente(raw_res)

                        nova = {
                            "tema": tema, 
                            "letra": letra_final, 
                            "prompt": prompt_suno,          # Prompt Musical (Suno)
                            "prompt_visual": prompt_visual, # Prompt Visual (Midjourney)
                            "data": time.strftime("%d/%m %H:%M")
                        }
                        
                        proj['versoes_criadas'].append(nova)
                        salvar_no_historico(url_atual, proj)
                        st.session_state['projeto_ativo'] = proj
                        st.success("Versão Criada com Sucesso!")
                        time.sleep(0.5)
                        st.rerun()

        # ABA 3: HISTÓRICO (Organizado e Limpo)
        with t_versoes:
            if proj['versoes_criadas']:
                for i in range(len(proj['versoes_criadas']) - 1, -1, -1):
                    v = proj['versoes_criadas'][i]
                    
                    with st.container(border=True):
                        # Cabeçalho da Versão com Botão de Ação
                        c_head, c_btn_vid = st.columns([4, 1.5])
                        with c_head:
                            st.markdown(f"#### 📅 {v['data']} | {v['tema']}")
                        with c_btn_vid:
                            # O BOTÃO QUE ABRE O POPUP
                            if st.button("🎬 Vídeo/Capa", key=f"vid_{i}", use_container_width=True):
                                abrir_modal_video(i, v, url_atual)

                        # Corpo: Letra e Prompt Suno (Lado a Lado)
                        c_l, c_p = st.columns(2)
                        
                        with c_l: 
                            st.caption("🎵 Letra (PT-BR)")
                            st.text_area(f"letra_{i}", v['letra'], height=250)
                        
                        with c_p: 
                            st.caption("🎛️ Prompt Suno (Musical - EN)")
                            # Aqui mostramos apenas o prompt de ÁUDIO para copiar pro Suno
                            prompt_suno_display = v.get('prompt', 'Prompt não disponível.')
                            st.text_area(f"prompt_{i}", prompt_suno_display, height=250)

                        if st.button("🗑️ Apagar Versão", key=f"del_v_{i}"):
                            proj['versoes_criadas'].pop(i)
                            salvar_no_historico(url_atual, proj)
                            st.rerun()
            else: 
                st.warning("Nenhuma versão criada ainda.")

    # MODO 2: INICIAR NOVO PROJETO (Busca e Análise Inicial)
    else:
        st.markdown("### 🚀 Iniciar Novo Projeto")
        
        status_container = st.empty()
        progress_bar_placeholder = st.empty()
        
        # --- [NOVO] DUPLOS SELETORES DE IDIOMAS LADO A LADO ---
        c_lang1, c_lang2 = st.columns(2)
        with c_lang1:
            idioma_audio = st.selectbox(
                "🎧 Idioma original da mídia:", 
                LISTA_IDIOMAS,
                index=0,
                help="Avisa a IA para ativar o vocabulário e gírias corretas na hora de ouvir o áudio."
            )
        with c_lang2:
            idioma_trad = st.selectbox(
                "🌐 Traduzir literalmente para:", 
                LISTA_IDIOMAS,
                index=0,
                help="Idioma em que a versão original será explicada para você."
            )
        st.divider()
        # ------------------------------------------------------
        
        # --- [ACRESCENTADO] COLUNAS PARA SUPORTAR LINK OU UPLOAD (AGORA COM VÍDEO) ---
        col_link, col_upload = st.columns(2)
        with col_link:
            entrada = st.text_input("Link ou Nome (YouTube):", value=link_pre_definido, placeholder="Cole o link do YouTube...")
        with col_upload:
            arquivo_upload = st.file_uploader("Ou Upload Local (Áudio ou Vídeo):", type=['mp3', 'wav', 'mp4', 'mov', 'avi'])
        # ----------------------------------------------------------------------------

        if st.button("🔍 Analisar & Criar Base", type="primary"):
            # --- [ACRESCENTADO] VALIDAÇÃO DE ENTRADA ---
            if not entrada and not arquivo_upload:
                st.warning("⚠️ Insira um link do YouTube ou faça o upload de um arquivo de mídia.")
                st.stop()
            # -------------------------------------------
                
            # 1. Busca no Histórico
            hist = carregar_historico()
            encontrado = None
            
            # Só faz sentido buscar no histórico se o usuário colou um link
            if entrada and not arquivo_upload:
                for u, d in hist.items():
                    if entrada in u:
                        encontrado = d
                        st.session_state['url_ativa'] = u
                        break
            
            # 2. Verificação Inteligente de Cache
            if encontrado and 'prompt_tecnico' in encontrado:
                st.session_state['projeto_ativo'] = encontrado
                status_container.success("Projeto completo encontrado! Carregando...")
                time.sleep(1)
                st.rerun()
            else:
                if encontrado:
                    status_container.warning("Projeto antigo detectado. Atualizando Análise Técnica...")
                else:
                    status_container.info("1/3: Iniciando preparação de mídia...")
                
                progress_bar_widget = progress_bar_placeholder.progress(0, text="0%")
                api_key_load = load_key()
                
                # --- [ACRESCENTADO] LÓGICA DE DECISÃO: DOWNLOAD VS UPLOAD (COM EXTRAÇÃO) ---
                d = None
                if arquivo_upload:
                    # Rota de Upload Local
                    progress_bar_widget.progress(10, text="Salvando arquivo temporário...")
                    timestamp = int(time.time())
                    nome_original = arquivo_upload.name
                    extensao = nome_original.split('.')[-1].lower()
                    
                    temp_path = f"temp_{timestamp}_{nome_original}"
                    
                    with open(temp_path, "wb") as f:
                        f.write(arquivo_upload.getbuffer())
                    
                    # --- MÓDULO DE EXTRAÇÃO DE ÁUDIO DE VÍDEOS ---
                    if extensao in ['mp4', 'mov', 'avi']:
                        progress_bar_widget.progress(20, text="Extraindo áudio do vídeo enviado...")
                        try:
                            from moviepy.editor import VideoFileClip
                            audio_temp_path = f"temp_{timestamp}_extraido.mp3"
                            
                            video_clip = VideoFileClip(temp_path)
                            if video_clip.audio is not None:
                                # Extrai o áudio sem poluir o terminal
                                video_clip.audio.write_audiofile(audio_temp_path, logger=None)
                                video_clip.close()
                                
                                # Apaga o vídeo original para limpar espaço
                                os.remove(temp_path)
                                temp_path = audio_temp_path # O sistema usará o mp3 gerado
                            else:
                                video_clip.close()
                                status_container.error("O vídeo enviado não contém uma faixa de áudio válida.")
                                st.stop()
                                
                        except Exception as e:
                            status_container.error(f"Erro ao tentar extrair o áudio do vídeo: {str(e)}")
                            st.stop()
                    # ---------------------------------------------
                        
                    fake_url = f"upload_{timestamp}_{nome_original}"
                    
                    d = {
                        'arquivo': temp_path,
                        'titulo': f"📁 {nome_original}",
                        'thumb': None,
                        'link': fake_url
                    }
                    progress_bar_widget.progress(30, text="30% - Arquivo processado localmente.")
                else:
                    # Rota Padrão YouTube
                    d = baixar_audio_youtube(entrada)
                    progress_bar_widget.progress(30, text="30% - Áudio baixado do YouTube.")
                # ------------------------------------------------------------
                
            if d:
                status_container.info(f"2/3: Analisando com {modelo_ia}...")
                progress_bar_widget.progress(60, text="Ouvindo áudio e separando Técnico, Letra e Tradução...")
                
                # --- [ATUALIZADO] ENVIANDO AS DUAS VARIAVEIS DE IDIOMA PARA A IA ---
                prompt_tec, letra_limpa, traducao_lit = analisar_original_com_mestre(
                    api_key_load, 
                    d['arquivo'], 
                    letra_mestre="",
                    modelo_escolhido=modelo_ia,
                    idioma_origem=idioma_audio,
                    idioma_destino=idioma_trad
                )
                # -------------------------------------------------------------------
                
                progress_bar_widget.progress(90, text="90% - Transcrição concluída.")
                
                # MONTA O NOVO OBJETO DE PROJETO
                np = {
                    "titulo": d['titulo'], 
                    "thumb": d['thumb'], 
                    "letra_original": letra_limpa,      # Apenas a letra limpa
                    "prompt_tecnico": prompt_tec,       # Apenas o script técnico (Suno)
                    "traducao_literal": traducao_lit,   # Apenas a tradução
                    "versoes_criadas": encontrado.get('versoes_criadas', []) if encontrado else []
                }
                
                salvar_no_historico(d['link'], np)
                
                st.session_state['projeto_ativo'] = np
                st.session_state['url_ativa'] = d['link']
                
                progress_bar_widget.progress(100, text="100% - Sucesso!")
                status_container.success("✅ Projeto Atualizado com Sucesso!")
                
                try: 
                    os.remove(d['arquivo'])
                except Exception: 
                    pass
                    
                time.sleep(1)
                st.rerun()
                
            else:
                status_container.error("Falha ao preparar o arquivo de áudio. Verifique se o link/arquivo está correto.")
                progress_bar_placeholder.empty()