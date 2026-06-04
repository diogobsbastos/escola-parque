import streamlit as st
import pandas as pd
import time
from datetime import datetime
from lab_storage import (
    load_monitored_channels, save_monitored_channels, 
    get_valid_youtube_key, mark_key_as_exhausted,
    load_fiscal_history, save_fiscal_history_item, delete_fiscal_history_item
)
from lab_utils import extrair_ultimos_videos_canal_dlp, obter_detalhes_video_api_rotativa, formatar_views

def render_fiscal_tab():
    st.markdown("### 🕵️ Fiscal de Canais (Hunter)")
    st.caption("Monitoramento automatizado de concorrência com detecção de Outliers.")

    # --- 0. HISTÓRICO DE BUSCAS ---
    with st.expander("📜 Histórico de Análises Salvas", expanded=False):
        history = load_fiscal_history()
        if not history:
            st.info("Nenhuma análise salva ainda.")
        else:
            for item in history:
                c_h1, c_h2, c_h3 = st.columns([4, 2, 1])
                with c_h1:
                    st.text(f"📁 {item['nome']} ({item['data']})")
                    # Tenta pegar os filtros salvos, se existirem (retrocompatibilidade)
                    f_dias = item.get('filtro_dias', 'N/A')
                    f_views = item.get('filtro_views', 'N/A')
                    st.caption(f"Diretriz: {item['modo']} | 📅 {f_dias} | 👁️ {f_views} | {len(item['dados'])} vídeos")
                with c_h2:
                    if st.button("📂 Abrir", key=f"load_fisc_{item['id']}", use_container_width=True):
                        st.session_state['resultado_fiscal_raw'] = pd.DataFrame(item['dados'])
                        st.toast(f"Análise '{item['nome']}' carregada!", icon="✅")
                        time.sleep(0.5)
                        st.rerun()
                with c_h3:
                    if st.button("🗑️", key=f"del_fisc_{item['id']}", use_container_width=True):
                        delete_fiscal_history_item(item['id'])
                        st.rerun()
            st.divider()

    # --- 1. CONFIGURAÇÃO DOS CANAIS ---
    with st.expander("📺 Gerenciar Canais Monitorados", expanded=False):
        canais_atuais = load_monitored_channels()
        texto_canais = "\n".join(canais_atuais)
        
        novo_texto = st.text_area(
            "Cole os links dos canais (um por linha):", 
            value=texto_canais, 
            height=150,
            placeholder="https://www.youtube.com/@CanalExemplo"
        )
        
        if st.button("💾 Salvar Lista de Canais"):
            lista = novo_texto.split("\n")
            if save_monitored_channels(lista):
                st.success(f"Lista atualizada com {len([x for x in lista if x.strip()])} canais.")
                time.sleep(1)
                st.rerun()

    # --- 2. ESTRATÉGIA E FILTROS ---
    with st.container(border=True):
        st.markdown("##### 🎯 Estratégia de Varredura")
        
        # LINHA 1: MODO DE BUSCA
        c_mode, c_qtd = st.columns([2, 1])
        with c_mode:
            modo_busca = st.selectbox(
                "O que buscar?", 
                ["Mais Populares (Em Alta/Hits)", "Mais Recentes (Novidades)"],
                index=0, 
                help="Recentes: O que postaram agora.\nPopulares: Busca os maiores hits."
            )
            # Define a variável técnica para passar pro backend
            ordem_api = "populares" if "Populares" in modo_busca else "recentes"
            
        with c_qtd:
            qtd_por_canal = st.number_input("Qtd. vídeos por canal:", min_value=5, max_value=50, value=10)

        st.divider()
        st.markdown("##### 🔍 Filtros de Exibição (Pós-Coleta)")
        
        # LINHA 2: FILTROS VISUAIS
        c2, c3, c4 = st.columns(3)
        with c2:
            filtro_dias = st.selectbox("Janela de Tempo:", 
                [
                    "Todo o Período (Sem Filtro)", 
                    "Últimos 30 Dias", 
                    "Últimos 90 Dias", 
                    "Últimos 6 Meses", 
                    "Últimos 12 Meses", 
                    "Apenas Antigos (> 1 Ano)"
                ], 
                index=0,
                help="Todo o Período: Mostra tudo.\nApenas Antigos: Esconde vídeos com menos de 1 ano."
            )
            
        with c3:
            # [ATUALIZADO] LISTA COMPLETA DE OPÇÕES DE VIEWS (INCLUINDO 10M, 50M, 100M)
            opcoes_views = [
                "Sem Filtro", 
                "50k+", "100k+", "500k+", 
                "1M+", "5M+", "10M+", "50M+", "100M+"
            ]
            filtro_views = st.selectbox("Mínimo de Views:", opcoes_views, index=4) 
            
        with c4:
            detectar_outliers = st.toggle("Destacar Outliers 🌟", value=True)

    # --- 3. BOTÃO DE AÇÃO ---
    st.divider()
    
    label_btn = "🚀 BUSCAR HITS (EM ALTA)" if ordem_api == "populares" else "🚀 BUSCAR NOVIDADES"
    
    if st.button(label_btn, type="primary", use_container_width=True):
        canais = load_monitored_channels()
        if not canais:
            st.warning("Adicione canais na lista acima primeiro.")
            st.stop()
            
        status = st.status(f"Iniciando modo: {modo_busca}...", expanded=True)
        all_videos_raw = []
        
        # --- PREPARAÇÃO DO ALVO PARA O MINERADOR ---
        # Converte a seleção do filtro em número para ativar o Loop Inteligente no backend
        # Isso garante que se o usuário pediu 100M+, o robô vai cavar até achar.
        mapa_views_scrape = {
            "Sem Filtro": 0, "50k+": 50_000, "100k+": 100_000, "500k+": 500_000,
            "1M+": 1_000_000, "5M+": 5_000_000, "10M+": 10_000_000, 
            "50M+": 50_000_000, "100M+": 100_000_000
        }
        # Só ativa o alvo se estiver buscando por populares, para evitar travar em recentes
        alvo_views = mapa_views_scrape.get(filtro_views, 0) if ordem_api == "populares" else 0

        # FASE 1: RASPAGEM (SEM GASTAR API)
        progresso_geral = status.progress(0, text="Minerando hits (pode demorar um pouco se o filtro for alto)...")
        
        for i, canal in enumerate(canais):
            status.write(f"📡 Acessando canal {i+1}/{len(canais)}: {canal}...")
            
            # Backend usa o Loop Inteligente (configurado no lab_utils.py)
            # Ele vai tentar buscar até encontrar a quantidade pedida que atenda ao 'alvo_views'
            vids = extrair_ultimos_videos_canal_dlp(
                canal, 
                qtd_por_canal, 
                ordem=ordem_api, 
                min_views_target=alvo_views
            )
            
            all_videos_raw.extend(vids)
            progresso_geral.progress(int((i+1)/len(canais) * 50), text=f"Lendo canais: {int((i+1)/len(canais)*100)}%")
        
        status.write(f"✅ Encontrados {len(all_videos_raw)} vídeos potenciais. Buscando estatísticas precisas via API...")
        
        # FASE 2: API COM ROTAÇÃO (ESTATÍSTICAS)
        dados_finais, msg = obter_detalhes_video_api_rotativa(
            all_videos_raw, 
            get_valid_youtube_key, 
            mark_key_as_exhausted
        )
        
        progresso_geral.progress(100, text="Finalizado!")
        
        if not dados_finais:
            status.update(label="Erro na coleta de dados API.", state="error")
            st.error(msg)
        else:
            status.update(label="Fiscalização Concluída!", state="complete", expanded=False)
            st.session_state['resultado_fiscal_raw'] = pd.DataFrame(dados_finais)

    # --- 4. EXIBIÇÃO E PROCESSAMENTO DOS DADOS ---
    if 'resultado_fiscal_raw' in st.session_state:
        df_full = st.session_state['resultado_fiscal_raw']
        
        # --- LÓGICA DE FILTRAGEM ---
        df_show = df_full.copy()
        
        # 1. Filtro de Data
        mask_data = pd.Series([True] * len(df_show), index=df_show.index)
        motivo_rejeicao = "Data"

        if "30 Dias" in filtro_dias:
            mask_data = df_show['Dias'] <= 30
            motivo_rejeicao = "> 30 Dias"
        elif "90 Dias" in filtro_dias:
            mask_data = df_show['Dias'] <= 90
            motivo_rejeicao = "> 90 Dias"
        elif "6 Meses" in filtro_dias:
            mask_data = df_show['Dias'] <= 180
            motivo_rejeicao = "> 6 Meses"
        elif "12 Meses" in filtro_dias:
            mask_data = df_show['Dias'] <= 365
            motivo_rejeicao = "> 1 Ano"
        elif "Apenas Antigos" in filtro_dias: 
            mask_data = df_show['Dias'] > 365
            motivo_rejeicao = "Recente (< 1 Ano)"
        
        df_hidden_data = df_show[~mask_data].copy()
        df_hidden_data['Motivo'] = f"Data ({motivo_rejeicao})"
        
        df_show = df_show[mask_data]
        
        # 2. Filtro de Views [ATUALIZADO: MAPEAMENTO EXATO]
        mapa_views = {
            "Sem Filtro": 0,
            "50k+": 50_000,
            "100k+": 100_000,
            "500k+": 500_000,
            "1M+": 1_000_000,
            "5M+": 5_000_000,
            "10M+": 10_000_000,
            "50M+": 50_000_000,
            "100M+": 100_000_000
        }
        
        min_v = mapa_views.get(filtro_views, 0)
        
        mask_views = df_show['Views'] >= min_v
        df_hidden_views = df_show[~mask_views].copy()
        # Formatação segura para o motivo
        def safe_fmt(v):
            try: return formatar_views(v)
            except: return str(v)

        df_hidden_views['Motivo'] = df_hidden_views['Views'].apply(lambda v: f"Views {safe_fmt(v)} (< {safe_fmt(min_v)})")
        
        df_show = df_show[mask_views]

        df_hidden = pd.concat([df_hidden_data, df_hidden_views])

        # 3. Métricas Avançadas
        if not df_show.empty:
            # Engajamento
            df_show['Engajamento'] = ((df_show['Likes'] + df_show['Comentários']) / df_show['Views']) * 100
            df_show['Engajamento'] = df_show['Engajamento'].fillna(0)

            # Velocidade
            dias_seguro = df_show['Dias'].replace(0, 1)
            df_show['Velocidade'] = df_show['Views'] / dias_seguro

        # 4. Análise de Outliers
        df_show['Outlier'] = False
        if detecting_outliers := detectar_outliers:
            if not df_show.empty:
                medias = df_show.groupby('Artista')['Views'].transform('mean')
                df_show.loc[df_show['Views'] > (medias * 2), 'Outlier'] = True

        # Ordenação Final
        df_show = df_show.sort_values(by=['Outlier', 'Views'], ascending=[False, False])
        
        # --- DASHBOARD DE RESULTADOS ---
        st.divider()
        
        # BOTÃO DE SALVAR BUSCA
        c_res_info, c_res_save = st.columns([3, 1])
        with c_res_info:
            m1, m2, m3 = st.columns(3)
            m1.metric("🌐 Total Coletado", len(df_full))
            m2.metric("👁️ Exibidos na Tabela", len(df_show))
            m3.metric("🗑️ Ocultos pelos Filtros", len(df_hidden))
        
        with c_res_save:
            with st.popover("💾 Salvar Análise"):
                nome_analise = st.text_input("Nome da Análise:", value=f"Busca {modo_busca} - {datetime.now().strftime('%H:%M')}")
                if st.button("Confirmar Salvar", type="primary", use_container_width=True):
                    # [CORREÇÃO] Passando os 5 argumentos exigidos (resolve o TypeError)
                    if save_fiscal_history_item(nome_analise, modo_busca, df_show.to_dict('records'), filtro_dias, filtro_views):
                        st.toast("Análise Salva!", icon="💾")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Erro ao salvar.")

        st.subheader(f"📊 Relatório de Performance")
        
        st.dataframe(
            df_show,
            column_config={
                "Thumb": st.column_config.ImageColumn("Capa", width="small"),
                "Link": st.column_config.LinkColumn("Abrir 🔗", display_text="Assistir"),
                "Views": st.column_config.NumberColumn("Visualizações", format="%d"),
                "Velocidade": st.column_config.NumberColumn("🚀 Views/Dia", format="%d"),
                
                "Engajamento": st.column_config.ProgressColumn(
                    "❤️ %", 
                    format="%.2f%%", 
                    min_value=0, 
                    max_value=10, 
                    width="small", 
                    help="Taxa de interação (Likes+Coments / Views)"
                ),
                
                "Outlier": st.column_config.CheckboxColumn("🔥 Outlier?", disabled=True),
                "Dias": st.column_config.NumberColumn("Dias de Vida", format="%d dias"),
            },
            use_container_width=True,
            hide_index=True,
            height=600
        )

        # --- DEBUG ---
        if not df_hidden.empty:
            with st.expander(f"🕵️ Ver {len(df_hidden)} Vídeos Ocultos (Debug)", expanded=False):
                st.caption("Estes vídeos foram coletados mas escondidos pelos filtros de Data ou Views.")
                st.dataframe(
                    df_hidden[['Motivo', 'Música', 'Artista', 'Views', 'Dias']],
                    use_container_width=True,
                    hide_index=True
                )