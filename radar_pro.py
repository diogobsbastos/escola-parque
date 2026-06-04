import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd
import random
import time
from datetime import datetime
from funcoes_lab import (
    obter_id_video_dlp, 
    obter_stats_video_api, 
    formatar_views
)
from lab_storage import (
    get_valid_youtube_key, 
    load_radar_presets, 
    save_radar_presets, 
    add_new_preset_style,
    delete_preset_style,
    rename_preset_style,
    set_preset_priority,
    load_radar_history,        # [NOVO]
    save_radar_history_item,   # [NOVO]
    delete_radar_history_item  # [NOVO]
)

# ==============================================================================
# LÓGICA DE NEGÓCIO
# ==============================================================================

def validar_artista_customizado(artista, lista_keywords, modo_filtro):
    if modo_filtro == "Ambos (Mix)": return True
    nome = artista.lower()
    for termo in lista_keywords:
        if termo.lower().strip() in nome: return True
    return False

def gerar_estimativa_realista(estilo):
    if estilo in ["Sertanejo", "Piseiro", "Forró"]: return random.randint(140, 168), random.randint(80, 96)
    elif estilo in ["Funk", "Mega Funk"]: return random.randint(130, 150), random.randint(85, 99)
    elif estilo in ["Samba", "Pagode"]: return random.randint(90, 110), random.randint(70, 90)
    elif estilo == "Rock": return random.randint(120, 160), random.randint(70, 90)
    else: return random.randint(110, 130), random.randint(60, 80)

def verificar_data_recente(data_str, filtro_opcao):
    if filtro_opcao == "Qualquer Data" or data_str in ["Data N/A", "Erro API"]: return True
    try:
        dt_video = datetime.strptime(data_str, "%d/%m/%Y")
        hoje = datetime.now()
        diff = (hoje - dt_video).days
        if filtro_opcao == "Último Mês (Tendência)": return diff <= 30
        if filtro_opcao == "Últimos 3 Meses": return diff <= 90
        if filtro_opcao == "Últimos 6 Meses": return diff <= 180
        if filtro_opcao == "Último Ano": return diff <= 365
    except: return True 
    return True

# --- MODAL PARA CRIAR NOVO ESTILO ---
@st.dialog("➕ Criar Novo Estilo de Busca")
def modal_novo_estilo():
    novo_nome = st.text_input("Nome do Estilo (ex: Country, Gospel):")
    if st.button("Criar", type="primary"):
        if novo_nome:
            ok, msg = add_new_preset_style(novo_nome)
            if ok: 
                st.success(msg)
                st.session_state['target_style_index'] = novo_nome
                time.sleep(0.5)
                st.rerun()
            else: st.error(msg)

# ==============================================================================
# RENDER
# ==============================================================================

