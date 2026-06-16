# Plano de Ação — Molde & Formulários (priorizado)

> Deriva dos riscos mapeados em [`DOC_MOLDE_E_FORMULARIOS.md`](./DOC_MOLDE_E_FORMULARIOS.md).
> Objetivo: tirar essas áreas do disco efêmero e dar a elas uma camada de
> persistência + API, **pré-requisito** para reconstruí-las no frontend de forma
> mais robusta. Execução recomendada: **Sonnet**, sessões curtas, push via GitHub MCP.

## Ordem (do mais crítico ao quick win)

### P0 — Persistir os MOLDES no Postgres/Storage  ⚠️ perda de dados
- **Problema:** moldes (JSON + PDF) vivem em `moldes/` em **disco efêmero, sem backup**.
  Uma limpeza/recriação do servidor apaga **todos** os moldes treinados.
- **Ação:** tabela `moldes` no Postgres (metadados + JSON do molde) + PDF de referência
  em Storage/bytea. `backend_molde.py` passa a ler/gravar do BD (com fallback de leitura
  do disco durante a transição). Migração: importar os moldes que ainda existirem em disco.
- **Por que primeiro:** é o único risco de **perda irreversível**, e tudo (OCR, professores)
  depende de os moldes existirem.

### P1 — Histórico de resultados de OCR no Postgres
- **Problema:** `ocr_cache_<professor_id>.json` é **sobrescrito** a cada análise — sem
  histórico, sem separação por aluno/data/molde.
- **Ação:** tabela `ocr_resultados` (aluno_id, molde, payload, criado_em). Grava nova linha
  a cada análise; a UI lê o mais recente mas mantém o histórico.
- **Casa com P0** (mesma frente de migração pra BD).

### P2 — Extrair a camada de backend dos FORMULÁRIOS
- **Problema:** **não existe `backend_formularios.py`** — a lógica de listar/carregar
  schema vive dentro de `pagina_formularios.py`, e o schema "ativo" é só o **primeiro
  arquivo da lista** (frágil).
- **Ação:** criar `backend_formularios.py` (listar/carregar/salvar schema) + marcar o schema
  ativo de forma **explícita** (flag/registro), não por ordem alfabética.
- **Por que:** é o **pré-requisito** pra expor formulários via API e reusar no frontend.

### P3 — Higiene do gabarito (quick win)
- **Problema:** `GABARITO_OFICIAL` **duplicado** em `backend_molde.py` e `gerar_molde.py`,
  com divergência na frase 14 (`manter` vs `mantener`).
- **Ação:** fonte única (um módulo/JSON importado pelos dois), remover a duplicata e fixar a
  grafia correta (`manter` — PT; `mantener` é espanhol, provável typo).
- Baixo risco, alto valor de consistência — pode entrar a qualquer momento.

## Sequência para o frontend
1. **P0 + P1** (persistência) — sem dado em BD/Storage, não há "versão mais poderosa" no front.
2. **P2** — destrava a API de formulários que o front vai consumir.
3. **P3** — quick win, encaixa em qualquer janela.

## Notas de execução
- Mudanças de schema no Postgres: usar a **MCP do Supabase** (`apply_migration`) ou `sql_local`,
  com cuidado e revisão — são alterações estruturais.
- Manter compatibilidade durante a transição (ler do BD com fallback pro disco) pra não
  derrubar o que já roda.
- Cada item = uma sessão Sonnet curta; push via GitHub MCP; nunca quebrar o serviço.
