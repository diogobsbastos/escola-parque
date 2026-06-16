# ARQUITETURA VPS - SUPABASE CASEIRO - AUTH - DEPLOY - Escola Parque V3

> FONTE DA VERDADE VIVA DA INFRA. Sempre que algo de servidor/auth/deploy mudar, atualize aqui.
> Objetivo: a proxima sessao (ou dev) comeca sabendo de tudo - sem redescobrir.
> Ultima atualizacao: 2026-06-15 (cutover do auth pra VPS + auto-deploy do front).

---

## 0. TL;DR

- Tudo roda no VPS Oracle (137.131.156.145, dominio oracle-vipworks.duckdns.org). A Supabase da nuvem foi descontinuada (reserva congelada).
- "Supabase caseiro" = Postgres `innova` + PostgREST (API REST) + pgvector + GoTrue (auth/login). Tudo systemd, sem Docker.
- Front (Next.js) em https://escolaparque-app.duckdns.org . Backend Central (Streamlit) em https://oracle-vipworks.duckdns.org/escola-parque/ .
- Deploy do front = automatico (push no GitHub -> VPS faz pull+build+restart). Deploy do Streamlit = `git pull` simples + restart (a pasta tem dados vivos - NUNCA reset --hard).

---

## 1. Servidor

| Item | Valor |
|---|---|
| Provedor | Oracle Cloud (ARM Ampere A1, Always Free) |
| Shape | 4 OCPU / 24 GB / Ubuntu 22.04 (aarch64) |
| IP | 137.131.156.145 |
| Dominios | oracle-vipworks.duckdns.org, escolaparque-app.duckdns.org, zap., ntfy. |
| SSH | ubuntu@137.131.156.145 (chave ssh-key-2026-06-03.key) |
| Proxy | Nginx (/etc/nginx/sites-available/{apps,innova,zap,ntfy,default}) |
| TLS | Let's Encrypt/Certbot |

### Rotas Nginx - site `apps` (oracle-vipworks.duckdns.org)
| Rota | Backend | O que e |
|---|---|---|
| /escola-parque/ | 127.0.0.1:8501 | Backend Central (Streamlit) |
| /admin/ | 127.0.0.1:8500 | Painel VPS Admin |
| /llm/ | 127.0.0.1:8600 | LLM Gateway (Ollama) |
| /rest/v1/, /db/ | 127.0.0.1:3001 | PostgREST (Supabase caseiro) |
| /auth/v1/ | 127.0.0.1:9999 | GoTrue (auth) |
| /hook-.../ | 127.0.0.1:8800 | Webhook de deploy |
| /bolao-copa26/ | 127.0.0.1:8510 | Bolao |

### Site `innova` (escolaparque-app.duckdns.org)
| Rota | Backend | O que e |
|---|---|---|
| /auth/v1/ | 127.0.0.1:9999 | GoTrue (login do front - same-origin) |
| / | 127.0.0.1:3000 | innova-front (Next.js) |

### Servicos systemd
| Servico | Porta | O que e |
|---|---|---|
| innovafront | 3000 | Front Next.js |
| escolaparque | 8501 | Backend Central (Streamlit) |
| postgrest | 3001 | PostgREST (/home/ubuntu/postgrest.conf) |
| gotrue | 9999 | GoTrue/Auth (/home/ubuntu/gotrue.env) |
| llmgateway | 8600 | API na frente do Ollama |
| vpsadmin | 8500 | Painel VPS |
| vpswebhook | 8800 | Recebe push -> dispara vpsautodeploy |
| vpsautodeploy (+ .timer) | - | "Vercel caseiro": pull+build+restart a cada 2 min |
| bolao-copa26 | 8510 | Bolao |
| postgresql | 5432 | Postgres (banco innova) |

---

## 2. Supabase caseiro (Postgres + PostgREST + GoTrue + pgvector)

- Postgres: banco `innova` em 127.0.0.1:5432. Outros: postgres, bolao_copa26, evolution.
- Roles (modelo Supabase): anon, authenticated, authenticator, service_role, innova_app, innova_worker, supabase_auth_admin (dono do schema auth).
- PostgREST: config /home/ubuntu/postgrest.conf (jwt-secret, db-uri, db-anon-role). Exposto em /rest/v1/.
- GoTrue: binario /usr/local/bin/gotrue (compilado do fonte supabase/auth v2.190.0). Config /home/ubuntu/gotrue.env. Schema auth.* (23 tabelas) no banco innova.
- JWT secret: UM so pra stack inteira = o jwt-secret do postgrest.conf. GoTrue reusa (GOTRUE_JWT_SECRET); chaves anon/service do front sao assinadas com ele.

