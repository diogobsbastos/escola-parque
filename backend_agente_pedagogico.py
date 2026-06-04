import json

def obter_dados_questionario_aluno(aluno_id):
    """
    Ponte com a IA (Motor de Agentes).
    Por enquanto, retorna a estrutura padronizada para manter a UI funcionando.
    Em breve, injetaremos o backend_ocr.py aqui.
    """
    # TODO: Implementar chamada ao Gemini usando Matriz de Strings
    
    return {
        "A. LINGUAGEM E COMPREENSÃO": [
            {"pergunta": "Compreensão de leitura (comandos simples)", "marcado": True, "escala": 1, "obs": "Lê com autonomia, mas de forma lenta."},
            {"pergunta": "Necessidade de releitura de comandos complexos", "marcado": True, "escala": 3, "obs": "Perde-se com o que a questão pede. Melhora com releitura guiada."},
            {"pergunta": "Literalidade da linguagem", "marcado": False, "escala": 0, "obs": ""}
        ],
        "B. FUNÇÃO EXECUTIVA / CARGA COGNITIVA": [
            {"pergunta": "Sustentação da atenção", "marcado": True, "escala": 3, "obs": "Distrai-se facilmente com estímulos da sala."},
            {"pergunta": "Organização espacial no papel", "marcado": True, "escala": 4, "obs": "Dificuldade organizando respostas e cálculos matemáticos."},
            {"pergunta": "Carga de memória de trabalho", "marcado": True, "escala": 5, "obs": "Esquece partes das instruções durante a execução."}
        ],
        "C. PRODUÇÃO ESCRITA / MOTORA": [
            {"pergunta": "Fadiga grafomotora", "marcado": False, "escala": 0, "obs": ""},
            {"pergunta": "Fluência de escrita", "marcado": True, "escala": 2, "obs": "Escrita lenta."}
        ]
    }