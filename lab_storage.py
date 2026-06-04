import os
import json
import time
from datetime import datetime

# --- ARQUIVOS DE CONFIGURAÇÃO ---
KEY_FILE = "gemini_key.txt"
HISTORY_FILE = "historico_sertanejo.json"
LYRICS_URL_FILE = "lyrics_url.txt" 
MODEL_PREF_FILE = "model_pref.txt" 
CONTEXT_FILE = "contexto_duda.txt" 
SPOTIFY_FILE = "spotify_keys.json"
YOUTUBE_KEYS_JSON = "youtube_keys_pool.json" 
RADAR_PRESETS_FILE = "radar_presets.json" 
RADAR_HISTORY_FILE = "radar_history.json" 
FISCAL_CHANNELS_FILE = "canais_fiscalizados.json"
FISCAL_HISTORY_FILE = "fiscal_history.json" 

# ==============================================================================
# 1. GERENCIAMENTO DE PRESETS DO RADAR (ESTILOS E TERMOS)
# ==============================================================================

def get_default_presets():
    """Retorna os presets originais do sistema com as 10 Melhores Buscas por estilo."""
    return {
        "Sertanejo": {
            "playlists": [
                "Esquenta Sertanejo", "Sertanejo Pop", "Sertanejo 2025", "Top Brasil", 
                "Arena Sertaneja", "Sofrência Sertaneja", "Modão Sertanejo", 
                "Churrasco e Sertanejo", "Sertanejo Universitário", "As Mais Tocadas Sertanejo"
            ],
            "masculinos": [
                "gusttavo", "jorge", "henrique", "zé neto", "matheus", "luan", "wesley", 
                "xand", "murilo", "hugo", "guilherme", "felipe", "daniel", "leonardo", 
                "bruno", "marrone", "israel", "rodolffo", "grelo", "menor", "hungria", 
                "kamisa", "kayky", "cristiano", "kauan", "juliano", "santiago", "hugo e guilherme"
            ],
            "femininos": [
                "marília", "maiara", "maraisa", "simone", "simaria", "lauana", "ana castela", 
                "naiara", "mari fernandez", "gabi martins", "paula fernandes", "yasmin santos", 
                "flay", "melody", "manu", "as patroas", "rainhas da sofrência"
            ]
        },
        "Samba & Pagode": {
            "playlists": [
                "Pagodeira", "Samba e Pagode", "Churrasquinho Menos é Mais", "Pagode 2025", 
                "Samba Prime", "Roda de Samba", "Pagode Saudade", "Isso é Pagode", 
                "Samba de Raiz", "Pagodinho de Leve"
            ],
            "masculinos": [
                "thiaguinho", "sorriso", "menos é mais", "ferrugem", "dilsinho", "péricles", 
                "mumuzinho", "pixote", "turma do pagode", "belo", "tiee", "diogo nogueira", 
                "xande", "fundo de quintal", "exaltasamba", "soweto", "revelação", "art popular", 
                "molejo", "jeito moleque", "imaginasamba", "tá na mente", "kamisa 10", "akatu"
            ],
            "femininos": [
                "alcione", "ludmilla", "marvvila", "teresa cristina", "mart'nália", 
                "beth carvalho", "leci brandão", "dona ivone lara", "roberta sá", "maria rita",
                "jovelina", "clara nunes"
            ]
        },
        "Piseiro & Forró": {
            "playlists": [
                "Piseiro 2025", "Top Piseiro", "Vaquejada e Forró", "Forró 2025", 
                "Paredão Explode", "Barões da Pisadinha", "Forró das Antigas", 
                "Pisadinha e Piseiro", "Forró Universitário", "Vaquejada 2025"
            ],
            "masculinos": [
                "joão gomes", "tarcísio", "vitor fernandes", "nattan", "wesley", "xand", 
                "jonas esticado", "eric land", "ze vaqueiro", "biu", "marcynho", "iguinho", 
                "lulinha", "raí", "saia rodada", "limão com mel", "calcinha preta", "henry freitas"
            ],
            "femininos": [
                "mari fernandez", "márcia fellipe", "solange almeida", "priscila senna", 
                "mara pavanelly", "walkyria santos", "taty girl", "paulinha abelha", 
                "silvânia", "kátia cilene", "eliane"
            ]
        },
        "Funk": {
            "playlists": [
                "Funk Hits", "Paredão Funk", "Mandelão 2025", "Funk BH", "Funk 2025", 
                "Mega Funk", "Funk Consciente", "Baile Funk", "Funk Pop", "Funk Antigo"
            ],
            "masculinos": [
                "ryan sp", "cabelinho", "hariel", "kevin", "daniel", "paiva", "poze", 
                "ig", "ph", "tubarão", "g15", "livinho", "pedrinho", "don juan", 
                "kevinho", "jerry", "kekel", "fioti", "menor mr"
            ],
            "femininos": [
                "anitta", "ludmilla", "lexa", "pocah", "rebecca", "pipokinha", "drika", 
                "tati zaqui", "melody", "dany", "mirella", "valesca", "tati quebra barraco"
            ]
        },
        "Rock": {
            "playlists": [
                "Rock Brasil", "Rock Classics", "Pop Rock Nacional", "Rock 2000", 
                "Nação Roqueira", "Rock Leve", "Clássicos do Rock Nacional", 
                "Hora do Rock", "Indie Brasil", "Rock Anos 80 Brasil"
            ],
            "masculinos": [
                "charlie brown", "legião", "cazuza", "capital inicial", "jota quest", 
                "skank", "titãs", "paralamas", "raus seixas", "detonautas", "cpm 22", 
                "engenheiros", "biquini", "ira", "nenhum de nós", "frejat"
            ],
            "femininos": [
                "pitty", "rita lee", "cássia eller", "kid abelha", "paula toller", 
                "baby do brasil", "fernanda takai", "zélia duncan"
            ]
        },
        "Top Brasil": {
            "playlists": [
                "Top 50 - Brasil", "Viral Brasil", "Hot Hits Brasil", "As Mais Tocadas 2025", 
                "Top Brasil Spotify", "Novidades da Semana", "Pop Brasil", "Internet Hits", 
                "TikTok Brasil", "Hits da Internet"
            ],
            "masculinos": [],
            "femininos": []
        },
        "Country": {
            "playlists": [
                "Hot Country", "Country Hits", "Country 2025", "New Boots", 
                "Country Gold", "Nashville Sound", "Country Rocks", "Country Coffeehouse", 
                "Country Top 50", "Country Kind of Love"
            ],
            "masculinos": [
                "morgan wallen", "luke combs", "zach bryan", "chris stapleton", "bailey zimmerman",
                "jelly roll", "kane brown", "jason aldean", "thomas rhett", "cole swindell",
                "alan jackson", "george strait", "garth brooks"
            ],
            "femininos": [
                "lainey wilson", "carrie underwood", "miranda lambert", "kelsea ballerini",
                "megan moroney", "carly pearce", "shania twain", "dolly parton", "reba"
            ]
        }
    }

