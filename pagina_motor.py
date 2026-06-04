# ARQUIVO: pagina_motor.py
import streamlit as st
import time

# --- BLINDAGEM DO BACKEND (Regra de Ouro 3) ---
try:
    import backend_ocr
except ImportError:
    backend_ocr = None

def renderizar():
    # Cabeçalho baseado no seu design
    st.subheader("Diogo Brandão — 6º ano — Turma 1601")
    
    # Navegação simulada (apenas visual, conforme seu print)
    st.markdown("""
        <style>
            .nav-link { margin-right: 20px; color: #555; text-decoration: none; }
            .nav-link.active { color: #FF4B4B; border-bottom: 2px solid #FF4B4B; padding-bottom: 5px; }
        </style>
        <div>
            <span class="nav-link">Informações</span>
            <span class="nav-link active">Questionário Base</span>
            <span class="nav-link">Perfil Pedagógico</span>
            <span class="nav-link">Relatório IA (Debug)</span>
        </div>
        <hr style="margin-top: 10px; margin-bottom: 20px;">
    """, unsafe_allow_html=True)

    col_titulo, col_btn = st.columns([3, 1])
    with col_titulo:
        st.markdown("### Questionários Preenchidos")
    with col_btn:
        st.button("Novo Questionário", type="primary", use_container_width=True)

    # --- UPLOAD DO RELATÓRIO (Regra de Ouro 1) ---
    with st.container(border=True):
        st.markdown("##### 📥 Importar Relatório (PDF)")
        st.caption("A IA Vision extrairá os dados visuais baseada na similaridade com seus gabaritos.")
        
        arquivo_pdf = st.file_uploader("Selecione o arquivo diagnóstico (escaneado)", type=["pdf"], label_visibility="collapsed")

    # Se houver arquivo, mostramos a área de análise
    if arquivo_pdf:
        with st.container(border=True):
            st.info(f"📄 Arquivo carregado: **{arquivo_pdf.name}** ({arquivo_pdf.size / 1024 / 1024:.1f} MB)")
            
            # Botão de iniciar a análise
            if st.button("🚀 Iniciar Análise Pedagógica", use_container_width=True):
                if backend_ocr:
                    # Usando st.status para feedback contínuo durante o OCR em lotes
                    with st.status("Extraindo dados do formulário escaneado...", expanded=True) as status:
                        st.write("Preparando arquivo para a IA Vision...")
                        
                        # 1. Salva o PDF localmente
                        caminho_temp = backend_ocr.extrair_texto_pdf(arquivo_pdf)
                        
                        if "ERRO" in caminho_temp:
                            status.update(label="Falha de Leitura", state="error", expanded=False)
                            st.error(caminho_temp)
                        else:
                            st.write("Iniciando a leitura cirúrgica dos lotes de questões...")
                            
                            # 2. Chama a função complexa do motor
                            resultado = backend_ocr.analisar_com_treinamento(caminho_temp)
                            
                            if "erro" in resultado:
                                status.update(label="Falha no Processamento IA", state="error", expanded=False)
                                st.error(resultado["erro"])
                            else:
                                status.update(label="Extração finalizada com sucesso!", state="complete", expanded=False)
                                st.session_state['resultado_ocr'] = resultado # Salva no state (Regra 1)
                else:
                    st.error("ERRO CRÍTICO: Arquivo 'backend_ocr.py' não encontrado na raiz.")

    # --- EXIBIÇÃO DOS RESULTADOS ---
    if 'resultado_ocr' in st.session_state:
        dados = st.session_state['resultado_ocr'].get("dados", {})
        
        st.markdown("<br>", unsafe_allow_html=True)
        with st.container(border=True):
            col_titulo_ext, col_toggle = st.columns([3, 1])
            with col_titulo_ext:
                st.markdown("#### 📋 Extração Fidedigna (Questionário Base)")
                st.caption("Dados sincronizados fisicamente com o formulário oficial da Escola Parque.")
            with col_toggle:
                st.toggle("Ver Dados Extraídos", value=True)
            
            st.divider()

            # Renderiza os dados lidos pelo OCR no formato de lista com checkboxes
            for secao, itens in dados.items():
                if itens: # Só renderiza a seção se houver itens processados
                    st.markdown(f"##### {secao}")
                    for item in itens:
                        marcado = item.get("marcado", False)
                        pergunta = item.get("pergunta", "")
                        
                        col_check, col_nivel = st.columns([9, 1])
                        with col_check:
                            # Se marcado = True, exibe o ícone de checkbox com "V"
                            icone = "☑️" if marcado else "⬜"
                            st.markdown(f"{icone} {pergunta}")
                        with col_nivel:
                            nivel = 4 if marcado else 0
                            st.caption(f"Nível {nivel}")
                    
                    st.divider()

            # Mostra a telemetria ao final
            with st.expander("💸 Telemetria Financeira"):
                st.json(st.session_state['resultado_ocr'].get("telemetria", {}))