def render_radar_tab(spotify_id, spotify_secret):
    st.markdown("### 📡 Radar Pro: Caçador de Tendências")
    st.caption("Estratégia: Varredura de Playlists Tops -> Filtragem Inteligente -> Validação YouTube")
    
    # 1. CARREGA PRESETS DO ARQUIVO
    presets_db = load_radar_presets()
    lista_estilos = list(presets_db.keys())
    
    # [NOVO] PAINEL DE HISTÓRICO NO TOPO
    with st.expander("📜 Histórico de Buscas Salvas", expanded=False):
        history = load_radar_history()
        if not history:
            st.info("Nenhuma busca salva ainda.")
        else:
            for item in history:
                c_hist_1, c_hist_2, c_hist_3 = st.columns([4, 2, 1])
                with c_hist_1:
                    st.text(f"📅 {item['data']} | 🎵 {item['estilo']} ({item['qtd']} músicas)")
                with c_hist_2:
                    if st.button("📂 Carregar", key=f"open_{item['id']}", use_container_width=True):
                        st.session_state['radar_resultado'] = pd.DataFrame(item['dados'])
                        st.toast(f"Histórico carregado: {item['estilo']}", icon="✅")
                        time.sleep(0.5)
                        st.rerun()
                with c_hist_3:
                    if st.button("🗑️", key=f"del_{item['id']}", use_container_width=True):
                        delete_radar_history_item(item['id'])
                        st.rerun()
            st.divider()

    # --- LÓGICA DE SELEÇÃO DEFAULT ---
    default_ix = 0
    if 'target_style_index' in st.session_state:
        try:
            target_name = st.session_state['target_style_index']
            if target_name in lista_estilos:
                default_ix = lista_estilos.index(target_name)
        except: pass
        del st.session_state['target_style_index']

    # --- PAINEL PRINCIPAL ---
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([1.5, 1.5, 2, 1]) 
        
        with c1:
            st.markdown("##### 🎵 Presets")
            escolha_estilo = st.selectbox(
                "Gênero Musical:", 
                lista_estilos, 
                index=default_ix,
                label_visibility="collapsed",
                key="sb_estilo_musical"
            )
            filtro_genero = st.selectbox("Filtro de Voz:", ["Ambos (Mix)", "Voz Masculina", "Voz Feminina"], label_visibility="collapsed")

        with c2:
            st.markdown("##### 📅 Recência")
            filtro_tempo = st.selectbox(
                "Lançamento:",
                options=["Qualquer Data", "Último Ano", "Últimos 6 Meses", "Últimos 3 Meses", "Último Mês (Tendência)"],
                index=2,
                label_visibility="collapsed"
            )
            
        with c3:
            st.markdown("##### 🔥 Popularidade")
            mapa_views = {
                "Sem Filtro": 0, "100k+": 100_000, "500k+": 500_000, "1M+": 1_000_000,
                "5M+": 5_000_000, "10M+": 10_000_000, "50M+": 50_000_000, "100M+": 100_000_000
            }
            label_views = st.select_slider(
                "Mínimo de Views:", options=list(mapa_views.keys()), value="100k+", label_visibility="collapsed"
            )
            min_views_val = mapa_views[label_views]

        with c4:
            st.markdown("##### 🎯 Meta")
            meta_musicas = st.number_input("Qtd:", min_value=5, max_value=50, value=20, step=5, label_visibility="collapsed")

    # --- ÁREA DE CUSTOMIZAÇÃO AVANÇADA ---
    with st.expander(f"🛠️ Editar Preset: {escolha_estilo} (Clique para expandir)", expanded=False):
        
        if 'estilo_anterior' not in st.session_state:
            st.session_state['estilo_anterior'] = escolha_estilo
        
        if escolha_estilo != st.session_state['estilo_anterior']:
            st.session_state['estilo_anterior'] = escolha_estilo
            keys_to_clear = [k for k in st.session_state.keys() if k.startswith("pl_") or k.startswith("art_") or k.startswith("name_")]
            for k in keys_to_clear: del st.session_state[k]
            st.rerun()

        dados_estilo = presets_db.get(escolha_estilo, {})
        
        # UI Edição
        novo_nome_estilo = st.text_input("Nome do Estilo (Edite para renomear):", value=escolha_estilo, key=f"name_{escolha_estilo}")
        
        # CHECKBOX DEFAULT
        is_current_first = (lista_estilos[0] == escolha_estilo) if lista_estilos else False
        check_default = st.checkbox("⭐ Definir como Padrão (Primeiro da Lista)", value=is_current_first, key=f"chk_def_{escolha_estilo}")

        c_edit_pl, c_edit_art = st.columns(2)
        
        with c_edit_pl:
            st.markdown("**🔍 Termos de Busca (Playlists)**")
            st.caption(f"Playlists que o robô vai caçar.")
            playlists_atuais = "\n".join(dados_estilo.get('playlists', []))
            key_pl = f"pl_{escolha_estilo}" 
            txt_playlists = st.text_area("Uma por linha:", value=playlists_atuais, height=200, key=key_pl)
        
        with c_edit_art:
            st.markdown(f"**🎤 Filtro de Nome: {filtro_genero}**")
            texto_artistas_padrao = ""
            disabled_art = True
            chave_json = ""
            
            if filtro_genero == "Voz Masculina":
                texto_artistas_padrao = "\n".join(dados_estilo.get('masculinos', []))
                disabled_art = False; chave_json = 'masculinos'; st.caption("Filtro Voz Masculina.")
            elif filtro_genero == "Voz Feminina":
                texto_artistas_padrao = "\n".join(dados_estilo.get('femininos', []))
                disabled_art = False; chave_json = 'femininos'; st.caption("Filtro Voz Feminina.")
            else:
                st.caption("Filtro desligado no modo 'Mix' (Busca tudo).")

            key_art = f"art_{escolha_estilo}_{filtro_genero}"
            txt_artistas = st.text_area("Palavras-chave (Artistas):", value=texto_artistas_padrao, height=200, disabled=disabled_art, key=key_art)

        # BOTÕES DE AÇÃO
        c_save, c_new, c_del = st.columns([2, 2, 1])
        
        with c_save:
            if st.button(f"💾 Salvar Alterações", type="primary", use_container_width=True):
                # 1. Renomear
                nome_final = escolha_estilo
                if novo_nome_estilo.strip() != escolha_estilo:
                    ok_rename, msg_rename = rename_preset_style(escolha_estilo, novo_nome_estilo)
                    if not ok_rename:
                        st.error(msg_rename)
                        st.stop()
                    else:
                        nome_final = novo_nome_estilo
                        presets_db = load_radar_presets() 

                # 2. Atualizar Dados
                novas_playlists = [t.strip() for t in txt_playlists.split('\n') if t.strip()]
                presets_db[nome_final]['playlists'] = novas_playlists
                
                if chave_json:
                    novos_artistas = [t.strip().lower() for t in txt_artistas.split('\n') if t.strip()]
                    presets_db[nome_final][chave_json] = novos_artistas
                
                # 3. Salvar
                if save_radar_presets(presets_db):
                    # 4. Definir Prioridade
                    if check_default:
                        set_preset_priority(nome_final)
                        
                    st.toast(f"Preset '{nome_final}' salvo!", icon="✅")
                    st.session_state['target_style_index'] = nome_final
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Erro ao salvar arquivo.")

        with c_new:
            if st.button("➕ Criar Novo Estilo", use_container_width=True):
                modal_novo_estilo()
                
        with c_del:
            if st.button("🗑️", help="Apagar este estilo", use_container_width=True):
                if delete_preset_style(escolha_estilo):
                    st.success("Estilo apagado com sucesso!")
                    if 'estilo_anterior' in st.session_state: del st.session_state['estilo_anterior']
                    if 'target_style_index' in st.session_state: del st.session_state['target_style_index']
                    keys_to_clear = [k for k in st.session_state.keys() if k.startswith("pl_") or k.startswith("art_") or k.startswith("name_")]
                    for k in keys_to_clear: del st.session_state[k]
                    time.sleep(0.5)
                    st.rerun()

    # --- BOTÃO DE BUSCA ---
    st.write("")
    btn_buscar = st.button(f"🚀 INICIAR VARREDURA EM '{escolha_estilo.upper()}'", type="primary", use_container_width=True)

    # --- LÓGICA DE EXECUÇÃO ---
    if btn_buscar:
        if 'radar_resultado' in st.session_state: del st.session_state['radar_resultado']
        
        termos_busca_finais = [t.strip() for t in txt_playlists.split('\n') if t.strip()]
        keywords_artistas_finais = []
        if filtro_genero != "Ambos (Mix)":
            keywords_artistas_finais = [k.strip().lower() for k in txt_artistas.split('\n') if k.strip()]

        yt_api_key = get_valid_youtube_key()
        if not yt_api_key: st.warning("⚠️ Modo Cego (Sem YT API)."); min_views_val = 0 
        
        if not spotify_id or not spotify_secret: st.error("❌ Configure o Spotify."); st.stop()

        try:
            auth = SpotifyClientCredentials(client_id=spotify_id, client_secret=spotify_secret)
            sp = spotipy.Spotify(auth_manager=auth)
        except: st.error("Erro Spotify."); st.stop()

        status_box = st.status("📡 Iniciando radar...", expanded=True)
        
        try:
            status_box.write(f"🔎 Buscando playlists: {len(termos_busca_finais)} termos...")
            playlists_candidatas = []
            for termo in termos_busca_finais:
                try:
                    res = sp.search(q=termo, type='playlist', limit=3)
                    if res['playlists']['items']: playlists_candidatas.extend(res['playlists']['items'])
                except: continue
            
            playlists_unicas = {p['id']: p for p in playlists_candidatas if p}.values()
            if not playlists_unicas: st.error("Nenhuma playlist encontrada."); st.stop()
                
            status_box.write(f"✅ {len(playlists_unicas)} playlists carregadas. Filtrando...")
            
            tabela_final = []
            musicas_vistas = set() 
            total_analisadas = 0
            limit_analise = 600 
            
            progresso = status_box.empty()
            log_rejeicoes = st.expander("👁️ Log de Rejeições (Detalhado)", expanded=False)
            logs = []
            
            for idx_pl, playlist in enumerate(playlists_unicas):
                if len(tabela_final) >= meta_musicas: break
                if total_analisadas >= limit_analise: break
                
                status_box.write(f"💿 Playlist {idx_pl+1}: **{playlist['name']}**")
                try: res = sp.playlist_tracks(playlist['id'], limit=50)
                except: continue
                if not res['items']: continue
                
                dados_lote = []
                ids_lote = []
                for item in res['items']:
                    if item.get('track') and item['track'].get('id'):
                        t = item['track']
                        artist = t['artists'][0]['name'] if t['artists'] else "Desconhecido"
                        nome_track = t['name']
                        
                        chave_unica = f"{nome_track} - {artist}".lower()
                        if chave_unica in musicas_vistas: continue 
                        musicas_vistas.add(chave_unica)
                        
                        if filtro_genero != "Ambos (Mix)":
                            if not validar_artista_customizado(artist, keywords_artistas_finais, filtro_genero):
                                continue
                            
                        ids_lote.append(t['id'])
                        dados_lote.append({'Nome': nome_track, 'Artista': artist, 'ID': t['id']})
                
                if not dados_lote: continue

                feats_map = {}
                try:
                    lote_feats = sp.audio_features(ids_lote)
                    for k, f in enumerate(lote_feats):
                        if f: feats_map[ids_lote[k]] = f
                except: pass
                
                for d in dados_lote:
                    if len(tabela_final) >= meta_musicas: break 
                    if total_analisadas >= limit_analise: break
                    
                    total_analisadas += 1
                    progresso.progress(min(len(tabela_final) / meta_musicas, 1.0), text=f"Aprovadas: {len(tabela_final)}/{meta_musicas} | Analisando: {d['Nome']}...")
                    
                    nome_limpo = d['Nome'].split('(')[0].split('-')[0].strip()
                    info_dlp = obter_id_video_dlp(f"{nome_limpo} {d['Artista']} audio")
                    if not info_dlp: info_dlp = obter_id_video_dlp(f"{nome_limpo} {d['Artista']}")
                    
                    if not info_dlp:
                        logs.append(f"⚠️ Não encontrado no YT: {d['Nome']}")
                        continue 

                    if yt_api_key:
                        views, data_fmt = obter_stats_video_api(yt_api_key, info_dlp['id'])
                        if views < min_views_val:
                            logs.append(f"📉 {d['Nome']}: {formatar_views(views)} views (Abaixo de {label_views})")
                            if len(logs) > 5: log_rejeicoes.text("\n".join(logs[-5:]))
                            continue 
                        
                        if not verificar_data_recente(data_fmt, filtro_tempo):
                            logs.append(f"📅 {d['Nome']}: Data antiga ({data_fmt})")
                            if len(logs) > 5: log_rejeicoes.text("\n".join(logs[-5:]))
                            continue

                        views_display = formatar_views(views)
                        link = info_dlp['link']
                    else:
                        link, data_fmt, views_display = info_dlp['link'], "N/A", "N/A (Modo Cego)"
                    
                    f = feats_map.get(d['ID'])
                    if f: bpm, energy = round(f['tempo']), int(f['energy'] * 100)
                    else: bpm, energy = gerar_estimativa_realista(escolha_estilo)
                    
                    genero_prompt = "voz masculina" if filtro_genero == "Voz Masculina" else "voz feminina" if filtro_genero == "Voz Feminina" else "dueto"
                    if energy > 80: mood = "Explosão/Festa"
                    elif energy > 50: mood = "Animada"
                    else: mood = "Acústico/Sentimental"
                    
                    prompt = f"Estilo {escolha_estilo}, {bpm} BPM, {mood}, {genero_prompt}, vibe {d['Artista']}"
                    
                    tabela_final.append({
                        "Música": d['Nome'], "Artista": d['Artista'], "Views": views_display,
                        "Lançamento": data_fmt, "BPM": bpm, "Energia": energy,
                        "Link": link, "Prompt": prompt
                    })

            progresso.progress(1.0, text="Finalizado!")
            
            if not tabela_final:
                status_box.update(label="Nenhuma música passou nos filtros.", state="error")
                st.warning(f"Analisamos {total_analisadas} músicas. Ajuste os filtros.")
            else:
                status_box.update(label=f"🎯 Sucesso! {len(tabela_final)} músicas encontradas.", state="complete", expanded=False)
                st.session_state['radar_resultado'] = pd.DataFrame(tabela_final)
            
        except Exception as e: st.error(f"Erro Crítico: {e}")

    # --- RESULTADOS ---
    if 'radar_resultado' in st.session_state:
        df = st.session_state['radar_resultado']
        st.divider()
        c_res_header, c_res_save = st.columns([3, 1])
        with c_res_header:
            st.markdown(f"#### 🏆 Top {len(df)} Oportunidades")
        with c_res_save:
            # [NOVO] BOTÃO DE SALVAR NO HISTÓRICO
            if st.button("💾 Salvar Busca", use_container_width=True):
                if save_radar_history_item(escolha_estilo, len(df), df.to_dict('records')):
                    st.toast("Busca salva no Histórico!", icon="📂")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Erro ao salvar histórico.")
        
        event = st.dataframe(
            df, on_select="rerun", selection_mode="single-row",
            column_config={
                "Link": st.column_config.LinkColumn("YouTube", display_text="▶️ Play"),
                "Energia": st.column_config.ProgressColumn("Vibe", format="%d%%", min_value=0, max_value=100),
                "Prompt": st.column_config.TextColumn("Prompt IA", width="large"),
                "Views": st.column_config.TextColumn("Audiência", help="No YouTube"),
            },
            use_container_width=True, height=(len(df) * 35) + 38, hide_index=True
        )
        
        if len(event.selection.rows) > 0:
            idx = event.selection.rows[0]
            musica = df.iloc[idx]
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.success(f"**{musica['Música']}** - {musica['Artista']}")
                    st.caption(musica['Prompt'])
                with c2:
                    if st.button("🚀 ENVIAR PARA NOVO TRABALHO", type="primary", use_container_width=True):
                        st.session_state['pacote_radar'] = {
                            "link": musica['Link'],
                            "titulo": f"{musica['Música']} - {musica['Artista']}",
                            "prompt_tecnico": musica['Prompt']
                        }
                        st.session_state['view_mode'] = 'editor' 
                        st.session_state['projeto_ativo'] = None
                        st.rerun()