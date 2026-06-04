# 🗺️ MAPA DO SISTEMA DUPLO — Escola Parque / Innova V2

> **Fonte da verdade viva.** Sempre que algo mudar (schema, fluxo, arquivo, regra),
> **atualize este arquivo**. É o primeiro lugar a consultar pra saber "o que é o quê".
>
> Última atualização: **2026-06-01** · Estado: Fase 1 **funcionando ponta-a-ponta** + **Fase 2 NO AR** (frontend publicado na Vercel: https://escola-parque-frontend.vercel.app).

---

## 0. Resumo em 30 segundos

Dois sistemas que **NÃO conversam direto** — só pelo **Supabase** (banco central compartilhado):

- **Frontend (Next.js)** — UI pros professores/alunos/ADMs. Vai pra **Vercel (www)**. Pasta `E:\VIPWORKS\PROGRAMAÇÃO\ESCOLA PARQUE\Innova_V2_cursor` (app em `web/`).
- **Backend Central (Python)** — toda a **inteligência** (LLM, visão, multi-provedor). Streamlit local + **worker** que processa. Pasta `C:\Users\DB LIVE STUDIO\Desktop\AUTOMACOES\ESCOLA_PARQUE`.
- **Supabase `innova-v2-br`** — o "vidro" compartilhado. Ref `awosfxlcjqotforkixps`, região `sa-east-1`, Postgres 17.

**Princípio governante:** o **frontend NÃO roda LLM** — ele enfileira no Supabase e lê o resultado. O **Backend Central é o superconjunto** (faz tudo que o front faz + config/prompt/benchmark/molde, que são exclusivos dele).

**Nome de produto:** o sistema Python é o **"Backend Central"** (nome pro usuário). `worker`/`agente1_worker` é só o nome interno do processo.

---

## 1. Diretórios e papéis

| Sistema | Caminho | Stack | Vai pra |
|---|---|---|---|
| **Backend Central** | `C:\Users\DB LIVE STUDIO\Desktop\AUTOMACOES\ESCOLA_PARQUE` | Python, Streamlit, OpenCV/PyMuPDF, asyncpg | roda **local** (depois hospedar) |
| **Frontend** | `E:\VIPWORKS\PROGRAMAÇÃO\ESCOLA PARQUE\Innova_V2_cursor` (`web/`) | Next.js (App Router), React, Drizzle ORM, Shadcn/Tailwind | **Vercel (www)** |
| **Banco** | Supabase `innova-v2-br` (`awosfxlcjqotforkixps`) | Postgres 17 + RLS | — |

**Conexão ao banco:**
- Worker Python: **Transaction Pooler 6543** (asyncpg, `statement_cache_size=0`). String em `bancos_pool.json` (cifrada Fernet com `.secret_key`); lida via `innova_bridge/config.get_database_url()` → `storage_bancos`.
- pgAdmin / `pg_dump`: **Session Pooler 5432** (host `aws-1-sa-east-1.pooler.supabase.com`, user `postgres.awosfxlcjqotforkixps`, db `postgres`, SSL require).
- Frontend (Vercel): via Drizzle + chaves Supabase (futuro: integração Supabase↔Vercel injeta as envs).

---

## 2. O fluxo (Sistema Duplo) — como o PAI é gerado

```
[Frontend / www]                         [Supabase innova-v2-br]                 [Backend Central / worker Python (local)]
  professor                                  (vidro compartilhado)
     │                                                                              loop: poll a cada ~10s + heartbeat
     ├── A) Questionário (form) ── lockSection ──► questionnaire_sections           ◄── poll status='locked' + canonical_response
     │      consolida (consolidate.ts) e grava        .canonical_response (jsonb)        → gerar_pai → grava em pais
     │                                                 (meta.source='web_form')
     │
     └── B) Upload CSV (Google) ──────────────► questionnaire_uploads (pending)     ◄── poll status='pending'
            uploadQuestionnaireCsvAction              (raw_content = texto do CSV)        → csv_to_questionnaire_response (adapter)
                                                                                          → gerar_pai → grava 1 PAI POR FAMÍLIA

  worker grava de volta:  pais (PAI) + agent_run_logs (custo+proveniência) + carimba secao.agent1_run_id + heartbeat
     │
  Frontend lê pais ◄────────────────────── pais (status active/needs_review) ──────────────────► Streamlit também lê pais
  (PaiViewer; uploader faz polling com spinner até ficar pronto e dá refresh)
```

**Há DOIS caminhos de entrada** pro mesmo motor:
- **A) Formulário** → grava `questionnaire_sections.canonical_response` (1 PAI por seção/família).
- **B) Upload de CSV** → grava `questionnaire_uploads` (worker parseia e gera **2 PAIs: Exatas + Humanas**).

