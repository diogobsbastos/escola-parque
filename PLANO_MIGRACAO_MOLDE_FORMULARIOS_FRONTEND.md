# Plano de Migração — Molde / PDF & Detecção, Novo Questionário e Correção

> **Autor:** AGENTE1 · **Data:** 2026-06-16
> **Escopo:** portar para o frontend Next.js (`innova-front`) os subsistemas de
> **Treinamento de Molde de Prova** (com ênfase em **PDF & Detecção**), **Novo
> Questionário** e **Correção de Questionários preenchidos**, com comunicação via
> **API (FastAPI novo)** e persistência no **Supabase `innova-v2-br`**.
> **Status:** plano para aprovação — **nenhum código foi alterado ainda**.
> **Base:** `ARQUITETURA_API_MOLDE_FORMULARIOS.md`, `DOC_MOLDE_E_FORMULARIOS.md`,
> `PLANO_ACAO_MOLDE_FORMULARIOS.md`, `DESIGN_F1_AGENTE1_SUPABASE.md`,
> `MODELO_LOGINS_HIERARQUIA.md` + leitura do schema Drizzle real e do banco vivo.

---

## 0. TL;DR (decisões desta sessão)

- **Começamos pelo Molde / PDF & Detecção** (sua prioridade), mas a fundação P0
  (tirar o molde do disco efêmero) vem **antes** de qualquer UI nova.
- **Camada de visão computacional = serviço FastAPI novo** no backend
  (`innova_bridge`). OpenCV (template matching) e PyMuPDF (rasterização) **não
  rodam no browser nem no Next.js** — ficam 100% em Python. O frontend chama a API
  por **server actions** (padrão real do `innova-front`), nunca direto do browser.
- **Persistência no Supabase desde a v1.** A "sessão" de treinar/calibrar/corrigir
  é **uma linha no banco** (pausável, retomável, auditável). Acaba o dado em disco.
- **NÚCLEO NOVO — Modelo de Sessões Dinâmicas (§8b).** O molde deixa de ser uma
  lista fixa de 46 checkboxes e passa a ser **composto por Sessões** declaradas
  (região + estilo + estratégia de LLM por sessão). Saída = um **mapa mastigado**
  (`Página;Sessão;Estilo;Resultado`) fatiado por página. Mesmo núcleo serve para
  (A) o formulário de captação do **Agente 1** e (B) a **correção de prova** (futuro).
- **RBAC:** Molde e Correção ficam disponíveis para `super_admin`, `admin`
  (school_admin), `teacher` (professor) e `aee` (apoio), com escopo por colégio/aluno.
- **Entregável desta sessão:** este documento. Código vem na próxima, fatiado.

---

## 1. O que estamos migrando (mapa do legado → alvo)

| Subsistema (legado Streamlit) | Arquivos-fonte | Alvo no frontend |
|---|---|---|
| **Treinamento de Molde** (4 fases) | `pagina_molde.py`, `backend_molde.py`, `gerar_molde.py` | Wizard Next.js + API FastAPI `/moldes/*` |
| **PDF & Detecção** (fase 2, o coração) | `detectar_candidatos_para_molde`, `_localizar_via_template`, `rasterizar_pagina` | API FastAPI `/moldes/detectar` (Python puro) + canvas no frontend |
| **Calibração visual** (fase 3) | `streamlit-image-coordinates`, `molde_manuais` | Canvas interativo (react-konva) no Next.js |
| **Correção / OCR** | `backend_ocr.py::analisar_com_treinamento`, `pagina_professores.py` | API FastAPI `/correcoes` + tabela de histórico + UI |
| **Novo Questionário** | `aluno_questionario_base.py`, `pagina_questionario_base.py` | UI Next.js + tabelas já existentes (`questionnaire_*`) |
| **Formulários / schemas NEEI** | `pagina_formularios*.py`, `innova_bridge/formularios/*` | (fase posterior) API `/formularios/schemas/*` |

**Como cada um conecta ao resto:** o molde treinado é consumido pelo OCR; o
resultado do OCR alimenta a correção; o questionário preenchido alimenta o
Agente 1 → PAI. Os três compartilham o mesmo banco e a mesma API.

---

## 2. Estado real verificado (não suposições)

