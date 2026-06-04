import streamlit as st
import time
import os
import json
import re
import shutil
import google.generativeai as genai
from fpdf import FPDF

# --- IMPORTAÇÕES DO SEU ECOSSISTEMA (ESTRUTURA DE PONTE) ---
from lab_media import baixar_audio_yt_dlp, cortar_audio_ffmpeg, limpar_pasta_downloads
from lab_storage import salvar_no_historico, carregar_historico
from lab_ai import analisar_original_com_mestre
from lab_utils import extrair_resumo_tecnico

# --- CONFIGURAÇÃO DE DIRETÓRIOS ---
SETLIST_TEMP_DIR = "downloads_setlist"
if not os.path.exists(SETLIST_TEMP_DIR):
    os.makedirs(SETLIST_TEMP_DIR)

# --- UTILITÁRIO: GERAÇÃO DE PDF ---
def gerar_pdf_setlist(nome_show, faixas):
    """Gera um PDF consolidado com todas as análises do show."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    for item in faixas:
        pdf.add_page()
        # Título da Música
        pdf.set_font("Arial", 'B', 16)
        titulo_limpo = item['titulo'].encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(200, 10, txt=titulo_limpo, ln=True, align='C')
        pdf.ln(10)
        
        # Conteúdo Técnico e Letras
        pdf.set_font("Arial", size=11)
        # Limpa quebras de linha e trata caracteres para o PDF
        corpo_texto = item['letra_original'].replace('\n\n', '\n').encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 5, txt=corpo_texto)
        
    return pdf.output(dest='S').encode('latin-1')

# --- CONFIGURAÇÃO DE SEGMENTAÇÃO REAL VIA IA ---

def detectar_segmentos_reais_ia(api_key: str, arquivo_path: str, modelo_ia: str) -> list[dict] | None:
    """
    Usa a IA para ouvir o arquivo bruto e mapear os tempos de início e fim de cada música.
    Inclui limpeza cirúrgica para evitar o erro 'Extra data'.
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(modelo_ia)
        
        with st.spinner("🛰️ IA analisando a estrutura sonora do show para encontrar os cortes exatos..."):
            # 1. Faz o upload para a API de arquivos do Google
            audio_file = genai.upload_file(path=arquivo_path)
            
            # 2. Aguarda o processamento no servidor do Google
            while audio_file.state.name == "PROCESSING":
                time.sleep(2)
                audio_file = genai.get_file(audio_file.name)
            
            # 3. Prompt de segmentação cirúrgica
            prompt = """
            Analise este áudio de show completo. 
            Sua tarefa é identificar onde cada música começa e termina.
            Ignore conversas longas ou introduções excessivas que não fazem parte da música.
            Retorne APENAS um JSON puro no seguinte formato:
            [
              {"start": "HH:MM:SS", "end": "HH:MM:SS", "titulo_sugerido": "Nome da Música"}
            ]
            """
            
            response = model.generate_content([prompt, audio_file])
            
            # Limpa o arquivo da nuvem após o processamento
            genai.delete_file(audio_file.name)
            
            # 4. EXTRAÇÃO ROBUSTA (Resolve o erro Extra Data)
            raw_text = response.text.strip()
            
            # Encontra o primeiro '[' e o último ']' para isolar o JSON de qualquer texto extra
            inicio_json = raw_text.find('[')
            fim_json = raw_text.rfind(']')
            
            if inicio_json != -1 and fim_json != -1:
                json_limpo = raw_text[inicio_json:fim_json+1]
                try:
                    segmentos = json.loads(json_limpo)
                    return segmentos if isinstance(segmentos, list) else None
                except json.JSONDecodeError as je:
                    st.error(f"Erro ao decodificar JSON: {je}")
                    return None
            else:
                st.error("A IA não retornou um formato de lista válido.")
                return None

    except Exception as e:
        st.error(f"Erro na segmentação inteligente: {e}")
        return None

# --- FUNÇÃO PRINCIPAL ---

