# DESIGN F1 — Agente 1 (Questionário Base) ligado ao Supabase

> Documento de design + **contrato de dados** front↔back↔Supabase.
> Fatia 1 do Sistema Duplo: religar o Agente 1 (já pronto) ao banco, sem fila, sem Molde, sem frontend novo.
> Escopo da Trilha A apenas. Trilha B (Molde/correção CV) fica fora.
> Gerado a partir de leitura do código real (`innova_bridge/`) + inspeção do banco `innova-v2-br` via MCP.

---

## 0. TL;DR (o que muda e o que NÃO muda)

- **O cérebro do Agente 1 já existe e está fechado.** `innova_bridge/agents/agente1/router.py::gerar_pai(payload, engine="hybrid", ...)` roda o Híbrido 2.0 e produz o PAI v1.0. **Não vamos tocar nele.**
- **O que falta é só a borda (I/O via Supabase):** hoje a entrada vem de CSV/fixture e a saída grava em arquivo local (`pais_gerados/*.json`). O próprio `persistence.py` diz textualmente: *"O Supabase BR fica pra F3.5"*. **Essa é a fatia.**
- **Trabalho real = 3 peças novas, todas de borda:** (1) adapter de entrada `from_supabase_section()`, (2) repositório de saída `pais_repo` (grava em `pais` + `agent_run_logs` + carimba a seção), (3) loop do worker + heartbeat.
- **Fila (`jobs`), Molde (`exam_templates`) e área de professores no frontend: adiados.** Para 1 worker e dados já presentes no banco, não são necessários agora.
- ⚠️ **Dois descompassos achados nos dados reais** (seções 5 e 6) precisam de decisão sua **antes** de eu escrever código.

---

## 1. Arquitetura do fluxo (alvo)

```
[Frontend Next.js (E:\...Innova_V2_cursor)]
   1. ADM seleciona aluno → Questionário Base → sobe arquivo Google (CSV) — única opção por enquanto
   2. Grava no Supabase e marca a seção como "pronta para o Agente 1"
            │
            ▼  (Supabase BR — sa-east-1 — fonte da verdade)
[questionnaire_sections] + [questionnaire_field_responses]  +  Storage: bucket questionnaire-uploads/
            │
            ▼  (poll a cada N s — worker Python LOCAL na sua máquina, via asyncpg já existente em db/client.py)
[Worker Agente 1]
   3. lê seção "pronta" sem PAI → adapter Supabase→canônico → router.gerar_pai(engine="hybrid", default)
   4. grava PAI em [pais], log em [agent_run_logs], carimba sections.agent1_run_id
   5. escreve heartbeat (system_settings) a cada ciclo
            │
            ▼
[Frontend] faz poll do status:
   • PAI pronto    → repagina para "Perfil Pedagógico" (lê pais.content)
   • worker online mas processando → "gerando…"
   • heartbeat velho (worker offline) → "Servidor Python fora do ar. Contate o setor de TI."
```

**Por que tirar a geração do frontend (LLM no Next.js)?** Decisão sua, registrada: mais caro, mais lento, não-multimodal. Toda a inteligência (Híbrido, visão computacional futura, multi-provedor) fica no Python. O frontend vira um cliente fino: sobe arquivo, mostra status, lê resultado.

---

## 2. Estado real do banco (lido via MCP em 2026-05-31)

Projeto `innova-v2-br` (ref `awosfxlcjqotforkixps`), 24 tabelas, RLS ativo em todas.

Tabelas que já sustentam a Trilha A **sem precisar criar nada**:

| Tabela | Papel no fluxo | Estado hoje |
|---|---|---|
| `students` | aluno | 7 alunos |
| `questionnaires` | questionário por (aluno, ano) | 1 |
| `questionnaire_sections` | unidade de processamento (1 por bloco: exatas/humanas) | 2 |
| `questionnaire_field_responses` | as respostas (field_id + value jsonb, por autor) | 42 |
| `pais` | **saída** — o Perfil Pedagógico | 16 (todos com `section_id=null`, origem local antiga) |
| `agent_run_logs` | telemetria/custo da execução | 17 |
| `provider_keys` / `system_settings` / `model_pricing` | config de LLM e defaults | ver seção 5 |

**Dado real de referência (o aluno de teste):**
- Aluno `aff9d57e-…`, ano `2026`.
- Seção **exatas** `51e2c3d0-…` → `status='draft'`, `agent1_run_id=null`, **42 respostas**. ← é esta que dá pra processar.
- Seção **humanas** `cfdc229a-…` → `status='draft'`, **0 respostas** (ainda não preenchida).

