# MAPA DE ARQUITETURA — Escola Parque V3 — Surgical RAG

> Documento de apoio do `.clauderules`. Detalha fluxos, diagramas ASCII e pontos cirúrgicos da migração Gemini → LiteLLM.
> Última varredura: 22/05/2026.

---

## 1. Diagrama macro (alta altitude)

```
┌──────────────────────────────────────────────────────────────────────┐
│                            USUÁRIO (Equipe PAEE)                     │
│   Streamlit Sidebar [Maestro] + Modal de Configurações [3 abas]      │
└──────────┬───────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                              app.py                                  │
│  view_mode ∈ {alunos | motor | treinamento | diagnostico |           │
│               financeiro | metas}                                    │
└──┬────────┬─────────┬─────────┬──────────────┬─────────────┬────────┘
   │        │         │         │              │             │
   ▼        ▼         ▼         ▼              ▼             ▼
pagina_  pagina_  pagina_   pagina_       pagina_       pagina_
alunos   motor    treina-   diagnos-      financeiro    metas
  │      │        mento     tico              │            │
  │      │          │          │              │            │
  ▼      ▼          ▼          ▼              ▼            ▼
back_  back_   treinamento_ back_         historico_    back_
ocr +  ocr      gemini.txt  diagnostico   consumo.json  metas
back_                                                       │
alunos                                                      ▼
  │                                                  metas_projeto.json
  ▼
banco_alunos.db (SQLite)
ocr_cache_{aluno_id}.json
  │
  ▼ (Consolidação RAG — Tela do Prontuário)
back_rag_export ─► back_banco_vetorial ─► Neon/Supabase (alunos_ppo + pgvector 384)
                                              ▲
                                              │
                            back_rag_busca ───┘ (sentence-transformers)
                                              │
                            back_obsidian_mcp ─► Vault local (.md)
```

---

## 2. Pipeline detalhado do OCR (`backend_ocr.py`)

```
PDF do questionário escaneado (a lápis)
        │
        ▼
extrair_texto_pdf()                      ──► temp_upload_{ts}.pdf (raiz)
        │
        ▼
analisar_com_treinamento(caminho_pdf)
        │
        ├── load_gemini_pool()                 → conta max_tentativas
        ├── load_model_pref()                  → modelo_config
        ├── fatiar_pdf_com_opencv()
        │     • fitz.open + pix(dpi=200)
        │     • 6 fatias verticais, overlap 25%
        │     • corte horizontal X = 80% (mata o "muro cego" direito)
        │     • salva em temp_fatias_{id_sessao}/pagN_fatiaN.jpg
        │
        ├── Loop rotação (tentativa = 0 .. max_tentativas-1):
        │     api_key = get_next_valid_key()
        │     genai.configure(api_key)
        │     model = GenerativeModel(modelo_config, temp=0.0, top_p=1, top_k=1)
        │
        │     UPLOADS:
        │       • Para cada fatia ALVO: genai.upload_file (ALVO_FATIA_n)
        │       • Para cada imagem em banco_contexto/treino_visao/:
        │           normalizar_referencia_opencv()  (contraste alpha=1.5)
        │           genai.upload_file (TREINO_{nome})
        │       • aguardar_processamento(...)
        │
        │     SUPER-PROMPT (3 passos forenses):
        │       PASSO 1 — Log de Inspeção Visual (3 tokens fechados):
        │         "Totalmente limpo." | "Apenas mancha." | "Traço detectado."
        │       PASSO 2 — Regra implacável: traço detectado → [X], senão [ ]
        │       PASSO 3 — Gabarito final EXATO (41 frases do mapeamento_fidedigno)
        │
        │     STREAM:
        │       response = model.generate_content(prompt, stream=True)
        │       for chunk → texto_transcrito += chunk.text
        │
        │     PARSING:
        │       linhas → identifica [X]/[ ] → frase_lida
        │       difflib.SequenceMatcher ratio ≥ 0.80 contra estado_final_frases
        │
        │     TELEMETRIA:
        │       usage_metadata.prompt_token_count / candidates_token_count
        │       calcular_custo_brl(modelo, in, out) → BRL
        │
        │     SE erro 429/503/500/403/quota/exhausted:
        │       mark_key_as_standby(api_key) + continue (próxima chave)
        │     SE outro erro:
        │       return {"erro": "Falha Crítica (não cota)..."}
        │
        │     SE sucesso:
        │       monta resultado_final por categoria
        │       dispara faxina_com_status_sidebar() em thread daemon
        │         (apaga arquivos cloud + pasta_sessao + PDF temp)
        │       registrar_consumo("OCR Transcricional...", modelo, total_tokens, BRL, t)
        │       return {sucesso: True, dados, telemetria}
        │
        └── Se loop esgota: return {"erro": "TODAS AS CHAVES FALHARAM."}
```