### Conexoes ao banco
| Quem | Como |
|---|---|
| Front (Next.js) | Drizzle/postgres-js direto: DATABASE_URL=postgres://innova_app:...@127.0.0.1:5432/innova (em /home/ubuntu/innova-front/.env.local). Auth via @supabase/ssr -> NEXT_PUBLIC_SUPABASE_URL=https://escolaparque-app.duckdns.org (GoTrue local). |
| Backend Central (Streamlit/worker) | innova_bridge -> run_async(get_pool()) (asyncpg). URL vem do carrossel bancos_pool.json (Fernet) via storage_bancos.get_active_bd_decifrado(). BD ativo = innova local (confirmado pelo heartbeat system_settings['python_worker_heartbeat'], host escola-parque-v3). |
| Claude via MCP | sql_local (banco innova, como worker=service_role ou app=front). |

---

## 3. AUTH (GoTrue) - cutover da nuvem pro VPS

Antes: front logava na nuvem (awosfxlcjqotforkixps.supabase.co); dados ja eram locais -> split-brain.
Depois (2026-06-15): GoTrue local; NEXT_PUBLIC_SUPABASE_URL aponta pro VPS; chaves anon/service novas (assinadas pelo jwt-secret local). Nuvem aposentada.

### Como subiu (script install_gotrue.sh na pasta do backend)
1. Go (arm64) -> make build do supabase/auth -> /usr/local/bin/gotrue.
2. Role supabase_auth_admin dono do schema auth; reassinala objetos pre-existentes; DROP FUNCTION auth.jwt() (a migracao recria).
3. gotrue.env (DB->innova, GOTRUE_JWT_SECRET=jwt-secret do PostgREST, GOTRUE_DISABLE_SIGNUP=true, SMTP opcional, SITE_URL/API_EXTERNAL_URL=escolaparque-app.duckdns.org).
4. systemd gotrue.service + rota /auth/v1 no Nginx.

### Logins atuais (5) - public.users.id == auth.users.id
| Papel | E-mail |
|---|---|
| super_admin | diogobsbastos@gmail.com |
| admin | admin@innova.dev |
| teacher | math@innova.dev |
| teacher | portuguese@innova.dev |
| aee | aee@innova.dev |

Criados por SQL direto em auth.users (script cutover_prep.sh), com email_confirmed_at setado. SMTP ainda desligado (MAILER_AUTOCONFIRM); ligar pra reset por e-mail.

---

## 4. Apps e repositorios

| App | Pasta VPS | Repo GitHub | Servico | Deploy |
|---|---|---|---|---|
| Front (Next.js) | /home/ubuntu/innova-front | diogobsbastos/escola-parque-frontend | innovafront | AUTO (push->pull+build+restart) |
| Backend Central (Streamlit) | /home/ubuntu/escola-parque | diogobsbastos/escola-parque | escolaparque | git pull simples + restart (pasta tem dados vivos) |
| Bolao | /home/ubuntu/bolao-copa26 | diogobsbastos/bolao-copa26 | bolao-copa26 | Auto |
| VPS Admin | /home/ubuntu/vps-admin | - | vpsadmin | scp |
| LLM Gateway | /home/ubuntu/llm-gateway | - | llmgateway | scp |

Front e backend = MESMO modelo de dados (Drizzle schema.ts e a fonte da verdade). Front NAO roda LLM - enfileira; o worker Python processa.

---

## 5. FLUXOS DE DEPLOY

### 5.1 Front (Next.js) - AUTOMATICO
1. Editar no clone local EscolaParque_DEV/escola-parque-frontend (ou Claude via MCP).
2. Push pra main.
3. VPS publica sozinho: vpsautodeploy (timer 2 min, ou webhook ~5s) faz fetch + reset --hard origin/main + npm run build + restart innovafront.
- Registro: ~/.vps_git_projetos.json -> {"escola-parque-frontend": {"auto":true,"pull":"/home/ubuntu/innova-front","build":"npm run build","servicos":["innovafront"]}}.
- Credencial git: GLOBAL (git config --global credential.helper store + ~/.git-credentials com PAT) - cobre todos os repos privados.
- Se o build quebrar, o front segue na versao anterior (so reinicia se o build passar).

