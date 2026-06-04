"""
innova_bridge/repositories - Adapters Supabase BR para o frontend Streamlit.

Cada modulo aqui devolve dados no MESMO FORMATO que os backend_* originais
(SQLite local) — assim a UI nao precisa saber se a fonte e local ou remota.

Modulos:
  - students_repo : alunos + counts de PAIs/questionarios (TELA 1 e dossie)
"""

from . import students_repo

__all__ = ["students_repo"]