**Repositórios**
- `escola-parque` — Streamlit/Python. Tem todo o motor de molde/OCR/formulários.
- `innova-front` — **Next.js 16, App Router, Tailwind v4, shadcn/ui (paleta
  Burgundy Heritage), Drizzle ORM, Supabase Auth/Storage.**
  Convenção declarada: **server actions, não REST** (`actions.ts` ao lado da
  página); clientes nunca chamam Supabase direto; RLS ligado em toda tabela.

**Banco vivo `innova-v2-br` (sa-east-1, ACTIVE_HEALTHY) — 25 tabelas:**
- Fluxo de questionário **já existe com dados reais**: `questionnaires` (1),
  `questionnaire_sections` (2), `questionnaire_field_responses` (42),
  `questionnaire_uploads` (5), `pais` (28), `agent_run_logs` (27),
  `agent_configs` (1), `provider_keys` (3), `model_pricing` (7).
- **Não existe nenhuma tabela de Molde nem de correção de prova.** O molde ainda
  vive em `moldes/*.json` + `*.pdf` no disco da VPS → **risco P0 de perda total.**

**Tensão de arquitetura resolvida nesta sessão:**
- O doc antigo (`ARQUITETURA_API_MOLDE_FORMULARIOS.md`) assume **FastAPI REST +
  MUI**. O frontend real é **shadcn + server actions**. → **Convenção válida = a
  do `innova-front`**: o browser fala com *server actions*; as server actions
  falam com o FastAPI (para a parte Python pesada) e/ou com o Postgres via Drizzle.

---

## 3. Arquitetura alvo

```
[Browser / React (shadcn/ui, Next 16)]
   |  (nunca chama Python nem Supabase direto)
   v
[Next.js server actions  (innova-front)]
   |- Drizzle -> Postgres (Supabase)        <- leitura/escrita de metadados, sessões, resultados
   |- Supabase Storage                      <- PDFs de referência, scans de prova, imagens rasterizadas
   |- fetch -> [API FastAPI no innova_bridge] <- SÓ a parte Python pesada
                 |- PyMuPDF: rasterizar PDF (DPI=200)
                 |- OpenCV: template matching multi-escala + NMS (detecção de checkbox)
                 |- OCR/Gemini: classificar marcado/não-marcado (correção)
                 |- valida JWT do Supabase (GoTrue) + usa service role internamente
```

**Princípios herdados dos docs (mantidos):**
- **Motor no backend, UI no frontend.** Parsing, OpenCV e chaves no servidor.
- **Tudo no Postgres desde a v1.** Sessão = linha no banco (auditável, retomável).
- **Backend Python é o superconjunto.** O frontend é cliente fino; config de
  provedores/chaves, engenharia de prompt e visão computacional são exclusivos do Python.
- **Auth:** Supabase Auth (GoTrue). Frontend manda JWT; FastAPI valida o JWT.

---

## 4. Serviço FastAPI novo (`innova_bridge`)

Serviço uvicorn na VPS, adicionado à whitelist do auto-deploy e à lista de serviços.

### 4.1 Endpoints — Molde
| Método | Rota | Faz | Python que reusa |
|---|---|---|---|
| `GET` | `/moldes` | Lista moldes (do Postgres) | `listar_moldes()` (agora lê BD) |
| `GET` | `/moldes/{id}` | Lê um molde | `carregar_molde()` |
| `POST` | `/moldes/detectar` | **PDF & Detecção** — recebe PDF (multipart), rasteriza, roda template matching, devolve candidatos + URLs de imagem por página | `detectar_candidatos_para_molde()`, `_localizar_via_template()`, `rasterizar_pagina()` |
| `POST` | `/moldes` | Salva molde (nome + gabarito + quadrados) | `montar_molde_final()`, `salvar_molde()` (grava BD + Storage) |
| `PUT` | `/moldes/{id}` | Atualiza/recalibra | idem |
| `DELETE` | `/moldes/{id}` | Remove (BD + Storage) | `deletar_molde()` |
| `GET` | `/moldes/{id}/pagina/{n}` | Serve a imagem rasterizada de uma página | `rasterizar_pagina()` |
| `POST` | `/moldes/gabarito/parse` | Faz parse de gabarito (JSON/CSV/XLSX/TXT/MD) | `parse_gabarito_arquivo()` |
| `GET` | `/moldes/gabarito/padrao` | Retorna o GABARITO_OFICIAL (46 frases) | `gabarito_padrao_como_lista()` |

