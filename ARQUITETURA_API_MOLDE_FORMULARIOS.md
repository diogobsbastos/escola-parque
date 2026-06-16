# Arquitetura — API de Molde, Formulários e Perfil Pedagógico

> Base para as próximas sessões de execução (Sonnet). Decisão fechada em Opus.
> Relacionados: [`DOC_MOLDE_E_FORMULARIOS.md`](./DOC_MOLDE_E_FORMULARIOS.md) ·
> [`PLANO_ACAO_MOLDE_FORMULARIOS.md`](./PLANO_ACAO_MOLDE_FORMULARIOS.md).

## 1. Princípio (o "porquê" desta arquitetura)

- **Uma API Python (FastAPI) pendurada no backend existente** (`innova_bridge`/worker) —
  **não** um microserviço novo isolado. Reaproveita o pool do Postgres, o LiteLLM/gateway
  e o OCR que já existem. É o caminho mais rápido de construir e o mais lógico.
- **Motor no backend, UI no frontend.** Parsing (PDF/DOC/scan), chamada de LLM e chaves
  ficam no servidor; a "sessão" de marcar/revisar/aprovar é o frontend (Next.js/MUI) chamando a API.
- **Tudo registrado no Postgres desde a v1.** A **sessão é uma linha no banco** (pausável,
  retomável, auditável). Acaba o problema de dado em disco efêmero do molde/OCR atual.
- **LLM com saída estruturada (JSON Schema / function calling).** Dois papéis:
  (1) **inferir schema** de um formato novo; (2) **extrair valores** de um preenchido.
  O **Agente1** recebe os valores já canônicos e **monta o perfil pedagógico**.

```
Arquivo (PDF/DOC/nativo) ─▶ [API FastAPI no innova_bridge]
                              1. parse (pdfplumber/PyMuPDF/python-docx/OCR)
                              2. LLM inferir schema   (formato novo)
                              3. LLM extrair valores   (preenchido)
                              4. Agente1: valores → PERFIL PEDAGÓGICO
                              5. persiste tudo no Postgres
        [Frontend Next.js/MUI] ◀── sessão: marcar · revisar · aprovar · ver perfil
```

## 2. Modelo de dados (Postgres) — `public.*`

| Tabela | Papel | Colunas-chave |
|---|---|---|
| `form_schemas` | Modelo canônico de um formulário (NEEI etc.), versionado | id · name · version · `canonical` jsonb (campos, value_maps, metadata) · is_active · created_at |
| `extraction_sessions` | A **sessão** human-in-the-loop | id · kind (`schema_infer`/`extraction`) · status (`draft`/`review`/`approved`/`discarded`) · schema_id · document_id · `annotations` jsonb (marcação) · `llm_payload` jsonb (o que foi enviado) · `llm_result` jsonb (o que voltou) · created_by · created_at · updated_at |
| `form_documents` | Arquivo recebido | id · session_id · source_type (`pdf`/`docx`/`native`) · storage_ref · `parsed` jsonb (texto/estrutura) · uploaded_by · created_at |
| `form_extractions` | Valores extraídos e canônicos | id · document_id · schema_id · `values` jsonb · confidence · status · created_at |
| `pedagogical_profiles` | Perfil gerado pelo Agente1 | id · student_id · extraction_id · `profile` jsonb · model_used · status (`draft`/`approved`) · created_at |
| `exam_templates` (molde) | Molde de prova (P0 — sai do disco) | id · name · `definition` jsonb · ref_pdf storage_ref · created_at |
| `exam_corrections` (OCR) | Resultado de auto-correção (P1 — com histórico) | id · template_id · student_id · professor_id · `result` jsonb · score · created_at |

Migração de schema: via **MCP do Supabase (`apply_migration`)** ou `sql_local`, com revisão.

## 3. Endpoints (FastAPI)

**Schemas (modelos de formulário)**
- `POST /schemas/infer` — recebe um doc, a LLM **propõe** o schema canônico → cria `extraction_sessions(kind=schema_infer)`.
- `GET /schemas` · `GET /schemas/{id}` — listar/ler.
- `POST /schemas` — salvar schema revisado. `PUT /schemas/{id}/activate` — marcar ativo (explícito, não por ordem de arquivo).

**Sessões (marcar / revisar / aprovar)**
- `POST /sessions` — abre sessão. `GET /sessions/{id}` — estado.
- `PATCH /sessions/{id}` — salvar marcação/anotação (o "o que é o quê").
- `POST /sessions/{id}/submit` — confirma e dispara o próximo passo (salvar schema OU gerar perfil).

**Documentos + extração**
- `POST /documents` — upload (pdf/doc/nativo) → parse → `form_documents`.
- `POST /extractions` — roda a LLM de extração sobre um documento+schema → `form_extractions`.
- `GET /extractions/{id}`.

**Perfil pedagógico (Agente1)**
- `POST /profiles` — Agente1 monta o perfil a partir de uma extração aprovada → `pedagogical_profiles`.
- `GET /profiles/{id}` · `PUT /profiles/{id}/approve`.

**Molde + auto-correção (Stream A)**
- `POST /moldes` (treinar/salvar) · `GET /moldes` · `GET /moldes/{id}`.
- `POST /correcoes` — roda OCR/auto-correção de uma prova com um molde → `exam_corrections`.
- `GET /correcoes/{id}`.

## 4. Fluxos

1. **Formato novo de formulário:** `POST /schemas/infer` → sessão de revisão → `POST /schemas` (salva) → `activate`.
2. **Formulário preenchido → perfil:** `POST /documents` → `POST /extractions` → sessão de revisão/aprovação → `POST /profiles` (Agente1) → aprovar.
3. **Prova (molde):** `POST /moldes` (treinar) → `POST /correcoes` (subir prova) → resultado com histórico.

## 5. Auth e deploy

- **Auth:** mantém **GoTrue**. O frontend manda o JWT do usuário; a API **valida o JWT do GoTrue**
  (e usa service role pra operações internas). Mantém Drizzle/Supabase como hoje — só a camada visual muda.
- **Deploy:** a API roda na VPS como serviço (FastAPI/uvicorn) — adicionar à whitelist do auto-deploy
  e à lista de serviços. Editar local → push → auto-deploy, como o resto.

## 6. Ordem de execução (amarra com o plano de ação)

1. **P0/P1** — `exam_templates` + `exam_corrections` no Postgres (tira molde/OCR do disco). *Pré-requisito.*
2. **Esqueleto da API** — FastAPI no `innova_bridge`, auth GoTrue, 1 endpoint de health + 1 real.
3. **Formulários** — `form_schemas` + `/schemas/infer` + `/extractions` com **saída estruturada**.
4. **Perfil** — `pedagogical_profiles` + Agente1 (`/profiles`).
5. **Frontend (MUI)** — UI de sessão consumindo a API (depois da migração de template).

## 7. Decisões registradas

- **API Python (FastAPI) no backend existente**, não microserviço novo. Persistência: **Postgres desde a v1**.
- **Human-in-the-loop total no MVP** (revisar toda extração); relaxar depois.
- **Formatos no MVP: nativo + PDF.** DOC fica pra segunda rodada.
- **LLM sempre em saída estruturada (JSON Schema).** Agente1 só recebe dado canônico.
- Auth permanece **GoTrue + Drizzle**.
