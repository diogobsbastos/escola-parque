"""
backend_professores.py - Storage SQLite local para Professores.

Espelho conceitual de backend_alunos.py, com adaptacoes ao contexto Professor:
  - Professor cria PROVAS (artefato avaliativo) - dimensao docente
  - Aluno responde QUESTIONARIOS (perfil pedagogico) - dimensao discente

Tabelas:
  - professores: identidade + dados de contato + materia
  - moldes_por_professor: relacionamento N:1 com a tabela de moldes (que vive
                          em backend_molde.py / pasta moldes_treinados/)
  - perfil_pedagogico_prof: JSON com estilo de avaliacao (futuro)
"""
import sqlite3
import pandas as pd
import uuid
import os
import json
from datetime import datetime
from pathlib import Path


DB_PATH = "banco_professores.db"


def inicializar_banco() -> None:
    """Cria as tabelas relacionais caso nao existam."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Tabela principal de professores
    c.execute('''CREATE TABLE IF NOT EXISTS professores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    apelido TEXT NOT NULL,
                    id_anon TEXT UNIQUE NOT NULL,
                    nome_completo TEXT,
                    email TEXT,
                    materia TEXT,
                    turmas_responsavel TEXT,
                    ativo INTEGER DEFAULT 1,
                    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')

    # Relacao com moldes (1 professor : N moldes treinados)
    c.execute('''CREATE TABLE IF NOT EXISTS moldes_por_professor (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    professor_id INTEGER NOT NULL,
                    nome_molde TEXT NOT NULL,
                    data_associacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(professor_id) REFERENCES professores(id),
                    UNIQUE(professor_id, nome_molde)
                )''')

    # Perfil pedagogico do professor (estilo de avaliacao, freq. adaptacoes)
    c.execute('''CREATE TABLE IF NOT EXISTS perfil_pedagogico_prof (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    professor_id INTEGER NOT NULL,
                    conteudo_json TEXT,
                    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(professor_id) REFERENCES professores(id)
                )''')

    conn.commit()
    conn.close()


# Inicializa ao importar
inicializar_banco()


# ============================================================================
# CRUD
# ============================================================================

def criar_professor(apelido: str, nome_completo: str = "", email: str = "",
                    materia: str = "", turmas: str = "") -> str:
    """Cria um novo professor e retorna o id_anon (hash curto)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    hash_curto = "P_" + str(uuid.uuid4())[:8].upper()
    c.execute(
        '''INSERT INTO professores
           (apelido, id_anon, nome_completo, email, materia, turmas_responsavel)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (apelido, hash_curto, nome_completo, email, materia, turmas),
    )
    conn.commit()
    conn.close()
    return hash_curto


def buscar_lista_professores() -> pd.DataFrame:
    """Retorna DataFrame com todos os professores cadastrados."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        '''SELECT id, apelido, id_anon, nome_completo, email,
                  materia, turmas_responsavel, ativo, data_cadastro
           FROM professores
           ORDER BY data_cadastro DESC''',
        conn,
    )
    conn.close()
    return df


def obter_detalhes_professor(professor_id) -> dict | None:
    """Busca os detalhes completos de um professor por ID ou id_anon."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Aceita tanto id numerico quanto id_anon textual
    if isinstance(professor_id, str) and not professor_id.isdigit():
        c.execute("SELECT * FROM professores WHERE id_anon = ?", (professor_id,))
    else:
        c.execute("SELECT * FROM professores WHERE id = ?", (int(professor_id),))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    cols = [d[0] for d in c.description]
    detalhes = dict(zip(cols, row))
    conn.close()
    return detalhes


def atualizar_professor(professor_id: int, **campos) -> None:
    """Atualiza campos arbitrarios do professor."""
    if not campos:
        return
    permitidos = {"apelido", "nome_completo", "email", "materia",
                  "turmas_responsavel", "ativo"}
    campos = {k: v for k, v in campos.items() if k in permitidos}
    if not campos:
        return
    set_clause = ", ".join(f"{k} = ?" for k in campos)
    valores = list(campos.values()) + [professor_id]
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"UPDATE professores SET {set_clause} WHERE id = ?", valores)
    conn.commit()
    conn.close()


def deletar_professor(professor_id: int) -> None:
    """Hard delete - usar com cuidado. Considere atualizar_professor(ativo=0)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM moldes_por_professor WHERE professor_id = ?", (professor_id,))
    conn.execute("DELETE FROM perfil_pedagogico_prof WHERE professor_id = ?", (professor_id,))
    conn.execute("DELETE FROM professores WHERE id = ?", (professor_id,))
    conn.commit()
    conn.close()


# ============================================================================
# Moldes associados ao professor
# ============================================================================

def associar_molde(professor_id: int, nome_molde: str) -> None:
    """Marca que um molde foi treinado por este professor."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO moldes_por_professor (professor_id, nome_molde) VALUES (?, ?)",
            (professor_id, nome_molde),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Ja existe a associacao, OK
        pass
    finally:
        conn.close()


def listar_moldes_do_professor(professor_id: int) -> list[str]:
    """Retorna lista de nomes de moldes treinados por este professor."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT nome_molde FROM moldes_por_professor WHERE professor_id = ? ORDER BY data_associacao DESC",
        (professor_id,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# ============================================================================
# Seed (cria 1 professor demo se base vazia, util pra primeira execucao)
# ============================================================================

def _seed_se_vazio() -> None:
    df = buscar_lista_professores()
    if df.empty:
        criar_professor(
            apelido="Prof. Demo",
            nome_completo="Professora Demonstracao",
            email="demo@escolaparque.local",
            materia="Matematica",
            turmas="U1, U2",
        )


_seed_se_vazio()