### 4.2 Endpoints — Correção (OCR)
| Método | Rota | Faz | Python que reusa |
|---|---|---|---|
| `POST` | `/correcoes` | Sobe prova preenchida (PDF/scan) + molde → roda OCR → grava resultado | `analisar_com_treinamento()` |
| `GET` | `/correcoes/{id}` | Lê resultado | novo (lê BD) |
| `GET` | `/correcoes?aluno_id=&molde_id=` | Histórico | novo (lê BD) |

### 4.3 Endpoints — Saúde / Auth
- `GET /health` (heartbeat — espelha o padrão `python_worker_heartbeat`).
- Toda rota valida o **JWT do Supabase** e checa **role** (ver §7).

### 4.4 Higiene aproveitada da migração (do `PLANO_ACAO`)
- **P3 (quick win):** unificar o `GABARITO_OFICIAL` (hoje duplicado em
  `backend_molde.py` e `gerar_molde.py`, com o typo "mantener"->"manter") numa
  fonte única importada pelos dois.
- **Fallback de transição:** durante a migração, ler molde do BD com fallback pro
  disco, para não derrubar o que já roda.

---

## 5. Migrações de schema (Supabase + espelho Drizzle)

> Regra de ouro do projeto: **o Drizzle (`src/db/schema.ts`) é a fonte da verdade.**
> Toda DDL aplicada via `apply_migration` precisa ser espelhada no Drizzle na
> mesma leva, senão dá drift. Nada destrutivo sem OK.

### 5.1 `exam_templates` (o molde — tira do disco, P0)
```
id uuid pk · school_id uuid fk · name text · version int
kind text                   -- 'agente1_intake' | 'exam_correction'  (as duas aplicações, §8b)
definition jsonb            -- o molde no NOVO formato de Sessões Dinâmicas (§8b): paginas + sessions[]
ref_pdf_path text           -- Supabase Storage: bucket exam-templates/
dpi_referencia int · qtd_sessoes int · template_layout text
is_active bool · created_by uuid fk users · created_at / updated_at
```
- O `definition` agora segue o **shape de Sessões Dinâmicas** (ver §8b), e não mais
  a lista plana de 46 quadrados. O formato v2.0 antigo é importável como caso
  particular (cada checkbox vira uma sessão de estilo `vertical_single`).
- Migração de dados: importar os `moldes/*.json` + `*.pdf` que ainda existirem em disco.
- **Evolução opcional:** se as sessões precisarem de queries relacionais, normalizar
  `definition.sessions[]` numa tabela `template_sessions` no futuro. Por ora, jsonb
  basta e mantém a flexibilidade (formulários nunca iguais).

### 5.2 `exam_corrections` (resultado de OCR, com histórico — P1)
```
id uuid pk · school_id uuid fk · template_id uuid fk exam_templates
student_id uuid fk · professor_id uuid fk users
result jsonb                -- por seção: [{pergunta, marcado}]
score numeric · confidence numeric · needs_review bool
agent_version text · created_at
```
- Resolve o problema do `ocr_cache_<id>.json` sobrescrito (sem histórico hoje).

### 5.3 (Opcional fase posterior) `form_schemas`
- Para os schemas NEEI saírem do disco e terem flag `is_active` explícita
  (hoje "ativo" = primeiro arquivo da lista, frágil). **Fora do MVP do molde.**

### 5.4 Storage (buckets)
- `exam-templates/` — PDF de referência de cada molde.
- `exam-submissions/` — scans de prova preenchida.
- (imagens rasterizadas podem ser servidas on-the-fly pela API ou cacheadas aqui.)

---

## 6. Frontend Next.js (`innova-front`)

### 6.1 Rotas (App Router)
- `/app/moldes` — lista de moldes (grid shadcn).
- `/app/moldes/novo` — **wizard de 4 fases** (stepper), orientado a **Sessões** (§8b):
  1. **Sessões** — inserir sessões por página: marcar região, escolher o **estilo**
     (vertical / horizontal / OCR / OCR hierárquico) e configurar rótulos + estratégia
     de LLM. (Para `agente1_intake`, ainda dá pra partir do gabarito padrão de 46.)
  2. **PDF & Detecção** — upload do PDF → chama `/moldes/detectar` → sugere regiões/candidatos.
  3. **Calibração** — canvas com a imagem da página; ajustar/descartar/adicionar região de sessão por clique; editar estilo e mapeamento de cada uma.
  4. **Salvar** — confirma `template_layout`/`kind` e grava.
