"""
utils_cripto.py — Criptografia local (Fernet/AES-128-CBC + HMAC).

Usado para proteger campos sensíveis salvos em arquivos JSON locais
(ex.: bancos_pool.json, futuros cofres de chaves).

Modelo:
  - Uma chave-mestra fica em `.secret_key` (binário, 32 bytes base64).
  - O arquivo `.secret_key` é gerado automaticamente na primeira execução.
  - Esse arquivo NUNCA deve ser commitado (já está coberto pelo .gitignore).
  - Os métodos `encriptar` e `decriptar` recebem/devolvem strings UTF-8.

Filosofia:
  - Simples o suficiente para um projeto Streamlit local.
  - Forte o suficiente para que, se alguém clonar a máquina sem o
    `.secret_key`, não consiga ler senhas em texto puro.
  - Análogo conceitual ao AES-256-GCM + PROVIDER_KEYS_SECRET do Innova V2,
    porém usando Fernet (simétrica, autenticada) pela simplicidade.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ARQUIVO_CHAVE = ".secret_key"


def _caminho_chave() -> Path:
    """Resolve o caminho absoluto da chave-mestra, ancorado na raiz do projeto.

    Estratégia: o arquivo `.secret_key` mora ao lado deste módulo. Isso
    evita problemas de CWD quando o Streamlit roda de subpastas.
    """
    return Path(__file__).resolve().parent / ARQUIVO_CHAVE


def _gerar_chave_se_preciso() -> bytes:
    """Cria o arquivo de chave-mestra se ele ainda não existir.

    Retorna o conteúdo (32 bytes base64) pronto pra alimentar o Fernet.
    """
    caminho = _caminho_chave()
    if not caminho.exists():
        nova = Fernet.generate_key()
        caminho.write_bytes(nova)
        # Em sistemas POSIX, restringe a leitura apenas pro dono.
        try:
            os.chmod(caminho, 0o600)
        except Exception:
            # Em Windows o chmod tem efeito limitado; ignoramos.
            pass
    return caminho.read_bytes()


def _instancia_fernet() -> Fernet:
    """Devolve uma instância de Fernet inicializada com a chave-mestra."""
    return Fernet(_gerar_chave_se_preciso())


# ============================================================================
# API pública
# ============================================================================

def encriptar(texto: str) -> str:
    """Encripta uma string UTF-8 e devolve o token Fernet em ASCII.

    Strings vazias ou `None` retornam string vazia (não fazem ida-e-volta).
    Isso simplifica o uso em campos opcionais do bancos_pool.json.
    """
    if not texto:
        return ""
    f = _instancia_fernet()
    token = f.encrypt(texto.encode("utf-8"))
    return token.decode("ascii")


def decriptar(token: str) -> str:
    """Decripta um token Fernet e devolve a string original em UTF-8.

    - Token vazio → string vazia.
    - Token inválido (chave trocada, conteúdo corrompido) → string vazia
      e NÃO levanta exceção pra UI. Quem usa decide o que fazer com vazio
      (ex.: pedir o usuário re-cadastrar a credencial).
    """
    if not token:
        return ""
    try:
        f = _instancia_fernet()
        claro = f.decrypt(token.encode("ascii"))
        return claro.decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""


def mascarar(texto: str, manter_inicio: int = 6, manter_fim: int = 4) -> str:
    """Mascaramento visual para a UI (não é segurança, é só pra mostrar).

    Ex.: 'eyJhbGciOi...vUKE' a partir de um JWT longo.
    """
    if not texto:
        return ""
    if len(texto) <= manter_inicio + manter_fim:
        return "●" * len(texto)
    return f"{texto[:manter_inicio]}…{texto[-manter_fim:]}"


def chave_existe() -> bool:
    """True se o `.secret_key` já foi criado em algum momento."""
    return _caminho_chave().exists()


def caminho_chave_str() -> str:
    """Caminho absoluto da chave-mestra (útil pra mensagens de diagnóstico)."""
    return str(_caminho_chave())
