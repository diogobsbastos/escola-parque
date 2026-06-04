import streamlit as st

# REGRA DE OURO 3: Blindagem de importação
try:
    import backend_ppo_agente as agente
except ImportError:
    agente = None

def renderizar():
    st.header("🧠 Perfil Pedagógico (PPO) - Inteligência de Agentes")
    
    if 'ppo_gerado' not in st.session_state:
        st.info("Aguardando processamento de relatório na aba Questionário.")
        return

    ppo = st.session_state['ppo_gerado']
    
    # REGRA DE OURO 1: Organização com containers[cite: 1]
    with st.container(border=True):
        st.subheader("📊 Mapa de Barreiras")
        
        # Cores conforme o nível de barreira (Padrão Escola Parque)
        cores = {1: "#00FF7F", 2: "#00e676", 3: "#FFA500", 4: "#FF4500", 5: "#D32F2F"}

        for categoria, itens in ppo.items():
            if categoria == "Ajustes_Sugeridos": continue
            
            st.markdown(f"**{categoria}**")
            for item in itens:
                col_t, col_b = st.columns([2, 2])
                col_t.write(f"**{item['item']}**")
                col_t.caption(item['obs'])
                
                # Barra visual de progresso
                valor = item['valor']
                porcentagem = (valor / 5) * 100
                cor = cores.get(valor, "#E0E0E0")
                
                col_b.markdown(f"""
                    <div style="background-color: #f0f2f6; border-radius: 10px; width: 100%; height: 12px; margin-top:10px;">
                        <div style="background-color: {cor}; width: {porcentagem}%; height: 12px; border-radius: 10px;"></div>
                    </div>
                """, unsafe_allow_html=True)
                st.divider()

    with st.container(border=True):
        st.subheader("💡 Plano de Ajustes (Agente Arquiteto)")
        for ajuste in ppo.get("Ajustes_Sugeridos", []):
            st.success(ajuste)