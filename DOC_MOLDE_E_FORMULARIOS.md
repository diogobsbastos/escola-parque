# Documentação — Treinamento de Molde & Formulários (backend Escola Parque V3)

> **Gerado em 2026-06-16 para handoff e para guiar a reimplementação no frontend (Next.js).**
> Leia junto com `MAPA_ARQUITETURA.md` e `HANDOFF_SISTEMA_DUPLO_SUPABASE.md`.

---

## Visão geral

O sistema Escola Parque V3 (Streamlit + FastAPI + Supabase) tem dois subsistemas independentes que hoje vivem no backend Python e precisam ser portados para o frontend Next.js:

| Subsistema | Propósito curto | Usuário principal |
|---|---|---|
| **Treinamento de Molde** | Ensinar ao motor de OCR onde estão os checkboxes de uma prova física e quais frases eles representam | Administrador / coordenador |
| **Formulários (schemas NEEI)** | Gerenciar os schemas declarativos do questionário pedagógico preenchido pelo professor/AEE no Google Forms | Administrador / coordenador de AEE |

Os dois subsistemas se conectam ao resto do sistema de formas distintas:

- **Molde → OCR**: o molde treinado é consumido por `backend_ocr.py` na função `analisar_com_treinamento`. Quando um professor sobe um PDF de questionário preenchido, o motor usa o molde para saber onde olhar na imagem e que frase cada checkbox representa.
- **Formulários (schemas NEEI) → PAI**: os schemas NEEI definem a estrutura do questionário respondido pelo professor via Google Forms. O adapter Python converte o CSV exportado do Forms para o formato canônico (Pydantic), que alimenta o `ProfileBuilderAgent` para gerar o PAI (Plano de Adaptação Individual) do aluno.

Nenhum dos dois subsistemas está integrado ao Supabase — ambos usam armazenamento em disco (JSON local).

---

## Área 1 — Treinamento de Molde

### O que é / para que serve

Um **molde** é um arquivo JSON que descreve a localização pixel-a-pixel de cada um dos 46 checkboxes de um questionário de prova físico (impresso e escaneado), mapeando cada checkbox para uma frase pedagógica específica e sua seção. O molde é treinado uma vez por layout de prova e reutilizado indefinidamente para processar qualquer PDF com esse mesmo layout.

O fluxo completo é: (1) treinar o molde com um PDF de referência → (2) salvar o JSON + PDF de referência em disco → (3) selecionar o molde ao subir uma prova de aluno/professor → (4) o motor OCR usa as coordenadas do molde para recortar cada região da imagem e perguntar à LLM (Gemini) se o checkbox está marcado.

### Arquivos envolvidos

| Arquivo | Papel |
|---|---|
| `pagina_molde.py` | UI Streamlit completa (v4) — fluxo de 4 fases: gabarito → PDF & detecção → calibração → salvar |
| `backend_molde.py` | Toda a lógica de I/O, detecção OpenCV, montagem e salvamento do molde |
| `gerar_molde.py` | Script CLI standalone (sem Streamlit) para gerar `molde_prova_oficial.json` a partir de um PDF |
| `molde_prova_oficial.json` | Instância de molde de referência com 46 quadrados em 3 páginas (formato v1.0) |
| `moldes/` | Pasta em disco onde ficam todos os moldes salvos (`<nome>.json` + `<nome>.pdf`) |
| `banco_contexto/treino_visao/referencia_branco.jpg` | Template de imagem do checkbox em branco usado no template matching |
| `backend_ocr.py` | Consumidor do molde — função `analisar_com_treinamento(pdf_path, molde_nome)` |
| `pagina_professores.py` | Seletor de molde na aba "Questionário Base" do prontuário do professor |

### Fluxo de uso

**Fase 1 — Gabarito (lista de frases)**
1. Usuário abre a página "Treinamento de Molde" (`renderizar()` em `pagina_molde.py`).
2. O sistema mostra a lista de moldes salvos (`listar_moldes()`).
3. Usuário clica "Novo Molde" → entra no editor com o gabarito padrão já carregado (46 frases do `GABARITO_OFICIAL`).
4. Usuário pode: manter o padrão, editar frases, ou subir um arquivo externo (JSON / CSV / XLSX / TXT / MD) via `parse_gabarito_arquivo()`.
5. Estado: `st.session_state["molde_gabarito_lista"]` = lista de `{id, frase, secao}`.

