import re
import json
import time
import streamlit as st
import google.generativeai as genai
from lab_storage import load_model_pref, carregar_contexto_duda

# --- DICIONÁRIO CULTURAL DE REGIONALIDADE ---
DICIONARIO_REGIONAL = {
    "PT-BR (Brasil)": "Use português do Brasil atual. Gírias sertanejas, linguagem coloquial, pronomes como 'você' e sintaxe fluida.",
    "PT-PT (Portugal)": "Use português de Portugal (Europeu). Empregue o gerúndio com 'a + infinitivo' (ex: a cantar), pronomes 'tu/vós', vocabulário típico (ex: rapariga, telemóvel, miúdo, fixe).",
    "PT-AO (Angola)": "Use português angolano. Inclua gírias e expressões do kuduro, kizomba e semba se aplicável (ex: bué, mambo, kamba, kota, cassule). Ritmo mais cadenciado.",
    "PT-MZ (Moçambique)": "Use português moçambicano. Gramática formal misturada com expressões locais (ex: maningue, txilar, machimbombo). Tom amigável e direto.",
    "Inglês": "Use idioma Inglês nativo.",
    "Espanhol": "Use idioma Espanhol nativo.",
    "Francês": "Use idioma Francês nativo."
}

# --- CONFIGURAÇÃO E TESTES ---

def obter_melhor_modelo() -> str:
    """Retorna o modelo definido nas preferências."""
    return load_model_pref()

def listar_modelos_disponiveis(api_key: str):
    """Lista modelos do Gemini disponíveis para a chave."""
    try:
        genai.configure(api_key=api_key)
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        return [m.replace("models/", "") for m in modelos]
    except:
        return []

def testar_conexao_gemini(api_key: str):
    """Testa se a chave conecta e retorna modelos."""
    if not api_key: return False, "Chave vazia.", []
    try:
        genai.configure(api_key=api_key)
        models = listar_modelos_disponiveis(api_key)
        if models:
            return True, f"Conectado! {len(models)} modelos.", models
        return False, "Chave válida, sem modelos.", []
    except Exception as e:
        return False, f"Erro: {str(e)}", []

def testar_modelo_especifico(api_key: str, nome_modelo: str):
    """Envia um 'Oi' para o modelo testar."""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(nome_modelo)
        response = model.generate_content("Responda apenas: OK")
        if response and response.text:
            return True, "Sucesso!"
        return False, "Sem resposta."
    except Exception as e:
        return False, str(e)

# --- FUNÇÕES DE EXTRAÇÃO (REGEX) ---

def extrair_resumo_tecnico(texto_analise: str):
    """Extrai BPM e Estilo do texto gerado."""
    if not isinstance(texto_analise, str) or not texto_analise.strip():
        return 'Dados vazios', 'N/A'
    
    bpm_match = re.search(r'BPM.*?:?\s*(\d{2,3})', texto_analise, re.IGNORECASE)
    bpm = bpm_match.group(1).strip() if bpm_match else 'Não identificado'
    
    estilo_match = re.search(r'Estilo Musical:\s*(.*?)(?:\n|\.)', texto_analise, re.IGNORECASE | re.DOTALL)
    estilo = estilo_match.group(1).strip() if estilo_match else 'Indefinido'
    
    return estilo, bpm

def extrair_conteudo_inteligente(texto_bruto: str):
    """Separa Letra, Prompt Suno e Prompt Visual."""
    letra = re.search(r'\[INICIO_LETRA\](.*?)\[FIM_LETRA\]', texto_bruto, re.DOTALL | re.IGNORECASE)
    letra_final = letra.group(1).strip() if letra else texto_bruto
    
    suno = re.search(r'\[INICIO_PROMPT_SUNO\](.*?)\[FIM_PROMPT_SUNO\]', texto_bruto, re.DOTALL | re.IGNORECASE)
    # Fallback para versão antiga
    if not suno:
        suno = re.search(r'\[INICIO_PROMPT\](.*?)\[FIM_PROMPT\]', texto_bruto, re.DOTALL | re.IGNORECASE)
    prompt_suno = suno.group(1).strip() if suno else "N/A"
    
    vis = re.search(r'\[INICIO_PROMPT_VISUAL\](.*?)\[FIM_PROMPT_VISUAL\]', texto_bruto, re.DOTALL | re.IGNORECASE)
    prompt_visual = vis.group(1).strip() if vis else "N/A"
    
    return letra_final, prompt_suno, prompt_visual

# --- FUNÇÕES DE GERAÇÃO (GEMINI) ---

