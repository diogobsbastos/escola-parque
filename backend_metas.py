import json
import os

ARQUIVO_METAS = "metas_projeto.json"

def gerar_metas_padrao():
    return [
        # MAIO
        {"id": 1, "mes": "Maio", "titulo": "Setup de Servidor Linux Dedicado", "status": "Pendente", "valor": "R$ 1.000"},
        {"id": 2, "mes": "Maio", "titulo": "Deploy do Banco Vetorial (pgvector)", "status": "Pendente", "valor": "R$ 1.000"},
        {"id": 3, "mes": "Maio", "titulo": "Integração Core API Gemini + Segurança", "status": "Pendente", "valor": "R$ 1.000"},
        # JUNHO
        {"id": 4, "mes": "Junho", "titulo": "Motor RAG: Ingestão e OCR de PDFs", "status": "Pendente", "valor": "R$ 1.000"},
        {"id": 5, "mes": "Junho", "titulo": "Viabilidade: Custo otimizado para R$ 0,05", "status": "Pendente", "valor": "R$ 1.000"},
        {"id": 6, "mes": "Junho", "titulo": "Criação do Banco de Prompts e Persona", "status": "Pendente", "valor": "R$ 1.000"},
        # JULHO
        {"id": 7, "mes": "Julho", "titulo": "Integração do Protocolo MCP (Obsidian Vault)", "status": "Pendente", "valor": "R$ 1.000"},
        {"id": 8, "mes": "Julho", "titulo": "Dashboard de Monitoramento Financeiro/Tokens", "status": "Pendente", "valor": "R$ 1.000"},
        {"id": 9, "mes": "Julho", "titulo": "Deploy Final e Testes de Carga do Sistema", "status": "Pendente", "valor": "R$ 1.000"}
    ]

def carregar_metas():
    if not os.path.exists(ARQUIVO_METAS):
        metas_iniciais = gerar_metas_padrao()
        salvar_metas(metas_iniciais)
        return metas_iniciais
        
    with open(ARQUIVO_METAS, "r", encoding="utf-8") as f:
        dados = json.load(f)
        
        # Sistema de segurança: Se ler o JSON antigo (sem o campo 'mes'), ele recria o arquivo
        if len(dados) > 0 and 'mes' not in dados[0]:
            novos_dados = gerar_metas_padrao()
            salvar_metas(novos_dados)
            return novos_dados
            
        return dados

def salvar_metas(metas):
    with open(ARQUIVO_METAS, "w", encoding="utf-8") as f:
        json.dump(metas, f, indent=4, ensure_ascii=False)

def forcar_reset():
    # Usado para zerar o banco de dados via interface
    metas_iniciais = gerar_metas_padrao()
    salvar_metas(metas_iniciais)
    return metas_iniciais