"""
storage_litellm.py — Pool de Provedores LiteLLM (Escola Parque V3)
------------------------------------------------------------------
Persiste a lista de provedores cadastrados (gemini, openai, anthropic,
groq, alibaba, kimi, custom/local etc.) em um único JSON na raiz.

Cada entrada tem o formato:
    {
        "provedor":     "openai",
        "modelo":       "gpt-4o-mini",
        "api_key":      "sk-...",
        "base_url":     "",                     # vazio = endpoint padrão
        "status":       "ativo" | "falhou",
        "ultimo_teste": "mensagem do último ping",
        "ts_cadastro":  "YYYY-MM-DD HH:MM:SS",
        "is_active":    True | False            # apenas UM provedor é ativo
    }
"""

import json
import os
import time

ARQUIVO_PROV = "providers_litellm.json"


# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATES DE PROMPT-PAI POR ESTRATÉGIA OCR
# ═══════════════════════════════════════════════════════════════════════════
# Cada estratégia tem um perfil ótimo distinto:
#   • Modo 1 (6 fatias clássico)  → prompt longo, agressivo, ideal para Gemini
#   • Modo 1 Turbo (v7 Gemini)    → prompt médio, formato CSV ID:M/V friendly
#   • Modo 2 v7 (LLM local)       → prompt CURTO, sem safety triggers
# Esses templates são oferecidos como botão "Carregar template" no Painel 1.
# ═══════════════════════════════════════════════════════════════════════════

PROMPT_TEMPLATE_MODO1_6FATIAS = """⛔ DIRETIVA DE ANÁLISE VISUAL — CLASSIFICADOR FORENSE DE CHECKBOX ⛔

CONTEXTO
Você é um sistema de visão computacional de alta precisão analisando um formulário
clínico/pedagógico. Cada item da análise é um QUADRADO IMPRESSO (checkbox) que pode
estar MARCADO (preenchido pelo aluno) ou VAZIO (não preenchido). A exatidão é
inegociável: este diagnóstico afetará o atendimento de um aluno real.

PRINCÍPIO Nº 1 — A REGRA DO CENTRO BRANCO
Sua maior fraqueza é confundir a linha preta que forma a BORDA IMPRESSA do quadrado
com um traço de caneta. Para vencer esse viés:
  → IGNORE COMPLETAMENTE as bordas pretas do quadrado.
  → Olhe APENAS para o MIOLO do quadrado (a área branca interna).
VEREDITO:
  • Se o MIOLO está predominantemente BRANCO (cor natural do papel),
    com no máximo manchas/sombras suaves → o checkbox está VAZIO.
  • Se o MIOLO está RASGADO/CRUZADO por uma linha intencional e forte
    (X, traço diagonal, riscado, ponto grosso, preenchimento) → MARCADO.

PRINCÍPIO Nº 2 — O QUE É RUÍDO (sempre VAZIO)
  ✗ Manchas difusas ou sombras sem bordas definidas.
  ✗ Pontos finíssimos ou linhas horizontais/verticais milimétricas.
  ✗ Bleed-through — sombra escura vinda de tinta no verso (parece névoa).
  ✗ Borda inferior/superior do quadrado um pouco mais grossa por JPEG.

PRINCÍPIO Nº 3 — ASSIMETRIA DE PENALIDADE
A penalidade por gerar um FALSO POSITIVO é INFINITAMENTE MAIOR que por falso negativo.
  → Na dúvida: VAZIO.
  → Só MARCADO com >85% de confiança de traço intencional cruzando o miolo.

PROTOCOLO MENTAL (não escreva):
  1. "Estou olhando o MIOLO BRANCO, não a borda."
  2. "Vejo limpo, sombra difusa ou traço intencional?"
  3. "Sombra/borda/névoa: VAZIO. Traço cruzando: MARCADO."
  4. ">85% confiante? Senão, VAZIO."

FORMATO DE OUTPUT
Siga estritamente o formato pedido pela tarefa específica. A semântica é sempre:
traço intencional no miolo = MARCADO; qualquer outra coisa = VAZIO.

⛔ FIM DA DIRETIVA SUPREMA ⛔"""


