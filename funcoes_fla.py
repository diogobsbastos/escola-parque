import json
import os
import time
import requests
import streamlit as st
import re

def load_key(provider="gemini"):
    """
    Carrega chaves de API de um arquivo JSON blindado.
    """
    config_file = "keys.json"
    if not os.path.exists(config_file):
        with open(config_file, "w") as f:
            json.dump({"gemini": "", "newsdata": ""}, f)
        return ""
    
    try:
        with open(config_file, "r") as f:
            keys = json.load(f)
        return keys.get(provider, "")
    except:
        return ""

def save_key(key, provider="gemini"):
    """ Salva ou atualiza uma chave de API no arquivo JSON local. """
    config_file = "keys.json"
    keys = {}
    if os.path.exists(config_file):
        try:
            with open(config_file, "r") as f:
                keys = json.load(f)
        except: keys = {}
    
    keys[provider] = key
    with open(config_file, "w") as f:
        json.dump(keys, f, indent=4)

def registrar_consumo(processo, modelo, total_tokens, custo_brl, tempo_execucao=0,
                      provedor="", tokens_in=0, tokens_out=0, tokens_cache=0):
    """
    Registra a telemetria financeira em JSON para o Dashboard.

    Campos adicionais (Multi-Provider LiteLLM):
      • provedor      — nome do provedor (gemini, openai, anthropic, groq, ...)
      • tokens_in     — tokens de entrada (prompt_tokens)
      • tokens_out    — tokens de saida (completion_tokens)
      • tokens_cache  — tokens lidos do cache (cache_read_input_tokens, quando disponivel)
    """
    log_file = "historico_consumo.json"
    logs = []

    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except: logs = []

    # Se quem chamou nao passou granular, usa o total como input
    if not tokens_in and not tokens_out and total_tokens:
        tokens_in = total_tokens

    logs.append({
        "timestamp":      time.strftime("%Y-%m-%d %H:%M:%S"),
        "processo":       processo,
        "provedor":       provedor,
        "modelo":         modelo,
        "tokens":         total_tokens,
        "tokens_in":      int(tokens_in or 0),
        "tokens_out":     int(tokens_out or 0),
        "tokens_cache":   int(tokens_cache or 0),
        "custo_brl":      round(custo_brl, 5),
        "tempo_execucao": tempo_execucao
    })

    try:
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=4, ensure_ascii=False)
    except:
        pass


# --- NOVO MOTOR FINANCEIRO (VIA PDF LOCAL) ---

def buscar_cotacao_dolar_realtime():
    """Busca a cotação oficial do USD/BRL na internet"""
    try:
        url = "https://economia.awesomeapi.com.br/last/USD-BRL"
        res = requests.get(url, timeout=3).json()
        return float(res["USDBRL"]["bid"])
    except:
        try:
            url_alt = "https://api.exchangerate-api.com/v4/latest/USD"
            res_alt = requests.get(url_alt, timeout=3).json()
            return float(res_alt["rates"]["BRL"])
        except:
            return 5.25 # Fallback final

def obter_precos_do_pdf(modelo_alvo, caminho_pdf="tabela_precos.pdf"):
    """
    Lê o PDF local e extrai os preços de Entrada e Saída do modelo selecionado.
    """
    # Dicionario de seguranca atualizado com os precos REAIS (USD por 1M tokens).
    # IMPORTANTE: chaves SEM prefixo "X/" - normalizamos modelo_alvo antes do lookup.
    fallbacks = {
        "gemini-3.1-flash-lite":     {"in": 0.075, "out": 0.30},
        "gemini-2.5-flash":          {"in": 0.30,  "out": 2.50},
        "gemini-2.5-flash-lite":     {"in": 0.10,  "out": 0.40},
        "gemini-2.5-pro":            {"in": 1.25,  "out": 10.00},
        "gemini-1.5-flash":          {"in": 0.075, "out": 0.30},
        "gemini-1.5-pro":            {"in": 1.25,  "out": 5.00},
        "gpt-4o":                    {"in": 2.50,  "out": 10.00},
        "gpt-4o-mini":               {"in": 0.15,  "out": 0.60},
        "claude-sonnet-4-6":         {"in": 3.00,  "out": 15.00},
        "claude-opus-4-7":           {"in": 15.00, "out": 75.00},
        "claude-haiku-4-5-20251001": {"in": 0.80,  "out": 4.00},
    }

    # NORMALIZACAO: o pool LiteLLM cadastra como "gemini/gemini-2.5-flash"
    # mas as chaves do fallback sao "gemini-2.5-flash" (sem prefixo). Sem
    # normalizar, o .get() devolve o default {0.30, 1.00} e o preco de SAIDA
    # do Gemini Flash vira 1.00 em vez do real 2.50 - subestimando o custo
    # em ~40% (BUG do hibrido onde R$ 0.008 aparecia como R$ 0.0048).
    nome_normalizado = modelo_alvo.split("/")[-1] if "/" in modelo_alvo else modelo_alvo

    if not os.path.exists(caminho_pdf):
        return fallbacks.get(nome_normalizado, {"in": 0.30, "out": 1.00})

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(caminho_pdf)
        texto_completo = ""
        for pagina in doc:
            texto_completo += pagina.get_text("text") + "\n"
        doc.close()

        # Localiza onde o nome do modelo aparece no PDF (busca normalizada)
        idx = texto_completo.lower().find(nome_normalizado.lower())

        if idx != -1:
            # Pega as próximas 2500 letras após o nome do modelo
            bloco_texto = texto_completo[idx:idx+2500]

            # Regex cirúrgico: Busca "Preço de entrada" e captura o primeiro número após US$
            match_in = re.search(r"Preço de entrada[\s\S]*?US\s*\$?\s*([\d,\.]+)", bloco_texto, re.IGNORECASE)
            match_out = re.search(r"Preço de saída[\s\S]*?US\s*\$?\s*([\d,\.]+)", bloco_texto, re.IGNORECASE)

            if match_in and match_out:
                # Converte formato brasileiro (0,30) para float Python (0.30)
                p_in = float(match_in.group(1).replace('.', '').replace(',', '.'))
                p_out = float(match_out.group(1).replace('.', '').replace(',', '.'))
                return {"in": p_in, "out": p_out}
    except Exception as e:
        print(f"Erro ao ler PDF de preços: {e}")

    return fallbacks.get(nome_normalizado, {"in": 0.30, "out": 1.00})