- `/app/correcao` — subir prova preenchida → escolher molde → ver resultado/histórico.
- `/app/questionario` — Novo Questionário + status (gerando/pronto/offline do worker).

### 6.1b Layout da tela de PDF (subir prova/formulário) — replica o modelo REAL do backend

> **Confirmado lendo `pagina_molde.py` (v4) por inteiro.** O frontend **replica o
> mesmo modelo que já existe** no Streamlit — não inventa fluxo novo.

**Padrão existente (a manter):**
- **List-detail:** tela de **lista de moldes** (criar/editar/deletar) → **editor**
  com **menu de fases no topo, sequencial e gated** (Fase 2 só com gabarito pronto;
  Fase 3 só com PDF detectado; Fase 4 só com >=1 quadrado) + barra de progresso.
- **Fase "PDF & Detecção":** dar nome ao molde, subir PDF, **Detectar candidatos**
  (template matching) → pula para Calibração.
- **Fase "Calibração" (o seu modelo de miniaturas):** layout em **2 colunas
  `[1, 4]`**:
  - **Esquerda — miniaturas clicáveis** de cada página (navegador), cada uma com
    **emoji de status** (vazia · auto · editada), **contagem** de quadrados
    e indicador da **página atual**. Clicar troca a página ativa.
  - **Direita — canvas** da página ativa: anota quadrados (verde=auto, vermelho=manual),
    com **modos de clique Adicionar / Descartar** e um **editor por quadrado**
    (escolher a frase/valor associado).
- **Fase "Salvar":** resumo + **seletor de `template_layout`**
  (`multipla_escolha_esquerda` recomendado · `hibrido_sem_corte` legado) +
  salvar **COMPLETO/PARCIAL** + preview do JSON.

**O que muda na migração (sem perder o padrão):**
- A coluna direita ganha a **gestão de Sessões** (§8b): **Incluir sessão**, **Editar
  sessão existente**, escolher **estilo** (vertical/horizontal/OCR/OCR hierárquico),
  os **valores dos quadrados** (estilos 1/2) ou o **retângulo** (estilos 3/4) e a
  **estratégia de LLM** por sessão.
- O "editar frase por quadrado" do legado vira "**valor por quadrado**" dentro da sessão.
- Mesma tela serve ao **molde de captação (Agente 1)** e ao **molde de correção** (`kind`).

### 6.2 Componentes-chave
- **Stepper** + estado local (`useState`) por fase; persiste no backend só ao salvar.
- **Canvas de seleção/calibração**: `react-konva` (precisão de pixel), com **dois
  modos**: (1/2) **clique em quadrados** numerados, cada um recebendo um **valor**;
  (3/4) **desenho de retângulo** por arraste. Reposiciona/redimensiona; itens
  numerados por sessão sobre a imagem servida pela API. É o ponto mais complexo —
  protótipo isolado primeiro.
- **Data grid** (shadcn/table) para gabarito e histórico de correções.
- **Server actions** (`actions.ts`) fazem o proxy para o FastAPI e o Drizzle.

### 6.3 Estado: hoje (`st.session_state`) → frontend
| Hoje | Frontend |
|---|---|
| `molde_gabarito_lista` | `useState` no wizard, salvo no BD ao concluir |
| `molde_candidatos`/`_descartados`/`_manuais` | estado local do step de calibração → payload do POST |
| `molde_paginas` (imagens np.array) | **não vive no front** — servidas como URL pela API |
| `molde_fase_ativa` | `activeStep` do stepper |

### 6.4 Template dinâmico (cor, fontes e modulações) — design system

As telas de molde **seguem o padrão de template do `innova-front`**, que já é
**dinâmico / white-label**, com as melhores ferramentas do stack:

- **Cores por colégio:** `schools.brand_primary` (claro) e `schools.brand_primary_dark`
  (escuro) já existem no schema e sobrescrevem `--primary`/`--ring`/`--sidebar-primary`
  via `<style>` server-side. As telas de molde **herdam** essas variáveis — nada de
  cor hardcoded. Default global = paleta **Burgundy Heritage** (`#911256` / `#D14C84`).
