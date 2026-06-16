"""
storage_email.py — Pool de Canais de E-mail (Escola Parque V3)
---------------------------------------------------------------
Mesma filosofia do storage_litellm.py: persiste uma lista de CANAIS de envio
(Gmail, SMTP próprio, etc.) num único JSON na raiz. O envio tenta os canais
HABILITADOS em ordem de PRIORIDADE (menor = tenta primeiro). Se um cai, o
email_sender passa pro PRÓXIMO automaticamente (failover).

NUNCA versionar este arquivo — ele guarda senhas/app-passwords (está no
.gitignore). É um segredo operacional que vive só na VPS.

Cada entrada tem o formato:
    {
        "nome":             "Gmail Principal",   # id único do canal
        "tipo":             "gmail" | "smtp",
        "host":             "smtp.gmail.com",
        "porta":            587,
        "seguranca":        "starttls" | "ssl",  # 587=starttls, 465=ssl
        "usuario":          "conta@gmail.com",
        "senha":            "app-password-16-digitos",
        "remetente_email":  "conta@gmail.com",
        "remetente_nome":   "Escola Parque",
        "habilitado":       True,
        "prioridade":       1,                    # menor tenta primeiro
        "status":           "nao_testado" | "ativo" | "falhou",
        "ultimo_teste":     "mensagem do último envio/teste",
        "ts_cadastro":      "YYYY-MM-DD HH:MM:SS"
    }
"""

import json
import os
import time

ARQUIVO_CANAIS = "canais_email.json"

# Presets de host/porta por tipo (o usuário só informa usuário + app-password).
PRESETS = {
    "gmail": {"host": "smtp.gmail.com", "porta": 587, "seguranca": "starttls"},
    "outlook": {"host": "smtp.office365.com", "porta": 587, "seguranca": "starttls"},
    "smtp": {"host": "", "porta": 587, "seguranca": "starttls"},
}


# ────────────────────────────────────────────────────────────────────────────
# I/O do JSON
# ────────────────────────────────────────────────────────────────────────────
def load_canais():
    """Lê a lista de canais. Sempre devolve list (nunca None).

    Mesma defesa contra null bytes do storage_litellm (Write no Windows às vezes
    injeta \\x00 e quebra o json.load silenciosamente)."""
    if not os.path.exists(ARQUIVO_CANAIS):
        return []
    try:
        with open(ARQUIVO_CANAIS, "rb") as f:
            raw = f.read()
        if b"\x00" in raw:
            raw = raw.replace(b"\x00", b"")
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return []
        dados = json.loads(text)
        return dados if isinstance(dados, list) else []
    except Exception:
        return []