**Fase 2 — PDF & Detecção**
6. Usuário faz upload do PDF de referência (prova impressa escaneada).
7. `detectar_candidatos_para_molde(pdf_path)` rasteriza todas as páginas (PyMuPDF, DPI=200) e roda template matching multi-escala (`_localizar_via_template`) contra `referencia_branco.jpg`.
8. Retorna lista de candidatos `{pag, x, y, w, h, score, stddev}` ordenada por (página, y, x).
9. Estado: `st.session_state["molde_candidatos"]`, `st.session_state["molde_paginas"]`.

**Fase 3 — Calibração**
10. Usuário vê a imagem de cada página anotada com os candidatos detectados (retângulos numerados).
11. Pode descartar candidatos falsos positivos (marcando no set `molde_descartados`) ou adicionar quadrados manualmente clicando na imagem (via `streamlit-image-coordinates`, armazenados em `molde_manuais`).
12. Pode editar a frase associada a cada quadrado via dropdown/selectbox.

**Fase 4 — Salvar**
13. Sistema autodetecta o `template_layout` (`multipla_escolha_esquerda` ou `hibrido_sem_corte`) via `detectar_template_layout()`.
14. Usuário confirma o template e clica "Salvar COMPLETO" ou "Salvar PARCIAL".
15. `montar_molde_final()` constrói o dict final e `salvar_molde(nome, dados)` grava `moldes/<nome>.json`.
16. `salvar_pdf_referencia(nome, pdf_path)` copia o PDF para `moldes/<nome>.pdf`.
17. Verificação forense pós-save é exibida (diagnóstico expandível).

**Consumo pelo OCR (em `pagina_professores.py`)**
18. Na aba "Questionário Base" do professor, o seletor chama `listar_moldes()` e exibe os moldes disponíveis.
19. Ao clicar "Iniciar Análise", `ocr.extrair_texto_pdf(doc_pdf)` salva o PDF em disco temporariamente.
20. `ocr.analisar_com_treinamento(caminho_temp, molde_nome=molde_escolhido)` carrega o molde com `carregar_molde()`, extrai as regiões de imagem conforme as coordenadas, e envia cada recorte ao Gemini para classificação (marcado/não marcado).
21. Resultado salvo em `ocr_cache_{professor_id}.json` na raiz do projeto.

### Modelo de dados

**Molde em disco — `moldes/<nome>.json` (formato v2.0)**

```json
{
  "versao": "2.0",
  "nome": "Prova_Padrao_v1",
  "criado_em": 1716000000,
  "fonte_pdf": "prova_referencia.pdf",
  "dpi_referencia": 200,
  "qtd_quadrados": 46,
  "qtd_frases_gabarito": 46,
  "template_layout": "multipla_escolha_esquerda",
  "config_template": {
    "margem_id_px": 90,
    "margem_marca_px": 60
  },
  "gabarito_frases": [
    {"id": 1, "frase": "Tem dificuldade para entender enunciados longos", "secao": "SEÇÃO 2 - LINGUAGEM E COMPREENSÃO"},
    "..."
  ],
  "paginas": {
    "0": {
      "altura_px": 2339,
      "largura_px": 1654,
      "ancoras_fiduciais": [
        {"nome": "cabecalho_pag0_0", "x": 171, "y": 226, "w": 976, "h": 57}
      ],
      "quadrados": [
        {
          "id": 1,
          "frase_id": 1,
          "frase": "Tem dificuldade para entender enunciados longos",
          "secao": "SEÇÃO 2 - LINGUAGEM E COMPREENSÃO",
          "pag": 0,
          "x": 181, "y": 947, "w": 37, "h": 31,
          "score": 0.738,
          "stddev": 60.6,
          "manual": false
        }
      ]
    }
  }
}
```

**Campos principais por quadrado:**

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | int | Índice ordinal (1..46), define a ordem no gabarito |
| `frase_id` | int | Referência ao `id` em `gabarito_frases` |
| `frase` | str | Texto da frase pedagógica associada |
| `secao` | str | Seção do gabarito (ex.: "SEÇÃO 2 - LINGUAGEM E COMPREENSÃO") |
| `pag` | int | Número da página (0-indexado) |
| `x`, `y` | int | Coordenadas do canto superior esquerdo em pixels (DPI=200) |
| `w`, `h` | int | Largura e altura do checkbox em pixels |
| `score` | float | Score de confiança do template matching (0.0–1.0) |
| `stddev` | float | Stddev da faixa à direita do checkbox (filtro anti-bleed) |
| `manual` | bool | `true` se adicionado manualmente pelo usuário na calibração |

