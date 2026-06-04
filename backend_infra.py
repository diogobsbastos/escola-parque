import os
import json
import streamlit as st

# REGRA DE OURO 3: Try-except para bibliotecas externas
try:
    import psycopg2
except ImportError:
    psycopg2 = None

PASTA_KEYS = "keys"

# Garante que a pasta de credenciais existe
if not os.path.exists(PASTA_KEYS):
    os.makedirs(PASTA_KEYS)

def save_db_config(host, porta, user, senha, dbname="neondb"):
    """Salva as credenciais do banco em um JSON local."""
    caminho = os.path.join(PASTA_KEYS, "db_config.json")
    dados = {"host": host, "porta": porta, "user": user, "senha": senha, "dbname": dbname}
    with open(caminho, "w") as f:
        json.dump(dados, f)
    return True

def load_db_config():
    """Carrega as credenciais do banco."""
    caminho = os.path.join(PASTA_KEYS, "db_config.json")
    if os.path.exists(caminho):
        with open(caminho, "r") as f:
            return json.load(f)
    return {}

def testar_conexao_postgres(host, porta, user, senha, dbname):
    """Realiza um teste de ping real no servidor do Neon.tech."""
    if not psycopg2:
        return False, "Biblioteca 'psycopg2-binary' ausente. Rode: pip install psycopg2-binary"
    
    try:
        conn = psycopg2.connect(
            host=host,
            port=porta,
            user=user,
            password=senha,
            dbname=dbname,
            connect_timeout=5
        )
        conn.close()
        return True, "✅ Conexão estabelecida com sucesso no Neon.tech!"
    except Exception as e:
        return False, f"❌ Falha na conexão: {str(e)}"
        # Adicione no final do backend_infra.py

def save_mcp_config(mcp_ativo, rag_ativo, vault_path):
    """Salva as configurações do Obsidian e MCP em um JSON local."""
    caminho = os.path.join(PASTA_KEYS, "mcp_config.json")
    dados = {"mcp_ativo": mcp_ativo, "rag_ativo": rag_ativo, "vault_path": vault_path}
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=4)
    return True

def load_mcp_config():
    """Carrega as configurações do Obsidian e MCP."""
    caminho = os.path.join(PASTA_KEYS, "mcp_config.json")
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"mcp_ativo": True, "rag_ativo": True, "vault_path": ""}