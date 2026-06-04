import os
import json
import streamlit as st

# REGRA DE OURO 3: Try-Except na importação de bibliotecas externas
try:
    import psycopg2
except ImportError:
    psycopg2 = None

PASTA_KEYS = "keys"

def _obter_conexao():
    """Função interna para conectar ao banco lendo as credenciais salvas no JSON."""
    if not psycopg2:
        st.error("Biblioteca psycopg2-binary não instalada.")
        return None

    caminho_config = os.path.join(PASTA_KEYS, "db_config.json")
    if not os.path.exists(caminho_config):
        return None

    with open(caminho_config, "r") as f:
        conf = json.load(f)

    try:
        conn = psycopg2.connect(
            host=conf.get('host'),
            port=conf.get('porta'),
            user=conf.get('user'),
            password=conf.get('senha'),
            dbname=conf.get('dbname', 'neondb')
        )
        conn.autocommit = True
        return conn
    except Exception as e:
        return None

def inicializar_infraestrutura_vetorial():
    """Cria a tabela do PPO e os índices de alta performance."""
    conn = _obter_conexao()
    if not conn: return False

    try:
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alunos_ppo (
                id SERIAL PRIMARY KEY,
                nome_anon TEXT UNIQUE NOT NULL,
                turma TEXT,
                perfil_texto TEXT,
                barreiras_json JSONB,
                vetor_ppo vector(384),
                data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_vetor_ppo 
            ON alunos_ppo USING hnsw (vetor_ppo vector_cosine_ops);
        """)
        cur.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erro de inicialização: {e}")
        return False

def inserir_aluno_ppo(nome_anon, turma, perfil_texto, vetor):
    """
    Recebe os dados e o vetor matemático e injeta no Neon.tech.
    Se o aluno já existir, ele atualiza (UPSERT).
    """
    conn = _obter_conexao()
    if not conn:
        return False, "Sem conexão com o banco Neon."

    try:
        cur = conn.cursor()
        # Converte a lista do Python para uma string que o PostgreSQL entende nativamente
        vetor_str = str(vetor) 
        
        query = """
            INSERT INTO alunos_ppo (nome_anon, turma, perfil_texto, vetor_ppo)
            VALUES (%s, %s, %s, %s::vector)
            ON CONFLICT (nome_anon) 
            DO UPDATE SET 
                turma = EXCLUDED.turma, 
                perfil_texto = EXCLUDED.perfil_texto, 
                vetor_ppo = EXCLUDED.vetor_ppo, 
                data_atualizacao = CURRENT_TIMESTAMP;
        """
        cur.execute(query, (nome_anon, turma, perfil_texto, vetor_str))
        cur.close()
        conn.close()
        return True, f"Perfil de '{nome_anon}' injetado e vetorizado no Neon!"
    except Exception as e:
        return False, f"Falha ao inserir no banco: {e}"