**Gabarito oficial padrão:** 46 frases em 8 seções (SEÇÃO 2 a SEÇÃO 9), com frases fixas hardcoded em `backend_molde.py` como `GABARITO_OFICIAL`. Cada molde pode sobrescrever com seu próprio gabarito dinâmico via `gabarito_frases`.

**Resultado OCR em disco — `ocr_cache_{id}.json`**

```json
{
  "_meta": {
    "molde_usado": "Prova_Padrao_v1",
    "gravado_em": 1716000000,
    "telemetria": {}
  },
  "SEÇÃO 2 - LINGUAGEM E COMPREENSÃO": [
    {"pergunta": "Tem dificuldade para entender enunciados longos", "marcado": true}
  ]
}
```

### Funções-chave do backend

| Função | O que faz | Entradas / Saídas |
|---|---|---|
| `listar_moldes()` | Lista nomes dos moldes em `moldes/*.json` | `→ List[str]` |
| `carregar_molde(nome)` | Lê e retorna o dict JSON do molde | `nome: str → Optional[Dict]` |
| `salvar_molde(nome, dados)` | Grava o JSON em `moldes/<nome>.json` | `→ (bool, str, str)` (ok, msg, path) |
| `deletar_molde(nome)` | Remove JSON + PDF de referência | `→ bool` |
| `detectar_candidatos_para_molde(pdf_path, template_path, dpi)` | Rasteriza PDF e detecta checkboxes via template matching multi-escala com NMS | `→ {paginas_imagens, candidatos, qtd_paginas, qtd_candidatos}` |
| `montar_molde_final(nome, fonte_pdf, quadrados_ordenados, ...)` | Monta o dict completo do molde pronto para salvar, incluindo enriquecimento com frases e autodetecção de layout | `→ Dict` |
| `salvar_pdf_referencia(nome, pdf_path_origem)` | Copia o PDF de referência para `moldes/<nome>.pdf` | `→ (bool, str, str)` |
| `existe_pdf_referencia(nome)` | Verifica se o PDF de referência existe | `→ bool` |
| `carregar_para_edicao(nome)` | Carrega molde + rasteriza PDF para edição (retorna imagens + quadrados + frases) | `→ Dict` |
| `detectar_template_layout(quadrados, dimensoes_pag)` | Autodetecta o template de crop para o OCR (estreito vs. híbrido) | `→ str` |
| `rasterizar_pagina(pdf_path, num_pag, dpi)` | Converte uma página do PDF em imagem OpenCV BGR | `→ np.ndarray or None` |
| `parse_gabarito_arquivo(bytes, nome_arquivo)` | Faz parse de arquivo de gabarito (JSON/CSV/XLSX/TXT/MD) para lista de dicts | `→ (bool, List[Dict], str)` |
| `gabarito_padrao_como_lista()` | Retorna o GABARITO_OFICIAL como lista de `{id, frase, secao}` | `→ List[Dict]` |

### Integrações e dependências

**Molde → OCR (`backend_ocr.py`)**
- `analisar_com_treinamento(pdf_path, molde_nome)`: carrega o molde via `carregar_molde(molde_nome)`, lê as coordenadas por página, rasteriza o PDF do aluno no mesmo DPI de referência, recorta cada região de checkbox, e envia para a LLM (Gemini) classificar se está marcado ou não.
- O campo `template_layout` do molde controla como o recorte horizontal é feito antes de enviar ao Gemini: `multipla_escolha_esquerda` aplica crop estreito (economiza ~89% de tokens); `hibrido_sem_corte` envia a página inteira.
- As `ancoras_fiduciais` (cabeçalhos detectados por morfologia) existem para possível alinhamento futuro de provas com layout levemente diferente — atualmente não são usadas ativamente pelo OCR.

**Molde → Professores (`pagina_professores.py`)**
- Aba "Questionário Base" do prontuário chama `bmolde.listar_moldes()` para popular o seletor.
- Após análise, `bp.associar_molde(prof_id, molde_nome)` registra no banco SQLite local qual molde foi usado (via `backend_professores.py`).

