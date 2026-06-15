# MODELO — Logins, Hierarquia e Páginas por Usuário (Escola Parque V3)

> Status: **proposta consolidada F2** (a construir). Fonte da verdade do schema = **Drizzle**
> (`escola-parque-frontend/src/db/schema.ts`). Banco vivo = **Postgres do VPS** (a nuvem é reserva congelada).

---

## 1. Decisões travadas (15/06/2026)

- **Aluno COM login** — aluno/responsável acessa e vê **só o próprio** (auth de aluno + RLS por aluno).
- **Multi-sede** — cada colégio pode ter várias **sedes (campus)**; turmas pertencem a uma sede.
- **Correção AUTOMÁTICA** — subsistema novo (um "Agente Corretor"). *Decisão pendente: OCR/scan vs resposta digital.*

---

## 2. Hierarquia de papéis

```
super_admin (PLATAFORMA — você)  ── todos os colégios · cria/edita colégio · ponte backend↔frontend
   └─ school_admin (Adm do Colégio) ── 1 colégio · gerencia tudo dele
        ├─ coordinator (coordenador) ── visão pedagógica do colégio
        ├─ teacher (professor)       ── suas turmas/matérias/alunos · provas · correção
        ├─ aee (apoio)               ── alunos especiais que acompanha
        └─ aluno/responsável         ── vê só o próprio perfil/PAI/provas/notas
```

`user_role` (enum atual): `admin, coordinator, teacher, aee` → **adicionar** `super_admin` e `student`/`guardian`.

---

## 3. Modelo de dados ( ✅ já existe · ➕ adicionar )

### Identidade & Acesso
- ✅ `schools` (raiz multi-tenant)
- ➕ `campuses` — sedes: `school_id`, nome, endereço, ativo
- ✅ `users` (login; `school_id`, `role`, ...) · ➕ papéis `super_admin` (school_id nulo) e `student`/`guardian`
- ➕ `student_access` — liga um **login** (`users`) a um **aluno** (`students`); tipo `self`/`guardian` (permite aluno OU responsável)
- ✅ `students` · ➕ `student_support` — aluno ↔ **apoio (AEE)** que o acompanha

### Organização acadêmica
- ✅ `classes` · ➕ coluna `campus_id` (turma pertence a uma sede)
- ✅ `subjects`, `discipline_families`, `class_teacher_subjects` (regente via `is_homeroom`), `student_classes`

### Pedagógico (tudo já existe)
- ✅ `questionnaires` → `questionnaire_sections` → `questionnaire_field_responses` → `pais` → `pai_reviews`
- ✅ `exams` → `adapted_exams` → `validations`

### Correção automática (novo subsistema)
- ➕ `exam_answer_keys` — gabarito por questão (+ pontos)
- ➕ `exam_submissions` — prova respondida do aluno (arquivo/scan + respostas extraídas)
- ➕ `exam_corrections` — nota por questão + total + confiança + `needs_review` + versão do agente + override humano

---

## 4. Páginas por papel

| Papel | Área (o que vê / faz) |
|---|---|
| **super_admin** | Cria/edita **colégios + sedes** · vê todos · alterna colégio · **botões ir-pro-Backend / voltar-pro-Frontend** · custos/telemetria globais |
| **school_admin** | Gerencia 1 colégio: sedes, turmas, matérias, **usuários** (prof/apoio/coord), alunos |
| **coordinator** | Visão pedagógica do colégio: PAIs, provas, alunos especiais, aprovações |
| **teacher** | Minhas turmas/matérias/alunos · **provas** (subir → adaptar) · **correção (auto)** · PAIs dos meus alunos |
| **aee** (apoio) | Meus alunos acompanhados · questionários (parte AEE) · PAIs |
| **aluno/responsável** | Meu perfil · meu PAI · minhas provas adaptadas · **minhas notas** |

---

## 5. 🔑 Fundação: auth unificada (SSO)

A **ponte Admin backend↔frontend** E o **login de aluno** dependem de **um login único** que valha nos dois apps
(Streamlit + Next.js) e carregue **papel + colégio + sede**. É o **NextAuth pendente**. Sem isso, nada de login
novo encaixa. **É o primeiro tijolo de verdade.**

---

## 6. Ordem de construção

1. **Este doc** (modelo consolidado) ✅
2. **Migration F2** — enums + tabelas novas (`campuses`, `student_access`, `student_support`, papéis, `classes.campus_id`). Via Drizzle → aplica no Postgres do VPS (SQL revisado **antes** de aplicar).
3. **Auth unificada** (NextAuth + SSO + papéis) — o tijolo-fundação.
4. **Páginas por papel** — começando pelo **super_admin** (a ponte).
5. **Correção automática** — depois de definir OCR vs digital.

---

## 7. Decisões abertas

- Correção automática: **OCR/scan** (aluno entrega papel) vs **digital** (responde na tela)?
- Escopo do `coordinator` (só leitura/aprovação? edita?).
- Um responsável pode ter **vários filhos** (1 login → N alunos)? (modelado por `student_access` N:N).
