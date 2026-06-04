import streamlit as st
import os

# REGRA DE OURO 2: Página isolada com função renderizar()
def renderizar():
    st.subheader("🧠 Central de Treinamento IA (PPO)")
    st.caption("Alimente o arquivo 'treinamento_gemini.txt' para ensinar a IA o estilo da Escola Parque.")

    # Definimos o arquivo de destino conforme o mapa do sistema
    caminho_treino = "treinamento_gemini.txt"

    # Criamos o arquivo caso ele não exista para evitar erros de leitura
    if not os.path.exists(caminho_treino):
        with open(caminho_treino, "w", encoding="utf-8") as f:
            f.write("### PERSONA PEDAGÓGICA ###\nEscreva aqui como a IA deve se comportar...")

    # REGRA DE OURO 1: Organização visual com container[cite: 1]
    with st.container(border=True):
        st.markdown("#### 📝 Editor de Base de Conhecimento")
        
        # Lemos o conteúdo atual para exibir no editor
        with open(caminho_treino, "r", encoding="utf-8") as f:
            conteudo_atual = f.read()

        # Área de texto para edição manual do treinamento
        novo_texto = st.text_area(
            "Exemplos de Ouro (Few-Shot Prompting):",
            value=conteudo_atual,
            height=500,
            help="Insira exemplos de 'Relatório Bruto' vs 'Análise PPO' da equipe pedagógica."
        )

        col_btn, col_info = st.columns([1, 2])
        
        with col_btn:
            if st.button("💾 Salvar Treinamento", type="primary", use_container_width=True):
                try:
                    with open(caminho_treino, "w", encoding="utf-8") as f:
                        f.write(novo_texto)
                    st.success("Base de conhecimento atualizada!")
                    st.balloons()
                except Exception as e:
                    st.error(f"Erro ao salvar arquivo: {e}")
        
        with col_info:
            st.info("A IA lerá este arquivo antes de processar qualquer PDF no OCR.")

    # Espaço para dicas técnicas
    with st.expander("💡 Dica do Arquiteto para Treinamento Eficaz"):
        st.write("""
        Para que o sistema aprenda a 'cara' da Escola Parque, use este formato no texto acima:
        
        **EXEMPLO 1:**
        - **Relato:** Aluno apresenta muita agitação e não foca no texto.
        - **Análise:** Sustentação da atenção: 4.
        - **Obs:** Demonstrada baixa tolerância a estímulos auditivos, necessita de fone abafador.
        
        **EXEMPLO 2:**
        ...
        """)