**Dependências de bibliotecas:**
- `PyMuPDF (fitz)`: rasterização de PDF
- `opencv-python (cv2)`: template matching, NMS, morfologia para âncoras
- `numpy`: operações matriciais nas imagens
- `streamlit-image-coordinates`: clique de coordenadas na calibração (componente externo)

---

## Área 2 — Formulários (schemas NEEI)

### O que é / para que serve

Os **formulários** (neste sistema chamados de "schemas declarativos") definem a estrutura do questionário pedagógico NEEI (Núcleo de Ensino e Educação Inclusiva) que é preenchido pelo professor e pelo profissional do AEE via Google Forms. O schema mapeia cada pergunta do formulário (coluna do CSV exportado) para um `field_id` canônico, e também define como converter os valores de texto bruto do CSV para valores canônicos tipados (Pydantic).

Esta área é chamada de "Área 0 — MLOps" no sistema: cuida da infraestrutura de schemas, não das respostas individuais dos alunos.

### Arquivos envolvidos

| Arquivo | Papel |
|---|---|
| `pagina_formularios.py` | UI Streamlit — lista schemas disponíveis, abre editor inline via botão `👁` |
| `pagina_formularios_editor.py` | Editor visual de schemas (3 abas: Mapping, Value Maps, Metadata) |
| `innova_bridge/formularios/schemas/neei_v2_0.json` | Único schema ativo: NEEI v2.0 com 73 field_ids mapeados |
| `innova_bridge/formularios/adapters/from_neei_v2_0.py` | Adapter que converte CSV do Google Forms (v2.0) para formato canônico |
| `innova_bridge/formularios/adapters/from_neei_v3_0.py` | Adapter para versão v3.0 (mais recente, maior) |
| `innova_bridge/formularios/pais_gerados/` | Pasta onde os PAIs gerados ficam armazenados (JSON) |
| `innova_bridge/formularios/responses_v3/` | Respostas brutas do formulário v3 (CSV/JSON armazenados) |
| `pagina_pai_renderer.py` | Renderiza o PAI gerado para visualização (independente dos schemas) |

### Fluxo de uso

**Gerenciamento de schemas (página Formulários)**
1. Usuário abre a página "Formulários" (`render_pagina_formularios()` em `pagina_formularios.py`).
2. Sistema lista todos os arquivos `.json` em `innova_bridge/formularios/schemas/` via `_listar_schemas()`.
3. Para cada schema, exibe um card com: versão, título, número de campos, data de produção.
4. O primeiro schema da lista é marcado como "EM USO" (lógica hardcoded — não há flag no JSON).
5. Usuário clica `👁` para abrir o editor inline (`render_editor_schema(schema_path)`).

**Editor de schema (3 abas)**
- **Aba Mapping**: tabela de `field_id → coluna CSV`, editável. O `field_id` e a categoria são read-only; apenas a coluna do CSV é editável para acomodar variações de versão do Google Forms exportado. Filtro por categoria (Meta, Caracterização, Capacidades, Barreiras, Suportes, Autorizações, Restrições, AEE).
- **Aba Value Maps**: para cada grupo (`capability`, `support`, `authorization`, `has_clinical_report`, `extra_time`), exibe mapeamentos de texto bruto → valor canônico. Usuário pode adicionar novas variações (com/sem acento, typos).
- **Aba Metadata**: edita `schema_version`, `title`, `produced_at`.

**Salvar**
6. "Salvar alterações": sobrescreve o arquivo atual em `innova_bridge/formularios/schemas/`.
7. "Salvar como nova versão": cria automaticamente `neei_v2_(N+1).json` na mesma pasta.
8. "Descartar alterações": limpa o buffer do `st.session_state` sem gravar.

**Validação opcional contra CSV**
9. Se houver um CSV carregado em `st.session_state["ultimo_csv_colunas"]` (importado em outra tela), o editor exibe diff entre colunas do CSV e colunas mapeadas no schema, destacando o que falta em cada lado.