def load_radar_presets():
    """Carrega os presets salvos ou mescla com os defaults."""
    defaults = get_default_presets()
    
    if not os.path.exists(RADAR_PRESETS_FILE):
        save_radar_presets(defaults)
        return defaults
    
    try:
        with open(RADAR_PRESETS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
            if not saved: return defaults
            return saved
    except:
        return defaults

def save_radar_presets(presets_dict):
    """Salva o dicionário completo de presets."""
    try:
        with open(RADAR_PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(presets_dict, f, indent=4, ensure_ascii=False)
        return True
    except: return False

def add_new_preset_style(style_name):
    """Cria um novo estilo vazio."""
    presets = load_radar_presets()
    if style_name in presets:
        return False, "Estilo já existe."
    
    presets[style_name] = {
        "playlists": [],
        "masculinos": [],
        "femininos": []
    }
    save_radar_presets(presets)
    return True, "Estilo criado com sucesso!"

def delete_preset_style(style_name):
    """Remove um estilo customizado."""
    presets = load_radar_presets()
    if style_name in presets:
        del presets[style_name]
        save_radar_presets(presets)
        return True
    return False

def rename_preset_style(old_name, new_name):
    """Renomeia um estilo existente mantendo a ordem visual."""
    if old_name == new_name: return True, "Nenhuma alteração."
    
    presets = load_radar_presets()
    if old_name not in presets: return False, "Estilo original não encontrado."
    if new_name in presets: return False, f"Já existe um estilo chamado '{new_name}'."
    
    # Reconstrói o dicionário para preservar a ordem
    new_presets = {}
    for key, value in presets.items():
        if key == old_name:
            new_presets[new_name] = value
        else:
            new_presets[key] = value
            
    if save_radar_presets(new_presets):
        return True, "Renomeado com sucesso!"
    return False, "Erro ao salvar."

def set_preset_priority(style_name):
    """[NOVO] Define um estilo como o PRIMEIRO (Default) da lista."""
    presets = load_radar_presets()
    if style_name not in presets: return False
    
    # Cria um novo dicionário colocando o style_name em primeiro
    new_order = {style_name: presets[style_name]}
    for k, v in presets.items():
        if k != style_name:
            new_order[k] = v
            
    return save_radar_presets(new_order)

# ==============================================================================
# 2. GERENCIAMENTO DE HISTÓRICO DE BUSCAS
# ==============================================================================

def load_radar_history():
    """Carrega o histórico de buscas salvas."""
    if not os.path.exists(RADAR_HISTORY_FILE): return []
    try:
        with open(RADAR_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return []

def save_radar_history_item(estilo, qtd_musicas, tabela_dados):
    """Salva uma nova busca no histórico (Topo da lista)."""
    history = load_radar_history()
    
    novo_item = {
        "id": int(time.time()),
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "estilo": estilo,
        "qtd": qtd_musicas,
        "dados": tabela_dados # Lista de dicionários (tabela)
    }
    
    history.insert(0, novo_item) # Insere no começo
    
    # Limita a 50 itens para não pesar
    if len(history) > 50:
        history = history[:50]
        
    try:
        with open(RADAR_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
        return True
    except: return False

def delete_radar_history_item(item_id):
    """Remove um item do histórico pelo ID."""
    history = load_radar_history()
    new_history = [h for h in history if h['id'] != item_id]
    
    try:
        with open(RADAR_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_history, f, indent=4, ensure_ascii=False)
        return True
    except: return False

# ==============================================================================
# 3. GERENCIAMENTO DE CHAVES YOUTUBE (ROTAÇÃO & TESTE)
# ==============================================================================

def load_youtube_keys_data():
    if not os.path.exists(YOUTUBE_KEYS_JSON): return []
    try:
        with open(YOUTUBE_KEYS_JSON, "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_youtube_keys_data(data):
    with open(YOUTUBE_KEYS_JSON, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)

def add_youtube_key_to_pool(new_key: str):
    keys = load_youtube_keys_data()
    if any(k['key'] == new_key.strip() for k in keys): return False, "Chave já existe."
    keys.append({
        "key": new_key.strip(),
        "status": "active", # active | exhausted
        "exhausted_at": 0,
        "label": f"Chave {len(keys)+1}"
    })
    save_youtube_keys_data(keys)
    return True, "Chave adicionada!"

def remove_youtube_key(key_to_remove: str):
    keys = load_youtube_keys_data()
    keys = [k for k in keys if k['key'] != key_to_remove]
    save_youtube_keys_data(keys)

def get_valid_youtube_key():
    """Retorna a primeira chave ativa. Reativa chaves após 24h."""
    keys = load_youtube_keys_data()
    changed = False
    valid_key = None
    now = time.time()
    
    for k in keys:
        if k['status'] == 'exhausted':
            if (now - k['exhausted_at']) > 86400: # 24 horas
                k['status'] = 'active'
                k['exhausted_at'] = 0
                changed = True
        
        if k['status'] == 'active' and not valid_key:
            valid_key = k['key']
            
    if changed: save_youtube_keys_data(keys)
    return valid_key

def mark_key_as_exhausted(key_str):
    """Bane a chave por 24h."""
    keys = load_youtube_keys_data()
    for k in keys:
        if k['key'] == key_str:
            k['status'] = 'exhausted'
            k['exhausted_at'] = time.time()
            break
    save_youtube_keys_data(keys)

# --- COMPATIBILIDADE ---
def load_youtube_key(): return get_valid_youtube_key() or ""
def save_youtube_key(key): add_youtube_key_to_pool(key); return True

# ==============================================================================
# 4. OUTRAS FUNÇÕES ESSENCIAIS
# ==============================================================================

def load_key():
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f: return f.read().strip()
        except: return ""
    return ""

def save_key(key):
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f: f.write(key.strip()); return True
    except: return False

def load_lyrics_url():
    if os.path.exists(LYRICS_URL_FILE):
        with open(LYRICS_URL_FILE, "r", encoding="utf-8") as f: return f.read().strip()
    return "https://www.letras.mus.br" 

def save_lyrics_url(url):
    with open(LYRICS_URL_FILE, "w", encoding="utf-8") as f: f.write(url.strip())

def save_model_pref(model_name):
    try:
        with open(MODEL_PREF_FILE, "w", encoding="utf-8") as f: f.write(model_name.strip())
    except: pass

def load_model_pref():
    if os.path.exists(MODEL_PREF_FILE):
        with open(MODEL_PREF_FILE, "r", encoding="utf-8") as f: return f.read().strip()
    return "gemini-1.5-flash"

def load_spotify_keys():
    if os.path.exists(SPOTIFY_FILE):
        try:
            with open(SPOTIFY_FILE, "r") as f: return json.load(f)
        except: return {"id": "", "secret": ""}
    return {"id": "", "secret": ""}

def save_spotify_keys(client_id, client_secret):
    try:
        with open(SPOTIFY_FILE, "w") as f:
            json.dump({"id": client_id.strip(), "secret": client_secret.strip()}, f)
        return True
    except: return False

def carregar_contexto_duda():
    if os.path.exists(CONTEXT_FILE):
        with open(CONTEXT_FILE, "r", encoding="utf-8") as f: return f.read()
    return ""

def atualizar_contexto_duda(novo_texto, modo="append"):
    conteudo_final = novo_texto
    if modo == "append":
        atual = carregar_contexto_duda()
        if atual: conteudo_final = atual + "\n\n" + novo_texto
    with open(CONTEXT_FILE, "w", encoding="utf-8") as f: f.write(conteudo_final)

def carregar_historico():
    if not os.path.exists(HISTORY_FILE): return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return {}

def salvar_no_historico(url, dados):
    hist = carregar_historico()
    hist[url] = dados
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=4, ensure_ascii=False)

def deletar_do_historico(url):
    hist = carregar_historico()
    if url in hist:
        del hist[url]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(hist, f, indent=4, ensure_ascii=False)
        return True
    return False

# ==============================================================================
# 5. DADOS DO FISCAL DE CANAIS (Monitoramento & Histórico)
# ==============================================================================

def load_monitored_channels():
    if not os.path.exists(FISCAL_CHANNELS_FILE): return []
    try:
        with open(FISCAL_CHANNELS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return []

def save_monitored_channels(lista_canais):
    try:
        # Remove duplicatas e vazios
        lista_limpa = list(set([c.strip() for c in lista_canais if c.strip()]))
        with open(FISCAL_CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(lista_limpa, f, indent=4)
        return True
    except: return False

def load_fiscal_history():
    """Carrega o histórico de buscas do Fiscal."""
    if not os.path.exists(FISCAL_HISTORY_FILE): return []
    try:
        with open(FISCAL_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return []

def save_fiscal_history_item(nome_salva, modo, tabela_dados, filtro_dias, filtro_views):
    """
    Salva uma análise fiscal no histórico com os filtros usados.
    """
    history = load_fiscal_history()
    
    novo_item = {
        "id": int(time.time()),
        "nome": nome_salva,
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "modo": modo, 
        "filtro_dias": filtro_dias,   # [NOVO] Salva o filtro de data
        "filtro_views": filtro_views, # [NOVO] Salva o filtro de views
        "dados": tabela_dados 
    }
    
    history.insert(0, novo_item) 
    
    if len(history) > 50:
        history = history[:50]
        
    try:
        with open(FISCAL_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
        return True
    except: return False

def delete_fiscal_history_item(item_id):
    """Remove um item do histórico fiscal pelo ID."""
    history = load_fiscal_history()
    new_history = [h for h in history if h['id'] != item_id]
    
    try:
        with open(FISCAL_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_history, f, indent=4, ensure_ascii=False)
        return True
    except: return False