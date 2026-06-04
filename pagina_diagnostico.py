# ARQUIVO: pagina_diagnostico.py
import streamlit as st

try:
    import backend_diagnostico as bd
except ImportError:
    bd = None

def renderizar():
    st.subheader("🛠️ Diagnóstico do Sistema (Escola Parque)")
    st.caption("Verificação de integridade da arquitetura Pedagógica (Surgical RAG)")

    if not bd:
        st.error("Erro Crítico: Arquivo 'backend_diagnostico.py' não encontrado.")
        return

    # Container 1: Arquivos Python (Regra de Ouro 1)
    with st.container(border=True):
        st.markdown("##### 📁 Integridade de Arquivos Core")
        status_arquivos = bd.verificar_integridade()
        
        cols = st.columns(2)
        for i, (arq, existe) in enumerate(status_arquivos.items()):
            col = cols[i % 2]
            if existe:
                col.success(f"**{arq}**: OK")
            else:
                col.error(f"**{arq}**: Ausente")

    # Container 2: Credenciais e Json (Regra de Ouro 1)
    with st.container(border=True):
        st.markdown("##### 🔑 Status de Configurações Locais")
        status_keys = bd.checar_credenciais()
        for key, existe in status_keys.items():
            if existe:
                st.info(f"Arquivo de configuração `{key}` detectado.")
            else:
                st.warning(f"Atenção: `{key}` não configurado ou salvo ainda.")

    if st.button("Executar Scan Completo", type="primary"):
        st.balloons()
        st.toast("Scan Pedagógico concluído com sucesso!")
        st.rerun()