**Relação com a resposta do professor (fluxo de importação)**
10. Quando um professor preenche o formulário NEEI no Google Forms e o administrador exporta o CSV, o adapter (`from_neei_v2_0.py` ou `from_neei_v3_0.py`) lê o CSV, usa o schema para identificar cada coluna, converte os valores textuais pelos `value_maps`, e produz um dict canônico.
11. Esse dict alimenta o modelo Pydantic e depois o `ProfileBuilderAgent` (LLM) que gera o PAI.
12. O PAI gerado é renderizado por `pagina_pai_renderer.py`.

### Modelo de dados

**Schema declarativo — `innova_bridge/formularios/schemas/neei_v2_0.json`**

```json
{
  "schema_version": "NEEI_v2.0",
  "title": "Questionario Integrado de Perfil Pedagogico",
  "produced_at": "2026-05-14",
  "mapping": {
    "meta.student_id": "Nome ou ID anonimizado do estudante",
    "characterization.has_clinical_report_raw": "1.2 Existe laudo ou avaliacao especializada?",
    "capability_2a_01": "2.A — Leitura e compreensao de texto [Le textos curtos do nivel escolar com compreensao]",
    "barriers_3a_raw": "3.A Linguagem e compreensao de enunciados",
    "support_4_01": "4.1 Quando recebe este suporte, o estudante consegue resolver? [...]",
    "auth_statement_fragmentation": "5.1 Intensidade autorizada por dimensao [Fragmentacao de enunciado]",
    "restrictions.specific_restrictions": "6.1 Ha restricoes especificas?",
    "aee.specific_strategies": "7.1 Estrategias especificas que o AEE recomenda"
  },
  "value_maps": {
    "capability": {
      "Realiza sem suporte": "without_support",
      "Realiza com apoio": "with_support",
      "Nao realiza": "cannot",
      "Nao observado": "not_observed"
    },
    "support": {"Sim, sozinho": "yes_alone", "...": "..."},
    "authorization": {"Nao autorizar": "not_authorized", "Leve": "light", "Moderada": "moderate", "Intensa": "intense"},
    "has_clinical_report": {"Existe laudo / avaliacao (preencham a sintese abaixo)": true},
    "extra_time": {"Sim, o estudante deve receber tempo adicional": true}
  }
}
```

**Estrutura de `mapping` (73 field_ids no v2.0):**

| Prefixo do field_id | Categoria | Quantidade approx. |
|---|---|---|
| `meta.*` | Metadados (aluno, professor, data) | 6 |
| `characterization.*` | Caracterização do estudante | 6 |
| `capability_2a_*` a `capability_2d_*` | Capacidades (leitura, escrita, matemática, executivas) | 30 |
| `barriers_3*_raw` | Barreiras pedagógicas observadas | 7 |
| `support_4_*` | Suportes testados | 10 |
| `auth_*` | Autorizações de adaptação + intensidade | 9 |
| `restrictions.*` | Restrições específicas | 2 |
| `aee.*` | Recomendações do AEE | 3 |

**Valores canônicos por tipo:**
- `capability`: `without_support | with_support | cannot | not_observed`
- `support`: `yes_alone | yes_with_support | no | not_tested`
- `authorization`: `not_authorized | light | moderate | intense`
- `has_clinical_report`, `extra_time`: `true | false`

### Funções-chave do backend

| Função / Componente | Arquivo | O que faz |
|---|---|---|
| `render_pagina_formularios()` | `pagina_formularios.py` | Ponto de entrada público chamado pelo `app.py` — lista schemas e renderiza cards |
| `_listar_schemas()` | `pagina_formularios.py` | Lê todos os `.json` de `schemas/`, extrai metadados básicos; retorna lista de dicts |
| `_card_schema(schema, em_uso)` | `pagina_formularios.py` | Renderiza card de um schema com botão de abrir/fechar editor |
| `render_editor_schema(schema_path)` | `pagina_formularios_editor.py` | Editor completo com 3 abas + botões de salvar/descartar |
| `_render_aba_mapping(schema, schema_path)` | `pagina_formularios_editor.py` | Tabela editável de field_id → coluna CSV, com filtro por categoria |
| `_render_aba_value_maps(schema, schema_path)` | `pagina_formularios_editor.py` | Editor de mapeamentos texto bruto → valor canônico por grupo |
| `_next_version_filename(current_filename)` | `pagina_formularios_editor.py` | Incrementa o número de versão do filename (`neei_v2_0.json → neei_v2_1.json`) |
| `_validar_contra_csv(schema)` | `pagina_formularios_editor.py` | Compara colunas mapeadas vs. colunas reais do CSV em `st.session_state` |
| `_hash_schema(schema)` | `pagina_formularios_editor.py` | MD5 12-char do conteúdo do schema (exibido na aba Metadata para controle) |

