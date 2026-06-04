# 📌 CHECKPOINT — Sessão 2026-05-25 — Escola Parque V3 Surgical RAG

> Cole o bloco "TEXTO PRA COLAR" no novo chat e seguimos exatamente daqui.

---

## 🎯 TEXTO PRA COLAR no próximo chat

```
PROJETO: Escola Parque V3 - Surgical RAG
SESSÃO ANTERIOR: 2026-05-25 (madrugada Brasil)

ESTADO ATUAL (todos os arquivos compilam, app está funcional):

✅ MOTORES OCR EM PRODUÇÃO:
  - Gemini 2.5 Flash + Modo 1 Turbo + template Esquerda: 100% (R$ 0,021, 56s)
  - Qwen 2.5 VL 72B (OpenRouter) + Modo 1 Turbo + Esquerda: 100%
  - Qwen 2.5 VL 7B local + Modo 2 v7: ainda pendente reativar (não mexido hoje)

✅ MUDANÇAS APLICADAS HOJE (todas validadas com py_compile):

1. backend_ocr.py:
   - MODO2_TEMPLATE_DEFAULT mudou de "hibrido_sem_corte" → "multipla_escolha_esquerda"
   - (calibrado por evidência: Prova_Nova vs Prova_Nova_EXP)

2. backend_molde.py:
   - Nova função _sanitizar_nome_filesystem (Unicode NFKD: Ç→C, Ã→A, Õ→O...)
   - molde_path/molde_pdf_path usam essa nova função
   - parse_gabarito_arquivo aceita .xlsx e .xls (além de .json/.csv/.txt/.md)
   - Nova função detectar_template_layout (autodetecta Esquerda vs Híbrido)
   - montar_molde_final aceita parâmetros template_layout + config_template
   - Dict de molde agora sempre contém template_layout e config_template

3. pagina_molde.py:
   - Nome do molde EDITÁVEL na Fase 1 (input no topo, persistente entre fases)
   - Removida duplicação de input de nome na Fase 2
   - Uploader de gabarito aceita XLSX/XLS
   - Botão "🗑️ Limpar arquivo" no uploader (counter dinâmico)
   - Função _salvar_molde_atual recuperada (estava truncada)
   - Removida blindagem bugada que apagava o nome digitado
   - Preview do filename na UI (mostra "moldes/X.json" antes de salvar)
   - Instrumentação forense de salvamento (colapsada, expanded=False)
   - Seletor de template_layout na Fase 4 (Esquerda/Híbrido) com autodetecção

4. pagina_alunos.py:
   - Tabela de Alunos COMPACTA (sem dividers gigantes, badge inline, zebra)
   - Coluna NOME (apelido) adicionada
   - Botão "Abrir" virou ícone "→" sem borda
   - Dossiê do Aluno: layout INLINE (label: valor na mesma linha, sem espaçamento)
   - Label "APELIDO / CÓDIGO" virou "Nome / Apelido"
   - CSS local de tabs REMOVIDO (agora vem do utils_estilo global)

5. backend_alunos.py:
   - buscar_lista_alunos() agora retorna a.apelido (era só id, serie, turma)

6. app.py:
   - Aplica utils_estilo.injetar_css_global() logo após set_page_config
   - RECUPERADO: bloco try órfão no view_mode=diagnostico + elif financeiro
     que estava TOTALMENTE AUSENTE (botão "Custos e Tokens" não funcionava)

7. utils_estilo.py (NOVO):
   - injetar_css_global() — CSS unificado para st.tabs + st.radio sidebar
   - Identidade visual: vermelho #d62728 destacado em selecionado
   - Mesma identidade do projeto, aplicado UMA vez no entry point

8. pagina_financeiro.py:
   - Resumo Geral COMPACTADO: 7 métricas em UMA linha (era 4+3 desalinhado)
   - Botão "🔄 Zerar Histórico" no cabeçalho com diálogo de confirmação

9. requirements.txt: +openpyxl +xlrd

✅ Gabaritos de teste gerados na raiz:
   - gabarito_46frases.txt
   - gabarito_46frases_com_secao.csv
   - gabarito_46frases.xlsx

❌ PENDÊNCIAS PARA O PRÓXIMO CHAT:

A. REFATORAR MOTORES IA EM 3 ABAS SUPERIORES
   - Local: app.py linha ~244 (elif opcao == "🤖 Motores IA (LiteLLM)":)
   - 4 painéis hoje: PAINEL 1 (Provedores, L250+), PAINEL 2 (Inserir Novo, L622+),
     PAINEL 3 (Preços, L765+), PAINEL 4 (Modelo Ativo, L1052+) — total ~1100 linhas
   - Agrupamento APROVADO pelo usuário:
     • Aba 1 🔌 Provedores = Painéis 1 + 2 (Inserir Novo é toggle dentro)
     • Aba 2 📊 Preços = Painel 3
     • Aba 3 🎯 Modelo Ativo = Painel 4
   - Estilo das abas já está unificado (utils_estilo)
   - REFATORAÇÃO GRANDE — fazer com Python splice (Edit do harness bugou várias
     vezes em arquivos grandes neste projeto, sempre validar com py_compile depois)

B. TESTAR VISUALMENTE NO STREAMLIT:
   - Tabela financeira compactada + botão Zerar funcional
   - Coluna AÇÃO da tabela de Alunos alinhada (verificar com 5+ alunos)
   - Menu radio das Configurações com estilo global aplicado

C. CRIAR MODO 3 EXPERIMENTAL (futuro):
   - Função _analisar_micro_vision_crop_v3_experimental em arquivo separado
   - Estratégia "modo3_qwen3vl_experimental" — não toca no Modo 2 v7
   - Para experimentos com Qwen 3 VL / LLaVA sem quebrar produção

D. RESOLVER 43/46 DO QWEN 2.5 LOCAL (pausado):
   - O Qwen 2.5 VL 7B local que dava 43/46 ainda não foi recuperado
   - Provavelmente é só rodar com molde NOVO criado pós-correção (já que
     o default template_layout agora é Esquerda, igual ao Prova_Nova_EXP)

REGRA INVIOLÁVEL: NÃO TRUNCAR CÓDIGO. Se pedir backend_ocr.py ou pagina_molde.py,
entregar do início ao fim. Se mudança pequena, dar apenas o bloco com linhas.
USAR Python splice (não Edit) em arquivos >500 linhas (Edit do harness bugou).
SEMPRE checkpoint defensivo antes de mexer em arquivo grande.
```

