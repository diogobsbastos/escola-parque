# Escola Parque V3 — Servidor Oracle Cloud (Handover / Status)

> ✅ **ATUALIZAÇÃO 03/06/2026 (noite): SERVIDOR NO AR!**
> - Instância **`escola-parque-v3`** — RUNNING 🟢
> - Shape: VM.Standard.A1.Flex (Always Free) — 4 OCPU / 24 GB / Ubuntu 22.04
> - **IP público: `137.131.156.145`** · usuário SSH: `ubuntu`
> - Compartment: `escola-parque` · VCN: `vcn-escola-parque` · Subnet: `subnet-escola-parque`
> - Chave SSH: `ssh-key-2026-06-03.key` (privada) + `.key.pub` — **guardar em local seguro + backup!**
> - Conta: upgrade Pay As You Go concluído (Always Free permanece R$0)
> - ✅ FASE 3 CONCLUÍDA: portas 80/443/8501 abertas (Security List Oracle + iptables).
>   ⚠️ Lição: no iptables, as regras ACCEPT devem ficar ANTES da regra REJECT (usar `-I INPUT 5`).
>   Teste confirmado: http://137.131.156.145 acessível pelo navegador.
> - Próximo: Fase 4 (deploy do app) — ver tarefas abaixo.

> Documento de continuidade. Registra tudo o que foi feito na sessão de **03/06/2026** e o que falta.
> Retome a partir da seção **"PRÓXIMOS PASSOS"**.

---

## 1. RESUMO DA SESSÃO

Objetivo: subir um VPS gratuito na **Oracle Cloud (ARM Ampere A1 — Always Free)** para hospedar o
Escola Parque V3 (Streamlit + OpenCV + PyMuPDF + LiteLLM).

O que aconteceu: descobrimos que o Diogo **já tinha uma conta Oracle antiga** (criada em 20/03/2026),
que estava com o **trial de 30 dias expirado** (convertida automaticamente para Always Free).
Recuperamos o acesso, ajustamos os e-mails para o e-mail pessoal e iniciamos o **upgrade para Pay As You Go**
(para vencer o problema de capacidade do ARM em São Paulo). **Paramos antes de criar a instância.**

---

## 2. DADOS DA CONTA ORACLE CLOUD

| Item | Valor |
|---|---|
| Cloud Account Name (Tenancy) | **`tecnicoeurio`** |
| Home Region | **Brazil East (São Paulo)** — `sa-saopaulo-1` |
| Tipo de conta | Promoção → **upgrade Pay As You Go EM ANDAMENTO** |
| Plan reference | `42765966` |
| Console | https://cloud.oracle.com |

### Usuários (Identity Domain "Default")
| Usuário | E-mail | Observação |
|---|---|---|
| `tecnico.eurio@gmail.com` | diogobsbastos@gmail.com | Admin original. Login via **passkey FIDO** no **outro laptop**. |
| `diogobsbastos@gmail.com` | diogobsbastos@gmail.com | Criado em 03/06/2026. **Verificar se está no grupo Administrators.** |

### Login / acesso
- Método atual: **passkey FIDO** ("Diogo's FIDO_AUTHENTICATOR-2") registrada **no outro laptop** (Windows Hello).
- ⚠️ **AÇÃO CRÍTICA (anti-lockout):** criar uma **senha** ou registrar uma **passkey neste computador**
  em `My profile → Security`, para não depender só do outro laptop.
- 🔒 A senha antiga (formato `@Ee...`) foi exposta durante a sessão — **trocar por segurança** e guardar
  em gerenciador de senhas.

### Limpeza do e-mail da empresa (`tecnico.eurio@gmail.com`)
- ✅ E-mail principal (notificações de identidade) → `diogobsbastos@gmail.com`
- ✅ E-mail de recuperação → `diogobsbastos@gmail.com`
- ⏳ **E-mail de contato da conta / cobrança** (em "Detalhes da conta") → ainda `tecnico.eurio`.
  Trocar se houver botão "Editar"; se estiver travado, abrir **ticket no suporte**. (É cosmético.)