PROMPT_TEMPLATE_MODO1_TURBO = """REGRA DE ANÁLISE VISUAL — CHECKBOX EM FORMULÁRIO ESCOLAR

Você está vendo fatias de uma prova com checkboxes numerados [#N] na margem esquerda.
Para cada um, decida MARCADO ou VAZIO.

CENTRO BRANCO (regra principal):
Olhe apenas o MIOLO interno do quadrado, ignorando as bordas pretas impressas.
  • Miolo branco/limpo = VAZIO
  • Miolo com X, traço, riscado, ponto grosso, preenchimento intencional = MARCADO

RUÍDOS A IGNORAR (sempre VAZIO):
  • Manchas difusas sem bordas definidas
  • Bleed-through (sombra cinza acastanhada do verso, parece névoa)
  • Pontos milimétricos de scanner
  • A própria borda preta impressa do quadrado

ASSIMETRIA DE PENALIDADE (importante):
Em formulários escolares, FALSO NEGATIVO (perder marcação real do professor) é PIOR
que falso positivo. Marcação a lápis ou caneta fraca CONTA:
  • X fraco, X incompleto, X com 1 traço só = MARCADO
  • Diagonal tênue mas com forma definida = MARCADO
  • Preenchimento parcial do miolo = MARCADO
  • Na dúvida entre traço fraco vs bleed: prefira MARCADO

FORMATO DE OUTPUT — CRUCIAL:
A tarefa específica pedirá CSV no formato ID:STATUS. Use:
  • Traço/marca/forma definida no miolo → escreva M
  • Miolo limpo ou sombra difusa        → escreva V

NÃO ESCREVA RACIOCÍNIO. Apenas o CSV completo, direto, sem markdown.
Exemplo: "1:V,2:M,3:V,4:V,5:M"

A semântica é sempre: traço intencional = MARCADO; qualquer outra coisa = VAZIO."""


PROMPT_TEMPLATE_MODO2_LOCAL = """ANÁLISE DE CHECKBOX EM PROVA

Para cada quadrado numerado [#N], decida MARCADO ou VAZIO.

Regra principal:
  • Miolo interno BRANCO e limpo = VAZIO
  • Miolo com X, traço, marca intencional = MARCADO
  • Ignore a borda preta impressa do quadrado

Descartar como VAZIO:
  • Sombras difusas sem forma definida
  • Bleed-through (névoa do verso da folha)
  • Pontos de scanner

Marcação a lápis pode estar fraca — qualquer traço com forma conta como
MARCADO. Falso negativo é pior que falso positivo neste contexto.

Responda apenas o CSV pedido. Sem texto explicativo."""


# ────────────────────────────────────────────────────────────────────────────
# I/O do JSON
# ────────────────────────────────────────────────────────────────────────────
def load_providers():
    """Lê a lista de provedores cadastrados. Sempre devolve list (nunca None).

    Defesa contra null bytes: o Write tool no Windows as vezes injeta \\x00
    no final do arquivo. Sem essa limpeza, json.load explode com 'Extra data'
    e a UI silenciosamente perde TODOS os provedores cadastrados.
    """
    if not os.path.exists(ARQUIVO_PROV):
        return []
    try:
        # Lemos em bytes pra remover null bytes antes do decode UTF-8
        with open(ARQUIVO_PROV, "rb") as f:
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


