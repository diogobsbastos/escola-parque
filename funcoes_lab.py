import os
import json
import streamlit as st

# --- IMPORTAÇÃO DOS BACKENDS REAIS DO LAB ---
try:
    import lab_ai
except ImportError:
    lab_ai = None

try:
    import lab_storage
except ImportError:
    lab_storage = None


def load_model_pref():
    """
    Entrega a preferência do modelo. 
    Usa o arquivo do lab_storage para persistência local.
    """
    if lab_storage and hasattr(lab_storage, 'load_model_pref'):
        return lab_storage.load_model_pref()
    return "gemini-1.5-flash"


def save_model_pref(modelo_nome):
    """
    Salva a preferência de modelo usando a infraestrutura do lab_storage.
    """
    if lab_storage and hasattr(lab_storage, 'save_model_pref'):
        try:
            lab_storage.save_model_pref(modelo_nome)
            return True
        except:
            return False
    return False


def testar_conexao_gemini(api_key):
    """
    Adapta a assinatura de retorno do lab_ai.py para o formato do app.py.
    Retorna exatamente: (Sucesso, Mensagem, Lista_de_Modelos)
    """
    if lab_ai and hasattr(lab_ai, 'testar_conexao_gemini'):
        try:
            # Chama o motor real contido no lab_ai.py
            sucesso, msg, modelos = lab_ai.testar_conexao_gemini(api_key)
            return sucesso, msg, modelos
        except Exception as e:
            return False, f"Erro interno no motor lab_ai: {str(e)}", []
    
    return False, "Motor 'lab_ai.py' inacessível ou corrompido.", []


def listar_modelos_disponiveis(api_key):
    """
    Retorna uma lista plana de modelos aceitos pela chave.
    """
    if lab_ai and hasattr(lab_ai, 'listar_modelos_disponiveis'):
        try:
            return lab_ai.listar_modelos_disponiveis(api_key)
        except:
            return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.5-flash"]
    return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.5-flash"]


def testar_modelo_especifico(api_key, modelo_nome):
    """
    Testa se o modelo selecionado responde requisições básicas.
    Retorna exatamente: (Sucesso, Mensagem)
    """
    if lab_ai and hasattr(lab_ai, 'testar_modelo_especifico'):
        try:
            sucesso, msg = lab_ai.testar_modelo_especifico(api_key, modelo_nome)
            return sucesso, msg
        except Exception as e:
            return False, str(e)
    return False, "Motor de teste individual indisponível."