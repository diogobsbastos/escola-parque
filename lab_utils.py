import requests
import spotipy
import time
import random
import re
from spotipy.oauth2 import SpotifyClientCredentials
from datetime import datetime, timedelta
from yt_dlp import YoutubeDL

# --- FORMATADORES ---
def formatar_views(num):
    try:
        n = int(num)
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M".replace(".0M", "M")
        elif n >= 1_000: return f"{n/1_000:.0f}K"
        return str(n)
    except: return "0"

# --- TESTES ---
def testar_conexao_url(url: str):
    if not url.startswith("http"): return False, "URL inválida"
    try:
        if requests.get(url, timeout=5).status_code == 200: return True, "OK"
        return False, "Erro status"
    except Exception as e: return False, str(e)

def testar_conexao_spotify(client_id, client_secret):
    if not client_id or not client_secret: return False, "Sem chaves"
    try:
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id.strip(), client_secret=client_secret.strip()))
        sp.search(q="teste", limit=1)
        return True, "Spotify OK! 🟢"
    except Exception as e: return False, f"Erro Spotify: {e}"

def testar_conexao_youtube_api(api_key):
    """
    Testa a chave e retorna (Sucesso: bool, Mensagem: str, Motivo: str)
    """
    if not api_key: return False, "Sem chave", "empty"
    
    # URL de teste leve
    url = f"https://www.googleapis.com/youtube/v3/videos?part=id&id=Ks-_Mh1QhMc&key={api_key.strip()}" 
    
    try:
        res = requests.get(url, timeout=5)
        
        if res.status_code == 200: 
            return True, "Chave Ativa e Funcionando! 🟢", "ok"
        
        try: erro_json = res.json().get('error', {})
        except: erro_json = {}
        
        mensagem = erro_json.get('message', 'Erro desconhecido')
        code = erro_json.get('code', res.status_code)
        
        if code == 403:
            if "quota" in mensagem.lower():
                return False, "Cota Excedida (403)", "quota"
            return False, f"Acesso Negado (403): {mensagem}", "forbidden"
            
        if code == 400:
            return False, "Chave Inválida (400)", "invalid"
            
        return False, f"Erro {code}: {mensagem}", "error"
        
    except Exception as e: 
        return False, f"Erro Conexão: {e}", "connection"

# --- ESTRATÉGIA HÍBRIDA (AGRESSIVA) ---

