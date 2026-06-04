import streamlit as st
import json
import os

def renderizar(aluno_id=None):
    st.subheader("📋 Extração Fidedigna (Questionário Base)")
    st.caption("Dados sincronizados fisicamente com o formulário oficial da Escola Parque.")

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

        # Mostra metadados (molde usado) se houver
        meta = dados_extraidos.get("_meta") or {}
        if meta.get("molde_usado"):
            st.info(f"🎓 Molde usado nesta extração: **{meta['molde_usado']}**")

        # Renderização visual protegida (Regra 1: container com borda)
        for categoria, itens in dados_extraidos.items():
            # Pula a chave de metadados — não é categoria de questionário
            if categoria.startswith("_"):
                continue
            if not isinstance(itens, list):
                continue
            with st.container(border=True):
                st.markdown(f"#### {categoria}")

                # Construção de um bloco HTML compacto para matar o espaçamento gigante do Streamlit
                linhas_html = ""
                for item in itens:
                    is_marcado = item.get("marcado", False)
                    texto_pergunta = item.get("pergunta", "Texto não encontrado")
                    nivel_escala = item.get("escala", 0)

                    if is_marcado:
                        icone = "☑"
                        estilo_texto = "font-weight: 600; color: #1f1f1f;"
                        texto_nivel = f"Nível {nivel_escala}"
                    else:
                        icone = "☐"
                        estilo_texto = "color: #8b8b8b;"
                        texto_nivel = "-"

                    # Flexbox garante alinhamento perfeito na mesma linha com padding mínimo (6px)
                    linhas_html += f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid #f0f2f6;">
                        <div style="display: flex; align-items: center; gap: 10px; {estilo_texto}">
                            <span style="font-size: 1.3rem;">{icone}</span>
                            <span style="font-size: 0.95rem;">{texto_pergunta}</span>
                        </div>
                        <div style="{estilo_texto} font-size: 0.85rem;">
                            {texto_nivel}
                        </div>
                    </div>
                    """

                # Renderiza todas as linhas da categoria de uma vez
                st.markdown(linhas_html, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Erro ao tentar exibir a interface do questionário: {str(e)}")
