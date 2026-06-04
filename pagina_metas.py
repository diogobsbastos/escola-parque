import streamlit as st

# Padrão de segurança
try:
    import backend_metas
except ImportError:
    backend_metas = None

def renderizar():
    st.title("🎯 Tracker de Metas de Implantação")
    
    if backend_metas is None:
        st.error("Erro: Módulo backend_metas não encontrado ou com erro.")
        return

    # Usando session_state para persistir dados na navegação
    if "dados_metas" not in st.session_state:
        st.session_state["dados_metas"] = backend_metas.carregar_metas()

    col_txt, col_btn = st.columns([4, 1])
    with col_txt:
        st.markdown("Acompanhamento das entregas técnicas atreladas ao acordo de remuneração (R$ 3k/mês).")
    with col_btn:
        # Botão de emergência para limpar tudo antes de mostrar para o dono
        if st.button("🔄 Resetar Tudo", use_container_width=True):
            st.session_state["dados_metas"] = backend_metas.forcar_reset()
            st.rerun()

    st.divider()

    metas = st.session_state["dados_metas"]
    meses_ordem = ["Maio", "Junho", "Julho"]

    for mes in meses_ordem:
        metas_do_mes = [m for m in metas if m.get('mes') == mes]
        
        if metas_do_mes:
            st.markdown(f"#### 📅 Mês: {mes}")
            
            for meta in metas_do_mes:
                # O container agora abriga uma linha única bem dividida, deixando o visual bem menor
                with st.container(border=True):
                    col_titulo, col_status, col_valor, col_acao = st.columns([3.5, 1.5, 1.5, 1.5])
                    
                    with col_titulo:
                        # Usando st.markdown(bold) ao invés de subheader para economizar espaço vertical
                        st.markdown(f"**{meta['titulo']}**")
                    with col_status:
                        st.caption(f"Status: {meta['status']}")
                    with col_valor:
                        st.caption(f"Gatilho: {meta['valor']}")

                    with col_acao:
                        # Encontra o ID real do item na lista principal para editar o status corretamente
                        idx_real = next(i for i, m in enumerate(metas) if m['id'] == meta['id'])
                        
                        if meta['status'] == "Pendente":
                            if st.button("Concluir ✅", key=f"btn_concluir_{meta['id']}", use_container_width=True):
                                metas[idx_real]['status'] = "Concluído 🚀"
                                backend_metas.salvar_metas(metas)
                                st.session_state["dados_metas"] = metas
                                st.rerun()
                        else:
                            # Botão de Reativar/Desfazer
                            if st.button("Desfazer ↩️", key=f"btn_desfazer_{meta['id']}", use_container_width=True):
                                metas[idx_real]['status'] = "Pendente"
                                backend_metas.salvar_metas(metas)
                                st.session_state["dados_metas"] = metas
                                st.rerun()
            st.markdown("<br>", unsafe_allow_html=True) # Espaçamento entre os meses