- ℹ️ O **username** `tecnico.eurio@gmail.com` é só identificador de login — **não recebe e-mail**.

---

## 3. RECURSOS ALWAYS FREE DISPONÍVEIS (de graça, permanente)

- **ARM Ampere A1:** até **4 OCPUs + 24 GB RAM** (shape `VM.Standard.A1.Flex`)
- **200 GB** de block storage
- **10 TB/mês** de tráfego de saída
- Os recursos Always Free **continuam grátis** mesmo após o upgrade para Pay As You Go.
- 💳 Pay As You Go: só cobra se criar recursos **além** do limite free. Configurar **Budget Alert (~US$1)**
  em `Billing & Cost Management → Budgets`.

---

## 4. PRÓXIMOS PASSOS (retomar daqui)

### Passo 0 — Pré-requisitos
1. [ ] Aguardar e-mail de **conclusão do upgrade Pay As You Go**.
2. [ ] Criar **senha/passkey própria** neste computador (anti-lockout).
3. [ ] Confirmar que `diogobsbastos@gmail.com` está no grupo **Administrators**.
4. [ ] (Opcional) Configurar **Budget Alert** de ~US$1.

### FASE 2 — Criar a instância ARM
- ☰ → **Compute → Instances → Create instance**
- Name: `escola-parque-v3`
- Image: **Canonical Ubuntu 22.04** (confirmar **aarch64/ARM**)
- Shape: **Ampere → VM.Standard.A1.Flex → 4 OCPU / 24 GB**
- Networking: **Create new VCN** + **marcar "Assign a public IPv4 address"**
- SSH: **"Generate a key pair for me"** → 🔴 **BAIXAR a chave privada** (`.key`) — só aparece uma vez!
- ⚠️ **Risco "Out of capacity"** (São Paulo só tem AD-1): com Pay As You Go deve ser raro.
  Se ocorrer: tentar **1 OCPU / 6 GB** e redimensionar depois, ou usar **script de retry** (OCI CLI em loop).

### FASE 3 — Rede e firewall
- Security List / NSG: abrir portas **22 (SSH)**, **80/443 (web)** e **8501 (Streamlit, temporário)**.
- No Ubuntu: ajustar **iptables** (Oracle Ubuntu vem com regras restritivas por padrão).

### FASE 4 — Deploy do Escola Parque V3
- Instalar Python + venv; deps de sistema do **OpenCV** e **PyMuPDF** compiladas para **ARM64**.
- Serviço **systemd** (`escolaparque.service`) para o Streamlit subir no boot e reiniciar.
- **Nginx** como reverse proxy + **HTTPS** (Let's Encrypt / certbot).

### DECISÃO PENDENTE — Motor de IA (define os scripts de deploy)
- [ ] **Só APIs externas** (LiteLLM → OpenAI/Anthropic/Groq/Gemini) — mais leve. *(recomendado p/ começar)*
- [ ] **Ollama/Qwen local** na VM — privacidade total, mais pesado em ARM.
- [ ] **Híbrido** — local + fallback de API.

---

## 5. PLANO B (se a Oracle voltar a travar)

**Hetzner** (VPS pago barato, cadastro sem burocracia, ARM = mesmos scripts):
- **CAX31:** 16 GB RAM / 8 vCPU ARM — ~R$70–85/mês (roda Ollama 7B quantizado)
- **CAX21:** 8 GB RAM — ~R$45/mês (suficiente p/ APIs externas)
- **CX23 (x86):** 4 GB — ~R$25/mês (só Streamlit + visão, sem LLM local)

Alternativa zero-custo sem servidor: **Hugging Face Spaces** (16 GB RAM, CPU, sem Ollama; LiteLLM via APIs externas).
⚠️ Atenção LGPD: dados de alunos com TDAH são sensíveis — preferir servidor próprio (Oracle/Hetzner).

---

*Última atualização: 03/06/2026.*