def obter_id_video_dlp(termo_busca):
    """
    PASSO 1: Busca o ID usando Scraping (yt_dlp).
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'default_search': 'ytsearch1',
        'socket_timeout': 10,
    }
    
    # Tentativa 1: Busca exata
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(termo_busca, download=False)
            if 'entries' in info and info['entries']:
                video = info['entries'][0]
                return {
                    'id': video['id'],
                    'titulo': video.get('title', 'N/A'),
                    'link': f"https://www.youtube.com/watch?v={video['id']}",
                    'data_raw': video.get('upload_date')
                }
    except Exception:
        pass
    
    # Tentativa 2: Fallback (Se falhar, tenta limpar o termo)
    if " audio" in termo_busca:
        termo_limpo = termo_busca.replace(" audio", "")
        try:
            with YoutubeDL(ydl_opts) as ydl:
                time.sleep(0.5) # Respiro
                info = ydl.extract_info(termo_limpo, download=False)
                if 'entries' in info and info['entries']:
                    video = info['entries'][0]
                    return {
                        'id': video['id'],
                        'titulo': video.get('title', 'N/A'),
                        'link': f"https://www.youtube.com/watch?v={video['id']}",
                        'data_raw': video.get('upload_date')
                    }
        except:
            pass
    
    return None

def obter_stats_video_api(api_key, video_id):
    """
    PASSO 2: Pega Views e Data Real via API.
    """
    if not api_key: return 0, "Data N/A"
    
    url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={video_id}&key={api_key}"
    
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            dados = res.json()
            if "items" in dados and dados["items"]:
                item = dados["items"][0]
                
                # Views
                views = int(item["statistics"].get("viewCount", 0))
                
                # Data
                raw_date = item["snippet"]["publishedAt"]
                try:
                    dt = datetime.strptime(raw_date, "%Y-%m-%dT%H:%M:%SZ")
                    data_fmt = dt.strftime("%d/%m/%Y")
                except: data_fmt = raw_date[:10]
                
                return views, data_fmt
    except:
        pass
    
    return 0, "Erro API"

def buscar_youtube_via_api(api_key, termo_busca, filtro_data=""):
    """Legacy."""
    return None, None, None, 0

# --- [NOVA FUNÇÃO] PROCESSAMENTO DE TEXTO ---

def extrair_resumo_tecnico(texto_ia):
    """
    Analisa o retorno da IA para extrair Estilo e BPM de forma limpa.
    """
    if not texto_ia or not isinstance(texto_ia, str):
        return "N/A", "N/A"
    
    estilo = "Gênero não detectado"
    bpm = "N/A"
    
    try:
        # Busca Estilo 
        match_estilo = re.search(r"Estilo:\s*([^,\n\r]*)", texto_ia, re.IGNORECASE)
        if match_estilo:
            estilo = match_estilo.group(1).strip()
            
        # Busca BPM 
        match_bpm = re.search(r"BPM:\s*(\d+)", texto_ia, re.IGNORECASE)
        if match_bpm:
            bpm = match_bpm.group(1).strip()
    except:
        pass
        
    return estilo, bpm

# --- NOVAS FUNÇÕES PARA O FISCAL DE CANAIS (COM LOOP PROGRESSIVO) ---

def extrair_ultimos_videos_canal_dlp(url_canal, qtd_videos=10, ordem="recentes", min_views_target=0):
    """
    Busca videos do canal.
    
    LOGICA DE LOOP: 
    Se 'min_views_target' > 0 (ex: 100M+), o script vai tentar buscar blocos maiores
    (50 -> 100 -> 200 -> 400) até encontrar a quantidade 'qtd_videos' que atenda 
    ao critério de visualizações.
    """
    from yt_dlp import YoutubeDL 

    # Definição dos níveis de profundidade (Loop de busca)
    # Se não achar no primeiro nível, tenta o próximo.
    niveis_busca = [50, 100, 200, 400]
    
    # Se não tiver filtro de views, busca apenas o nível básico para ser rápido
    if min_views_target == 0:
        niveis_busca = [max(qtd_videos * 3, 50)]

    videos_candidatos = []
    
    # Preparação da URL
    url_base = url_canal.strip().rstrip('/')
    
    if ordem == 'populares':
        if "/videos" not in url_base:
            url_busca = f"{url_base}/videos?view=0&sort=p"
        else:
            url_busca = f"{url_base}?view=0&sort=p"
    else:
        if "/videos" not in url_base and "/shorts" not in url_base:
            url_busca = f"{url_base}/videos"
        else:
            url_busca = url_base

    # LOOP DE MINERAÇÃO
    for limite_atual in niveis_busca:
        
        ydl_opts = {
            'extract_flat': True, 
            'playlistend': limite_atual, 
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url_busca, download=False)
                
                temp_videos = []
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry:
                            v_count = entry.get('view_count')
                            if v_count is None: v_count = 0
                            
                            temp_videos.append({
                                'id': entry.get('id'),
                                'titulo': entry.get('title'),
                                'url': f"https://www.youtube.com/watch?v={entry.get('id')}",
                                'pre_views': int(v_count) # Guardamos para ordenar e filtrar
                            })
                
                # Se for populares, reordena para garantir
                if ordem == 'populares':
                    temp_videos.sort(key=lambda x: x['pre_views'], reverse=True)

                # VERIFICAÇÃO DE META (LOOP)
                if min_views_target > 0:
                    # Filtra apenas os que superam a meta
                    validos = [v for v in temp_videos if v['pre_views'] >= min_views_target]
                    
                    # Se já achamos a quantidade que o usuário pediu, ou se estamos no último nível
                    if len(validos) >= qtd_videos or limite_atual == niveis_busca[-1]:
                        # Retorna os top X válidos
                        return validos[:qtd_videos]
                    
                    # Se não achou, o loop continua para o próximo nível (busca mais profunda)
                    continue 
                else:
                    # Sem meta de views, retorna o que achou no primeiro nível
                    return temp_videos[:qtd_videos]

        except Exception as e:
            print(f"Erro no scrape do canal {url_canal}: {e}")
            break
            
    # Se sair do loop sem retornar, retorna o que tiver (fallback)
    return []

def obter_detalhes_video_api_rotativa(lista_videos, get_key_func, mark_exhausted_func):
    """
    Pega estatísticas detalhadas usando rotação de chaves.
    """
    import requests
    from datetime import datetime
    
    dados_completos = []
    
    if not lista_videos:
        return [], "Nenhum vídeo encontrado para processar."

    # Processa em lotes de 50
    for i in range(0, len(lista_videos), 50):
        lote = lista_videos[i:i+50]
        ids_lote = ",".join([v['id'] for v in lote])
        
        sucesso_lote = False
        tentativas = 0
        
        while not sucesso_lote and tentativas < 5:
            api_key = get_key_func()
            if not api_key: return dados_completos, "Sem chaves API disponíveis."
            
            url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id={ids_lote}&key={api_key}"
            
            try:
                res = requests.get(url, timeout=10)
                
                if res.status_code == 403:
                    erro_msg = res.json().get('error', {}).get('message', '')
                    if 'quota' in erro_msg.lower():
                        mark_exhausted_func(api_key) 
                        tentativas += 1
                        continue 
                
                if res.status_code == 200:
                    data = res.json()
                    for item in data.get('items', []):
                        stats = item['statistics']
                        snippet = item['snippet']
                        
                        pub_date_str = snippet['publishedAt']
                        try:
                            pub_date = datetime.strptime(pub_date_str, "%Y-%m-%dT%H:%M:%SZ")
                        except:
                            pub_date = datetime.now()

                        dias_atras = (datetime.now() - pub_date).days
                        
                        dados_completos.append({
                            "Thumb": snippet['thumbnails']['default']['url'],
                            "Música": snippet['title'],
                            "Artista": snippet['channelTitle'],
                            "Views": int(stats.get('viewCount', 0)),
                            "Likes": int(stats.get('likeCount', 0)),
                            "Comentários": int(stats.get('commentCount', 0)),
                            "Data": pub_date.strftime("%d/%m/%Y"),
                            "Dias": dias_atras,
                            "Link": f"https://www.youtube.com/watch?v={item['id']}",
                            "ID": item['id']
                        })
                    sucesso_lote = True
                else:
                    break 
            except:
                break
                
    return dados_completos, "Sucesso"