Ambos terminam em `pais`, lidos por frontend **e** Streamlit.

---

## 3. Tabelas do banco (o que é o quê)

**Tenancy/base:** `schools`, `users` (role: admin/coordinator/teacher/aee; espelha `auth.users` via trigger `handle_new_user`), `students`, `classes`, `subjects`, `student_classes`, `class_teacher_subjects`.

**Disciplinas:** `discipline_families` → **id 1 = Exatas** (`logical_mathematical`), **id 2 = Humanas e Português** (`textual_interpretive`).

**Questionário → PAI:**
| Tabela | Papel |
|---|---|
| `questionnaires` | 1 por (aluno, ano) |
| `questionnaire_sections` | 1 por bloco (`exatas`/`humanas`). Campos-chave: `status` (draft/aee_ready/locked/superseded), `agent1_run_id`, **`canonical_response` (jsonb, NOVO)** = input pronto do Agente 1 |
| `questionnaire_field_responses` | respostas achatadas (field_id pontilhado + value jsonb + author_role regente/aee) |
| **`questionnaire_uploads`** (NOVO) | fila do CSV: `raw_content` (texto), `student_id`, `engine`, `status` (pending/processing/done/failed), `result_pai_ids[]`, `created_by_user_id` |
| `pais` | **o PAI**. 1 por (`student_id`,`family_id`). `content` jsonb, `version`, `status`, `generated_by_agent`, `section_id` |

**Agentes / IA:**
| Tabela | Papel |
|---|---|
| **`agent_configs`** (NOVO) | **fonte da verdade do default por agente**: `engine`, `model`, `strict_no_fallback`, `provider_key_id`. O worker lê daqui. Painel do Streamlit grava aqui |
| `agent_prompts` | prompts versionados por agente (`is_default`) |
| `agent_run_logs` | **razão de custo/telemetria** (1 linha por chamada LLM). + colunas NOVAS: `triggered_by_user_id`, `school_id`, `request_source` |
| `model_pricing` | preços por modelo (com datação `effective_from/until`). Custo lido daqui |
| `provider_keys` | chaves LLM do **frontend** (cifradas com segredo do Next; Python NÃO decifra). `is_global_default` |
| `system_settings` | chave→valor jsonb. Inclui `usd_brl_rate`, `default_school_id`, e **`python_worker_heartbeat`** (online/offline) |

**Provas (Agente 2/3 — futuro):** `exams`, `adapted_exams`, `validations`, `adaptation_components_cache`.

**Outros:** `pai_reviews`, `audit_log`, `questionnaire_tokens`.

---

## 4. Regras de negócio (explícitas)

1. **PAI por família:** 1 PAI vigente por (`student_id`, `family_id`). ⚠️ **REGRA ATUAL (2026-06-01):** o upload de CSV gera **APENAS 1 PAI** — `family_id=1` (Exatas/Matemática), como padrão. **NÃO duplicar** (o Agente 2 lê UM perfil; 2 cópias idênticas quebram). Se um dia for por família de verdade, gerar conteúdo **DISTINTO** por família, nunca cópia. *(A decisão "2A" anterior — 2 PAIs duplicados — foi REVERTIDA.)*
2. **Supersede:** ao gravar PAI novo, aposenta (`status='superseded'`) TODOS os vigentes (`active`+`needs_review`) do mesmo (aluno, família). Reenviar questionário **regenera sem duplicar**.
3. **status_rule:** `rationale.low_confidence_areas` vazio → `active`; senão → `needs_review`.
4. **version:** `max(version)+1` por (aluno, família).
5. **Engine default:** lido de `agent_configs` (profile_builder). Hoje: `hybrid` + `ollama/qwen2.5:14b` (local, R$0) — **trocável pelo painel** (era `gemini-2.5-flash`).
6. **Modo estrito:** se ligado, NÃO cai pro Native quando a LLM falha (erra alto).
7. **Custo:** lido de `model_pricing` (match por nome **normalizado** — tira prefixo `X/`) × `usd_brl_rate`. Modelo local = R$0.
8. **Nome canônico de modelo:** `gemini-2.5-flash` (sem prefixo). Normalizado no **save** (`storage_litellm`) e na **lista** (`backend_litellm`). Prefixos legítimos (OpenRouter `meta-llama/`, `ollama/` local) são **preservados**.
9. **Origem (proveniência):** `request_source` = `web_form` (Frontend) | `python_manual` | `worker_auto`. Vem de `canonical_response.meta.source` (ou do upload). + `triggered_by_user_id`, `school_id`.
10. **Frontend não roda LLM** nem grava `agent_run_logs` — só enfileira e lê. **Backend Central = superconjunto.**
11. **RLS:** `tenant_isolation_*` por `school_id = current_school_id()` (lê `auth.uid()`). O worker usa asyncpg direto (role postgres) → **bypassa RLS**; sempre filtrar `school_id` no código.
12. **Heartbeat:** worker grava `system_settings['python_worker_heartbeat']` a cada ciclo. `now()-ts < 60s` ⇒ Backend Central **Online**.