`pais.content` (shape de saída, top-level keys): `meta, narrative, capabilities, barriers, support_response, adaptation_budget, hard_restrictions, rationale, schema_version`. Bate 1:1 com o que `native.py`/`hybrid` produzem.

---

## 3. Contrato de ENTRADA — como o motor espera receber

Fonte: `innova_bridge/agents/agente1/native.py` (linhas 199–326). O `router.gerar_pai` recebe um **dict NEEI-nested**:

```jsonc
{
  "questionnaire_response": {
    "identification":   { "student_id", "age", "grade_level", "fill_date",
                          "teacher_name", "aee_professional_name" },
    "characterization": { "has_clinical_report"(bool), "student_summary", "current_supports",
                          "what_works", "what_did_not_work", "clinical_summary" },
    "capabilities": {                          // ANINHADO, valores enum string
      "reading_comprehension":   { "<field>": "without_support|with_support|cannot" },
      "writing_production":       { ... },
      "mathematical_reasoning":   { ... },
      "executive_functions":      { ... }
    },
    "barriers": { "<flag>": true|false },      // dict de flags
    "support_response":          [ { "support_type": "...", "response": "yes_alone|yes_with_support|no|not_tested" } ],   // LISTA
    "adaptation_authorizations": [ { "dimension": "...", "intensity": "not_authorized|light|moderate|intense" } ],        // LISTA (enums!)
    "extra_time_authorized": true,             // bool TOP-LEVEL
    "specific_restrictions": "…|null",
    "personality_notes": "…|null",
    "aee_observations": { "specific_strategies", "material_resources", "other" }
  },
  "laudo_summary": "…|null",
  "historical_data": null
}
```

Ponto-chave (linha 207–212): **o motor recebe `adaptation_authorizations` como ENUMS e calcula o orçamento sozinho** (`INTENSITY_TO_INT`: intense=3, moderate=2, light=1, not_authorized=0). Ele explicitamente "transcreve a autorização" — não recebe orçamento pronto.

---

## 4. Como o banco GUARDA hoje (e como mapear)

`questionnaire_field_responses` = uma linha por campo: `field_id` (texto pontilhado) + `value` (jsonb) + `author_role` (`regente`|`aee`) + `section_id`.

Amostra real:

| field_id | value | author_role |
|---|---|---|
| `characterization.student_summary` | `"Estudante de 13 anos…"` | aee |
| `characterization.has_clinical_report` | `true` | aee |
| `capabilities.mathematical_reasoning.place_value` | `"without_support"` | regente |
| `capabilities.executive_functions.working_memory_load` | `"cannot"` | aee |
| `barriers.easy_distraction` | `true` | aee |
| `barriers.multi_step_loss` | `true` | aee |
| `adaptation_budget.statement_fragmentation` | `3` | regente |
| `adaptation_budget.metacognitive_hints` | `3` | aee |
| `adaptation_budget.extra_time_allowed` | `true` | regente |
| `aee_observations.material_resources` | `"Cronômetro visual…"` | aee |

**O adapter `from_supabase_section(section_id)` precisa:**
1. **Mesclar** as linhas de `regente` + `aee` da seção num só dict pontilhado.
2. **Des-achatar** (`a.b.c` → `{a:{b:{c:…}}}`).
3. Reagrupar `capabilities.*`, `characterization.*`, `aee_observations.*`, `barriers.*` (já batem).
4. **Reverter `adaptation_budget` (números) → `adaptation_authorizations` (lista de enums)** usando o inverso de `INTENSITY_TO_INT` (3→intense, 2→moderate, 1→light, 0→not_authorized). Lossless.
5. Mapear `adaptation_budget.extra_time_allowed` → `extra_time_authorized` (top-level).
6. Reformatar `support_response` de dict pontilhado → **lista** `[{support_type, response}]`.
7. Montar `identification` a partir de `students` + `users` (nome do regente/AEE) + `questionnaires.academic_year`.

Saída: o dict NEEI-nested da seção 3, pronto pro `gerar_pai`.

---

## 5. ⚠️ DESCOMPASSO 1 — Config default contradiz a própria UI

Você pediu: *"quando puxar o sistema Python, ele usa o default da imagem"* = **Híbrido + `gemini-2.5-flash` + Modo Estrito**.

O banco tem **duas fontes de "default" que se contradizem**:

