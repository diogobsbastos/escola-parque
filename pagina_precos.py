import streamlit as st
import google.generativeai as genai
import time
import json
import os
from funcoes_fla import load_key

def renderizar():
    st.title("📊 Atualização da Tabela de Preços")
    st.caption("Faça o upload do PDF oficial de preços do Google para atualizar o sistema.")

    arquivo_pdf = st.file_uploader("Envie o PDF de preços (Ex: Preços da API Gemini.pdf)", type=["pdf"])

    if st.button("🔄 Processar e Atualizar Preços") and arquivo_pdf:
        api_key = load_key("gemini")
        if not api_key:
            st.error("Chave de API não encontrada.")
            return

        genai.configure(api_key=api_key)
        
        try:
            with st.spinner("Subindo PDF para análise..."):
                # Salva o arquivo temporariamente
                caminho_temp = "temp_precos.pdf"
                with open(caminho_temp, "wb") as f:
                    f.write(arquivo_pdf.getbuffer())
                
                # Faz o upload para o Gemini
                pdf_genai = genai.upload_file(caminho_temp, mime_type="application/pdf")
                
                # Aguarda processamento
                while pdf_genai.state.name == "PROCESSING":
                    time.sleep(2)
                    pdf_genai = genai.get_file(pdf_genai.name)

            with st.spinner("A IA está lendo o documento e mapeando os valores..."):
                # Pedimos para a IA extrair estritamente um JSON
                prompt = """
                Você é um extrator de dados financeiros. Leia este PDF oficial de preços de APIs do Google.
                Crie um JSON estrito onde a chave é o nome do modelo (ex: 'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-3.1-flash-lite') e os valores são 'input' (preço de entrada de texto) e 'output' (preço de saída de texto/pensamento) por 1 milhão de tokens.
                
                Regras:
                - Considere os preços da coluna "Nível pago, por 1 milhão de tokens em USD".
                - Se houver diferença de preço por tamanho de prompt (ex: <= 200 mil tokens), extraia SEMPRE o menor valor (o valor base).
                - Use ponto para decimais.
                - Responda APENAS com o JSON válido e NENHUMA outra palavra. Não use blocos de código (```json).
                """
                
                model = genai.GenerativeModel("gemini-2.5-pro") # Usamos o Pro para melhor precisão de leitura
                response = model.generate_content([prompt, pdf_genai])
                
                # Limpando a string para garantir que é um JSON válido
                texto_json = response.text.strip().replace("```json", "").replace("```", "")
                
                # Valida e salva o JSON
                novos_precos = json.loads(texto_json)
                
                with open("precos_ia.json", "w", encoding="utf-8") as f:
                    json.dump(novos_precos, f, indent=4)
                    
                st.success("✅ Tabela de preços atualizada com sucesso!")
                st.json(novos_precos)
                
                # Limpeza
                genai.delete_file(pdf_genai.name)
                os.remove(caminho_temp)
                
        except Exception as e:
            st.error(f"Erro ao processar o PDF: {e}")