---

## 5. Arquivos-chave (onde mexer)

### Backend Central (Python — C:)
| Arquivo | O que faz | Estado |
|---|---|---|
| `innova_bridge/workers/agente1_worker.py` | **O worker.** Pola seções + uploads; roda motor; grava PAI/log/heartbeat | **NOVO** |
| `innova_bridge/repositories/pais_repo.py` | Persiste PAI no Supabase (supersede/status/version) | **NOVO** |
| `innova_bridge/repositories/agent_configs_repo.py` | read/save de `agent_configs` (usado pelo painel) | **NOVO** |
| `innova_bridge/repositories/agent_run_logs_repo.py` | leitura de `agent_run_logs` pra tela de custos | **NOVO** |
| `innova_bridge/agents/agente1/router.py` | `gerar_pai(engine=native\|hybrid\|llm, ...)` — **ponto de entrada do motor** | existente |
| `innova_bridge/agents/agente1/{native,hybrid,schemas,persistence,providers}.py` | motor determinístico, híbrido, schema NEEI/PAI, persistência local, multi-provedor | existente |
| `innova_bridge/formularios/adapters/from_neei_v3_0.py` | `csv_to_questionnaire_response(texto)` — **adapter do CSV Google** | existente |
| `innova_bridge/db/client.py` · `config.py` | pool asyncpg + URL do BD ativo | existente |
| `storage_litellm.py` | pool LiteLLM local (chaves/modelos). PATCH: normaliza prefixo no save | PATCH |
| `backend_litellm.py` | chamadas LLM + `listar_modelos_provedor`. PATCH: normaliza prefixo na lista | PATCH |
| `pagina_agentes_treinamento.py` | Treinamento de Agentes. PATCH: painel **"🎯 Default consumido"** (Salvar → `agent_configs`) | PATCH |
| `pagina_financeiro.py` | Gestão de Custos. PATCH: lê `agent_run_logs` do Supabase + coluna **Origem** | PATCH |

### Frontend (Next.js — E:\...\web\src\)
| Arquivo | O que faz | Estado |
|---|---|---|
| `db/schema.ts` | **Drizzle = fonte da verdade do schema.** Espelha `canonical_response`, colunas de `agent_run_logs`, `agentConfigs`, `questionnaireUploads` | PATCH |
| `lib/agents/agent1/dispatcher.ts` | **`stageAgent1ForSection`** (grava `canonical_response`, NÃO roda LLM). `dispatchAgent1ForSection` antigo mantido intacto | PATCH |
| `lib/questionnaire/consolidate.ts` | `consolidateSection()` → `ProfileBuilderInput` (regente vence; achatado→agrupado; nº→enum). **É o "adapter" do form** | existente |
| `app/app/alunos/[id]/questionario/actions.ts` | `lockSection` → chama `stageAgent1ForSection` | PATCH |
| `app/app/alunos/[id]/actions.ts` | `uploadQuestionnaireCsvAction` + `checkUploadStatusAction` | PATCH |
| `app/app/alunos/[id]/backend-central-uploader.tsx` | uploader (arrastar/colar/clicar) + spinner + polling + refresh | **NOVO** |
| `app/app/alunos/[id]/pai-empty-state.tsx` | usa o uploader; botão DEV (fixture) escondido em `<details>` | PATCH |
| `app/app/configuracoes/page.tsx` | badge **Backend Central Online/Offline** (heartbeat) + "Painel de Roteamento de IA" recolhido em "(Descontinuado)" | PATCH |
| `docs/PYTHON_INTEGRATION_HANDOFF.md` | handoff original (referência do contrato) | existente |