| Fonte | Valor | Bate com a imagem? |
|---|---|---|
| `provider_keys` (is_global_default=true) | `google` / `models/gemini-2.5-flash` | ✅ SIM |
| `system_settings.default_model_profile_builder` | `"claude-opus-4-7"` | ❌ NÃO (Anthropic, caro) |

Decisão necessária: **qual é a fonte da verdade do default do Agente 1?** Recomendação (a confirmar):
- Worker lê o **provedor** de `provider_keys.is_global_default` (= Gemini) e o **engine/strict** de uma chave nova em `system_settings` (ex.: `agent1_default_run = {"engine":"hybrid","strict_no_fallback":true,"model":"models/gemini-2.5-flash"}`).
- **Aposentar ou corrigir** `system_settings.default_model_profile_builder` (hoje `claude-opus-4-7`) pra não haver dois donos da verdade. *(Mudança de dado, não destrutiva — só após seu OK.)*

---

## 6. ⚠️ DESCOMPASSO 2 — O banco já guarda o orçamento decidido; o motor quer decidir

- **Princípio do Híbrido 2.0** (handoff): *"o native DECIDE orçamento/intensidades"*. O motor espera `adaptation_authorizations` (o que o professor autorizou) e calcula o `adaptation_budget`.
- **Realidade do banco:** o frontend (ou seed) já gravou `adaptation_budget.*` como **números 0–3** — ou seja, a decisão de orçamento já foi tomada fora do Python.

Isso é uma divergência de arquitetura, não só de formato. Dois caminhos:

- **Caminho A (recomendado, não-quebra):** o adapter **reverte** os números do `adaptation_budget` para a lista de `adaptation_authorizations` (enums) e deixa o motor re-derivar o orçamento. Como o mapa é 1:1, o PAI sai idêntico e **o motor não muda**. O front continua gravando o que já grava.
- **Caminho B:** mudar o contrato do motor pra aceitar orçamento pré-pronto. Mexe no que está fechado — evito.

Pendência menor relacionada: o **vocabulário de `barriers`** no banco (`easy_distraction`, `working_memory_overload`, `multi_step_loss`…) precisa ser confirmado contra o que `native._build_barriers()` aceita; se divergir, entra uma tabela de-para no adapter.

### 6.1 ⚠️ ACHADO CONFIRMADO — `support_response` (Parte 4 do NEEI) NÃO existe no banco

Inspecionando a seção real `51e2c3d0-…` (42 respostas), os grupos de `field_id` são **só**: `adaptation_budget` (10), `aee_observations` (2), `barriers` (7), `capabilities` (16), `characterization` (6), `fill_metadata` (1). **Não há nenhum `support_response.*`** (e `identification` vem de joins, não de field_responses).

Problema: `native.py` linha 215 faz `qr["support_response"]` **sem `.get`** → **KeyError** se ausente. Consequências/decisões:
- **Imediato (não-quebra):** o adapter sempre injeta `support_response: []` quando não houver linhas. O PAI sai com `support_response` vazio. Seguro.
- **De produto:** o frontend atual **não coleta a Parte 4 (resposta a suportes)** do NEEI. Decidir se essa parte entra no formulário do frontend ou se é abandonada de propósito. (Afeta a riqueza do PAI, não a execução.)

---

## 7. Persistência de SAÍDA (a peça que falta) — `pais_repo`

Espelhar a governança que já existe em `persistence.py`, mas gravando no Supabase:

1. **status_rule:** `rationale.low_confidence_areas` vazio → `active`; senão → `needs_review`.
2. **supersede:** marcar como `superseded` todos os `pais` vigentes (`active`+`needs_review`) do mesmo `(student_id, family_id)` **antes** de inserir o novo. (Regra do "1 PAI vigente por aluno+família".)
3. **version:** `max(version)+1` para aquele `(student_id, family_id)`.
4. **insert** em `pais`: `content` (o PAI), `student_id`, `family_id` (1=exatas/logical, 2=humanas/textual), `school_id`, **`section_id`** (novidade — os 16 antigos têm null), `version`, `status`, `generated_by_agent` (ex.: `ProfileBuilderHibrido_v2.0`).
5. **insert** em `agent_run_logs`: `agent_name='profile_builder'`, `model`, `student_id`, `target_type='pai'`, `target_id`, tokens, `cost_brl`, `latency_ms`, `status`, `prompt_version`.
6. **update** `questionnaire_sections.agent1_run_id` = id do log → é o sinal de "já processado".

---

## 8. Trigger + Heartbeat (online/offline)