def render_setlist_analyzer_tab(api_key: str, modelo_ia: str):
    """
    Renderiza a aba SETLIST com Histórico e Processamento com Corte Realista.
    Permite Upload de arquivo ou Link do YouTube.
    """
    
    # --- 1. PAINEL DE HISTÓRICO ---
    st.markdown("### ✂️ Setlist Analyzer PRO (Corte Inteligente)")
    
    with st.expander("📜 Consultar Shows Gravados", expanded=False):
        historico_geral = carregar_historico()
        # Filtra apenas itens processados pelo Setlist (pelo prefixo setlist_)
        itens_setlist = {k: v for k, v in historico_geral.items() if "setlist_" in k}
        
        if not itens_setlist:
            st.info("Nenhuma análise de lote encontrada no histórico.")
        else:
            for url in sorted(itens_setlist.keys(), reverse=True):
                dados = itens_setlist[url]
                col_h1, col_h2 = st.columns([4, 1])
                with col_h1:
                    st.markdown(f"**{dados.get('titulo', 'Sem Título')}**")
                    estilo, bpm = extrair_resumo_tecnico(dados.get('letra_original', ''))
                    st.caption(f"Estilo: {estilo} | BPM: {bpm}")
                with col_h2:
                    if st.button("Ver", key=f"btn_hist_{url}"):
                        st.session_state['setlist_view'] = dados
            
            if 'setlist_view' in st.session_state:
                st.divider()
                st.info(f"Visualizando: {st.session_state['setlist_view']['titulo']}")
                # MELHORIA: Exibe o texto COMPLETO no histórico sem cortes
                st.text_area("Ficha Técnica e Letras:", st.session_state['setlist_view']['letra_original'], height=400)

    st.divider()

    # --- 2. ÁREA DE ENTRADA (UPLOAD OU LINK) ---
    st.markdown("#### 🚀 Novo Processamento")
    st.info(f"🤖 IA Atual: **{modelo_ia}** | ✂️ O corte será baseado na minutagem real detectada.")

    # [MELHORIA] Opção para manter os arquivos fatiados
    manter_arquivos = st.checkbox("💾 **MANTER MÚSICAS CORTADAS** (Cria pasta com MP3s renomeados)", value=False)

    # Implementação das Abas para os dois modos de entrada
    tab_upload, tab_link = st.tabs(["📁 Upload de Arquivo", "🔗 Link do YouTube"])
    
    caminho_arquivo_trabalho = None
    nome_original_show = "Show_Desconhecido"

    with tab_upload:
        uploaded_file = st.file_uploader(
            "Carregar Arquivo de Show (MP3, MP4, M4A, WAV):",
            type=['mp3', 'mp4', 'm4a', 'wav'],
            key="setlist_uploader"
        )
        if uploaded_file:
            nome_original_show = uploaded_file.name
            caminho_arquivo_trabalho = os.path.join(SETLIST_TEMP_DIR, f"upload_{nome_original_show}")
            with open(caminho_arquivo_trabalho, "wb") as f:
                f.write(uploaded_file.getbuffer())

    with tab_link:
        url_input = st.text_input("Cole a URL do vídeo/áudio:", placeholder="https://www.youtube.com/watch?v=...", key="setlist_url")
        if url_input:
            if st.button("📥 Baixar Áudio para Processamento", use_container_width=True):
                # INSERÇÃO DA BARRA DE CARREGAMENTO
                placeholder_pbar = st.empty()
                barra_progresso = placeholder_pbar.progress(0, text="Iniciando conexão...")
                
                with st.status("Baixando áudio do link...", expanded=True) as status:
                    # Passamos a barra_progresso para a função de download
                    resultado_dl = baixar_audio_yt_dlp(url_input, progress_widget=barra_progresso, pasta_destino=SETLIST_TEMP_DIR)
                    if resultado_dl:
                        barra_progresso.progress(100, text="✅ Download concluído!")
                        caminho_arquivo_trabalho = resultado_dl['arquivo']
                        nome_original_show = resultado_dl['titulo']
                        st.session_state['setlist_temp_path'] = caminho_arquivo_trabalho
                        st.session_state['setlist_temp_name'] = nome_original_show
                        status.update(label="✅ Download concluído!", state="complete")
                        st.rerun()
                    else:
                        status.update(label="❌ Erro ao baixar áudio.", state="error")
        
        # Recupera dados do download se já foi feito
        if 'setlist_temp_path' in st.session_state:
            caminho_arquivo_trabalho = st.session_state['setlist_temp_path']
            nome_original_show = st.session_state['setlist_temp_name']

    # --- 3. BOTÃO DE AÇÃO ---
    if caminho_arquivo_trabalho and os.path.exists(caminho_arquivo_trabalho):
        st.warning(f"📍 Arquivo pronto: `{nome_original_show}`")
        
        if st.button("🚨 INICIAR PROCESSAMENTO REAL", type="primary", use_container_width=True):
            if not api_key: 
                st.error("Configure a chave API na sidebar."); st.stop()

            # --- PLACEHOLDERS PARA FEEDBACK EM TEMPO REAL ---
            status_placeholder = st.empty()
            progress_bar_widget = st.progress(0)
            
            with st.expander("📝 Log de Atividades (Passo a Passo)", expanded=True):
                log_box = st.empty()
                logs = []
                def update_log(msg):
                    logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
                    log_box.code("\n".join(logs[-10:])) # Mostra os últimos 10 eventos

            # PASSO B: SEGMENTAÇÃO REAL
            status_placeholder.info("🚀 **Etapa 1/4: Mapeando Músicas**")
            update_log("Enviando show completo para a IA analisar a estrutura...")
            progress_bar_widget.progress(10, text="10% - Mapeando estrutura sonora...")
            
            segmentos = detectar_segmentos_reais_ia(api_key, caminho_arquivo_trabalho, modelo_ia)
            
            if not segmentos or not isinstance(segmentos, list):
                status_placeholder.error("A IA não conseguiu mapear os tempos deste show corretamente.")
                if os.path.exists(caminho_arquivo_trabalho): os.remove(caminho_arquivo_trabalho)
                st.stop()
                
            # [MELHORIA] Cria diretório da Playlist se marcado
            pasta_final_show = ""
            if manter_arquivos:
                nome_folder = re.sub(r'[\\/*?:"<>|]', "", nome_original_show)[:50].strip()
                pasta_final_show = os.path.join(SETLIST_TEMP_DIR, nome_folder)
                if not os.path.exists(pasta_final_show): 
                    os.makedirs(pasta_final_show)
                update_log(f"Pasta de destino criada: {nome_folder}")

            total = len(segmentos)
            update_log(f"✅ {total} músicas detectadas! Iniciando fatiamento.")
            progress_bar_widget.progress(25, text="25% - Mapeamento finalizado.")
            
            # PASSO C: CORTAR E ANALISAR
            historico_sessao = []
            
            for idx, seg in enumerate(segmentos):
                # Progresso proporcional entre 25% e 90%
                perc = int(25 + ((idx + 1) / total * 65))
                if perc > 95: perc = 95
                
                titulo_faixa = seg.get('titulo_sugerido', f'Faixa {idx+1}')
                status_placeholder.warning(f"✂️ **Etapa 2/4: Processando {idx+1}/{total}** - {titulo_faixa}")
                update_log(f"Fatiando: {titulo_faixa} ({seg['start']} - {seg['end']})")
                
                out_faixa = os.path.join(SETLIST_TEMP_DIR, f"faixa_temp_{idx}.mp3")
                sucesso_corte = cortar_audio_ffmpeg(
                    input_path=caminho_arquivo_trabalho,
                    output_path=out_faixa,
                    start_time=seg['start'],
                    end_time=seg['end']
                )
                
                if sucesso_corte:
                    # [MELHORIA] Delay Anti-429 (10 segundos) solicitado
                    time.sleep(10) 

                    update_log(f"Analisando técnica e letra de: {titulo_faixa}...")
                    # UNIFICAÇÃO DA RESPOSTA DA IA
                    res_tec, res_letra, res_trad = analisar_original_com_mestre(api_key, out_faixa, "", modelo_ia)
                    
                    # Unifica o conteúdo para salvar de forma limpa no campo letra_original
                    conteudo_unificado = f"{res_tec}\n\n--- TRANSCRIÇÃO ---\n\n{res_letra}\n\n--- TRADUÇÃO ---\n\n{res_trad}"
                    
                    id_unico = f"setlist_{int(time.time())}_{idx}"
                    proj = {
                        "titulo": f"{nome_original_show} - {titulo_faixa}",
                        "thumb": None,
                        "letra_original": conteudo_unificado,
                        "versoes_criadas": []
                    }
                    salvar_no_historico(id_unico, proj)
                    historico_sessao.append(proj)
                    update_log(f"✅ Concluído: {titulo_faixa}")
                    
                    # [MELHORIA] Manutenção de arquivos cortados numerados e renomeados
                    if manter_arquivos:
                        nome_mp3 = re.sub(r'[\\/*?:"<>|]', "", titulo_faixa)
                        caminho_final_mp3 = os.path.join(pasta_final_show, f"{idx+1:02d} - {nome_mp3}.mp3")
                        shutil.copy(out_faixa, caminho_final_mp3)
                        update_log(f"Arquivo salvo na playlist: {idx+1:02d} - {nome_mp3}.mp3")

                    if os.path.exists(out_faixa): os.remove(out_faixa)
                
                progress_bar_widget.progress(perc, text=f"Processando: {titulo_faixa}")

            # PASSO D: FINALIZAÇÃO
            status_placeholder.success(f"🏆 **Etapa 3/4: Finalizado!** {len(historico_sessao)} faixas salvas.")
            update_log("🏆 Sucesso! Limpando ambiente...")
            progress_bar_widget.progress(100, text="✅ Processamento concluído!")
            
            # [MELHORIA] Botão de PDF Consolidado (Suno Ready)
            if historico_sessao:
                st.divider()
                pdf_bytes = gerar_pdf_setlist(nome_original_show, historico_sessao)
                st.download_button(
                    label="📄 Baixar Dossiê Completo em PDF (Suno Ready)",
                    data=pdf_bytes,
                    file_name=f"SETLIST_{nome_original_show}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

            # Limpa arquivo bruto e estados temporários
            if os.path.exists(caminho_arquivo_trabalho): os.remove(caminho_arquivo_trabalho)
            if 'setlist_temp_path' in st.session_state: del st.session_state['setlist_temp_path']
            
            st.markdown("---")
            st.subheader("🎵 Resultados da Análise:")
            for item in historico_sessao:
                estilo, bpm = extrair_resumo_tecnico(item['letra_original'])
                with st.expander(f"📌 {item['titulo']}"):
                    st.write(f"**Vibe Detectada:** {estilo} | **BPM:** {bpm}")
                    # MELHORIA: Exibe o prompt completo aqui também (removido o fatiamento)
                    st.markdown(item['letra_original'])

            # Mantém a pasta da playlist intacta, limpa apenas temporários avulsos
            limpar_pasta_downloads(SETLIST_TEMP_DIR)
            st.balloons()
    else:
        st.info("Aguardando carregamento de arquivo ou link...")