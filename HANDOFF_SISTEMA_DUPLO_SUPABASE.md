# HANDOFF — Escola Parque V3 (Surgical RAG) · Fase Sistema Duplo + Supabase

> Cole isto no início de um chat NOVO (com o conector Supabase já ativo) para continuar de onde paramos.

---

## Quem você é / como agir
Você é meu **Mentor Master de Desenvolvimento e Arquiteto de Software Sênior**. Seja direto, técnico e cirúrgico. Regras inegociáveis:
- **PROIBIDO truncar código** (nada de "# resto do código aqui"). Arquivo pedido = 100% completo. Mudança pequena = bloco exato de substituição com as linhas.
- **BLINDAR o que funciona:** backup automático antes de qualquer alteração; nunca quebrar o que está validado.
- **Decisões de arquitetura são minhas** — não mude sem autorização. Nada destrutivo (DROP/delete) sem me mostrar o SQL e confirmar antes.
- Contar caracteres com precisão quando relevante.

## Projeto e stack
Sistema que mapeia alunos com TDAH/TEA/neurodivergências e adapta provas via IA + visão computacional.
- **Frontend:** Python/Streamlit (app local, `localhost:8501`). Pasta: `C:\Users\DB LIVE STUDIO\Desktop\AUTOMACOES\ESCOLA_PARQUE`.
- **Visão:** OpenCV + PyMuPDF.
- **IA:** LiteLLM multi-provedor (Gemini, Anthropic, Groq, Ollama local Qwen).
- **Banco:** PostgreSQL + pgvector via **Supabase**.
- **App web do sócio (Innova V2):** Next.js 16 + Supabase + Drizzle ORM + Anthropic SDK. Pasta: `Migração BD/innova-v2-python-handoff-v2/web`.

## O que JÁ está CONCLUÍDO — Agente 1 (Construtor de Perfil) — FECHADO ✅
- **Hybrid 2.0:** o `native` (Python determinístico) DECIDE orçamento/intensidades; o LLM só escreve prosa (summary, low_confidence_areas, missing_evidence, personality_notes).
- **Prompt v6.0 (14.791 chars)** unificado em toda a frota (Gemini, `qwen2.5:14b`, `_default_`, etc.) em `agent_prompts.json`: removida a **recitação de intensidade** (era a fonte dos erros do 14B); intensidade vive só nos cards nativos.
- **`hybrid.py`:** fecho de LCA vazia nativo + guard que injeta `missing_evidence` determinístico (histórico/AEE/Parte 1.5) a partir dos flags e dropa itens falsos da LCA. LLM só contribui itens de julgamento.
- **Adapter CSV Google Forms → canônico** em `innova_bridge/formularios/adapters/from_neei_v3_0.py`: `csv_to_questionnaire_response(source, linha)` + `listar_respostas_csv(source)`. FIEL: estrutura→enums canônicos, prosa→texto literal da professora. Validado reproduzindo a camada estrutural do fixture `INPUT_INTENSO_formulario.json`.
- **UI:** upload de CSV em `_render_origem_resposta` (`aluno_questionario_base_v3.py`). Origem rotulada como `csv_forms_<id>`.
- **Defaults de abertura:** Molde Novo + Motor Híbrido + Gemini + Origem "Subir CSV" + Supabase BR.
- **Aposentados (arquivados, não deletados):** Molde Antigo + engine "LLM completo". Mantido o **Nativo** (fallback R$0/offline).
- **Validado em produção:** Gemini (nuvem) E `qwen2.5:14b` (local) geram PAI **estruturalmente idêntico** a partir do Google Forms real, com prosa fiel. Local é determinístico (seed 42).

## Fase ATUAL — Sistema Duplo (web público + Python + Supabase compartilhado)
**Arquitetura:** Web (Next.js na Vercel) grava o questionário submetido no Supabase BR → **Worker Python** lê, roda o Agente 1, grava o PAI de volta → Web mostra.

**Decisões já tomadas:**
- Deploy do web: **Vercel**.
- Python em produção: **worker local na minha máquina** (começar simples; lê jobs do Supabase e processa).
- Supabase: **migrado pro BR (sa-east-1) — JÁ FEITO.** Org `diogobsbastos's Org`, projeto **`innova-v2-br`** (ref `awosfxlcjqotforkixps`), PRODUCTION.
- Contrato de dados: `docs/SUPABASE_SCHEMA.md` no handoff do sócio (**22 tabelas, 12 enums**). Fonte da verdade do schema = **Drizzle** (`web/src/db/schema.ts`) — em conflito, o TypeScript ganha. Python entra via **service_role** (RLS ativo).

## Conector Supabase
O **MCP oficial do Supabase** foi conectado à conta Claude (autorizado com escopo da org `diogobsbastos's Org`). Neste chat novo as ferramentas do Supabase devem estar carregadas.

## PRIMEIRA AÇÃO neste chat novo
1. **Testar o acesso (ping leve):** listar os projetos, confirmar o `innova-v2-br`, e **ler o schema real** (tabelas/colunas/enums/RLS). Se enxergar o banco, a autonomia está valendo.
2. Em seguida, **desenhar as tabelas do "fluxo de jobs"** do sistema duplo: onde o web grava o questionário submetido, de onde o worker Python lê pra gerar o PAI, e onde grava o PAI de volta (status, agent_runs, etc.). Comparar com o que já existe no schema antes de propor qualquer tabela nova.

## Constraints técnicas (importantes)
- O **sandbox Linux do Cowork NÃO alcança o Supabase pela rede** (`*.supabase.co` bloqueado). Por isso o **MCP é a ponte** (roda fora do sandbox). Mudança de schema: usar o MCP, mantendo **sincronia com o Drizzle** (`web/src/db/schema.ts`) pra não dar drift. RLS/policies/funções via SQL.
- O **mount do sandbox às vezes serve versões "torn"/stale** de arquivos recém-editados → validar via leitor real (Read/Grep no path Windows), **não** confiar em `py_compile` no mount.
- Backups com timestamp antes de cada edição; o usuário roda os comandos de rede (deploy/migração) do terminal dele.
