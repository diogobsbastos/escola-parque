import json
import os
import time

FILE_GEMINI_POOL = "gemini_pool.json"
COOLDOWN_TIME = 3600  # 60 minutos em segundos

def load_gemini_pool():
    if not os.path.exists(FILE_GEMINI_POOL): return []
    try:
        with open(FILE_GEMINI_POOL, "r") as f: return json.load(f)
    except: return []

def save_gemini_pool(pool):
    with open(FILE_GEMINI_POOL, "w") as f: json.dump(pool, f, indent=4)

def get_next_valid_key():
    pool = load_gemini_pool()
    agora = time.time()
    
    # 1º Passo: Verifica quem já saiu da geladeira (passou 60 min)
    for k in pool:
        if k['status'] == 'standby':
            tempo_passado = agora - k.get('exhausted_at', 0)
            if tempo_passado >= COOLDOWN_TIME:
                k['status'] = 'active'
                k['exhausted_at'] = 0
    save_gemini_pool(pool)

    # 2º Passo: Tenta achar a chave que o usuário marcou como Principal
    for k in pool:
        if k['status'] == 'active' and k.get('is_primary') == True:
            return k['key']
            
    # 3º Passo: Se a principal estiver na geladeira, pega a primeira ativa que achar
    for k in pool:
        if k['status'] == 'active':
            return k['key']
            
    return None

def mark_key_as_standby(key):
    pool = load_gemini_pool()
    for k in pool:
        if k['key'] == key:
            k['status'] = 'standby'
            k['exhausted_at'] = time.time()
    save_gemini_pool(pool)

def add_key_to_pool(new_key):
    pool = load_gemini_pool()
    if any(k['key'] == new_key for k in pool): return False, "Chave já existe no carrossel."
    pool.append({"key": new_key, "status": "active", "exhausted_at": 0, "is_primary": False})
    save_gemini_pool(pool)
    return True, "Chave adicionada com sucesso!"

def reset_key_standby(key):
    """Tira a chave do Cooldown (Geladeira) manualmente."""
    pool = load_gemini_pool()
    for k in pool:
        if k['key'] == key:
            k['status'] = 'active'
            k['exhausted_at'] = 0
    save_gemini_pool(pool)

def set_key_as_primary(key_to_promote):
    """Apenas marca a chave como 'Em Uso' sem mudar ela de lugar na lista."""
    pool = load_gemini_pool()
    for k in pool:
        if k['key'] == key_to_promote:
            k['is_primary'] = True
            k['status'] = 'active'
            k['exhausted_at'] = 0
        else:
            k['is_primary'] = False # Tira a coroa das outras
    save_gemini_pool(pool)