- **Tema claro/escuro:** via `theme-provider` + `theme-toggle` já existentes.
- **Fontes e modulações:** tokens do design system (Tailwind v4 + `globals.css`),
  componentes **shadcn/ui** (`ui/`), espaçamento/raio/tipografia padronizados.
- **Consistência:** reusar os primitivos existentes (botões, cards, tabela, stepper,
  dialog) em vez de criar estilo próprio — o molde parece parte do produto, não um anexo.

> Ou seja: o molde no frontend não inventa visual — **consome o template dinâmico**
> (cor + fonte + modulação) que o resto do `innova-front` já aplica por colégio.

---

## 7. RBAC (papéis e escopo)

`user_role` no enum: `admin, coordinator, teacher, aee, super_admin, student, guardian`.
Disponibilizar Molde + Correção para **super_admin, admin, teacher (professor),
aee (apoio)** — e coordinator conforme escopo a definir.

| Papel | Molde | Correção |
|---|---|---|
| `super_admin` | CRUD global, todos os colégios | tudo |
| `admin` (school_admin) | CRUD no próprio colégio | tudo do colégio |
| `teacher` (professor) | usar moldes; criar/editar (a confirmar) | corrige provas dos seus alunos |
| `aee` (apoio) | usar moldes | corrige/lê dos alunos que acompanha |

- **RLS por papel** sobre `exam_templates` / `exam_corrections` usando `school_id`
  (e `student_id` para teacher/aee), espelhando a política já desenhada para
  `agent_run_logs` no `DESIGN_F1`.
- Hoje qualquer usuário logado no Streamlit cria/deleta molde — **endurecer** isso
  no Next.js por role é requisito da migração.

---

## 8. Fases de execução (priorizadas)

> Ordem deriva dos riscos do `PLANO_ACAO`: persistência antes de UI.

**Fase 0 — Fundação (P0/P1) · pré-requisito**
- `exam_templates` + `exam_corrections` no Supabase + espelho Drizzle.
- Buckets de Storage. Importar moldes do disco. Esqueleto FastAPI (`/health` + 1 real).

**Fase 1 — PDF & Detecção + Modelo de Sessões (sua prioridade)**
- Definir o shape de **Sessões Dinâmicas** (§8b) no `definition` jsonb + espelho Drizzle.
- `POST /moldes/detectar` (rasterização + template matching, sugere regiões) e `GET .../pagina/{n}`.
- `POST /moldes/processar` (documento + molde → **mapa** `Página;Sessão;Estilo;Resultado`).
- `backend_molde.py` lendo/gravando do BD (fallback disco). P3 (gabarito único).

**Fase 2 — Wizard de Molde no frontend (orientado a Sessões)**
- Rotas/stepper + **inserir Sessões** (estilo + região + estratégia de LLM por sessão).
- **Canvas de calibração** (react-konva) para marcar/ajustar regiões.
- Salvar molde via server action → FastAPI/BD.

**Fase 3 — Correção (OCR) end-to-end**
- `POST /correcoes` + histórico em `exam_corrections` + UI de resultado.

**Fase 4 — Novo Questionário no frontend**
- UI de intake (já há base no banco) + status do worker (heartbeat online/offline).

**Fase 5 — Formulários/schemas NEEI (posterior)**
- `form_schemas` com `is_active` explícito + editor + validação contra CSV.

---

## 8b. APRIMORAMENTO CENTRAL — Modelo de Sessões Dinâmicas

> Aprimoramento pedido pelo Marcos. É o novo **núcleo** do molde. Como os formulários
> nunca são iguais, o molde deixa de ser uma lista fixa de 46 checkboxes e passa a
> ser **composto por Sessões declaradas**. Cada Sessão é uma **região da página**
> com um **estilo** e uma **estratégia de LLM próprios**. Isso vale tanto para
> montar o formulário de captação do Agente 1 quanto para a correção de prova.

### 8b.1 Conceito

Um molde = um conjunto de **Sessões**. Para cada sessão o usuário define, na hora
da criação: **em qual página está**, **qual a região** (posição), **qual o estilo**
e **como a LLM deve procurar a resposta** (modelo + instrução). Na hora de processar
um documento preenchido, **fatiamos cada página pela região de cada sessão** e
enviamos à LLM **uma sessão por vez, tudo mastigado** (prompt específico do estilo).
Isso é mais confiável e mais barato que jogar a página inteira na LLM.