---

## 6. Migrations aplicadas (Supabase, via MCP)

1. `f1_agente1_partA_canonical_provenance_agentconfigs` — `questionnaire_sections.canonical_response`; `agent_run_logs.{triggered_by_user_id,school_id,request_source}`; tabela `agent_configs` + seed do profile_builder.
2. `f1b_questionnaire_uploads_job` — tabela `questionnaire_uploads` + RLS `tenant_isolation_questionnaire_uploads`.

> **Regra anti-drift:** toda mudança de schema feita no Supabase tem que ser **espelhada no Drizzle** (`web/src/db/schema.ts`). Em conflito, o **TypeScript ganha**.

**Artefatos gerados (na pasta do backend):**
- `DESIGN_F1_AGENTE1_SUPABASE.md` — contrato/design da Fase 1.
- `MIGRATION_F1_AGENTE1.sql` — SQL revisável (Parte A/B/C).
- `BACKUP_innova_v2_br_2026-06-01.sql` — snapshot lógico do schema public + dados.
- Backups `*.bak_<ts>` ao lado de cada arquivo editado.

---

## 7. Como rodar / operar

- **Worker (loop):** `python -m innova_bridge.workers.agente1_worker` (use `--once` pra processar 1 e sair). Precisa do mesmo Python do Streamlit + **Ollama rodando** (pro modelo local). **Reiniciar após mudar código** (carrega na inicialização).
- **Streamlit (backend):** `streamlit run app.py`.
- **Frontend dev:** `npm run dev` em `web/` (reiniciar após mudar `schema.ts`/actions).
- **Backup completo:** pgAdmin → botão direito no DB `postgres` → **Backup** (Custom), ou `pg_dump` na porta 5432. ⚠️ Backup contém dado sensível (alunos/diagnósticos/chaves) → guardar seguro, **NUNCA em git**.

---

## 8. Pendências / próximos passos

- ~~**#15** ocultar "Painel de Roteamento de IA" (Descontinuado)~~ ✅ **FEITO** (`configuracoes/page.tsx`, dentro de `<details>`).
- ~~**#16** indicador Backend Central Online/Offline~~ ✅ **FEITO** (`configuracoes/page.tsx`, badge no topo da aba LLM lendo o heartbeat).
- ~~**Fase 2 — ir ao ar:** conectar repo no **GitHub** → **deploy Vercel** → integração **Supabase↔Vercel** (envs) → **login do sócio**~~ ✅ **FEITO (2026-06-01)**. Detalhes:
  - **Repo:** `github.com/diogobsbastos/escola-parque-frontend` (privado, **só a pasta `web/`** é o repo; raiz da Innova_V2_cursor com PII/dumps ficou de fora). Vercel GitHub App restrito a esse 1 repo.
  - **Vercel:** projeto `escola-parque-frontend` (team Hobby `diogobsbastos-3390s-projects`), Root Directory `./`, preset Next.js. **URL de produção:** https://escola-parque-frontend.vercel.app
  - **Env vars (8) na Vercel:** `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL` (Transaction pooler **6543**), `PROVIDER_KEYS_SECRET`, `USD_BRL_RATE`, `ANTHROPIC_API_KEY`, **`HUSKY=0`** (pro `prepare` script não tentar git hooks no build).
  - **Login do sócio:** `diogobsbastos@gmail.com` promovido **teacher → admin** (em `public.users.role` **e** no `auth.users.raw_user_meta_data.role`), escola Escola Parque. Senha = seed (`innova-dev-2026`).
  - **Fluxo de deploy contínuo:** `git push` na branch `main` → Vercel **rebuilda/republica sozinha** (sem reimportar, sem reconfigurar env). A Vercel é o **gate de build**.
- **Pendências da Fase 2:** domínio próprio (`www`) em Vercel→Domains; ativar 2FA na conta Vercel; hospedar o **worker Python** always-on (segue local). Botão DEV de fixture e painel multi-DB (db-configs) **não funcionam em produção** (features dev/descontinuadas, fora do fluxo real).
- **Worker em produção:** hospedar always-on (Railway/Render/Fly/VPS) com auto-restart. Com **LLM local** precisa de máquina com Ollama; com **cloud (Gemini)** um host barato basta.
- **Robustez:** reaper pra upload preso em `processing` (se o worker cair no meio). Fila genérica `jobs` quando entrarem Agente 2/3.
- **Higiene:** `model_pricing` consolidado pro Gemini; revisar outros modelos.