---

## 📂 ARQUIVOS MODIFICADOS HOJE

| Arquivo | Linhas | Status |
|---|---|---|
| `app.py` | 1505 | ✅ compila (recuperado de truncamento) |
| `backend_ocr.py` | 3920 | ✅ compila |
| `backend_molde.py` | 856 | ✅ compila |
| `backend_alunos.py` | ~ | ✅ compila |
| `pagina_molde.py` | 1397 | ✅ compila |
| `pagina_alunos.py` | 706 | ✅ compila |
| `pagina_financeiro.py` | 167 | ✅ compila |
| `utils_estilo.py` | **NOVO** ~130 | ✅ compila |
| `requirements.txt` | +2 linhas (openpyxl, xlrd) | ✅ |

## 🗂️ CHECKPOINTS DEFENSIVOS (.bak) na pasta

- `ckpt_pre_nome_editavel_20260525_*_pagina_molde.py.bak` (1215 linhas, íntegro)
- `ckpt_pre_xlsx_20260525_*_pagina_molde.py.bak` (1203 linhas)
- `ckpt_pre_xlsx_20260525_*_backend_molde.py.bak` (695 linhas)
- `ckpt_pre_default_layout_20260525_*_backend_ocr.py.bak`
- `ckpt_pre_default_layout_20260525_*_backend_molde.py.bak`
- `ckpt_pre_default_layout_20260525_*_pagina_molde.py.bak`
- `ckpt_pre_tabela_compacta_20260525_*_pagina_alunos.py.bak`
- `ckpt_pre_recovery_20260525_*_app.py.bak` (do app truncado)
- `ckpt_pre_zerar_20260525_*_pagina_financeiro.py.bak`

## 📋 TASKS COMPLETADAS (#1 a #43)

Todas marcadas como completed. Task #41 (Refatorar Motores IA em 3 abas) **pending** —
é o próximo grande item.

## 🎬 SITUAÇÃO DO VÍDEO

Sistema está PRONTO pra gravar o vídeo:
- Novo molde do zero → nasce com template Esquerda automático
- Gemini + Modo 1 Turbo → 100% acurácia, R$ 0,021, 56s
- Tabela de Alunos compacta
- Dossiê do Aluno enxuto
- Abas (st.tabs) com identidade visual padronizada

Antes da gravação, recomendo:
1. Reiniciar Streamlit (Ctrl+C + `streamlit run app.py`) pra pegar utils_estilo
2. Conferir tabela financeira com botão Zerar
3. Criar molde demonstração com nome "Prova_Demo" (sem acentos)
