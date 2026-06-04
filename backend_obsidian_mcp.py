import os
import re
import streamlit as st

# REGRA DE OURO 3: Blindagem na importação
try:
    from backend_infra import load_mcp_config
except ImportError:
    load_mcp_config = None

def varrer_vault_obsidian(caminho_opcional=None):
    """Lê a pasta do Obsidian e retorna a lista de arquivos Markdown (.md)"""
    
    # Se passamos um caminho para teste, usa ele. Senão, pega do arquivo salvo.
    if caminho_opcional:
        vault_path = caminho_opcional
    else:
        if not load_mcp_config:
            return False, "Módulo de infraestrutura não carregado.", []
        conf = load_mcp_config()
        vault_path = conf.get("vault_path", "")

    if not vault_path or not os.path.exists(vault_path):
        return False, f"Caminho do Vault inválido ou não configurado: '{vault_path}'", []

    notas_encontradas = []
    try:
        # Varre as pastas e subpastas do Obsidian
        for root, dirs, files in os.walk(vault_path):
            # Ignora pastas ocultas do sistema/Obsidian (como .obsidian, .git)
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for file in files:
                if file.endswith(".md"): # Pega apenas arquivos Markdown
                    caminho_completo = os.path.join(root, file)
                    notas_encontradas.append(caminho_completo)
                    
        return True, f"✅ {len(notas_encontradas)} notas encontradas no Vault.", notas_encontradas
    except Exception as e:
        return False, f"❌ Erro ao varrer o Obsidian: {e}", []

def ler_conteudo_nota(caminho_nota):
    """Extrai o texto puro de uma nota específica para alimentar a IA"""
    try:
        with open(caminho_nota, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Erro ao ler a nota: {e}"

def criar_nota_obsidian(titulo, conteudo_markdown, subpasta=""):
    """
    Cria um novo arquivo Markdown (.md) diretamente no Vault.
    No VPS, a ferramenta de sincronização baixará isso para o seu PC.
    """
    if not load_mcp_config:
        return False, "Módulo de infraestrutura não carregado."

    conf = load_mcp_config()
    vault_path = conf.get("vault_path", "")

    if not vault_path or not os.path.exists(vault_path):
        return False, f"Vault não configurado. Vá nas configurações e salve o caminho."

    try:
        # Limpa o título para ser um nome de arquivo válido no SO
        nome_arquivo = re.sub(r'[\\/*?:"<>|]', "", titulo) + ".md"
        
        caminho_final = os.path.join(vault_path, subpasta)
        if subpasta and not os.path.exists(caminho_final):
            os.makedirs(caminho_final)
            
        caminho_completo = os.path.join(caminho_final, nome_arquivo)
        
        with open(caminho_completo, "w", encoding="utf-8") as f:
            f.write(conteudo_markdown)
            
        return True, f"✅ Nota '{nome_arquivo}' injetada com sucesso no Vault!"
    except Exception as e:
        return False, f"❌ Erro ao criar nota física: {e}"