"""
innova_bridge - Ponte Python <-> Supabase BR (Innova V2).

Este pacote isola toda a integracao com o banco compartilhado do Innova V2.
Le configuracao do storage_bancos (BD ativo do carrossel) e expoe:
  - config: monta dict de conexao
  - db: pool asyncpg + queries basicas (SELECT 1, version, counts)

Convencoes:
  - Nada aqui toca em backend_ocr/backend_molde/storage_gemini.
  - Tudo e isolado, importado sob demanda pra nao quebrar boot se algo faltar.
  - Pool asyncpg e singleton via run-once, reusado entre queries.
"""

__version__ = "0.1.0"
