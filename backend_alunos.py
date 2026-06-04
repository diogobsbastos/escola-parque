import sqlite3
import pandas as pd
import uuid
import os
import json
from datetime import datetime

DB_PATH = "banco_alunos.db"

def inicializar_banco():
    """Cria as tabelas relacionais caso não existam."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Tabela de Alunos
    c.execute('''CREATE TABLE IF NOT EXISTS alunos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    apelido TEXT NOT NULL,
                    id_anon TEXT UNIQUE NOT NULL,
                    serie TEXT,
                    turma TEXT,
                    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    
    # Tabela de Questionários Base (JSON)
    c.execute('''CREATE TABLE IF NOT EXISTS questionarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aluno_id INTEGER,
                    conteudo_json TEXT,
                    data_extracao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(aluno_id) REFERENCES alunos(id)
                )''')

    # Tabela de PPO (JSON)
    c.execute('''CREATE TABLE IF NOT EXISTS ppo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aluno_id INTEGER,
                    conteudo_json TEXT,
                    data_geracao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(aluno_id) REFERENCES alunos(id)
                )''')
    
    conn.commit()
    conn.close()

# Inicializa o banco ao importar o backend
inicializar_banco()

def criar_aluno(apelido, serie, turma):
    """Cria um novo aluno e gera um ID Anonimizado para o RAG."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Gera um hash único para proteger a identidade da criança no RAG
    hash_curto = str(uuid.uuid4())[:8]
    id_anon = f"ID-{apelido[:2].upper()}-{hash_curto}"
    
    try:
        c.execute("INSERT INTO alunos (apelido, id_anon, serie, turma) VALUES (?, ?, ?, ?)",
                  (apelido, id_anon, serie, turma))
        conn.commit()
        sucesso = True
    except Exception as e:
        sucesso = False
    finally:
        conn.close()
    
    return sucesso

def buscar_lista_alunos():
    """Retorna o dataframe para a TELA 1"""
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT
            a.id, a.apelido, a.serie, a.turma,
            (SELECT COUNT(*) FROM ppo WHERE aluno_id = a.id) as ppos,
            (SELECT COUNT(*) FROM questionarios WHERE aluno_id = a.id) as quest,
            strftime('%d/%m/%Y', a.data_cadastro) as cadastro
        FROM alunos a
        ORDER BY a.id DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def obter_detalhes_aluno(aluno_id):
    """Retorna o dicionário de dados do aluno para a TELA 2"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, apelido, id_anon, serie, turma FROM alunos WHERE id = ?", (aluno_id,))
    row = c.fetchone()
    
    if not row:
        return None
        
    c.execute("SELECT COUNT(*) FROM ppo WHERE aluno_id = ?", (aluno_id,))
    ppos = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM questionarios WHERE aluno_id = ?", (aluno_id,))
    quests = c.fetchone()[0]
    conn.close()
    
    return {
        "id": row[0],
        "apelido": row[1],
        "id_anon": row[2],
        "serie": row[3],
        "turma": row[4],
        "ppos_ativos": ppos,
        "questionarios": quests
    }

def obter_ppo_completo():
    """Fallback temporário para manter o layout da UI funcionando enquanto não conectamos a Tabela PPO."""
    return {
        "A. LINGUAGEM E COMPREENSÃO": [
            {"item": "Compreensão de leitura", "valor": 3, "obs": "Aguardando dados reais do banco..."}
        ]
    }