### Integrações e dependências

**Schemas → Adapters → Modelo Canônico → PAI**
- `from_neei_v2_0.py`: recebe o CSV exportado do Google Forms, usa o schema para mapear colunas, aplica `value_maps` para converter strings para tipos canônicos, e produz um dict compatível com o modelo Pydantic do `innova_bridge`.
- `from_neei_v3_0.py`: versão mais recente (maior, mais campos), mesmo padrão.
- O modelo canônico gerado alimenta o `ProfileBuilderAgent` (LLM Gemini/Anthropic) que escreve o PAI.
- O PAI é renderizado por `pagina_pai_renderer.py` (CSS puro, sem Streamlit nativo para a parte visual — usa `st.markdown(unsafe_allow_html=True)`).

**Sem Supabase:** os schemas ficam em arquivos JSON no disco do servidor. Não há tabela no Supabase para schemas de formulário. As respostas individuais processadas ficam em `innova_bridge/formularios/responses_v3/` e os PAIs gerados em `innova_bridge/formularios/pais_gerados/` — também em disco.

**Seleção do schema "em uso":** atualmente hardcoded como o primeiro arquivo retornado por `sorted(SCHEMAS_DIR.glob("*.json"))` — não há flag `ativo` no JSON nem configuração de qual schema está em uso.

---

## Lacunas, riscos e dívidas técnicas

### 1. Moldes armazenados em disco da VPS — sem versioning e sem backup

Os moldes ficam em `moldes/` na raiz do servidor. Um deploy que recria o container ou limpa o diretório de trabalho apaga todos os moldes treinados. O PDF de referência também fica ali. **Risco crítico**: perda de moldes exige re-treinamento manual.

### 2. Resultado do OCR salvo como `ocr_cache_{id}.json` na raiz do projeto

O arquivo `ocr_cache_<professor_id>.json` é sobrescrito a cada nova análise — não há histórico de múltiplas aplicações de um mesmo professor. Dados de análises anteriores são perdidos silenciosamente. Não há separação por aluno/data/molde — o resultado é monolítico por professor.

### 3. Schema "em uso" é hardcoded como o primeiro da lista

Em `pagina_formularios.py`: `em_uso_default = schemas[0]["filename"]`. Se um novo arquivo for criado com nome alfabeticamente anterior, ele passa a ser o "ativo" sem aviso. Não há mecanismo de promoção/despromoção de versões.

### 4. `pagina_professores.py` — dupla responsabilidade e estado global frágil

A tab "Questionário Base" do professor contém lógica OCR completa copiada de `pagina_alunos.py`. Qualquer correção precisa ser duplicada. O estado de UI (`show_ocr_uploader`, `resultado_ocr`, `ultimo_molde_usado`) vive em `st.session_state` global, sem namespace — risco de colisão se múltiplos prontuários forem abertos na mesma sessão. A função `associar_molde` no SQLite local está presente mas o resultado OCR não é persistido de forma estruturada (só o cache JSON avulso).

### 5. Gabarito duplicado em três lugares

O `GABARITO_OFICIAL` (46 frases) está hardcoded em `backend_molde.py` E em `gerar_molde.py` (como `MAPEAMENTO_FIDEDIGNO`). Qualquer atualização no gabarito precisa ser feita nos dois arquivos manualmente. Há também uma divergência de texto: a frase 14 em `gerar_molde.py` usa "mantener" (espanhol) enquanto `backend_molde.py` usa "manter" (português).

### 6. `streamlit-image-coordinates` — dependência externa sem fallback

A calibração manual da Fase 3 depende inteiramente do pacote `streamlit-image-coordinates`. Se ele não estiver instalado, toda a página de treinamento aborta com erro. Não há fallback para inserção manual de coordenadas via campos numéricos.

### 7. Schemas de formulário sem validação de estrutura

O editor salva qualquer JSON de volta para disco sem validação de schema mínima (ex.: se o usuário apagar todas as colunas de `mapping`, salva um schema inválido que quebra os adapters silenciosamente). Não há schema JSON Schema ou Pydantic para validar os próprios schemas.

---