def save_canais(pool):
    """Persiste a lista de canais em disco."""
    try:
        with open(ARQUIVO_CANAIS, "w", encoding="utf-8") as f:
            json.dump(pool, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False


# ────────────────────────────────────────────────────────────────────────────
# Operações de domínio
# ────────────────────────────────────────────────────────────────────────────
def _proxima_prioridade(pool):
    """Retorna a maior prioridade + 1 (novo canal entra no fim da fila)."""
    if not pool:
        return 1
    return max(int(c.get("prioridade", 0) or 0) for c in pool) + 1


def add_canal(nome, tipo="gmail", usuario="", senha="", remetente_nome="Escola Parque",
              remetente_email="", host=None, porta=None, seguranca=None):
    """Adiciona um novo canal de e-mail. Retorna (ok, mensagem)."""
    nome = (nome or "").strip()
    if not nome:
        return False, "O nome do canal não pode ficar em branco."

    usuario = (usuario or "").strip()
    if not usuario:
        return False, "Informe o usuário (e-mail de login do SMTP)."
    if not (senha or "").strip():
        return False, "Informe a senha / app-password do canal."

    pool = load_canais()
    if any((c.get("nome") or "").lower() == nome.lower() for c in pool):
        return False, f"Já existe um canal chamado '{nome}'."

    preset = PRESETS.get(tipo, PRESETS["smtp"])
    host_f = (host if host is not None else preset["host"]) or ""
    porta_f = int(porta if porta is not None else preset["porta"])
    seg_f = (seguranca if seguranca is not None else preset["seguranca"]) or "starttls"

    if not host_f:
        return False, "Para SMTP próprio, informe o host (ex.: smtp.seudominio.com)."

    novo = {
        "nome":            nome,
        "tipo":            tipo,
        "host":            host_f,
        "porta":           porta_f,
        "seguranca":       seg_f,
        "usuario":         usuario,
        "senha":           senha,
        "remetente_email": (remetente_email or usuario).strip(),
        "remetente_nome":  (remetente_nome or "Escola Parque").strip(),
        "habilitado":      True,
        "prioridade":      _proxima_prioridade(pool),
        "status":          "nao_testado",
        "ultimo_teste":    "",
        "ts_cadastro":     time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    pool.append(novo)
    save_canais(pool)
    return True, f"Canal '{nome}' cadastrado! Use 'Testar envio' antes de confiar nele."


def remove_canal(nome):
    """Remove um canal pelo nome e renumera a prioridade dos restantes."""
    pool = [c for c in load_canais() if (c.get("nome") or "") != nome]
    _renumerar(pool)
    save_canais(pool)
    return True


def update_canal(nome, **campos):
    """Edita campos de um canal existente. Campos aceitos: tipo, host, porta,
    seguranca, usuario, senha, remetente_email, remetente_nome.
    Senha vazia/None NÃO sobrescreve a senha atual (mantém a guardada)."""
    pool = load_canais()
    achou = False
    permitidos = {"tipo", "host", "porta", "seguranca", "usuario",
                  "senha", "remetente_email", "remetente_nome"}
    for c in pool:
        if (c.get("nome") or "") == nome:
            for k, v in campos.items():
                if k not in permitidos:
                    continue
                if k == "senha" and not (v or "").strip():
                    continue  # não apaga a senha guardada
                if k == "porta":
                    try:
                        v = int(v)
                    except Exception:
                        continue
                c[k] = v
            c["ts_atualizacao"] = time.strftime("%Y-%m-%d %H:%M:%S")
            achou = True
            break
    if achou:
        save_canais(pool)
    return achou


def set_habilitado(nome, habilitado):
    """Liga/desliga um canal (desligado é pulado no failover)."""
    pool = load_canais()
    for c in pool:
        if (c.get("nome") or "") == nome:
            c["habilitado"] = bool(habilitado)
            save_canais(pool)
            return True
    return False


def update_status(nome, status, msg=""):
    """Atualiza status ('ativo'|'falhou'|'nao_testado') e a msg do último teste."""
    pool = load_canais()
    for c in pool:
        if (c.get("nome") or "") == nome:
            c["status"] = status
            c["ultimo_teste"] = f"{time.strftime('%Y-%m-%d %H:%M')} · {msg}"
            save_canais(pool)
            return True
    return False


def _renumerar(pool):
    """Reescreve prioridade 1..N seguindo a ordem atual da lista."""
    ordenado = sorted(pool, key=lambda c: int(c.get("prioridade", 0) or 0))
    for i, c in enumerate(ordenado, start=1):
        c["prioridade"] = i


def mover_prioridade(nome, direcao):
    """Sobe (-1) ou desce (+1) um canal na fila de failover."""
    pool = load_canais()
    pool.sort(key=lambda c: int(c.get("prioridade", 0) or 0))
    idx = next((i for i, c in enumerate(pool) if (c.get("nome") or "") == nome), None)
    if idx is None:
        return False
    novo_idx = idx + (1 if direcao > 0 else -1)
    if novo_idx < 0 or novo_idx >= len(pool):
        return False
    pool[idx], pool[novo_idx] = pool[novo_idx], pool[idx]
    _renumerar(pool)
    save_canais(pool)
    return True


def get_canais_ordenados(somente_habilitados=True):
    """Retorna os canais em ordem de prioridade (failover). Por padrão só os
    habilitados — é a lista que o email_sender percorre."""
    pool = load_canais()
    if somente_habilitados:
        pool = [c for c in pool if c.get("habilitado", True)]
    return sorted(pool, key=lambda c: int(c.get("prioridade", 0) or 0))


def tem_canal_ativo():
    """True se existe ao menos um canal habilitado (pronto pra tentar enviar)."""
    return len(get_canais_ordenados(somente_habilitados=True)) > 0