def atualizar_taxas_local(modelo):
    """Acionado pelo botão Testar: Consulta dólar na Web e lê o PDF Local"""
    dolar = buscar_cotacao_dolar_realtime()
    precos = obter_precos_do_pdf(modelo) # Lê do arquivo PDF
    
    dados = {
        "modelo": modelo,
        "dolar": dolar,
        "preco_in": precos["in"],
        "preco_out": precos["out"],
        "ultima_atualizacao": time.strftime("%d/%m/%Y %H:%M")
    }
    
    with open("taxas_config.json", "w") as f:
        json.dump(dados, f, indent=4)
    return dados

def ler_taxas_local(modelo):
    """Lê o arquivo JSON local (Latência Zero para o OCR).

    Normaliza o nome do modelo (remove prefixo "X/") em AMBOS os lados da
    comparacao - sem isso, "gemini/gemini-2.5-flash" do pool LiteLLM nunca
    bate com "gemini-2.5-flash" do taxas_config.json e o sistema cai pra
    um fallback com dolar=5.25 hardcoded e precos errados.
    """
    # Normalizacao: remove prefixo "provedor/" se houver
    modelo_norm = modelo.split("/")[-1] if "/" in modelo else modelo

    if os.path.exists("taxas_config.json"):
        try:
            with open("taxas_config.json", "r") as f:
                dados = json.load(f)
            modelo_arq = str(dados.get("modelo", ""))
            modelo_arq_norm = modelo_arq.split("/")[-1] if "/" in modelo_arq else modelo_arq
            if modelo_arq_norm == modelo_norm:
                return dados
        except:
            pass

    # Fallback: precos via obter_precos_do_pdf (que ja eh normalizado) +
    # dolar via obter_dolar_persistido (cotacao_dolar.json) em vez de 5.25
    # hardcoded - assim usamos a cotacao REAL que o usuario configurou.
    precos_iniciais = obter_precos_do_pdf(modelo, "caminho_falso.pdf")
    try:
        dolar_real = obter_dolar_persistido() or 5.25
    except Exception:
        dolar_real = 5.25
    return {
        "dolar": float(dolar_real),
        "preco_in": precos_iniciais["in"],
        "preco_out": precos_iniciais["out"],
        "ultima_atualizacao": "Padrão do Sistema (dolar persistido)"
    }

def calcular_custo_brl(modelo, input_tokens, output_tokens):
    """Motor de cálculo usado pelo backend_ocr.py"""
    taxas = ler_taxas_local(modelo)
    
    custo_usd = (
        (input_tokens / 1_000_000) * taxas["preco_in"] +
        (output_tokens / 1_000_000) * taxas["preco_out"]
    )
    
    return custo_usd * taxas["dolar"]


# ────────────────────────────────────────────────────────────────────────────
# COTAÇÃO DO DÓLAR PERSISTIDA (manual, sob comando)
# ────────────────────────────────────────────────────────────────────────────
ARQUIVO_DOLAR = "cotacao_dolar.json"


def info_dolar():
    """
    Le o dolar persistido em disco.
    Se nao existir, faz UMA busca inicial e cria o arquivo.
    Retorna dict {valor: float, atualizado_em: 'YYYY-MM-DD HH:MM:SS'}.
    """
    if os.path.exists(ARQUIVO_DOLAR):
        try:
            with open(ARQUIVO_DOLAR, "r", encoding="utf-8") as f:
                dados = json.load(f)
                return {
                    "valor":         float(dados.get("valor", 5.25)),
                    "atualizado_em": dados.get("atualizado_em", "—"),
                }
        except Exception:
            pass

    # Primeira vez — busca e cria
    try:
        valor = buscar_cotacao_dolar_realtime() or 5.25
    except Exception:
        valor = 5.25

    info = {
        "valor":         float(valor),
        "atualizado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(ARQUIVO_DOLAR, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=4, ensure_ascii=False)
    except Exception:
        pass
    return info


def obter_dolar_persistido():
    """Atalho que retorna apenas o valor numerico do dolar persistido."""
    return info_dolar().get("valor", 5.25)


def atualizar_dolar_agora():
    """
    Forca uma nova consulta a API de cotacao e persiste o resultado em disco.
    Retorna (ok: bool, info_dict, mensagem: str).
    """
    try:
        valor = buscar_cotacao_dolar_realtime()
        if not valor:
            return False, info_dolar(), "Falha ao consultar API de cotacao."

        info = {
            "valor":         float(valor),
            "atualizado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(ARQUIVO_DOLAR, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=4, ensure_ascii=False)
        return True, info, f"Dolar atualizado: R$ {valor:.4f}"
    except Exception as e:
        return False, info_dolar(), f"Erro: {str(e)[:200]}"