**Trigger (sem fila ainda):** worker faz poll:
```sql
SELECT id FROM questionnaire_sections
WHERE status = 'locked'          -- ver seção 9 sobre o estado "pronto"
  AND agent1_run_id IS NULL
ORDER BY updated_at LIMIT 1
FOR UPDATE SKIP LOCKED;          -- já deixa pronto pra 2+ workers no futuro
```

**Heartbeat (atende o "servidor Python fora do ar"):** o worker grava a cada ciclo (sem DDL):
```sql
INSERT INTO system_settings(key, value, updated_at)
VALUES ('python_worker_heartbeat',
        jsonb_build_object('ts', now(), 'host', :host, 'version', :ver), now())
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
```
Frontend: `now() - heartbeat.ts < 60s` → online; senão → mensagem de TI.

---

## 9. SQL aditivo necessário (nada destrutivo — só após seu OK)

Mínimo para o fluxo:

1. **Estados de processamento na seção** (pra o front mostrar "gerando/falhou"). `questionnaire_section_status` hoje = `draft, aee_ready, locked, superseded`. Adicionar:
   ```sql
   ALTER TYPE questionnaire_section_status ADD VALUE IF NOT EXISTS 'agent1_processing';
   ALTER TYPE questionnaire_section_status ADD VALUE IF NOT EXISTS 'agent1_done';
   ALTER TYPE questionnaire_section_status ADD VALUE IF NOT EXISTS 'agent1_failed';
   -- (ADD VALUE é aditivo; roda fora de transação)
   ```
   *Alternativa sem mexer no enum:* coluna `agent1_state text` separada. A decidir.
2. **Heartbeat:** nenhuma DDL — usa `system_settings` (seção 8).
3. **Storage:** criar bucket `questionnaire-uploads` (config de Storage, não SQL) para o arquivo Google cru — necessário só quando o frontend entrar.
4. **`provider_keys`/`system_settings`:** correção do default (seção 5) — UPDATE, não destrutivo.

**Espelho Drizzle:** toda alteração acima precisa ser refletida em `web/src/db/schema.ts` (E:\…Innova_V2_cursor) na mesma leva, senão dá drift. O TypeScript é a fonte da verdade do schema.

**Fora de escopo desta fatia:** `jobs` (fila genérica) e `exam_templates` (Molde). Entram quando ligarmos Agente 2/3 e correção por CV.

---

## 10. Plano de execução (fatia 1) e verificação

1. Resolver os 2 descompassos (seções 5 e 6) — **decisão sua**.
2. `from_supabase_section()` (adapter de entrada) + testes contra a seção real `51e2c3d0-…`.
3. `pais_repo` (saída com supersede/status/version) + carimbo de `agent1_run_id` e `agent_run_logs`.
4. Worker loop + heartbeat.
5. **Verificação:** rodar o Agente 1 na seção real e **diffar** o PAI gerado contra (a) o fixture validado e (b) um `pais.content` existente, confirmando que a camada estrutural (capabilities, adaptation_budget, barriers) é idêntica à do fluxo local. Conferir que o supersede deixou exatamente 1 PAI vigente por (aluno, família).

---

## 11. Contrato resumido para o frontend (levar pro Cowork do E:)

O frontend **escreve**:
- `students` (se aluno novo), `questionnaires` (aluno+ano), `questionnaire_sections` (1 por bloco).
- `questionnaire_field_responses`: uma linha por campo, `field_id` pontilhado, `value` jsonb, `author_role`.
- arquivo Google cru no bucket `questionnaire-uploads/`.
- marca a seção como **pronta** (status `locked` ou o estado que decidirmos) — é o gatilho do worker.

O frontend **lê**:
- `system_settings['python_worker_heartbeat']` → online/offline.
- `questionnaire_sections.status` / `agent1_run_id` → "gerando" vs "pronto".
- `pais` (vigente, por `student_id`+`family_id`, `status in (active, needs_review)`) → renderiza o Perfil Pedagógico.

O frontend **NÃO** chama LLM. Geração é 100% Python.

---

## 12. DECISÕES FECHADAS (atualização)

> **Princípio de paridade (governante):** o **backend Python é o superconjunto**. Tudo que o frontend faz, o Python faz (mesmas tabelas, mesmo `canonical_response`). O inverso NÃO vale: config de provedores/chaves, engenharia de prompt, benchmark de modelos, Molde/visão computacional, gestão de preços e ajustes internos são **exclusivos do Python**. O frontend é cliente fino e nunca expõe essas capacidades.