def save_providers(pool):
    """Persiste a lista de provedores em disco."""
    try:
        with open(ARQUIVO_PROV, "w", encoding="utf-8") as f:
            json.dump(pool, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False


# ────────────────────────────────────────────────────────────────────────────
# Operações de domínio
# ────────────────────────────────────────────────────────────────────────────
def _strip_redundant_provider_prefix(provedor, modelo):
    """Remove o prefixo 'X/' do modelo SOMENTE quando X repete o nome do provedor.

    Ex.: provedor 'gemini' + 'gemini/gemini-2.5-flash' -> 'gemini-2.5-flash'.

    PRESERVA prefixos que fazem parte do id REAL do modelo (ex.: OpenRouter
    'meta-llama/llama-3.3-70b-instruct'): ali 'meta-llama' NAO bate com o provedor
    ('custom/local'), entao nada e removido. Idem 'google/gemini-...' via OpenRouter.
    """
    if not modelo or "/" not in modelo:
        return modelo
    prefixo, resto = modelo.split("/", 1)
    p = (prefixo or "").strip().lower()
    prov = (provedor or "").strip().lower()
    _GEMINI_ALIASES = {"google", "gemini"}
    redundante = (p == prov) or (p in _GEMINI_ALIASES and any(a in prov for a in _GEMINI_ALIASES))
    return resto if redundante else modelo


def add_provider(provedor, modelo_str, api_key="", base_url=""):
    """Adiciona um novo provedor ao pool LiteLLM. Retorna (ok, mensagem)."""
    if not modelo_str:
        return False, "Model String não pode ficar em branco."

    # Normaliza: tira o prefixo redundante do provedor (gemini/gemini-... -> gemini-...).
    modelo_str = _strip_redundant_provider_prefix(provedor, modelo_str)

    pool = load_providers()
    if any(p.get("modelo") == modelo_str for p in pool):
        return False, f"Modelo '{modelo_str}' já está cadastrado."

    # Default sensato de max_output_tokens conforme provedor (cada modelo tem teto diferente)
    DEFAULTS_MAX_OUT = {
        "gemini":    16384,
        "openai":    16384,
        "anthropic":  8192,
        "groq":       8192,
        "alibaba":    8192,
        "kimi":       8192,
    }
    max_out_default = 8192
    for chave_d, val_d in DEFAULTS_MAX_OUT.items():
        if chave_d in (provedor or "").lower():
            max_out_default = val_d
            break

    novo = {
        "provedor":          provedor,
        "modelo":            modelo_str,
        "api_key":           api_key or "",
        "base_url":          base_url or "",
        "status":            "ativo",
        "ultimo_teste":      "",
        "ts_cadastro":       time.strftime("%Y-%m-%d %H:%M:%S"),
        "is_active":         len(pool) == 0,   # o primeiro cadastrado já vira ativo
        "apenas_precos":     False,            # False = aparece no Painel 1 (em uso). True = só na biblioteca de Preços (Painel 3).
        "max_output_tokens": int(max_out_default),
        "prompt_reforco":    "",          # Prompt-PAI opcional (calibracao por modelo)
        "custos": {                       # Tabela de precos editavel (USD por 1M tokens)
            "in_usd_1M":    0.0,
            "out_usd_1M":   0.0,
            "cache_usd_1M": 0.0,
        },
    }
    pool.append(novo)
    save_providers(pool)
    return True, f"Provedor '{modelo_str}' cadastrado com sucesso!"


def remove_provider(modelo_str):
    """Remove um provedor pelo modelo. Reativa o primeiro se removermos o ativo."""
    pool = load_providers()
    era_ativo = any(p.get("modelo") == modelo_str and p.get("is_active") for p in pool)
    pool = [p for p in pool if p.get("modelo") != modelo_str]

    if era_ativo and pool:
        pool[0]["is_active"] = True

    save_providers(pool)


def set_active_model(modelo_str):
    """Marca um modelo como ativo (cérebro principal). Os demais ficam False."""
    pool = load_providers()
    achou = False
    for p in pool:
        if p.get("modelo") == modelo_str:
            p["is_active"] = True
            achou = True
        else:
            p["is_active"] = False
    save_providers(pool)
    return achou


def get_active_provider():
    """Retorna o dicionário do provedor ativo (ou None se nada cadastrado)."""
    pool = load_providers()
    for p in pool:
        if p.get("is_active"):
            return p
    return pool[0] if pool else None


def update_status(modelo_str, status, msg=""):
    """Atualiza status e mensagem do último teste de ping."""
    pool = load_providers()
    for p in pool:
        if p.get("modelo") == modelo_str:
            p["status"] = status
            p["ultimo_teste"] = msg
    save_providers(pool)


def listar_modelos_cadastrados():
    """Retorna apenas a lista plana de Model Strings cadastradas."""
    return [p.get("modelo") for p in load_providers() if p.get("modelo")]


def get_custos_provedor(modelo_str):
    """Retorna dict {in_usd_1M, out_usd_1M, cache_usd_1M} do provedor (ou zeros)."""
    pool = load_providers()
    for p in pool:
        if p.get("modelo") == modelo_str:
            c = p.get("custos") or {}
            return {
                "in_usd_1M":    float(c.get("in_usd_1M",    0.0) or 0.0),
                "out_usd_1M":   float(c.get("out_usd_1M",   0.0) or 0.0),
                "cache_usd_1M": float(c.get("cache_usd_1M", 0.0) or 0.0),
            }
    return {"in_usd_1M": 0.0, "out_usd_1M": 0.0, "cache_usd_1M": 0.0}


def set_custos_provedor(modelo_str, in_usd_1M=0.0, out_usd_1M=0.0, cache_usd_1M=0.0):
    """Salva os custos editados manualmente (ou via buscar_custos_no_catalogo) no JSON."""
    pool = load_providers()
    achou = False
    for p in pool:
        if p.get("modelo") == modelo_str:
            p["custos"] = {
                "in_usd_1M":    float(in_usd_1M    or 0.0),
                "out_usd_1M":   float(out_usd_1M   or 0.0),
                "cache_usd_1M": float(cache_usd_1M or 0.0),
            }
            achou = True
            break
    if achou:
        save_providers(pool)
    return achou


def update_provider(modelo_antigo, novo_provedor=None, novo_modelo_str=None,
                    nova_api_key=None, nova_base_url=None):
    """
    Edita um provedor existente. Qualquer kwarg deixado em None mantem o valor atual.

    Comportamento se 'novo_modelo_str' for diferente do 'modelo_antigo':
      • a entrada NAO e removida — ela e atualizada com o novo nome
      • os custos sao RESETADOS para zero (porque e um novo modelo na lista de precos)
      • is_active/status sao preservados

    Retorna (ok: bool, mensagem: str).
    """
    if not modelo_antigo:
        return False, "Modelo antigo nao informado."

    pool = load_providers()
    achou = False
    for i, p in enumerate(pool):
        if p.get("modelo") == modelo_antigo:
            achou = True

            # Normaliza o novo nome (tira prefixo redundante do provedor efetivo).
            if novo_modelo_str:
                _prov_efetivo = novo_provedor if novo_provedor is not None else p.get("provedor", "")
                novo_modelo_str = _strip_redundant_provider_prefix(_prov_efetivo, novo_modelo_str)

            # Se o novo modelo ja existe em OUTRA entrada, bloqueia
            if novo_modelo_str and novo_modelo_str != modelo_antigo:
                if any(q.get("modelo") == novo_modelo_str for j, q in enumerate(pool) if j != i):
                    return False, f"Modelo '{novo_modelo_str}' ja existe em outra linha."

            # Aplica atualizacoes
            if novo_provedor   is not None: p["provedor"] = novo_provedor
            if nova_api_key    is not None: p["api_key"]  = nova_api_key
            if nova_base_url   is not None: p["base_url"] = nova_base_url

            if novo_modelo_str and novo_modelo_str != modelo_antigo:
                p["modelo"] = novo_modelo_str
                # Reset custos — e um modelo "novo" para a tabela de precos
                p["custos"] = {
                    "in_usd_1M":    0.0,
                    "out_usd_1M":   0.0,
                    "cache_usd_1M": 0.0,
                }
                # status volta para ativo, ultimo_teste limpa
                p["status"]       = "ativo"
                p["ultimo_teste"] = ""

            p["ts_atualizacao"] = time.strftime("%Y-%m-%d %H:%M:%S")
            break

    if not achou:
        return False, f"Modelo '{modelo_antigo}' nao encontrado."

    save_providers(pool)
    return True, f"Provedor atualizado com sucesso."


def get_max_output_tokens(modelo_str, default=16384):
    """Retorna o max_output_tokens configurado para o provedor (ou default)."""
    pool = load_providers()
    for p in pool:
        if p.get("modelo") == modelo_str:
            v = p.get("max_output_tokens")
            try:
                return int(v) if v else int(default)
            except Exception:
                return int(default)
    return int(default)


def set_max_output_tokens(modelo_str, valor):
    """Salva o max_output_tokens editado pelo usuario."""
    try:
        valor = int(valor)
    except Exception:
        return False
    if valor < 256 or valor > 200000:
        return False
    pool = load_providers()
    achou = False
    for p in pool:
        if p.get("modelo") == modelo_str:
            p["max_output_tokens"] = valor
            achou = True
            break
    if achou:
        save_providers(pool)
    return achou


def get_prompt_reforco(modelo_str, estrategia=None):
    """Retorna o prompt-PAI configurado para o provedor.

    Se 'estrategia' for fornecida (ex.: "modo1_6fatias", "modo1_turbo",
    "modo2_microvision") e o provedor tiver um prompt específico cadastrado
    em prompts_por_estrategia, retorna ESSE prompt. Senão, cai no
    prompt_reforco geral (legado). Se nenhum existir, retorna string vazia.

    Esse design preserva 100% retrocompatibilidade.
    """
    pool = load_providers()
    for p in pool:
        if p.get("modelo") == modelo_str:
            if estrategia:
                prompts_esp = p.get("prompts_por_estrategia") or {}
                prompt_esp = (prompts_esp.get(estrategia) or "").strip()
                if prompt_esp:
                    return prompt_esp
            return (p.get("prompt_reforco") or "").strip()
    return ""


def set_prompt_reforco(modelo_str, texto):
    """Salva o prompt-PAI GERAL (legado) do provedor.
    Para salvar específico por estratégia, use set_prompt_por_estrategia."""
    pool = load_providers()
    achou = False
    for p in pool:
        if p.get("modelo") == modelo_str:
            p["prompt_reforco"] = (texto or "").strip()
            achou = True
            break
    if achou:
        save_providers(pool)
    return achou


def get_prompt_por_estrategia(modelo_str, estrategia):
    """Retorna SÓ o prompt específico da estratégia (sem fallback), ou ''."""
    pool = load_providers()
    for p in pool:
        if p.get("modelo") == modelo_str:
            prompts_esp = p.get("prompts_por_estrategia") or {}
            return (prompts_esp.get(estrategia) or "").strip()
    return ""


def set_prompt_por_estrategia(modelo_str, estrategia, texto):
    """Salva um prompt-PAI específico para combinação modelo + estratégia.
    Texto vazio remove o prompt (volta a usar o legado)."""
    if estrategia not in ESTRATEGIAS_OCR_VALIDAS:
        return False
    pool = load_providers()
    achou = False
    for p in pool:
        if p.get("modelo") == modelo_str:
            if "prompts_por_estrategia" not in p or not isinstance(p.get("prompts_por_estrategia"), dict):
                p["prompts_por_estrategia"] = {}
            texto_limpo = (texto or "").strip()
            if texto_limpo:
                p["prompts_por_estrategia"][estrategia] = texto_limpo
            else:
                p["prompts_por_estrategia"].pop(estrategia, None)
            achou = True
            break
    if achou:
        save_providers(pool)
    return achou


def clonar_provedor_com_novo_modelo(modelo_antigo, novo_modelo_str, tornar_ativo=True):
    """
    CLONA um provedor existente trocando apenas o nome do modelo.
    O provedor ANTIGO PERMANECE INTACTO na lista (com seu max_output, custos, prompt_reforco).
    O NOVO entra como nova entrada, herdando:
      • provedor (mesma plataforma)
      • api_key  (mesma chave do dashboard)
      • base_url (mesma URL)
      • prompt_reforco (mesma calibracao — normalmente serve para todos os modelos do mesmo provedor)
    E inicializa zerado/default:
      • custos        (cada modelo tem seu preco — usuario precisa configurar)
      • max_output_tokens (default por provedor — geralmente bom o suficiente)
      • status        (ativo)
      • is_active     (True se tornar_ativo=True; libera o flag do antigo)

    Retorna (ok: bool, mensagem: str).
    """
    if not modelo_antigo or not novo_modelo_str:
        return False, "Modelo antigo ou novo nao informado."

    if modelo_antigo == novo_modelo_str:
        return False, "O modelo novo e igual ao antigo — nada a clonar."

    pool = load_providers()

    # Localiza o antigo
    fonte = None
    for p in pool:
        if p.get("modelo") == modelo_antigo:
            fonte = p
            break

    if not fonte:
        return False, f"Modelo '{modelo_antigo}' nao encontrado."

    # Bloqueia se o novo nome ja existe
    if any(p.get("modelo") == novo_modelo_str for p in pool):
        return False, f"Modelo '{novo_modelo_str}' ja existe — clique nele direto ou troque o nome."

    # Default sensato de max_output_tokens para o novo modelo
    DEFAULTS_MAX_OUT = {
        "gemini":    16384,
        "openai":    16384,
        "anthropic":  8192,
        "groq":       8192,
        "alibaba":    8192,
        "kimi":       8192,
    }
    max_out_default = 8192
    prov_low = (fonte.get("provedor") or "").lower()
    for chave_d, val_d in DEFAULTS_MAX_OUT.items():
        if chave_d in prov_low:
            max_out_default = val_d
            break

    # Se for ativar o novo, tira o flag de TODOS os outros
    if tornar_ativo:
        for p in pool:
            p["is_active"] = False

    novo = {
        "provedor":          fonte.get("provedor", ""),
        "modelo":            novo_modelo_str,
        "api_key":           fonte.get("api_key", ""),
        "base_url":          fonte.get("base_url", ""),
        "status":            "ativo",
        "ultimo_teste":      "",
        "ts_cadastro":       time.strftime("%Y-%m-%d %H:%M:%S"),
        "is_active":         bool(tornar_ativo),
        "max_output_tokens": int(max_out_default),
        "prompt_reforco":    fonte.get("prompt_reforco", "") or "",
        "custos": {
            "in_usd_1M":    0.0,
            "out_usd_1M":   0.0,
            "cache_usd_1M": 0.0,
        },
        "clonado_de":        modelo_antigo,
    }
    pool.append(novo)
    save_providers(pool)
    return True, f"Modelo '{novo_modelo_str}' clonado a partir de '{modelo_antigo}'. Antigo preservado na lista."


# ────────────────────────────────────────────────────────────────────────────
# ARQUITETURA SEPARADA: Painel 1 (em uso) vs Painel 3 (biblioteca de precos)
# ────────────────────────────────────────────────────────────────────────────

def load_ativos():
    """
    Retorna SOMENTE os provedores em uso (apenas_precos=False).
    Usado pelo Painel 1 (Provedores Configurados) — modelos que voce esta usando agora.
    """
    return [p for p in load_providers() if not p.get("apenas_precos", False)]


def arquivar_provedor(modelo_str):
    """
    Tira o modelo do Painel 1 (vira apenas_precos=True), mas PRESERVA na biblioteca
    de Preços (Painel 3) com seus custos editados. Util quando voce quer parar de
    usar um modelo mas pode voltar a usar no futuro.
    Se era o modelo ATIVO, transfere o flag is_active para outro ativo.
    """
    pool = load_providers()
    achou = False
    era_ativo = False
    for p in pool:
        if p.get("modelo") == modelo_str:
            p["apenas_precos"] = True
            era_ativo = bool(p.get("is_active"))
            p["is_active"] = False
            achou = True
            break

    if not achou:
        return False

    # Se era o ativo, reativa o primeiro outro disponivel (apenas_precos=False)
    if era_ativo:
        for p in pool:
            if not p.get("apenas_precos") and p.get("modelo") != modelo_str:
                p["is_active"] = True
                break

    save_providers(pool)
    return True


def substituir_e_arquivar(modelo_antigo, novo_modelo_str, tornar_ativo=True):
    """
    Substitui o modelo de uso (no Painel 1) por um novo:
      • O ANTIGO e arquivado (apenas_precos=True) — fica visivel apenas na biblioteca
        de Precos (Painel 3) com seus custos editados intactos.
      • O NOVO entra no Painel 1 (apenas_precos=False), herdando do antigo:
          - provedor, api_key, base_url, prompt_reforco
        e iniciando zerado/default:
          - custos, max_output_tokens
      • Se tornar_ativo=True, o novo vira o modelo ATIVO.

    Retorna (ok: bool, mensagem: str).
    """
    if not modelo_antigo or not novo_modelo_str:
        return False, "Modelo antigo ou novo nao informado."

    if modelo_antigo == novo_modelo_str:
        return False, "O modelo novo e igual ao antigo — nada a fazer."

    pool = load_providers()

    fonte = None
    for p in pool:
        if p.get("modelo") == modelo_antigo:
            fonte = p
            break

    if not fonte:
        return False, f"Modelo '{modelo_antigo}' nao encontrado."

    # Bloqueia se o novo nome ja existe (mesmo arquivado)
    existente = next((q for q in pool if q.get("modelo") == novo_modelo_str), None)
    if existente:
        # Se ja existe E esta arquivado, REATIVA ele em vez de criar duplicata
        if existente.get("apenas_precos"):
            # Arquiva o antigo
            fonte["apenas_precos"] = True
            fonte["is_active"] = False
            # Reativa o existente (move de "apenas precos" pra "em uso")
            existente["apenas_precos"] = False
            if tornar_ativo:
                # Desliga is_active de TODOS e ativa o que voltou
                for p in pool:
                    p["is_active"] = False
                existente["is_active"] = True
            save_providers(pool)
            return True, f"Modelo '{novo_modelo_str}' reativado da biblioteca! Antigo '{modelo_antigo}' arquivado."
        else:
            return False, f"Modelo '{novo_modelo_str}' ja esta em uso. Use o ⭐ para troca-lo de ativo."

    # Default sensato de max_output_tokens
    DEFAULTS_MAX_OUT = {
        "gemini":    16384,
        "openai":    16384,
        "anthropic":  8192,
        "groq":       8192,
        "alibaba":    8192,
        "kimi":       8192,
    }
    max_out_default = 8192
    prov_low = (fonte.get("provedor") or "").lower()
    for chave_d, val_d in DEFAULTS_MAX_OUT.items():
        if chave_d in prov_low:
            max_out_default = val_d
            break

    # Arquiva o antigo
    fonte["apenas_precos"] = True
    fonte["is_active"] = False

    if tornar_ativo:
        for p in pool:
            p["is_active"] = False

    novo = {
        "provedor":          fonte.get("provedor", ""),
        "modelo":            novo_modelo_str,
        "api_key":           fonte.get("api_key", ""),
        "base_url":          fonte.get("base_url", ""),
        "status":            "ativo",
        "ultimo_teste":      "",
        "ts_cadastro":       time.strftime("%Y-%m-%d %H:%M:%S"),
        "is_active":         bool(tornar_ativo),
        "apenas_precos":     False,
        "max_output_tokens": int(max_out_default),
        "prompt_reforco":    fonte.get("prompt_reforco", "") or "",
        "custos": {
            "in_usd_1M":    0.0,
            "out_usd_1M":   0.0,
            "cache_usd_1M": 0.0,
        },
        "substituiu":        modelo_antigo,
    }
    pool.append(novo)
    save_providers(pool)
    return True, f"Modelo '{novo_modelo_str}' em uso. Antigo '{modelo_antigo}' arquivado na biblioteca de Preços."

# ═══════════════════════════════════════════════════════════════════════════
# CAMPO estrategia_ocr — escolha de esteira (Modo 1 vs Modo 2 Micro-Vision)
# ═══════════════════════════════════════════════════════════════════════════
# Valores válidos:
#   "auto"             → comportamento padrão (Gemini cloud → Modo 1; local → Modo 2)
#                        ESTE É O DEFAULT — não muda nada para quem não escolher.
#   "modo1_6fatias"    → força a esteira CLÁSSICA (6 fatias enviadas inteiras).
#                        Para Gemini → fluxo nativo genai.upload_file (100% calibrado).
#                        Para outros cloud → HTTP direto base64 inline.
#   "modo1_turbo"      → MODO 1 TURBO - EXP · clone idêntico do Modo 1 para
#                        experimentação futura (prompts novos, multi-pass, etc.)
#                        sem tocar no Modo 1 original que está blindado.
#   "modo2_microvision"→ força a esteira Micro-Vision v7 (fatias adaptativas
#                        guiadas pelo molde — substituiu o grid v6).
#                        Funciona para QUALQUER provedor (Gemini, OpenAI, Ollama, etc.).
ESTRATEGIAS_OCR_VALIDAS = ("auto", "modo1_6fatias", "modo1_turbo", "modo2_microvision")


def get_estrategia_ocr(modelo_str, default="auto"):
    """Lê a estratégia OCR do provedor. Default = 'auto' (mantém comportamento clássico)."""
    try:
        provs = load_providers()
        for p in provs:
            if p.get("modelo") == modelo_str:
                valor = (p.get("estrategia_ocr", default) or default).strip().lower()
                if valor not in ESTRATEGIAS_OCR_VALIDAS:
                    return default
                return valor
    except Exception:
        pass
    return default


def set_estrategia_ocr(modelo_str, estrategia):
    """Salva a estratégia OCR do provedor. Aceita apenas valores válidos."""
    try:
        estrategia = (estrategia or "auto").strip().lower()
        if estrategia not in ESTRATEGIAS_OCR_VALIDAS:
            return False
        provs = load_providers()
        achou = False
        for p in provs:
            if p.get("modelo") == modelo_str:
                p["estrategia_ocr"] = estrategia
                achou = True
                break
        if achou:
            save_providers(provs)
            return True
    except Exception:
        pass
    return False