def analisar_original_com_mestre(api_key: str, arquivo_path: str, letra_mestre: str, modelo_escolhido="gemini-1.5-flash", idioma_origem="PT-BR (Brasil)", idioma_destino="PT-BR (Brasil)"):
    """Envia áudio para análise técnica com bloqueio de minutagem."""
    genai.configure(api_key=api_key)
    try:
        myfile = genai.upload_file(arquivo_path)
        while myfile.state.name == "PROCESSING": 
            time.sleep(1)
            myfile = genai.get_file(myfile.name)
    except Exception as e:
        return f"Erro upload: {e}", "Erro.", "Erro."
    
    model = genai.GenerativeModel(modelo_escolhido)
    
    prompt = f"""
    ATUE COMO UM ENGENHEIRO DE SOM E ESPECIALISTA EM LINGUÍSTICA.
    
    O áudio fornecido está no idioma/sotaque: {idioma_origem}.
    Preste MUITA atenção às gírias, sotaques e expressões regionais desse local para não errar a transcrição.
    
    REGRAS RÍGIDAS (PUNIÇÃO SE DESCUMPRIR):
    1. É ABSOLUTAMENTE PROIBIDO INCLUIR TIMESTAMPS OU MINUTAGEM (ex: 0:15, 1:20) na letra e na tradução. Escreva apenas os versos em texto contínuo.
    2. Não invente palavras que não estão no áudio.
    
    Gere 3 blocos separados OBRIGATORIAMENTE nesta estrutura:
    BLOCO 1: ANÁLISE TÉCNICA (Suno) -> |||DIVISOR_LETRA|||
    BLOCO 2: TRANSCRIÇÃO LIMPA (Fiel ao áudio, SEM TIMESTAMPS) -> |||DIVISOR_TRADUCAO|||
    BLOCO 3: TRADUÇÃO LITERAL (Traduza fielmente para: {idioma_destino}. SEM TIMESTAMPS)
    """
    try:
        response = model.generate_content([myfile, prompt])
        try: genai.delete_file(myfile.name)
        except: pass
        
        texto = response.text
        
        prompt_tec, letra, trad = "N/A", texto, "N/A"
        
        if "|||DIVISOR_LETRA|||" in texto:
            p1 = texto.split("|||DIVISOR_LETRA|||")
            prompt_tec = p1[0].strip()
            rest = p1[1]
            if "|||DIVISOR_TRADUCAO|||" in rest:
                p2 = rest.split("|||DIVISOR_TRADUCAO|||")
                letra = p2[0].strip()
                trad = p2[1].strip()
            else:
                letra = rest.strip()
                
        return prompt_tec, letra, trad
    except Exception as e:
        return f"Erro: {str(e)}", "Erro", "Erro"

def traduzir_texto_existente(api_key: str, texto_original: str, modelo_escolhido="gemini-1.5-flash", regiao="PT-BR (Brasil)"):
    """Traduz texto sem áudio, respeitando regionalidade."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(modelo_escolhido)
    
    diretriz = DICIONARIO_REGIONAL.get(regiao, DICIONARIO_REGIONAL["PT-BR (Brasil)"])
    
    prompt = f"""
    Traduza a letra abaixo mantendo o sentido literal. Não inclua minutagem.
    REGRA CRÍTICA DE IDIOMA: {diretriz}
    
    [TEXTO ORIGINAL]:
    {texto_original}
    """
    try:
        return model.generate_content(prompt).text
    except: 
        return "Erro tradução."

def criar_nova_versao(api_key: str, letra_original: str, tema_novo: str, modelo_escolhido="gemini-1.5-flash", usar_treino=True, regiao="PT-BR (Brasil)"):
    """Cria nova versão usando contexto da Duda e Regionalidade."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(modelo_escolhido)
    
    contexto = ""
    if usar_treino:
        duda = carregar_contexto_duda()
        if duda: contexto = f"[BASE CONHECIMENTO]\n{duda}\n[FIM]"
        
    diretriz_idioma = DICIONARIO_REGIONAL.get(regiao, DICIONARIO_REGIONAL["PT-BR (Brasil)"])
    
    prompt = f"""
    ATUE COMO COMPOSITOR DE SUCESSO.
    {contexto}
    
    DIRETRIZ DE IDIOMA: {diretriz_idioma}
    
    [MOLDE BASE]: {letra_original}
    [TEMA/PEDIDO]: {tema_novo}
    
    SAÍDA OBRIGATÓRIA:
    [INICIO_LETRA] (Escreva a letra aqui, seguindo rigorosamente a DIRETRIZ DE IDIOMA acima) [FIM_LETRA]
    [INICIO_PROMPT_SUNO] (Prompt EN com gênero, vibe, instrumentos) [FIM_PROMPT_SUNO]
    [INICIO_PROMPT_VISUAL] (Visual EN para Midjourney) [FIM_PROMPT_VISUAL]
    """
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Erro na geração: {str(e)}"

def detectar_segmentos_ia(api_key: str, arquivo_path: str, titulo_show: str):
    """Analisa áudio longo para achar inicio e fim das músicas."""
    genai.configure(api_key=api_key)
    try:
        myfile = genai.upload_file(arquivo_path)
        while myfile.state.name == "PROCESSING": 
            time.sleep(1)
            myfile = genai.get_file(myfile.name)
        
        model = genai.GenerativeModel(obter_melhor_modelo())
        prompt = f'Analise "{titulo_show}". JSON: [{{ "start": "00:00", "end": "03:00", "titulo_sugerido": "X" }}]'
        res = model.generate_content([myfile, prompt])
        
        try: genai.delete_file(myfile.name)
        except: pass
        
        match = re.search(r'```json\s*(\[.*?\])\s*```', res.text, re.DOTALL)
        return json.loads(match.group(1)) if match else None
    except: 
        return None