Estas substituem os pontos em aberto das seções anteriores:

- **Casa do JSON:** ✅ coluna `canonical_response jsonb` em `questionnaire_sections` (não tabela nova). A seção já é a unidade 1:1 (bloco → família → 1 PAI).
- **Shape do JSON:** ✅ exatamente o formato que o Agente 1 já consome (seção 3): autorizações em **palavras**, `support_response` como **lista**. O frontend web e a opção manual do Python emitem o MESMO JSON. **Não há adapter de remontagem.**
- **Adapter / descompassos 5 e 6:** ✅ resolvidos por contrato — como o JSON nasce pronto, não há reversão número→palavra nem reconstrução. O `support_response` ausente vira `[]` por contrato no emissor.
- **Versão antiga do frontend:** ✅ vai pra **outro Supabase**. O sócio usa o Supabase dele. O `innova-v2-br` é exclusivo da versão web. → **Worker NÃO precisa de filtro anti-formato-antigo.**
- **Config por agente (isolada da global):** ✅ nova tabela **`agent_configs`** (irmã de `agent_prompts`, mesma enum `agent_name`), 1 linha por agente com `{engine, provider_key_id, model, strict_no_fallback, temperature, max_tokens}`. O **painel do backend** (a imagem "Configuração do Agente 1") é o dono da verdade: botão **Salvar** → grava em `agent_configs[profile_builder]` → o worker lê de lá quando roda. Mesma lógica pro Agente 2 e 3.
  - **Global (fallback):** `provider_keys.is_global_default` (Gemini) = provedor padrão quando um agente não tem config própria.
  - **Aposentar** as chaves magras `system_settings.default_model_*` (a `default_model_profile_builder='claude-opus-4-7'` estava obsoleta porque o painel nunca gravava nela) — migrar pra `agent_configs` pra não ter dono duplicado.
  - `agent_configs` mapeia 1:1 nos parâmetros do `router.gerar_pai(engine=, provider_key_id=, model_override=, strict_no_fallback=)` — encaixa direto, sem mexer no motor.

---

## 13. Custos, Proveniência & Acesso

### 13.1 Cálculo (no Python, lendo o banco)
- Preços vêm de **`model_pricing`** (não mais de mapa local hardcoded), respeitando `effective_from/until` → execução antiga mantém o preço da época.
- `custo_usd = t_in/1M·preço_in + t_out/1M·preço_out + t_cache/1M·preço_cache`.
- `custo_brl = custo_usd · system_settings.usd_brl_rate` (foto da cotação no momento do run).
- Modelos locais (Ollama/Qwen local, base_url localhost) = **R$0**; tokens/latência ainda são logados.
- ⚠️ **Normalizar o nome do modelo** (existe `gemini-2.5-flash` e `models/gemini-2.5-flash` em `model_pricing` e `agent_run_logs`) → uma só chave canônica, senão o lookup de preço fura (foi a causa do R$0 fantasma — config a corrigir).

### 13.2 Razão imutável = `agent_run_logs`
Uma linha por execução de LLM. Guarda `cost_usd_raw` (verdade do consumo) **e** `cost_brl` (foto da cotação). Já vivo (17 linhas).

### 13.3 Proveniência — cadeia de custódia (NOVO requisito)
Quem dispara está no frontend; quem loga é o Python. Logo:
1. O frontend carimba na submissão (`questionnaire_sections.canonical_response.meta`): `submitted_by_user_id`, `source` (`web_form` | `python_manual`), `school_id`.
2. O worker, ao logar o run, **copia** esses campos pra `agent_run_logs`.

**SQL aditivo (não-destrutivo) em `agent_run_logs`:**
```sql
ALTER TABLE public.agent_run_logs
  ADD COLUMN IF NOT EXISTS triggered_by_user_id uuid REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS school_id uuid REFERENCES public.schools(id),
  ADD COLUMN IF NOT EXISTS request_source text;  -- 'web_form' | 'python_manual' | 'worker_auto'
```
(Espelhar em `web/src/db/schema.ts`.)

### 13.4 Área de "de onde vem cada gasto" + acesso
- Leituras agregadas sobre `agent_run_logs` por `school_id`, `triggered_by_user_id`, `agent_name`, `model`, `student_id`/`family_id`, `created_at`.
- **RLS por papel** (`users.role`): `admin` vê tudo; `coordinator` vê a própria escola; `teacher` vê os próprios alunos; `aee` vê os alunos atribuídos. Definir as policies sobre `agent_run_logs` usando `school_id`.