### Pontos finos a observar

| # | Ponto | Implicação para refatoração |
|---|-------|-----------------------------|
| 1 | `num_fatias = 6` hard-coded | Deve virar config no `model_pref` ou `taxas_config.json` |
| 2 | Corte `int(largura * 0.8)` mata o lado direito do papel — cuidado em layouts novos | Parametrizar (ex.: `crop_x_ratio`) |
| 3 | `temperature=0.0, top_p=1.0, top_k=1` (modo forense) | Migrar para `litellm.completion(..., temperature=0)` |
| 4 | `aguardar_processamento` faz polling 15× a cada 2s | LiteLLM Vision (OpenAI, Anthropic) é síncrono → simplificar |
| 5 | `difflib` ratio ≥ 0.80 | Trocar por embedding (cosine) com `all-MiniLM-L6-v2` se houver erro de OCR (mais robusto) |
| 6 | Thread de faxina não dá join | OK em produção, mas se app reiniciar antes da thread terminar fica lixo. Considerar `atexit` ou janitor em backend separado |

---

## 3. Pipeline de cadastro e consolidação RAG do aluno

```
pagina_alunos.modal_novo_aluno()
        │
        ▼
backend_alunos.criar_aluno(apelido, serie, turma)
        │  ─► SQLite INSERT em "alunos" com id_anon (UUID curto)
        ▼
[Lista renderizada → seleciona aluno → tab "Questionário Base"]
        │
        ▼
Upload PDF + ocr.analisar_com_treinamento()
        │
        ▼ resultado salvo em ocr_cache_{aluno_id}.json
        │
        ▼ (botão "🧠 Consolidar no RAG")
backend_rag_export.consolidar_estudo_de_caso(aluno_id)      ⚠️ AINDA NÃO CRIADO
        │
        ├─► gera perfil_texto consolidado (juntando seções marcadas)
        ├─► backend_rag_busca.gerar_vetor_zero_tokens(perfil_texto)
        │       (sentence-transformers, 384 dim, local, $0)
        └─► backend_banco_vetorial.inserir_aluno_ppo(nome_anon, turma, perfil, vetor)
                UPSERT em alunos_ppo (Neon/Supabase)
                Índice HNSW vector_cosine_ops
```