## Notas para levar ao frontend (Next.js)

### Separação lógica de negócio vs. UI

**O que é lógica de negócio (deve ser portada para API/backend):**
- Toda a lógica de I/O de moldes (`listar`, `carregar`, `salvar`, `deletar`) → virar endpoints REST no FastAPI
- Template matching e rasterização OpenCV → manter em Python (FastAPI), nunca no browser
- Parsing de arquivo de gabarito (`parse_gabarito_arquivo`) → endpoint de upload
- Adapters NEEI (v2.0, v3.0) → manter em Python
- Validação de schemas contra CSV → endpoint de validação

**O que é UI (deve ser refeito em React/MUI):**
- Fluxo de 4 fases do editor de molde → wizard com stepper (MUI `Stepper`)
- Calibração visual (clique em imagem para adicionar coordenadas) → componente canvas com `react-konva` ou `fabric.js`
- Listagem e cards de schemas → tabela ou grid MUI
- Editor de tabela de `field_id → coluna CSV` → `@mui/x-data-grid` com edição inline
- Visualização do PAI → componente React com os mesmo estilos CSS (já bem definidos em `pagina_pai_renderer.py`)

### Onde o estado vive hoje → como vira no frontend

| Estado atual (`st.session_state`) | Equivalente no frontend |
|---|---|
| `molde_gabarito_lista` (lista de frases em edição) | `useState` local no wizard, persistido no backend ao salvar |
| `molde_candidatos` / `molde_descartados` / `molde_manuais` | Estado local do step de calibração; payload enviado ao endpoint de salvar |
| `molde_paginas` (imagens rasterizadas) | Não vive no frontend — as imagens são servidas como URLs pelo backend (endpoint de rasterização por página) |
| `molde_fase_ativa` | Estado do stepper (`activeStep`) |
| `schema_em_edicao` (qual schema está aberto) | Estado local do componente de listagem |
| `schema_editor::<stem>::buffer` (edições não salvas) | `useState` no componente editor, com `useUnsavedChanges` para prevenir saída acidental |
| `ultimo_csv_colunas` (colunas do CSV importado) | Context ou Zustand, compartilhado entre editor de schema e tela de importação |

### O que deve ir para API/endpoint

| Funcionalidade | Endpoint sugerido |
|---|---|
| Listar moldes | `GET /api/moldes` |
| Carregar molde | `GET /api/moldes/{nome}` |
| Detectar candidatos (upload PDF) | `POST /api/moldes/detectar` (multipart, retorna candidatos + URLs de imagens por página) |
| Salvar molde | `POST /api/moldes` (body: nome + quadrados + gabarito) |
| Deletar molde | `DELETE /api/moldes/{nome}` |
| Rasterizar página | `GET /api/moldes/{nome}/pagina/{n}` (retorna imagem) |
| Listar schemas | `GET /api/formularios/schemas` |
| Carregar schema | `GET /api/formularios/schemas/{nome}` |
| Salvar schema | `PUT /api/formularios/schemas/{nome}` |
| Criar nova versão do schema | `POST /api/formularios/schemas/{nome}/nova-versao` |
| Validar schema contra CSV | `POST /api/formularios/schemas/{nome}/validar` (multipart CSV) |

### Riscos da migração

1. **Moldes em disco**: antes de migrar, mover todos os JSONs e PDFs de referência para o Supabase Storage (ou S3). O frontend não pode depender de disco efêmero.
2. **Calibração visual**: o clique em imagem para adicionar coordenadas é o passo mais complexo de recriar — requer um componente canvas interativo com precisão de pixel. Considerar manter essa tela no Streamlit até ter o frontend maduro.
3. **Imagens em memória**: hoje as imagens rasterizadas vivem em `st.session_state` como numpy arrays. No frontend, o backend precisa servir as imagens como endpoints (URLs temporárias ou streaming) para que o componente canvas as carregue.
4. **Autenticação nos endpoints de molde**: hoje qualquer usuário logado no Streamlit pode criar/deletar moldes. No Next.js, esses endpoints devem ser protegidos por role (`admin` ou `coordenador`).
5. **Schemas de formulário**: a lógica de "qual schema está ativo" precisa ser explicitada antes da migração (adicionar campo `ativo: bool` ao JSON ou tabela no Supabase), pois o comportamento atual (primeiro da lista) é frágil e não escalável.