### 5.2 Backend Central (Streamlit) - SEMI-MANUAL SEGURO
> NUNCA colocar essa pasta no auto-deploy com reset --hard/clean -fd: tem banco_alunos.db, keys/, bancos_pool.json, .gotrue_keys, caches - seriam APAGADOS.
1. Editar local + push pra diogobsbastos/escola-parque.
2. No VPS: git pull (fast-forward; nao toca arquivo nao-rastreado) -> sudo systemctl restart escolaparque.

### 5.3 Claude sem shell no VPS
Via MCP: sql_local (SQL/DDL), escrever_arquivo/ler_arquivo (dentro das pastas de app), git (status|pull|log|diff), servico (restart/stop/start da whitelist), logs, recursos. NAO ha terminal livre - npm build, apt, systemctl arbitrario e edicao de /etc sao do usuario.

---

## 6. CILADAS JA RESOLVIDAS (nao tropecar de novo)

1. GoTrue "must be owner of function uid/jwt" -> schema auth tinha funcoes pre-existentes de outro dono. Fix: reassinar posse pro supabase_auth_admin + DROP FUNCTION auth.jwt().
2. GoTrue "Database error querying schema" no login -> colunas texto em auth.users ficaram NULL (Go espera ''). Fix: UPDATE auth.users SET <col>='' WHERE <col> IS NULL para colunas character varying/text, EXCETO phone e email (unique).
3. git pull pedindo Username -> repo privado sem credencial. Fix: PAT em ~/.git-credentials (global).
4. Type-check do build quebrando (super_admin/student/guardian) -> schema.ts do VPS velho. Sincronizar schema.ts ao mexer em papeis; mapas exaustivos Record<User["role"],...> (ex.: user-menu.tsx) precisam cobrir os 7 papeis.
5. Arvore git "toda modificada" no Windows -> CRLF. Fix: git config core.autocrlf false + git reset --hard origin/main.
6. .git/index.lock travado -> del .git\index.lock (Win) e refazer.
7. Mount do sandbox serve versao stale -> validar pelo Read/Grep no path real.
8. GoTrue nao publica binario ARM64 -> compilar do fonte (make build). Sem Docker.

---

## 7. SEGREDOS - onde moram (NUNCA em git)

| Segredo | Onde |
|---|---|
| jwt-secret (stack) | /home/ubuntu/postgrest.conf e /home/ubuntu/gotrue.env |
| chaves anon/service do front | /home/ubuntu/escola-parque/.gotrue_keys e /home/ubuntu/innova-front/.env.local |
| senha supabase_auth_admin | /home/ubuntu/escola-parque/.gotrue_dbpw |
| PAT do GitHub (deploy) | /home/ubuntu/.git-credentials |
| segredo HMAC do webhook | /home/ubuntu/.vps_webhook_secret |
| chaves LLM / Fernet | bancos_pool.json, keys/, .secret_key (cifrados) |

### Acoes de higiene pendentes
- [ ] Trocar as 5 senhas temporarias; ligar SMTP no gotrue.env.
- [ ] Revogar o PAT colado em chat e gerar outro (fine-grained read-only).
- [ ] .gitignore do escola-parque cobrir .gotrue_keys, .gotrue_dbpw, gotrue.secrets, *.db, keys/.
- [ ] Aposentar o projeto Supabase da nuvem (awosfxlcjqotforkixps) e rotacionar o service_role antigo.

---

## 8. Modelo de papeis (F2) e o que falta

user_role (7): super_admin, admin, coordinator, teacher, aee, student, guardian.
Hierarquia: super_admin (plataforma, ponte) > admin (Adm do Colegio/Diretor) > coordinator/teacher/aee > student/guardian (ve so o proprio, via student_access).

Feito: cutover auth; auto-deploy front; ponte super_admin->Backend Central na sidebar; super_admin herda acesso de admin.
Falta (F2): (1) botao "voltar pro Frontend" no Streamlit; (2) super_admin CRUD de Colegios+Sedes; (3) login de aluno/responsavel (student_access + RLS por aluno); (4) gating por papel (coordinator/teacher/aee); (5) console de Gestao & Hierarquia no Backend + CRUD de cadastros com criacao de login (GoTrue Admin API).

---
Fim. Documento vivo.