### 8b.2 Os 4 estilos de Sessão

| # | Estilo | Seleção na imagem | Config na criação | O que a LLM devolve |
|---|---|---|---|---|
| 1 | **Vertical** (`vertical_single`) | **clique nos quadrados** (numerados) | um **valor por quadrado** (ex.: 1=bom, 2=muito bom, 3=ótimo); marcar **qual é a certa** | valor do quadrado marcado |
| 2 | **Horizontal** (`horizontal_labeled`) | **clique nos quadrados** (numerados) | **quantos** quadrados + **um valor por quadrado** | valor(es) do(s) quadrado(s) marcado(s) |
| 3 | **Leitura de OCR** (`ocr_text`) | **desenhar retângulo** com o mouse | região de texto livre | string lida |
| 4 | **OCR hierárquico** (`ocr_hierarchical`) | **desenhar retângulo** com o mouse | níveis **1-2-3** (ranking/grau) | nível/ranking lido |

> **Resumo da interação:** estilos **1 e 2 = quadrados por clique** (cada quadrado
> ganha um valor); estilos **3 e 4 = retângulo desenhado** com o mouse.

### 8b.3 Codificação do mapa (a saída "mastigada")

Uma linha por sessão: **`Página ; Sessão ; Estilo ; Resultado`**.

Exemplo: `1;2;3;2` → **Página 1 · Sessão 2 · Estilo 3 (OCR) · Resultado 2**.

O mapa completo é a lista dessas linhas — é o que a LLM recebe pré-fatiado e o que
guardamos como resultado do processamento.

### 8b.4 Estrutura de dados (`definition.sessions[]`)

```jsonc
{
  "versao": "3.0-sessoes",
  "kind": "agente1_intake",          // ou "exam_correction"
  "paginas": [
    { "numero": 1, "largura_px": 1654, "altura_px": 2339, "imagem_ref": "storage://..." }
  ],
  "sessions": [
    {
      "numero": 1,                   // nº da sessão no molde
      "pagina": 1,
      "estilo": "vertical_single",   // ESTILOS 1/2 = quadrados por clique
      "quadrados": [                 // cada quadrado: posição (clicada) + VALOR
        { "n": 1, "x": 181, "y": 947, "w": 37, "h": 31, "valor": "bom" },
        { "n": 2, "x": 181, "y": 985, "w": 37, "h": 31, "valor": "muito bom" },
        { "n": 3, "x": 181, "y": 1023, "w": 37, "h": 31, "valor": "ótimo" }
      ],
      "llm": { "modelo": "models/gemini-2.5-flash", "instrucao": "...", "estrategia": "crop_estreito" },
      "mapeamento": { "field_id": "capabilities.reading.level", "questao": null, "pontos": null }
    },
    {
      "numero": 2,
      "pagina": 1,
      "estilo": "ocr_text",          // ESTILOS 3/4 = retângulo desenhado com o mouse
      "regiao": { "x": 181, "y": 1120, "w": 420, "h": 90 },   // px @ DPI ref
      "llm": { "modelo": "models/gemini-2.5-flash", "instrucao": "Como a LLM deve ler esta região", "estrategia": "pagina_inteira" },
      "mapeamento": { "field_id": "characterization.student_summary", "questao": null, "pontos": null }
    }
  ]
}
```

- **Estilos 1/2** carregam `quadrados[]` (cada um com `x,y,w,h` clicado + `valor`).
  O `valor` é o significado do quadrado (ex.: 1=bom, 2=muito bom, 3=ótimo) — é o que
  vira o **Resultado** quando aquele quadrado está marcado.
- **Estilos 3/4** carregam um único `regiao` (o retângulo desenhado).

### 8b.5 Fluxo (criação → processamento)

1. **Criação (wizard):** usuário **insere sessões** página a página. A seleção na
   imagem depende do estilo: **estilos 1/2 (vertical/horizontal) = clique nos
   quadrados** (cada quadrado é numerado e recebe um **valor**, ex.: 1=bom,
   2=muito bom, 3=ótimo); **estilos 3/4 (OCR/OCR hierárquico) = desenhar o
   retângulo** da região com o mouse. Depois escolhe o **estilo** e a **estratégia
   de LLM**. A detecção por template matching (§4.1) só **sugere** os quadrados — a
   marcação manual é a fonte da verdade.