---

## 9. Armadilhas conhecidas (gotchas)

- **Mount stale do sandbox (Cowork):** `py_compile` dá **falso positivo** em arquivos recém-editados (versão "torn"). Validar pelo **Read no path real**, não confiar no compile do mount.
- **Reiniciar o worker** após mudar o código dele — senão roda a versão antiga (já aconteceu: upload ficou `pending` porque o worker rodava versão sem a função de upload).
- **Cold start do Ollama:** 1ª geração após carregar o modelo é ~2x mais lenta (model load); as seguintes são "quentes".
- **CSV deve estar no formato Google Forms NEEI** (o que `csv_to_questionnaire_response` parseia) — senão o upload vira `failed` com a mensagem do erro.
- **provider_keys.encrypted_key** é cifrada com segredo do Next — o Python resolve a chave pelo **pool LiteLLM local** (`storage_litellm`), não por essa coluna.

---

## 10. Changelog

### 2026-06-01 (Fase 2 NO AR — frontend na Vercel)
- **Frontend publicado:** https://escola-parque-frontend.vercel.app (repo privado `diogobsbastos/escola-parque-frontend`, **só a pasta `web/`**). GitHub→Vercel com deploy automático a cada push em `main`. Env vars das 8 chaves importadas do `.env.local` + `HUSKY=0`.
- **Login do sócio:** `diogobsbastos@gmail.com` → **admin** (sincronizado em `public.users` e `auth.users` metadata).
- **BUG de build corrigido (Zod v4):** em `web/src/app/app/configuracoes/actions.ts` (updateProviderKeySchema), o `.default()` vinha **depois** do `.transform()` (quebra no Zod v4: "Argument of type 'string' is not assignable to '() => boolean'"). Corrigido invertendo a ordem: `z.enum([...]).default("true").transform((v) => v === "true")` (linhas 544-545). **Regra:** no Zod v4, `.default()` vem ANTES do `.transform()`.
- **Aprendizado (gotcha confirmado):** o build NÃO roda no sandbox do Cowork (node_modules de Windows + rede restrita + mount "torn"). A **Vercel é o gate de build**: push → build limpo no ambiente dela → se falhar, ler o log, corrigir via Read/Edit no host e dar push de novo.

### 2026-06-01 (autostart do worker)
- **`innova_bridge/workers/autostart.py` (NOVO):** sobe o worker **automático junto com o Streamlit** (sem ligar na mão). Idempotente — só dispara se o heartbeat não estiver fresco (<60s), evitando duplicados.
- **FALTA injetar no `app.py`** (1 trecho, no topo, depois do `import streamlit as st`):
  ```python
  @st.cache_resource
  def _autostart_backend_central():
      from innova_bridge.workers.autostart import ensure_worker_running
      return ensure_worker_running()
  _autostart_backend_central()
  ```
  `@st.cache_resource` garante 1x por processo do servidor. O worker sobe **detached** (sobrevive a reruns; some quando você matar no Task Manager). Pra produção, virar serviço (Task Scheduler/systemd) ou host always-on.

### 2026-06-01 (continuação)
- **Migração `f1c_pais_created_via`:** coluna `pais.created_via` (origem: `web_form`/`python_manual`/`worker_auto`). Worker grava (seção=`req_source`, upload=`web_form`); Drizzle espelhado. Backfill dos PAIs de hoje → `web_form`.
- **BUG corrigido — "PAI não aparece no backend":** o Streamlit lia o PAI de **arquivo local** (`pais_gerados/`) + fixture. Agora lê **do Supabase `pais` PRIMEIRO** (fonte única) via `pais_repo.listar_pais_ativos_supabase(code|uuid)`, em `pagina_alunos.py::render_ppo_tab`. **Regra-mestra:** front e Streamlit veem SEMPRE os mesmos PAIs (tabela `pais`), independente de quem criou.
- **Frontend `configuracoes/page.tsx`:** botão **"Ping"** (re-checa o heartbeat na hora) + Cotação USD e Preços dos Modelos movidos pra dentro do `<details>` "(Descontinuado)" junto com o Roteamento de IA.
- **Diagnóstico útil:** U4 (`91adc890…`) tinha 2 PAIs no Supabase o tempo todo — o "bug" era só o Streamlit lendo da fonte errada.
