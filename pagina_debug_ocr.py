import streamlit as st
import json
import os
import pandas as pd

def renderizar(aluno_id=None):
    st.subheader("🐛 Modo Debug - Cérebro da IA")
    st.caption("Relatório analítico do raciocínio (Chain of Thought) utilizado no último escaneamento.")
    
    if not aluno_id:
        st.warning("Nenhum aluno selecionado. Volte para a aba de alunos.")
        return
        
    caminho_cache = f"ocr_cache_{aluno_id}.json"
    
    if not os.path.exists(caminho_cache):
        st.info("Nenhum questionário extraído encontrado para este aluno. Faça o upload na aba anterior.")
        return
        
    try:
        with open(caminho_cache, "r", encoding="utf-8") as f:
            dados_extraidos = json.load(f)
            
        if not dados_extraidos:
            st.warning("O arquivo de cache está vazio.")
            return

        # Achata os dados do JSON para criar um DataFrame analítico
        linhas_relatorio = []
        for categoria, itens in dados_extraidos.items():
            for item in itens:
                linhas_relatorio.append({
                    "Categoria": categoria.split(" - ")[0], # Pega só o "SEÇÃO X"
                    "Item Avaliado": item.get("pergunta", ""),
                    "Veredito": "✅ MARCADO" if item.get("marcado", False) else "⚪ VAZIO",
                    "Confiança IA": f"{item.get('confianca_ia', 0)}%",
                    "Justificativa Visual (O que a IA viu)": item.get("obs_ia", "Sem log de análise")
                })
        
        df_debug = pd.DataFrame(linhas_relatorio)
        
        with st.container(border=True):
            st.markdown("### 📊 Relatório de Tomada de Decisão")
            st.markdown("Use esta tabela para identificar onde a IA está alucinando (vendo tinta onde não tem).")
            
            # Destaca em vermelho as linhas onde a IA tem baixa confiança
            def highlight_confianca(val):
                try:
                    conf = int(val.replace("%", ""))
                    if conf < 80:
                        return 'color: #D32F2F; font-weight: bold;'
                except: pass
                return ''

            st.dataframe(
                df_debug.style.map(highlight_confianca, subset=['Confiança IA']),
                use_container_width=True,
                hide_index=True
            )
            
        with st.expander("📦 Ver JSON Bruto Gerado pelo Backend"):
            st.json(dados_extraidos)

    except Exception as e:
        st.error(f"Erro ao gerar o relatório de debug: {str(e)}")