2. **Processamento (`POST /moldes/processar`):** dado um documento preenchido + um
   molde → para cada sessão, **recorta a região** na página → monta o **prompt
   específico do estilo** com o **modelo da sessão** → LLM responde → monta o **mapa**.
3. **Persistência:** o mapa vira `exam_corrections.result` (app B) ou
   `questionnaire_field_responses` (app A), conforme o `kind`/`mapeamento`.

### 8b.6 Duas aplicações sobre o mesmo núcleo

- **(A) Formulário de captação do Agente 1** (`kind = agente1_intake`): cada sessão
  tem `mapeamento.field_id` canônico → o resultado vira linha em
  `questionnaire_field_responses` → alimenta o Agente 1 → PAI. Isso torna a captação
  **dinâmica** (formulários diferentes, mesmo pipeline).
- **(B) Correção de prova** (`kind = exam_correction`, **futuro, já modelado**): cada
  sessão tem `mapeamento.questao`/`pontos` → o resultado alimenta o score em
  `exam_corrections`. O professor "marca como iremos corrigir" escolhendo o estilo
  e a estratégia de cada sessão.

### 8b.7 Impacto na API e no wizard

- **API:** acrescenta `POST /moldes/processar` (documento + molde → mapa). A
  detecção e o OCR passam a respeitar **modelo/estratégia por sessão** (não mais um
  modelo único global).
- **Wizard (Fase 1):** deixa de ser "lista de 46 frases" e passa a ser **"inserir
  Sessões"** — por página, marcar região, escolher estilo, configurar. As demais
  fases (detecção, calibração, salvar) seguem, agora orientadas a sessões.

### 8b.8 Pontos a refinar (iterativo — não bloqueiam o escopo)

- Indexação de página (0 ou 1) e da sessão — padronizar.
- Estilo **Horizontal**: é seleção única ou múltipla? (o "quantas" sugere múltipla).
- Formato exato do **Resultado** por estilo (índice, texto, ou nível).
- **OCR hierárquico**: o que exatamente significa 1-2-3 (grau de domínio? ordem?).
- Reaproveitar `referencia_branco.jpg` (template do checkbox) só para os estilos 1/2.

**Decidido:** seleção na imagem é por estilo — **estilos 1/2 = clique nos quadrados**
(numerados, cada um com um **valor**, ex.: 1=bom, 2=muito bom, 3=ótimo);
**estilos 3/4 = retângulo desenhado** com o mouse. A detecção automática só sugere
os quadrados; a marcação manual prevalece.

---

## 9. Riscos e decisões em aberto

1. **Calibração visual** é o item mais complexo — pode-se manter no Streamlit
   temporariamente (sugestão do próprio doc) se o canvas atrasar as outras fases.
2. **Correção automática: OCR/scan vs digital** — `MODELO_LOGINS_HIERARQUIA`
   deixa essa decisão em aberto. Este plano assume **OCR/scan** (reusa o motor atual).
3. **Escopo de criação de molde por `teacher`** (cria ou só usa?) — confirmar.
4. **Migração dos moldes em disco**: rodar o import antes de qualquer limpeza de
   container, senão perda irreversível.
5. **DPI fixo (200)**: provas com layout levemente diferente exigem âncoras
   fiduciais (já capturadas no molde, hoje não usadas ativamente) — fica para evolução.

---

## 10. Verificação (como vamos provar que funciona)

- **Detecção:** rodar `/moldes/detectar` no PDF de referência e conferir que a
  contagem de candidatos bate com o molde legado (`molde_prova_oficial.json`, 46).
- **Round-trip de molde:** salvar via API → reler → diff contra o JSON legado
  (mesmos `quadrados`, `frase_id`, `secao`, `template_layout`).
- **Correção:** rodar OCR numa prova conhecida e comparar marcado/não-marcado
  com o `ocr_cache` legado.
- **RBAC:** testar cada papel (super_admin/admin/teacher/aee) contra as policies RLS.
- **Sem regressão:** o fluxo de questionário/PAI existente continua intacto.

---

## 11. Próximo passo proposto

Com a aprovação deste plano, a próxima sessão começa pela **Fase 0** (schema
`exam_templates`/`exam_corrections` + espelho Drizzle + esqueleto FastAPI) e já
emenda a **Fase 1** (`/moldes/detectar`), que é o PDF & Detecção priorizado.