> **Gap arquitetural detectado:** `backend_rag_export.py` é referenciado em `pagina_alunos.py` mas NÃO existe no disco. Sprint Junho/2026 (meta #4 — "Motor RAG: Ingestão e OCR de PDFs") deve criá-lo.

---

## 4. Carrossel de chaves (`storage_gemini.py`)

```
gemini_pool.json = [
  { key: "AIza...", status: "active"|"standby", exhausted_at: 0|ts, is_primary: bool },
  ...
]

get_next_valid_key():
  1. Para toda chave standby cujo (now - exhausted_at) ≥ 3600s → reativa
  2. Tenta achar a chave is_primary=True e active
  3. Senão, primeira active
  4. Senão, None  → backend_ocr devolve erro "todas na geladeira"

mark_key_as_standby(key):
  Marca status="standby" + exhausted_at=now()

Estados visuais no painel de Configurações (Aba 2):
  🔵 EM USO (Principal)   — active + is_primary + igual ao retornado por get_next_valid_key
  🟢 DISPONÍVEL (Reserva) — active mas não principal
  🔴 STANDBY              — em cooldown, com timer regressivo (60min)
```

---

## 5. Migração Gemini → LiteLLM (plano cirúrgico)

### Estado HOJE (Aba 2 do modal)

```python
opcao == "🤖 Motor IA (Gemini)":
    # Adiciona chave, lista chaves, raspa modelos via lab_ai.testar_conexao_gemini
    # Botão "Raspar/Atualizar Lista de Modelos"
    # Upload tabela_precos.pdf + regex em pdfplumber para preencher taxas_config.json
    # st.selectbox(modelos_disponiveis)
    # Botão "Testar Modelo & Atualizar Cotação" → atualiza preços via regex no PDF
    # Botão "Salvar como Padrão" → save_model_pref(novo_modelo)
```

### Estado ALVO (Aba 2 — LiteLLM)

```python
opcao == "🤖 Motor IA (LiteLLM Multi-Provider)":

    with st.expander("➕ Inserir Novo Provedor / LLM"):
        provedor = st.selectbox("Provedor", [
            "gemini", "openai", "anthropic", "groq",
            "custom/local (Ollama, vLLM, LM Studio)"
        ])
        api_key = st.text_input("API Key", type="password")
        base_url = st.text_input("Base URL",
            placeholder="http://localhost:11434/v1 (Ollama)")
        modelo_str = st.text_input("Model String",
            placeholder="gpt-4o-mini | claude-3-5-sonnet | groq/llama3-8b-8192 | ollama/qwen2.5-coder")

        if st.button("🔌 Ping + Salvar"):
            ok, msg = backend_litellm.validar_provedor(provedor, api_key, base_url, modelo_str)
            if ok: storage_provedores.adicionar(...)

    # Tabela dinâmica
    if st.button("🔄 Puxar Preços do LiteLLM"):
        custos = backend_litellm.snapshot_custos()
        # Renderiza tabela: modelo | input/1M | output/1M | provedor

    # Selectbox de modelo ativo + Salvar como Padrão
```

### Novo backend (`backend_litellm.py`) — esqueleto

```python
import litellm
import os

def validar_provedor(provider, api_key, base_url=None, modelo_str=None):
    """Ping mínimo com litellm.completion. Retorna (ok, msg)."""
    try:
        kwargs = {"messages": [{"role":"user","content":"ping"}], "max_tokens": 1}
        if provider == "custom/local":
            kwargs["model"] = modelo_str  # ex.: "ollama/qwen2.5-coder"
            kwargs["api_base"] = base_url
        else:
            os.environ[f"{provider.upper()}_API_KEY"] = api_key
            kwargs["model"] = modelo_str
        litellm.completion(**kwargs)
        return True, "✅ Provedor respondeu."
    except Exception as e:
        return False, f"❌ {e}"

def obter_custos(modelo_str):
    """Lê litellm.model_cost (dict oficial). Retorna {"in": usd_per_1M, "out": usd_per_1M}."""
    info = litellm.model_cost.get(modelo_str, {})
    return {
        "in":  info.get("input_cost_per_token",  0) * 1_000_000,
        "out": info.get("output_cost_per_token", 0) * 1_000_000,
    }

def snapshot_custos():
    """Retorna lista [{modelo, provedor, in, out}] para tabela do Streamlit."""
    return [
        {"modelo": m,
         "provedor": litellm.model_cost[m].get("litellm_provider", "—"),
         "in":  litellm.model_cost[m].get("input_cost_per_token", 0)  * 1_000_000,
         "out": litellm.model_cost[m].get("output_cost_per_token", 0) * 1_000_000}
        for m in litellm.model_cost
    ]

def gerar_resposta(modelo, messages, **kw):
    """Wrapper unificado — substitui genai.GenerativeModel(...).generate_content."""
    return litellm.completion(model=modelo, messages=messages, **kw)
```

### Pontos de integração no `funcoes_fla.py`

```python
# ANTES (regex sobre PDF):
def calcular_custo_brl(modelo, input_tokens, output_tokens):
    taxas = ler_taxas_local(modelo)
    custo_usd = (input_tokens/1e6) * taxas["preco_in"] + (output_tokens/1e6) * taxas["preco_out"]
    return custo_usd * taxas["dolar"]

# DEPOIS (LiteLLM):
def calcular_custo_brl(modelo, input_tokens, output_tokens):
    from backend_litellm import obter_custos
    custos = obter_custos(modelo)
    dolar = buscar_cotacao_dolar_realtime()
    custo_usd = (input_tokens/1e6) * custos["in"] + (output_tokens/1e6) * custos["out"]
    return custo_usd * dolar
```

### Pontos de integração no `backend_ocr.py`

```python
# Substituir:
#   genai.configure(api_key=api_key)
#   model = genai.GenerativeModel(modelo_config, generation_config=config_forense)
#   response = model.generate_content(conteudo_prompt, stream=True)
#
# Por (apenas para provedores não-Gemini ou rota local):
#   from backend_litellm import gerar_resposta
#   response = gerar_resposta(
#       modelo=modelo_config,
#       messages=[{"role":"user", "content": [
#           {"type":"text","text": prompt_texto},
#           {"type":"image_url","image_url":{"url": b64_da_fatia}},
#           ...
#       ]}],
#       temperature=0, stream=True
#   )
#
# Atenção: upload via `genai.upload_file` é específico Google.
# LiteLLM exige base64 inline ou URL — vamos precisar converter as fatias.
```

> **Risco arquitetural:** o LiteLLM não tem upload persistente. As fatias terão de virar `data:image/jpeg;base64,...` no payload — pode estourar limites de contexto se subirmos 6 fatias × N páginas. Mitigar: enviar 1 fatia por chamada e agregar parsing no Python (já fazemos parsing por difflib).

---

## 6. Configurações persistidas — onde mora cada coisa

| Arquivo | Conteúdo | Quem lê | Quem grava |
|---------|----------|---------|------------|
| `gemini_pool.json` | Pool rotativo de chaves Google | `storage_gemini`, `backend_ocr`, `app.py` (Aba 2) | `storage_gemini` |
| `keys.json` | `gemini` (chave primária legada) + `newsdata` | `funcoes_fla.load_key`, `backend_ppo_agente`, `pagina_precos` | `funcoes_fla.save_key` |
| `keys/db_config.json` | host/porta/user/senha/dbname Neon | `backend_infra.load_db_config`, `backend_banco_vetorial._obter_conexao` | `backend_infra.save_db_config` |
| `keys/mcp_config.json` | `mcp_ativo`, `rag_ativo`, `vault_path` | `backend_obsidian_mcp`, `app.py` (Aba 3) | `backend_infra.save_mcp_config` |
| `taxas_config.json` | Última cotação + preços `in/out` do modelo ativo | `funcoes_fla.ler_taxas_local`, `backend_ocr` (via `calcular_custo_brl`) | `funcoes_fla.atualizar_taxas_local`, `app.py` (Aba 2) |
| `model_pref.txt` | Modelo ativo (string) | `funcoes_lab.load_model_pref` → `lab_storage.load_model_pref` | `funcoes_lab.save_model_pref` |
| `metas_projeto.json` | 9 metas de implantação | `backend_metas`, `pagina_metas` | `backend_metas` |
| `historico_consumo.json` | Log de chamadas LLM (timestamp, processo, modelo, tokens, custo_brl, tempo) | `pagina_financeiro` | `funcoes_fla.registrar_consumo` |
| `treinamento_gemini.txt` | Persona PAEE (Few-Shot) | `pagina_treinamento` (apenas leitura/edição manual) | `pagina_treinamento` |
| `banco_alunos.db` | SQLite (alunos / questionarios / ppo) | `backend_alunos`, `pagina_alunos` | `backend_alunos.criar_aluno`, futuras `salvar_questionario_aluno` |
| `ocr_cache_{aluno_id}.json` | Última extração consolidada por aluno | `pagina_alunos.render_ppo_tab`, `pagina_debug_ocr` | `pagina_alunos` (botão "💾 Salvar no Prontuário") |
| `tabela_precos.pdf` | PDF oficial Google AI Studio | `funcoes_fla.obter_precos_do_pdf`, `app.py` (Aba 2) | `app.py` upload + `pagina_precos` |
| `temp_fatias_{ts}/` | Fatias OpenCV da sessão atual | `backend_ocr` | criada/apagada por `backend_ocr` |
| `banco_contexto/treino_visao/` | Imagens de calibragem (baseline, marcado_fraco, vazado, linha_fina, etc.) | `backend_ocr.analisar_com_treinamento` | manual (você sobe as referências) |

---

## 7. Lista negra (arquivos legados de outro projeto)

Estes existem na raiz mas **não pertencem ao Escola Parque** — são resquícios de um estúdio musical (Sertanejo / Suno / YouTube). Não tocar a menos que estejam quebrando algo:

- `fabrica_video.py`, `setlist_analyzer.py`, `single_song.py`, `radar_pro.py`, `vendas_especialista.py`
- `lab_ai.py`, `lab_media.py`, `lab_storage.py`, `lab_utils.py` (parcialmente reusados via `funcoes_lab.py` — apenas `load_model_pref`/`save_model_pref` e funções de listagem de modelos Gemini)
- `fiscal_canais.py`, `canais_fiscalizados.json`, `fiscal_history.json`, `historico_sertanejo.json`, `radar_history.json`, `radar_presets.json`, `spotify_keys.json`, `youtube_keys_pool.json`, `youtube_api_key.txt`, `lyrics_url.txt`, `contexto_duda.txt`, `treinamento_gemini.txt` (essa última é dupla função — pedagogia + persona Duda)
- `SertanejoDB.zip`, `temp_*.WAV`, `ffmpeg*.exe`, `f.jpg`, `downloads/`, `downloads_setlist/`

**Recomendação futura:** mover tudo para `/legacy_musical/` no commit de pré-deploy.

---

## 8. Checklist do desenvolvedor antes de qualquer push

- [ ] Imports em `app.py` todos blindados com `try/except ImportError`?
- [ ] Nenhum `st.rerun()` novo dentro de `@st.dialog` que feche o modal indevidamente?
- [ ] Toda chamada LLM passou por `get_next_valid_key()` (ou seu equivalente LiteLLM futuro)?
- [ ] `registrar_consumo()` foi chamado para a nova rota?
- [ ] id_anon usado em todo prompt que sai do servidor local?
- [ ] Faxina de cache (thread daemon) ainda dispara?
- [ ] `historico_consumo.json` recebe entry coerente (modelo, tokens, custo, tempo)?
- [ ] Nenhuma frase do `mapeamento_fidedigno` foi alterada sem aprovação clínica?

---

*Fim do MAPA_ARQUITETURA.md — documento vivo, evolui junto com o projeto.*
