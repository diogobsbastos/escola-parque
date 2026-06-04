import os
import json
import streamlit as st

# REGRA DE OURO 3: Blindagem extrema para bibliotecas pesadas de IA e Banco
try:
    import psycopg2
except ImportError:
    psycopg2 = None

try:
    # Esta biblioteca usa a sua CPU/GPU local para transformar texto em matemática
    from sentence_transformers import SentenceTransformer
    # O modelo 'all-MiniLM-L6-v2' gera vetores de 384 dimensões ultrarrápidos e de graça
    modelo_embedding_local = SentenceTransformer('all-MiniLM-L6-v2')
except ImportError:
    modelo_embedding_local = None

# Importa a conexão segura que já construímos no outro backend
try:
    from backend_banco_vetorial import _obter_conexao
except ImportError:
    _obter_conexao = None


def gerar_vetor_zero_tokens(texto):
    """
    Usa processamento local para criar o embedding. 
    CUSTO DE API: $0.00
    """
    if not modelo_embedding_local:
        return None
    # Converte o texto em uma lista de 384 números flutuantes
    return modelo_embedding_local.encode(texto).tolist()


def buscar_contexto_rag(texto_base, limite=3):
    """
    O Coração da Inteligência Escalável.
    Pesquisa no Neon.tech quais perfis/arquivos são matematicamente mais similares ao texto atual.
    """
    if not modelo_embedding_local or not psycopg2 or not _obter_conexao:
        return False, "Bibliotecas 'sentence-transformers' ou 'psycopg2' não instaladas.", []

    try:
        # 1. Transforma a busca atual em matemática localmente
        vetor_busca = gerar_vetor_zero_tokens(texto_base)
        if not vetor_busca:
            return False, "Falha ao gerar vetor local.", []

        # 2. Conecta no banco Neon
        conn = _obter_conexao()
        if not conn:
            return False, "Sem conexão com o banco vetorial.", []

        cur = conn.cursor()
        
        # 3. A MÁGICA DO PGVECTOR: O operador <=> calcula a distância geométrica (cosseno)
        # entre o que estamos buscando e TODOS os itens do banco instantaneamente.
        query = """
            SELECT nome_anon, perfil_texto, barreiras_json,
                   1 - (vetor_ppo <=> %s::vector) AS taxa_similaridade
            FROM alunos_ppo
            ORDER BY vetor_ppo <=> %s::vector
            LIMIT %s;
        """
        
        cur.execute(query, (vetor_busca, vetor_busca, limite))
        resultados = cur.fetchall()
        
        cur.close()
        conn.close()

        # 4. Formata a resposta para injetar no Prompt do Gemini depois
        exemplos_encontrados = []
        for row in resultados:
            exemplos_encontrados.append({
                "nome_aluno": row[0],
                "contexto_pedagogico": row[1], # Aqui podemos depois cruzar com os arquivos .md do Vault
                "score_matematico": round(row[3] * 100, 2) # Porcentagem de "match"
            })

        return True, f"{len(exemplos_encontrados)} fragmentos de conhecimento resgatados.", exemplos_encontrados

    except Exception as e:
        return False, f"Falha crítica no Motor RAG: {str(e)}", []