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

Consulte a versão completa apresentada na sessão para as seções 1–11 e 8b
(detalhamento de endpoints, schema, RBAC, fases, Modelo de Sessões Dinâmicas,
verificação). Este arquivo é o checkpoint versionado do plano.
