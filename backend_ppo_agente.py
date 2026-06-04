import google.generativeai as genai
import json
import os

# REGRA DE OURO 3: Importação protegida e uso de load_key
try:
    from funcoes_fla import load_key, registrar_consumo, calcular_custo_brl
except ImportError:
    def load_key(p): return ""
    def registrar_consumo(p, m, t, c): pass
    def calcular_custo_brl(m, i, o): return 0

def processar_relatorio_agente(texto_ocr):
    """
    Simula o fluxo de agentes: 
    Agente 1 (Extrator) -> Agente 2 (Classificador) -> Agente 3 (Projetista PPO)
    """
    api_key = load_key("gemini")
    if not api_key:
        return {"erro": "Chave Gemini não configurada."}

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-pro')

        # O PROMPT ATUA COMO O "ORQUESTRADOR DE AGENTES"
        prompt = f"""
        Você é uma Agência de Inteligência Pedagógica composta por 3 especialistas:
        1. Analista de Dados PAEE (Lê o relatório e identifica marcas de ☑)
        2. Psicopedagogo Clínico (Classifica o nível de barreira de 1 a 5)
        3. Arquiteto de Aprendizagem (Sugere ajustes práticos)

        INPUT (Relatório do Professor):
        {texto_ocr}

        SUA MISSÃO: Transformar esse relatório no Perfil Pedagógico (PPO) em JSON.
        
        FORMATO DE SAÍDA (OBRIGATÓRIO):
        {{
            "Cognição": [
                {{"item": "Atenção", "valor": 4, "obs": "Distração fácil com estímulos externos"}},
                {{"item": "Função Executiva", "valor": 4, "obs": "Perda em múltiplas instruções"}}
            ],
            "Linguagem": [
                {{"item": "Compreensão de Enunciado", "valor": 3, "obs": "Dificuldade com enunciados longos"}}
            ],
            "Matemática": [
                {{"item": "Organização Espacial", "valor": 5, "obs": "Troca ordem de números e desalinhamento"}}
            ],
            "Ajustes_Sugeridos": ["Redução de números", "Comandos em destaque", "Fragmentação de tarefas"]
        }}
        """

        response = model.generate_content(prompt)
        
        # Telemetria Financeira (Antigravity Standard)
        usage = response.usage_metadata
        custo = calcular_custo_brl("gemini-1.5-pro", usage.prompt_token_count, usage.candidates_token_count)
        registrar_consumo("AGENTE_PPO", "gemini-1.5-pro", usage.total_token_count, custo)

        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except Exception as e:
        return {"erro": str(e)}