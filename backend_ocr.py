import os
import time
import json
import mimetypes
import difflib
import shutil
import threading
import streamlit as st

# --- BLINDAGEM DE IMPORT (REGRA DE OURO 3) ---
try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    import fitz  # PyMuPDF
    import cv2
    import numpy as np
    VISAO_ATIVA = True
except ImportError:
    VISAO_ATIVA = False

# pdfplumber é o motor de OCR coordenado usado SOMENTE pela esteira Micro-Vision Crop
# (modelos locais). Para Gemini/cloud não é necessário.
try:
    import pdfplumber
    PDFPLUMBER_ATIVO = True
except ImportError:
    PDFPLUMBER_ATIVO = False

# requests é usado SOMENTE pela esteira Micro-Vision Crop (POST direto ao Ollama).
try:
    import requests as _requests_micro
except ImportError:
    _requests_micro = None

# Carrossel Gemini (RESTAURADO no fluxo nativo)
try:
    from storage_gemini import get_next_valid_key, mark_key_as_standby, load_gemini_pool
except ImportError:
    def get_next_valid_key(): return None
    def mark_key_as_standby(k): pass
    def load_gemini_pool(): return []

# Pool LiteLLM (multi-provider)
try:
    from storage_litellm import get_active_provider, get_custos_provedor, get_max_output_tokens, get_prompt_reforco, get_estrategia_ocr
except ImportError:
    def get_active_provider(): return None
    def get_custos_provedor(m): return {"in_usd_1M": 0.0, "out_usd_1M": 0.0, "cache_usd_1M": 0.0}
    def get_max_output_tokens(m, default=16384): return int(default)
    def get_prompt_reforco(m): return ""
    def get_estrategia_ocr(m, default="auto"): return default

# Backend LiteLLM (apenas para provedores nao-Gemini)
try:
    from backend_litellm import enviar_completion_http, obter_custos
except ImportError:
    def enviar_completion_http(prov, m, msgs, api_key="", base_url="", **kw): return False, {}, "backend_litellm.py ausente"
    def obter_custos(m): return {"in": 0.0, "out": 0.0}

try:
    from funcoes_fla import load_key, registrar_consumo, calcular_custo_brl, buscar_cotacao_dolar_realtime, obter_dolar_persistido
except ImportError:
    def load_key(provider="gemini"): return ""
    def registrar_consumo(p, m, t, c, tempo_execucao=0, **kw): pass
    def calcular_custo_brl(m, i, o): return 0.0
    def buscar_cotacao_dolar_realtime(): return 5.25
    def obter_dolar_persistido(): return 5.25

try:
    from funcoes_lab import load_model_pref
except ImportError:
    def load_model_pref(): return "gemini-2.5-flash"


# ─────────────────────────────────────────────────────────────────────
# HELPERS DE TELEMETRIA — formato "Modelo + Modo" na coluna Processo
# ─────────────────────────────────────────────────────────────────────
def _compactar_modelo(modelo_str: str) -> str:
    """
    Compacta o nome do modelo para caber na coluna Processo do histórico.
    Remove prefixo de provedor (formato 'provedor/modelo') e trunca se passar de 28 chars.
    Ex.: 'gemini/gemini-2.5-flash' -> 'gemini-2.5-flash'
         'openai/gpt-4o-mini-2024-07-18' -> 'gpt-4o-mini-2024-07-18'
         'ollama/llama3.2-vision:11b' -> 'llama3.2-vision:11b'
    """
    if not modelo_str:
        return "modelo-desconhecido"
    nome = str(modelo_str).strip()
    if "/" in nome:
        nome = nome.split("/", 1)[1]
    if len(nome) > 28:
        nome = nome[:25] + "..."
    return nome


def _label_modo(estrategia: str) -> str:
    """
    Mapeia estrategia interna -> rótulo limpo p/ histórico financeiro.
      modo1_6fatias    -> 'Modo1'
      modo1_turbo      -> 'Modo1-Turbo'
      modo2_microvision-> 'Modo2'
      (qualquer outro) -> 'Auto'
    """
    e = (estrategia or "").strip().lower()
    if e == "modo1_6fatias":     return "Modo1"
    if e == "modo1_turbo":       return "Modo1-Turbo"
    if e == "modo2_microvision": return "Modo2"
    return "Auto"


def aguardar_processamento(arquivos_genai):
    if not genai:
        return True
    for arq in arquivos_genai:
        tentativas = 0
        while arq.state.name == "PROCESSING" and tentativas < 15:
            time.sleep(2)
            arq = genai.get_file(arq.name)
            tentativas += 1
    return True


def fatiar_pdf_com_opencv(caminho_pdf, pasta_sessao):
    if not VISAO_ATIVA:
        return False, "Bibliotecas PyMuPDF ou OpenCV nao instaladas."

    caminhos_recortes = []
    os.makedirs(pasta_sessao, exist_ok=True)

    try:
        doc = fitz.open(caminho_pdf)
        for num_pag in range(len(doc)):
            pagina = doc.load_page(num_pag)
            pix = pagina.get_pixmap(dpi=200)

            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR) if pix.n == 4 else cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            altura, largura = img_cv.shape[:2]
            num_fatias = 6

            passo_y = altura // num_fatias
            margem_overlap = int(passo_y * 0.25)

            for i in range(num_fatias):
                y_inicio = max(0, (i * passo_y) - margem_overlap)
                # ── Otimização: overlap inferior só na ÚLTIMA fatia (até altura).
                #    Demais fatias terminam exatamente em (i+1)*passo_y porque a
                #    redundância visual já é garantida pelo overlap SUPERIOR da
                #    próxima fatia (linhas-fronteira aparecem em duas fatias).
                if i == num_fatias - 1:
                    y_fim = altura
                else:
                    y_fim = (i + 1) * passo_y

                recorte = img_cv[y_inicio:y_fim, 0:int(largura * 0.8)]

                nome_recorte = os.path.join(pasta_sessao, f"pag{num_pag}_fatia{i}.jpg")
                cv2.imwrite(nome_recorte, recorte)
                caminhos_recortes.append(nome_recorte)

        doc.close()
        return True, caminhos_recortes
    except Exception as e:
        return False, f"Erro no fatiamento OpenCV: {str(e)}"


def normalizar_referencia_opencv(caminho_original, pasta_temp):
    if not VISAO_ATIVA: return caminho_original

    try:
        nome_arquivo = os.path.basename(caminho_original)
        nome_sem_ext = os.path.splitext(nome_arquivo)[0]
        caminho_normalizado = os.path.join(pasta_temp, f"norm_{nome_sem_ext}.jpg")

        img = cv2.imread(caminho_original)
        img_contrast = cv2.convertScaleAbs(img, alpha=1.5, beta=0)

        cv2.imwrite(caminho_normalizado, img_contrast)
        return caminho_normalizado
    except Exception as e:
        return caminho_original


def extrair_texto_pdf(arquivo_pdf):
    try:
        caminho_temp = f"temp_upload_{int(time.time())}.pdf"
        with open(caminho_temp, "wb") as f:
            f.write(arquivo_pdf.getbuffer())
        return caminho_temp
    except Exception as e:
        return f"ERRO FISICO: {str(e)}"


def _imagem_para_data_url(caminho_imagem):
    try:
        import base64
        with open(caminho_imagem, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


def _carregar_mapeamento_fidedigno():
    return {
        "SEÇÃO 2 - LINGUAGEM E COMPREENSÃO": [
            "Tem dificuldade para entender enunciados longos",
            "Confunde o que a questão está pedindo",
            "Precisa reler várias vezes para compreender",
            "Tem dificuldade com linguagem indireta ou figurada",
            "Entende melhor quando o comando está destacado",
            "Se perde quando há múltiplas instruções na mesma questão",
            "Compreende melhor quando as instruções estão numeradas"
        ],
        "SEÇÃO 3 - ATENÇÃO E FUNÇÃO EXECUTIVA": [
            "Distrai-se facilmente com estímulos ao redor",
            "Começa a prova bem, mas perde foco ao longo do tempo",
            "Responde impulsivamente e erra por desatenção",
            "Tem dificuldade para organizar a resposta",
            "Se perde quando precisa seguir vários passos",
            "Apresenta melhora quando a tarefa é dividida em partes menores"
        ],
        "SEÇÃO 4 - MEMÓRIA E CARGA COGNITIVA": [
            "Demonstra dificuldade para mantener várias informações na mente ao mesmo tempo",
            "Esquece parte das instruções ao longo da execução",
            "Tem desempenho melhor quando pode consultar novamente o enunciado"
        ],
        "SEÇÃO 5 - PRODUÇÃO ESCRITA E REGISTRO": [
            "Escreve lentamente",
            "Demonstra cansaço ao escrever por períodos mais longos",
            "Tem dificuldade na organização espacial da escrita",
            "Perde pontos por não conseguir registrar tudo a tempo",
            "Apresenta melhora quando há espaço delimitado para resposta"
        ],
        "SEÇÃO 6 - ORGANIZAÇÃO VISUAL E ESPACIAL": [
            "Se perde em tabelas ou gráficos densos",
            "Comete erros por desalinhamento (colunas, casas decimais etc.)",
            "Apresenta melhora quando usa quadriculado ou linhas-guia",
            "Demonstra dificuldade em organizar informações no espaço da folha"
        ],
        "SEÇÃO 7 - PROCESSAMENTO EM MATEMÁTICA / DISCIPLINAS DE EXATAS": [
            "Confunde sinais matemáticos (+, -, x, ÷)",
            "Troca a ordem de números em operações",
            "Demonstra dificuldade em organizar contas no papel",
            "Tem dificuldade em interpretar problemas matemáticos escritos",
            "Apresenta melhora quando a operação é visualmente organizada",
            "Comete erros por desorganização espacial, não por desconhecimento do conteúdo"
        ],
        "SEÇÃO 8 - O QUE JÁ FUNCIONOU": [
            "Dividir a prova em blocos menores",
            "Destacar palavras-chave",
            "Instruções em passos numerados",
            "Layout mais limpo",
            "Maior espaçamento entre questões",
            "Tempo adicional (quando previsto)",
            "Ambiente com menos distração",
            "Quadriculado / guia visual",
            "Imagem de suporte",
            "Outro (campo curto)"
        ],
        "SEÇÃO 9 - LIMITES IMPORTANTES": [
            "Simplificar o conteúdo",
            "Dar pistas ou respostas",
            "Alterar o objetivo da questão",
            "Infantilizar a linguagem",
            "Separar enunciado das alternativas"
        ]
    }


ARQUIVOS_CALIBRAGEM = {
    "referencia_branco":       "BASELINE 0: Fundo vazio.",
    "exemplo_marcado_fraco":   "LIMITE MÍNIMO DE 1.",
    "exemplo_vazado":          "LIMITE DE BORDA DE 1.",
    "exemplo_linha_fina":      "LIMITE DE PRESSA.",
    "exemplo_passou_longe":    "O HUMANO PREGUIÇOSO.",
    "exemplo_preguicoso_fraco":"O FANTASMA.",
    "referencia_raspa_fora":   "O TANGENCIAL."
}


# ═══════════════════════════════════════════════════════════════════════════
# MODO 2 v7 — Fatias adaptativas guiadas pelo molde
# ═══════════════════════════════════════════════════════════════════════════
# Substitui o GRID-MINIMAL empilhado (v6 deprecated). Em vez de mandar 46
# micro-recortes empilhados num grid abstrato, agrupa os checkboxes do molde
# em blocos de K consecutivos e envia UMA FATIA HORIZONTAL DA PÁGINA por
# chamada — cada fatia mostra K checkboxes COM A FRASE NATURAL AO LADO, em
# contexto, anotados com [#frase_id] na margem esquerda.
#
# Vantagens:
#   • LLM enxerga ~K checkboxes por vez (default 5), não 46 empilhados
#   • Contexto natural preservado (texto ao lado, espaçamento real da página)
#   • Recorte determinístico (vem do molde, não de detector)
#   • Anti-corte: se borda do envelope passa por cima de checkbox, expande
#   • Custo zero local (Ollama) · 1 chamada por fatia · ~10 chamadas/prova
# ═══════════════════════════════════════════════════════════════════════════
MODO2_K_FATIAS         = 5     # checkboxes por fatia (DEFAULT, usado por Modo 1 Turbo / Gemini)
# K por estratégia — Llama 3.2 Vision 11B sofre de "homogeneização" (decide 1
# valor para a fatia inteira) quando K>=2. Forçando K=1 no caminho local cada
# imagem tem 1 checkbox isolado → 1 decisão atômica do encoder. Mais chamadas
# LLM (~46 vs ~10), mas custo R$0 (local) e acurácia esperada >90%.
MODO2_K_FATIAS_TURBO   = 5     # Gemini Modo 1 Turbo — preservado (100% calibrado)
MODO2_K_FATIAS_LOCAL   = 1     # Llama/Qwen local Modo 2 v7 — força 1 decisão atômica
MODO2_MARGEM_Y_PX      = 30    # padding vertical do envelope (DPI 200)
MODO2_ANTI_CORTE_PX    = 15    # margem extra anti-corte sobre checkbox
MODO2_ALTURA_MAX_FATIA = 900   # altura máxima em pixels antes de forçar K menor
MODO2_USAR_CLAHE       = False # PDFs digitais não precisam — CLAHE confunde encoder visual
MODO2_DEBUG_FATIAS     = True  # salva PNG de cada fatia em temp folder
# ─── Normalização Llama-friendly (encoder CLIP do Llama 3.2 Vision) ───
# Llama 3.2 Vision usa tiles 336×336 com proporção saudável 1:1 a 3:1.
# Imagens muito esticadas (>3:1) ou muito pequenas (<336) confundem o encoder
# e geram resposta `!!!!!` com IN=0. A normalização adiciona padding branco
# (simula papel) e depois faz resize proporcional.
MODO2_FATIA_LADO_MIN       = 336   # input mínimo do CLIP (cada lado >= 336px)
MODO2_FATIA_PROPORCAO_MAX  = 3.0   # razão máxima largura/altura (e altura/largura)
MODO2_FATIA_ALTURA_MAX     = 672   # após normalização, faz resize para no máx 672 altura
MODO2_FATIA_LARGURA_MAX    = 896   # após normalização, faz resize para no máx 896 largura

# ─── TEMPLATES DE LAYOUT (crop horizontal por tipo de formulário) ───
# Cada molde declara um 'template_layout' que controla o quanto da página
# é enviado ao LLM. Reduzir a área visual reduz tokens, custo e — em LLMs
# locais — VRAM/latência. O default 'hibrido_sem_corte' preserva
# 100% do comportamento atual (full-width) para formulários com layout misto.
MODO2_TEMPLATE_MARGEM_ID_PX    = 90   # px à ESQUERDA do checkbox para o [#N] caber (DPI 200)
MODO2_TEMPLATE_MARGEM_MARCA_PX = 60   # px à DIREITA do checkbox para "X" extrapolado (DPI 200)
MODO2_TEMPLATE_DEFAULT         = "multipla_escolha_esquerda"
# CALIBRADO 2026-05-25 (evidência empírica): Prova_Nova (hibrido_sem_corte) vs
# Prova_Nova_EXP (multipla_escolha_esquerda) — mesmo conteúdo, único campo
# diferente — com Gemini + Modo 1 Turbo, hibrido_sem_corte deu desastre (mais
# tokens visuais distratores) e multipla_escolha_esquerda deu 100% + mais
# rápido. Default anterior era hibrido_sem_corte — virou bug latente quando
# molde nasce pela UI sem campo template_layout.

# ─── RENDERIZAÇÃO EM ALTA RESOLUÇÃO (Modo 2 v7) ───
# O JSON dos moldes foi calibrado em DPI 200 (referência), mas renderizamos a
# página em DPI maior antes de cortar as fatias — assim o checkbox chega ao LLM
# em alta nitidez (vs upscale via interpolação, que estica pixels sem detalhe).
# Coords e margens (em DPI 200) são escaladas dinamicamente pelo fator render/molde.
MODO2_MOLDE_DPI   = 200   # DPI de referência (do JSON do molde — NÃO MUDAR)
MODO2_RENDER_DPI  = 200   # DPI da rasterização (REVERTIDO ao original — DPI 400
                          # foi tentado mas degradou Qwen 2.5 VL gerando !!!!!! ).


# ═══════════════════════════════════════════════════════════════════════════
# MOLDE DINÂMICO — substitui o gabarito hardcoded por um JSON treinado
# ═══════════════════════════════════════════════════════════════════════════
def _carregar_mapeamento_do_molde(molde_nome=None):
    """
    Retorna tupla (mapeamento_dict, gabarito_lista, coords_lista_or_None).

    Parâmetros:
      molde_nome: nome do molde salvo em moldes/<nome>.json. Se None ou
                  inválido, cai no fallback hardcoded (_carregar_mapeamento_fidedigno).

    Estrutura de retorno:
      mapeamento_dict:   {secao: [frase, ...]}  — preserva ordem do gabarito
      gabarito_lista:    [{id, frase, secao}, ...] — id = posição no gabarito (1..N)
      coords_lista_or_None: lista de dicts com coords dos quadrados se molde existir
                            [{pag, x, y, w, h, id, frase, frase_id, secao}, ...]
                            ORDENADA por (pag, y, x) = ordem visual = ordem do gabarito.
                            None se molde_nome ausente / inválido.

    BLINDAGEM: nenhum erro deste helper interrompe a análise — sempre retorna algo
    utilizável, com fallback para o gabarito fidedigno antigo.
    """
    if molde_nome:
        try:
            from backend_molde import carregar_molde, normalizar_gabarito_frases
            dados = carregar_molde(molde_nome)
            if dados:
                gab_raw = dados.get("gabarito_frases") or []
                if gab_raw:
                    gab_norm = normalizar_gabarito_frases(gab_raw)
                    # Reconstrói {secao: [frases]} preservando a ordem do gabarito
                    mapeamento = {}
                    for g in gab_norm:
                        sec = (g.get("secao") or "(sem seção)").strip() or "(sem seção)"
                        mapeamento.setdefault(sec, []).append(g["frase"])

                    # Reconstrói coords (lista plana ordenada)
                    coords = []
                    paginas = dados.get("paginas") or {}
                    for pag_str, pag_data in paginas.items():
                        try:
                            pag = int(pag_str)
                        except Exception:
                            continue
                        for q in pag_data.get("quadrados", []):
                            coords.append({
                                "pag":      pag,
                                "x":        int(q.get("x", 0)),
                                "y":        int(q.get("y", 0)),
                                "w":        int(q.get("w", 35)),
                                "h":        int(q.get("h", 30)),
                                "id":       int(q.get("id", 0)),
                                "frase":    q.get("frase", ""),
                                "frase_id": q.get("frase_id", 0),
                                "secao":    q.get("secao", ""),
                            })
                    coords.sort(key=lambda c: (c["pag"], c["y"], c["x"]))

                    try:
                        st.caption(
                            f"📐 Molde **{molde_nome}** carregado · "
                            f"{len(gab_norm)} frases · {len(coords)} coordenadas"
                        )
                    except Exception:
                        pass

                    return mapeamento, gab_norm, (coords or None)
        except Exception as e:
            try:
                st.warning(
                    f"⚠️ Falha ao carregar molde **{molde_nome}**: {e}. "
                    f"Usando gabarito padrão hardcoded."
                )
            except Exception:
                pass

    # ── FALLBACK: gabarito hardcoded antigo (BLINDAGEM) ──
    mapeamento_hc = _carregar_mapeamento_fidedigno()
    gabarito_lista = []
    i = 1
    for sec, frases in mapeamento_hc.items():
        for fr in frases:
            gabarito_lista.append({"id": i, "frase": fr, "secao": sec})
            i += 1
    return mapeamento_hc, gabarito_lista, None


def _carregar_template_cfg_do_molde(molde_nome=None):
    """Lê 'template_layout' e 'config_template' do JSON do molde e retorna
    dict normalizado pronto para _calcular_faixa_horizontal.

    Função SEPARADA do loader principal para não quebrar nenhum dos 3 call
    sites existentes de _carregar_mapeamento_do_molde (todos esperam tupla
    de 3 elementos).

    Fallback BLINDADO: se molde ausente, campos ausentes, ou QUALQUER erro,
    retorna {'layout': 'hibrido_sem_corte'} — exatamente o comportamento
    histórico (full-width preservado).

    Estrutura esperada no JSON do molde:
      {
        ...,
        "template_layout": "multipla_escolha_esquerda",
        "config_template": {
          "margem_id_px": 90,
          "margem_marca_px": 60
        }
      }
    """
    if not molde_nome:
        return {"layout": MODO2_TEMPLATE_DEFAULT}
    try:
        from backend_molde import carregar_molde
        dados = carregar_molde(molde_nome) or {}
        layout = str(dados.get("template_layout") or MODO2_TEMPLATE_DEFAULT).strip().lower()
        cfg_extra = dados.get("config_template") or {}
        cfg = {"layout": layout}
        if isinstance(cfg_extra, dict):
            if "margem_id_px" in cfg_extra:
                try:
                    cfg["margem_id_px"] = int(cfg_extra["margem_id_px"])
                except Exception:
                    pass
            if "margem_marca_px" in cfg_extra:
                try:
                    cfg["margem_marca_px"] = int(cfg_extra["margem_marca_px"])
                except Exception:
                    pass
        return cfg
    except Exception:
        return {"layout": MODO2_TEMPLATE_DEFAULT}


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS DO MODO 2 v7 — fatias adaptativas guiadas pelo molde
# ═══════════════════════════════════════════════════════════════════════════
def _agrupar_coords_em_blocos(coords_pag, k=MODO2_K_FATIAS):
    """Agrupa coords de UMA página em blocos de K consecutivos (ordem visual).
    coords_pag já vem ordenado por (y, x) — manter essa ordem.
    Retorna lista de blocos (cada bloco = lista de até K coords)."""
    if not coords_pag:
        return []
    k = max(1, int(k))
    blocos = []
    for i in range(0, len(coords_pag), k):
        blocos.append(coords_pag[i:i + k])
    return blocos


def _calcular_faixa_horizontal(bloco, pag_w, template_cfg=None):
    """Calcula (x_left, x_right) do crop horizontal conforme o template de
    layout do formulário declarado no JSON do molde.

    POLÍTICA DE TEMPLATES:
      • 'hibrido_sem_corte' (default) → retorna (0, pag_w). BLINDADO — preserva
        100% do comportamento histórico para formulários com checkboxes em
        posições variáveis ao longo da página (layout misto).
      • 'multipla_escolha_esquerda' → crop estreito mantendo apenas:
          [margem_id_px à esquerda do checkbox]   ← caber o [#N] anotado
          [largura do checkbox]
          [margem_marca_px à direita do checkbox] ← folga para "X" extrapolado
        Reduz drasticamente a área visual enviada ao LLM.
      • 'multipla_escolha_direita' → STUB — delega para hibrido_sem_corte
        até que _anotar_quadrados_na_pagina seja adaptado para desenhar o
        [#N] à DIREITA do checkbox (hoje ele desenha sempre à esquerda).

    template_cfg esperado:
      {
        'layout':         'hibrido_sem_corte' | 'multipla_escolha_esquerda' | 'multipla_escolha_direita',
        'margem_id_px':    int (opcional, default MODO2_TEMPLATE_MARGEM_ID_PX),
        'margem_marca_px': int (opcional, default MODO2_TEMPLATE_MARGEM_MARCA_PX),
      }

    Fallback: cfg None / layout inválido / bloco vazio → (0, pag_w) full-width.
    """
    cfg = template_cfg or {}
    layout = str(cfg.get("layout") or MODO2_TEMPLATE_DEFAULT).strip().lower()

    # FULL-WIDTH (blindado) — comportamento histórico preservado
    if layout in ("hibrido_sem_corte", "full", "full_width", ""):
        return (0, int(pag_w))

    if not bloco:
        return (0, int(pag_w))

    x_min = min(q["x"]          for q in bloco)
    x_max = max(q["x"] + q["w"] for q in bloco)

    margem_id    = int(cfg.get("margem_id_px",    MODO2_TEMPLATE_MARGEM_ID_PX))
    margem_marca = int(cfg.get("margem_marca_px", MODO2_TEMPLATE_MARGEM_MARCA_PX))

    if layout == "multipla_escolha_esquerda":
        x_left  = max(0,          x_min - margem_id)
        x_right = min(int(pag_w), x_max + margem_marca)
        # Sanidade: nunca devolve faixa invertida nem mais larga que a página
        if x_right <= x_left:
            return (0, int(pag_w))
        return (int(x_left), int(x_right))

    if layout == "multipla_escolha_direita":
        # STUB — manter sistema 100% até adaptar o anotador [#N]
        return (0, int(pag_w))

    # Fallback final — qualquer layout não reconhecido vira full-width
    return (0, int(pag_w))


def _calcular_envelope_com_anticorte(bloco, todos_quads_pag, pag_h, pag_w,
                                      margem_y=MODO2_MARGEM_Y_PX,
                                      margem_extra=MODO2_ANTI_CORTE_PX,
                                      template_cfg=None):
    """Calcula o envelope (x, y, w, h) da fatia que contém EXATAMENTE os
    checkboxes do bloco. Se um quadrado de OUTRO bloco invadiria a margem,
    CONTRAI a borda para excluí-lo (anti-contaminação vertical).

    Se template_cfg declarar um layout com corte horizontal (ex.:
    'multipla_escolha_esquerda'), também restringe o eixo X para enviar ao
    LLM apenas a faixa onde os checkboxes vivem — economia agressiva de
    tokens visuais. Se template_cfg=None ou layout='hibrido_sem_corte', o
    eixo X permanece full-width (comportamento histórico BLINDADO).

    Bug histórico (já corrigido): a versão antiga EXPANDIA o envelope para
    "não cortar" vizinhos, mas isso fazia checkboxes de outros blocos
    entrarem inteiros na fatia. Como esses vizinhos não têm rótulo [#N], o
    LLM atribuía erroneamente seu X ao último ID listado (falso positivo).

    Esta versão garante: a fatia mostra apenas os quadrados do bloco — nada
    de vizinhos cortados nem inteiros.

    Retorna tupla (x, y, w, h) em coords da página original.
    """
    if not bloco:
        return (0, 0, pag_w, 0)

    y_min_bloco = min(q["y"]            for q in bloco)
    y_max_bloco = max(q["y"] + q["h"]   for q in bloco)

    # Envelope ideal (com margem confortável)
    y_top    = y_min_bloco - margem_y
    y_bottom = y_max_bloco + margem_y

    # IDs deste bloco — para ignorar nos checks
    ids_do_bloco = set()
    for q in bloco:
        fid = q.get("frase_id") or q.get("id") or id(q)
        ids_do_bloco.add(fid)

    # CONTRAI o envelope se vizinhos de OUTROS blocos invadem
    for q in todos_quads_pag:
        fid = q.get("frase_id") or q.get("id") or id(q)
        if fid in ids_do_bloco:
            continue  # pula quadrados do próprio bloco

        q_top = q["y"]
        q_bot = q["y"] + q["h"]

        # Vizinho ABAIXO do bloco invadindo a margem inferior?
        if q_top > y_max_bloco and q_top < y_bottom:
            # Corta o envelope ANTES do vizinho (com folga margem_extra)
            y_bottom = min(y_bottom, q_top - margem_extra)

        # Vizinho ACIMA do bloco invadindo a margem superior?
        if q_bot < y_min_bloco and q_bot > y_top:
            y_top = max(y_top, q_bot + margem_extra)

    # Garante que o bloco ainda cabe (segurança contra over-contração)
    if y_bottom < y_max_bloco:
        y_bottom = y_max_bloco + 1
    if y_top > y_min_bloco:
        y_top = y_min_bloco - 1

    # Clipping nos limites da página
    y_top    = max(0, int(y_top))
    y_bottom = min(int(pag_h), int(y_bottom))

    # ── EIXO X: full-width (default) ou crop conforme template do molde ──
    x_left, x_right = _calcular_faixa_horizontal(bloco, pag_w, template_cfg)

    return (int(x_left), int(y_top),
            int(x_right - x_left), int(y_bottom - y_top))


def _normalizar_fatia_para_llm(img, lado_min=None, proporcao_max=None,
                                 altura_max=None, largura_max=None):
    """Normaliza fatia para faixa que o Llama 3.2 Vision processa bem:
       (1) Padding BRANCO para garantir cada lado >= lado_min (=336, input CLIP).
       (2) Padding BRANCO para garantir proporção <= proporcao_max (=3:1).
       (3) Resize proporcional para no máximo altura_max × largura_max.

    Imagens muito esticadas (e.g. 1654×88 = 18:1) ou com lado < 336px geram
    resposta `!!!!!` com IN=0 — o encoder visual trava antes de processar.
    O padding branco simula "papel em branco" ao redor da fatia anotada,
    preservando a posição do checkbox e do [#N].

    Retorna tupla (img_pronta, dim_original, dim_apos_padding, dim_final).
    """
    if lado_min       is None: lado_min       = MODO2_FATIA_LADO_MIN
    if proporcao_max  is None: proporcao_max  = MODO2_FATIA_PROPORCAO_MAX
    if altura_max     is None: altura_max     = MODO2_FATIA_ALTURA_MAX
    if largura_max    is None: largura_max    = MODO2_FATIA_LARGURA_MAX

    BRANCO = (255, 255, 255)  # BGR

    h, w = img.shape[:2]
    dim_original = (w, h)

    # Step 0 (UPSCALE AGRESSIVO — RESTAURADO 2026-05-23):
    # Patch estava ATIVO durante a rodada que entregou 43/46 acurácia no Qwen 2.5 VL.
    # Removê-lo quebrou o motor (resposta `!!!!!!`). Voltou ao estado funcional.
    # Lógica: se fatia menor que 260px no maior lado, upscale 2x via INTER_CUBIC
    # antes do padding até 336. Faz o checkbox ocupar mais área visual no tile final.
    UPSCALE_TARGET_MIN = 260
    maior_lado = max(h, w)
    if maior_lado < UPSCALE_TARGET_MIN:
        fator = UPSCALE_TARGET_MIN / maior_lado
        novo_w = int(w * fator)
        novo_h = int(h * fator)
        img = cv2.resize(img, (novo_w, novo_h), interpolation=cv2.INTER_CUBIC)
        h, w = img.shape[:2]

    # Step 1: padding vertical para garantir altura >= lado_min
    if h < lado_min:
        pad_total = lado_min - h
        pad_top = pad_total // 2
        pad_bot = pad_total - pad_top
        img = cv2.copyMakeBorder(img, pad_top, pad_bot, 0, 0,
                                 cv2.BORDER_CONSTANT, value=BRANCO)
        h, w = img.shape[:2]

    # Step 2: padding lateral para garantir largura >= lado_min (raro, mas
    # pode acontecer se algum bloco for muito estreito)
    if w < lado_min:
        pad_total = lado_min - w
        pad_left  = pad_total // 2
        pad_right = pad_total - pad_left
        img = cv2.copyMakeBorder(img, 0, 0, pad_left, pad_right,
                                 cv2.BORDER_CONSTANT, value=BRANCO)
        h, w = img.shape[:2]

    # Step 3: padding vertical para que largura/altura <= proporcao_max
    if w / max(1, h) > proporcao_max:
        h_alvo = int(w / proporcao_max)
        pad_total = h_alvo - h
        pad_top = pad_total // 2
        pad_bot = pad_total - pad_top
        img = cv2.copyMakeBorder(img, pad_top, pad_bot, 0, 0,
                                 cv2.BORDER_CONSTANT, value=BRANCO)
        h, w = img.shape[:2]

    # Step 4: padding lateral para que altura/largura <= proporcao_max
    # (caso fatia seja muito alta e estreita — raro)
    if h / max(1, w) > proporcao_max:
        w_alvo = int(h / proporcao_max)
        pad_total = w_alvo - w
        pad_left  = pad_total // 2
        pad_right = pad_total - pad_left
        img = cv2.copyMakeBorder(img, 0, 0, pad_left, pad_right,
                                 cv2.BORDER_CONSTANT, value=BRANCO)
        h, w = img.shape[:2]

    dim_apos_padding = (w, h)

    # Step 5: resize proporcional final (no máximo altura_max × largura_max)
    if h > altura_max or w > largura_max:
        escala = min(altura_max / float(h), largura_max / float(w))
        novo_w = max(1, int(w * escala))
        novo_h = max(1, int(h * escala))
        img = cv2.resize(img, (novo_w, novo_h), interpolation=cv2.INTER_AREA)

    # REVERTIDO (2026-05-23): patch de padding até múltiplo de 28 foi tentado
    # para Qwen 3 VL (que continua quebrado por bug do Ollama) mas estava
    # SABOTANDO o Qwen 2.5 VL — causando travamento com `!!!!!!` a partir da
    # fatia ~37 + falsos positivos massivos. Voltamos ao estado dos 43/46.

    dim_final = (img.shape[1], img.shape[0])
    return img, dim_original, dim_apos_padding, dim_final


def _recortar_e_anotar_fatia(img_pagina, envelope, quads_do_bloco,
                              usar_clahe=None, estrategia_origem=None):
    """Crop da página pelo envelope, opcionalmente aplica CLAHE, recalcula
    coords dos quads no espaço local da fatia e anota [#frase_id] na margem.

    Comportamento por estratégia:
      • modo1_turbo (Gemini cloud) → envia a fatia EM RESOLUÇÃO NATIVA
        (sem padding nem resize). Gemini aguenta imagens grandes e a
        resolução original preserva detalhes do checkbox.
      • modo2_microvision (Llama/Qwen local) → aplica padding (anti
        proporção extrema) + resize (max 672×896). O encoder CLIP do
        Llama 3.2 Vision trava com imagens muito esticadas/grandes.

    Retorna tupla (img_fatia_pronta, ids_globais, frases_dessa_fatia,
                    dim_original, dim_final, dim_padding).
    """
    if usar_clahe is None:
        usar_clahe = MODO2_USAR_CLAHE

    env_x, env_y, env_w, env_h = envelope
    if env_h <= 0 or env_w <= 0:
        return None, [], [], (0, 0), (0, 0), (0, 0)

    # Crop da página
    fatia = img_pagina[env_y:env_y + env_h, env_x:env_x + env_w].copy()
    if fatia.size == 0:
        return None, [], [], (0, 0), (0, 0), (0, 0)

    # CLAHE local OPCIONAL (default False — PDFs digitais não precisam)
    if usar_clahe:
        fatia = _aplicar_clahe_preprocessing(fatia, clip_limit=2.5, tile_size=8)

    # Recalcula coords no espaço da fatia
    bboxes_locais = []
    ids_globais   = []
    frases_dessa_fatia = []
    for q in quads_do_bloco:
        x_local = q["x"] - env_x
        y_local = q["y"] - env_y
        bboxes_locais.append((x_local, y_local, q["w"], q["h"]))
        ident = q.get("frase_id") or q.get("id") or 0
        ids_globais.append(int(ident))
        frases_dessa_fatia.append(q.get("frase", "") or "")

    # Anota [#N] na margem esquerda usando função já existente
    fatia_anotada = _anotar_quadrados_na_pagina(fatia, bboxes_locais, ids_globais)

    # ── DECISÃO POR ESTRATÉGIA ──
    if estrategia_origem == "modo1_turbo":
        # GEMINI CLOUD — envia em resolução nativa (preserva detalhe dos checkboxes)
        h, w = fatia_anotada.shape[:2]
        dim = (w, h)
        return fatia_anotada, ids_globais, frases_dessa_fatia, dim, dim, dim
    else:
        # LLM LOCAL (Modo 2 v7) — padding + resize para encoder CLIP frágil
        fatia_pronta, dim_orig, dim_padding, dim_fin = _normalizar_fatia_para_llm(fatia_anotada)
        return fatia_pronta, ids_globais, frases_dessa_fatia, dim_orig, dim_fin, dim_padding


def _classificar_fatia_via_llm(provedor, modelo_str, api_key, base_url,
                                img_fatia_bgr, ids_globais, frases_dessa_fatia,
                                timeout=90, estrategia_origem=None):
    """UMA chamada LLM para classificar K checkboxes de uma fatia.

    Prompt curto (K checkboxes, não gabarito completo). Espera output CSV no
    formato 'ID:M,ID:V,...'. Parser tolerante.

    Retorna tupla (sucesso, dict_id_para_bool, resposta_raw, tokens_in, tokens_out).
      dict_id_para_bool = {frase_id: True/False, ...}
    """
    import base64 as _b64
    import re as _re

    if img_fatia_bgr is None or img_fatia_bgr.size == 0:
        return False, {}, "Fatia vazia", 0, 0

    ok_enc, buf = cv2.imencode(".png", img_fatia_bgr)
    if not ok_enc:
        return False, {}, "Falha ao codificar PNG", 0, 0
    img_b64 = _b64.b64encode(buf.tobytes()).decode("utf-8")

    n = len(ids_globais)
    linhas_gabarito = []
    for ident, frase in zip(ids_globais, frases_dessa_fatia):
        linhas_gabarito.append(f"  [#{ident}] {frase}")
    gabarito_str = "\n".join(linhas_gabarito)

    ids_str = ",".join(f"#{i}" for i in ids_globais)

    # ── PROMPT-PAI (diretiva suprema) ──
    # Se o provedor tem prompt_reforco cadastrado, injeta como diretiva
    # com precedência absoluta sobre o prompt da tarefa específica.
    try:
        prompt_pai = get_prompt_reforco(modelo_str, estrategia=estrategia_origem) or ""
    except Exception:
        prompt_pai = ""

    bloco_pai = ""
    if prompt_pai:
        bloco_pai = (
            "⛔ DIRETIVA SUPREMA — PRECEDÊNCIA ABSOLUTA SOBRE TUDO QUE VEM A SEGUIR ⛔\n"
            f"{prompt_pai}\n"
            "⛔ FIM DA DIRETIVA SUPREMA — agora siga rigorosamente as instruções "
            "abaixo, sempre respeitando a diretiva acima quando houver conflito ⛔\n"
            "\n"
        )

    prompt_texto = bloco_pai + (
        f"Você está vendo uma FATIA de prova com {n} checkbox(es) numerados {ids_str}.\n"
        "Cada quadrado tem o número entre colchetes [#N] em AZUL-MARINHO na margem esquerda — "
        "esse número é só REFERÊNCIA visual, não influencia se está marcado.\n"
        "\n"
        "🎯 SUA TAREFA: para CADA quadrado desta fatia, decida se está MARCADO ou VAZIO.\n"
        "\n"
        "REGRAS DE CLASSIFICAÇÃO:\n"
        " • Se houver DIRETIVA SUPREMA acima → siga-a integralmente (Centro Branco, Anti-Ruído, Assimetria de Penalidade).\n"
        " • MARCADO = miolo branco do quadrado RASGADO por traço intencional (X, diagonal, riscado, preenchimento).\n"
        " • VAZIO   = miolo branco limpo, ou apenas com sombra/bleed-through/borda impressa.\n"
        "\n"
        f"📋 GABARITO DESTA FATIA ({n} itens):\n"
        f"{gabarito_str}\n"
        "\n"
        "📤 FORMATO OBRIGATÓRIO DA RESPOSTA — apenas pares ID:STATUS separados por vírgula.\n"
        "Use STATUS = M (marcado) ou V (vazio). Sem texto explicativo, sem markdown, sem JSON.\n"
        "Se a diretiva suprema usar [X]/[ ] ou outro vocabulário, traduza para este formato:\n"
        "   'Traço detectado' / [X] / MARCADO  ⇒ escreva M\n"
        "   'Totalmente limpo' / [ ] / VAZIO   ⇒ escreva V\n"
        f"Exemplo válido para esta fatia: {','.join(f'{i}:V' for i in ids_globais)}\n"
        "\n"
        "Responda agora (apenas o CSV):"
    )

    prov_lower   = (provedor or "").lower()
    modelo_lower = (modelo_str or "").lower()
    base_lower   = (base_url   or "").lower()
    eh_gemini_p  = ("gemini" in prov_lower) or modelo_lower.startswith("gemini/")

    # Detecta endpoints CLOUD OpenAI-compatible (OpenRouter, Together, Fireworks etc.)
    # que NÃO devem ir pro branch Ollama mesmo quando o provedor é "custom/local".
    # OpenRouter usa /chat/completions com payload OpenAI — incompatível com Ollama.
    _CLOUD_OPENAI_COMPAT = (
        "openrouter.ai", "together.xyz", "together.ai",
        "fireworks.ai", "deepinfra.com", "perplexity.ai",
        "anyscale.com", "groq.com",  # groq quando vier via custom/local
    )
    eh_cloud_openai_compat = any(d in base_lower for d in _CLOUD_OPENAI_COMPAT)

    eh_local_p   = (
        "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower
        or modelo_lower.startswith("ollama/")
    ) and not eh_cloud_openai_compat   # ← exclui clouds OpenAI-compatible

    resposta_raw = ""
    tok_in  = 0
    tok_out = 0

    # max_tokens por estratégia:
    # • Modo 1 Turbo (Gemini cloud): 2048 — modelo gasta tokens em "thinking" interno.
    # • Modo 2 v7 (LLM local): 1024 — Qwen 3 VL e outros locais com raciocínio
    #   embutido precisam de espaço antes de chegar na resposta. Antes era 256
    #   (suficiente pro Qwen 2.5 VL que responde direto), mas Qwen 3 VL trava
    #   com resposta vazia se estourar o budget durante o thinking interno.
    _eh_turbo = (estrategia_origem == "modo1_turbo")
    # 2048 para Turbo (Gemini cloud), 256 para Modo 2 v7 (LLM local).
    # 256 é o valor ORIGINAL que entregou 43/46 com Qwen 2.5 VL 7B.
    # Subir para 1024+ não trouxe ganho mensurável e arrisca regressão.
    _max_tokens_alvo = 2048 if _eh_turbo else 256

    # ── BRANCH GEMINI nativo ──
    if eh_gemini_p:
        if not genai:
            return False, {}, "google-generativeai ausente", 0, 0
        modelo_config = modelo_str[len("gemini/"):] if modelo_str.startswith("gemini/") else modelo_str
        try:
            chave = api_key or (load_gemini_pool() or [""])[0]
            if not chave:
                return False, {}, "Sem chave Gemini", 0, 0
            genai.configure(api_key=chave)
            # Modo 1 Turbo (Gemini cloud): max_tokens 2048 + thinking_off
            # Outros (Modo 2 v7 com Gemini): 256 (não tem thinking estourando)
            if _eh_turbo:
                try:
                    cfg = genai.types.GenerationConfig(
                        temperature=0.0, top_p=1.0, top_k=1,
                        max_output_tokens=_max_tokens_alvo,
                        thinking_config={"thinking_budget": 0},
                    )
                except Exception:
                    cfg = genai.types.GenerationConfig(
                        temperature=0.0, top_p=1.0, top_k=1,
                        max_output_tokens=_max_tokens_alvo,
                    )
            else:
                cfg = genai.types.GenerationConfig(
                    temperature=0.0, top_p=1.0, top_k=1,
                    max_output_tokens=_max_tokens_alvo,
                )
            model = genai.GenerativeModel(model_name=modelo_config, generation_config=cfg)
            resp = model.generate_content([prompt_texto, {"mime_type": "image/png", "data": _b64.b64decode(img_b64)}])
            resposta_raw = (resp.text or "").strip()
            try:
                u = resp.usage_metadata
                tok_in  = int(getattr(u, "prompt_token_count", 0) or 0)
                tok_out = int(getattr(u, "candidates_token_count", 0) or 0)
            except Exception:
                pass
        except Exception as e:
            return False, {}, f"Gemini erro: {str(e)[:200]}", 0, 0

    # ── BRANCH LOCAL (Ollama / vLLM) ──
    elif eh_local_p:
        if not _requests_micro:
            return False, {}, "Biblioteca 'requests' ausente", 0, 0
        base = (base_url or "http://localhost:11434").rstrip("/")
        if base.endswith("/v1"):   base = base[:-3]
        if base.endswith("/api"):  base = base[:-4]
        url = f"{base}/api/generate"
        modelo_ollama = modelo_str[len("ollama/"):] if modelo_lower.startswith("ollama/") else modelo_str
        # num_ctx CRÍTICO para Llama Vision:
        # Default do Ollama = 2048. Prompt-PAI (~350) + tarefa (~250) + gabarito (~150)
        # + 1 tile de imagem CLIP (1601 tokens) = ~2351 → estoura 2048 → encoder trava
        # com resposta `!!!!!` e IN=0. 8192 dá margem confortável para 2 tiles + prompts
        # generosos. Não tem custo extra (LLM local).
        payload = {
            "model":   modelo_ollama,
            "prompt":  prompt_texto,
            "images":  [img_b64],
            "stream":  False,
            "options": {
                "temperature": 0.0,
                "top_p":       1.0,
                "num_predict": _max_tokens_alvo,
                "num_ctx":     8192,
            },
        }
        try:
            import time as _time_dbg
            _t0_py = _time_dbg.time()
            r = _requests_micro.post(url, json=payload, timeout=timeout)
            _tempo_py = _time_dbg.time() - _t0_py
            if r.status_code != 200:
                return False, {}, f"HTTP {r.status_code}: {r.text[:200]}", 0, 0
            data = r.json()
            resposta_raw = (data.get("response", "") or "").strip()
            tok_in  = int(data.get("prompt_eval_count", 0) or 0)
            tok_out = int(data.get("eval_count", 0) or 0)
            # DEBUG EXTRA: se OUT=0, mostra JSON cru completo pra diagnóstico
            try:
                if tok_out == 0 or not resposta_raw:
                    import json as _json_dbg
                    _raw_json = _json_dbg.dumps(data, ensure_ascii=False)[:1500]
                    st.warning(
                        f"🔬 **RAW JSON do Ollama (OUT=0 detectado)** · "
                        f"tempo_py={_tempo_py:.2f}s · "
                        f"HTTP={r.status_code} · "
                        f"chars={len(_raw_json)}\n\n"
                        f"```\n{_raw_json}\n```"
                    )
            except Exception:
                pass
            # ─── LOG DE DIAGNÓSTICO POR FATIA (Qwen 3 VL thinking debug) ───
            # Mostra em tempo real: budget, motivo da parada, tokens OUT,
            # quantos chars de thinking foram gerados, e tempo total.
            # Crítico para diagnosticar quando done_reason=length (estourou).
            try:
                _done_reason  = data.get("done_reason", "?")
                _thinking_str = data.get("thinking", "") or ""
                _total_ns     = int(data.get("total_duration", 0) or 0)
                _total_s      = _total_ns / 1_000_000_000.0 if _total_ns else 0.0
                _emoji_status = "✅" if _done_reason == "stop" and resposta_raw else "⚠️"
                st.caption(
                    f"{_emoji_status} LLM debug · "
                    f"num_predict={_max_tokens_alvo} · "
                    f"done_reason=`{_done_reason}` · "
                    f"OUT={tok_out} · "
                    f"thinking={len(_thinking_str)} chars · "
                    f"resp={len(resposta_raw)} chars · "
                    f"{_total_s:.1f}s"
                )
            except Exception:
                pass
        except Exception as e:
            return False, {}, f"Local erro: {str(e)[:200]}", 0, 0

    # ── BRANCH HTTP universal (outros providers — OpenRouter, OpenAI, Anthropic etc.) ──
    else:
        try:
            from backend_litellm import enviar_completion_http
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_texto},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ],
            }]
            # CORREÇÃO CRÍTICA (2026-05-23):
            # Assinatura real: enviar_completion_http(provedor, modelo_str, messages,
            #                                          api_key, base_url, temperature, max_tokens, timeout)
            # Retorno real: (ok: bool, dados: dict, mensagem: str)
            #   dados = {"texto", "tokens_in", "tokens_out", "tokens_cache", ...}
            # Bug anterior: passava (modelo_str, api_key, base_url, messages) — argumentos
            # trocados causavam "unhashable type: 'slice'" e IN=0/OUT=0 com 100% falhas.
            ok_h, dados_h, msg_h = enviar_completion_http(
                provedor, modelo_str, messages, api_key, base_url,
                temperature=0.0, max_tokens=_max_tokens_alvo, timeout=timeout,
            )
            if not ok_h:
                return False, {}, f"HTTP universal erro: {str(msg_h)[:200]}", 0, 0
            resposta_raw = (dados_h or {}).get("texto", "") or ""
            try:
                tok_in  = int((dados_h or {}).get("tokens_in",  0) or 0)
                tok_out = int((dados_h or {}).get("tokens_out", 0) or 0)
            except Exception:
                pass
        except Exception as e:
            return False, {}, f"HTTP erro: {str(e)[:200]}", 0, 0

    # ── PARSE TOLERANTE — extrai pares ID:M ou ID:V de qualquer string ──
    resultado_dict = {}
    pares = _re.findall(r"\b(\d+)\s*:\s*([MVmv])\b", resposta_raw)
    for ident_str, status in pares:
        try:
            ident = int(ident_str)
            if ident in ids_globais:
                resultado_dict[ident] = (status.upper() == "M")
        except Exception:
            continue

    # Fallback: se vier sequência de letras pura "MVMVM" do tamanho exato
    if not resultado_dict:
        letras = _re.findall(r"[MVmv]", resposta_raw)
        if len(letras) == n:
            for ident, letra in zip(ids_globais, letras):
                resultado_dict[ident] = (letra.upper() == "M")

    sucesso = (len(resultado_dict) > 0)
    return sucesso, resultado_dict, resposta_raw, tok_in, tok_out


def _parse_transcricao(texto_transcrito, estado_final_frases):
    """Parsing [X]/[ ] com difflib >= 0.80 — IDENTICO ao original."""
    linhas = texto_transcrito.split('\n')
    for linha in linhas:
        linha_limpa = linha.strip()
        if not linha_limpa: continue

        marcado = False
        frase_lida = ""

        linha_upper = linha_limpa.upper()

        if "[X]" in linha_upper or "(X)" in linha_upper:
            marcado = True
            frase_lida = linha_limpa.replace("[X]", "").replace("[x]", "").replace("(X)", "").replace("(x)", "").replace("-", "").replace("*", "").strip()
        elif "[ ]" in linha_upper or "( )" in linha_upper:
            marcado = False
            frase_lida = linha_limpa.replace("[ ]", "").replace("( )", "").replace("-", "").replace("*", "").strip()
        else:
            continue

        for f_oficial in estado_final_frases.keys():
            similaridade = difflib.SequenceMatcher(None, f_oficial.lower(), frase_lida.lower()).ratio()
            if similaridade >= 0.80:
                if marcado: estado_final_frases[f_oficial] = True
                break


def analisar_com_treinamento(caminho_pdf, molde_nome=None):
    """
    Entry point do motor de OCR.

    Parâmetros:
      caminho_pdf: caminho do PDF do aluno
      molde_nome:  nome do molde salvo (de moldes/<nome>.json). Se None, usa
                   o gabarito hardcoded original (BLINDAGEM).

    O molde_nome é propagado para todos os 3 modos (Gemini nativo, HTTP direto,
    Micro-Vision crop). Quando presente, substitui o gabarito hardcoded e — no
    Modo 2 — também substitui o template matching pelas coordenadas treinadas.
    """
    tempo_inicio = time.time()

    provedor_ativo = get_active_provider()
    if not provedor_ativo:
        return {"erro": "Nenhum provedor cadastrado/ativo. Va em Configuracoes -> Motores IA (LiteLLM)."}

    modelo_str = provedor_ativo.get("modelo",   "") or load_model_pref()
    api_key    = provedor_ativo.get("api_key",  "")
    base_url   = provedor_ativo.get("base_url", "")
    provedor   = (provedor_ativo.get("provedor", "") or "").lower()

    max_out_cfg = get_max_output_tokens(modelo_str, default=16384)

    # ─── DETECTORES DE PROVEDOR ───
    eh_gemini = "gemini" in provedor
    eh_local  = (
        "custom" in provedor or "local" in provedor or "ollama" in provedor
        or (modelo_str or "").lower().startswith("ollama/")
    )

    # ─── ESCOLHA DE ESTRATÉGIA OCR (campo persistido por provedor) ───
    # Default = "auto": comportamento clássico (Gemini→Modo 1; local→Modo 2).
    # Override possível: "modo1_6fatias" ou "modo2_microvision".
    # ★ BLINDAGEM: se estrategia inválida ou ausente → cai em "auto", sem risco.
    try:
        estrategia = get_estrategia_ocr(modelo_str, default="auto")
    except Exception:
        estrategia = "auto"
    estrategia = (estrategia or "auto").strip().lower()
    if estrategia not in ("auto", "modo1_6fatias", "modo1_turbo", "modo2_microvision"):
        estrategia = "auto"

    try:
        st.caption(f"🛤️ Estratégia OCR ativa: **{estrategia}**")
    except Exception:
        pass

    # ─── ROTEAMENTO ────────────────────────────────────────────────────────
    # 1) Force MODO 1 (6 fatias clássico) — BLINDADO, não alterar.
    if estrategia == "modo1_6fatias":
        if eh_gemini:
            return _analisar_gemini_nativo(caminho_pdf, provedor_ativo, modelo_str, max_out_cfg, tempo_inicio, molde_nome=molde_nome)
        else:
            return _analisar_http_direto(caminho_pdf, provedor_ativo, modelo_str, api_key, base_url, max_out_cfg, tempo_inicio, molde_nome=molde_nome)

    # 1b) MODO 1 TURBO — EXP · esteira v7 (fatias adaptativas) dedicada a
    #     Gemini cloud. Bancada de experimentação separada do Modo 2 v7,
    #     que fica reservado para LLMs locais (Llama, Qwen local, etc.).
    if estrategia == "modo1_turbo":
        return _analisar_micro_vision_crop(
            caminho_pdf, provedor_ativo, modelo_str, api_key, base_url, tempo_inicio,
            molde_nome=molde_nome, estrategia_origem="modo1_turbo",
        )

    # 2) MODO 2 v7 — esteira de fatias adaptativas RESERVADA para LLMs locais
    #    (Llama, Qwen local, etc.). Mesma esteira do Modo 1 Turbo, mas com
    #    prompt-PAI específico (mais curto, sem safety triggers).
    if estrategia == "modo2_microvision":
        return _analisar_micro_vision_crop(
            caminho_pdf, provedor_ativo, modelo_str, api_key, base_url, tempo_inicio,
            molde_nome=molde_nome, estrategia_origem="modo2_microvision",
        )

    # 3) AUTO (default) — preserva 100% o comportamento clássico:
    #    Gemini cloud → Modo 1 nativo (já calibrado em 100% de acerto)
    #    Local        → Modo 2 Micro-Vision (a única alternativa viável p/ VRAM limitada)
    #    Outros cloud → Modo 1 HTTP direto
    if eh_gemini:
        return _analisar_gemini_nativo(caminho_pdf, provedor_ativo, modelo_str, max_out_cfg, tempo_inicio, molde_nome=molde_nome)
    elif eh_local:
        return _analisar_micro_vision_crop(caminho_pdf, provedor_ativo, modelo_str, api_key, base_url, tempo_inicio, molde_nome=molde_nome)
    else:
        return _analisar_http_direto(caminho_pdf, provedor_ativo, modelo_str, api_key, base_url, max_out_cfg, tempo_inicio, molde_nome=molde_nome)


def _analisar_gemini_nativo(caminho_pdf, provedor_ativo, modelo_str, max_out_cfg, tempo_inicio, molde_nome=None):
    if not genai:
        return {"erro": "Biblioteca google-generativeai ausente. Rode: pip install google-generativeai"}

    modelo_config = modelo_str[len("gemini/"):] if modelo_str.startswith("gemini/") else modelo_str

    pool_chaves = load_gemini_pool()
    chave_provedor = provedor_ativo.get("api_key", "")
    max_tentativas = len(pool_chaves) if pool_chaves else 1

    # GABARITO DINÂMICO via molde (fallback = hardcoded antigo)
    mapeamento_fidedigno, _gab_lista, _coords = _carregar_mapeamento_do_molde(molde_nome)
    lista_oficial_plana = [frase for sublist in mapeamento_fidedigno.values() for frase in sublist]
    qtd_frases_gabarito = len(lista_oficial_plana)

    id_sessao = int(time.time())
    pasta_sessao = f"temp_fatias_{id_sessao}"

    st.write("⚙️ Fatiando PDF para alta resolução...")
    sucesso_fatias, recortes = fatiar_pdf_com_opencv(caminho_pdf, pasta_sessao)
    if not sucesso_fatias:
        return {"erro": recortes}

    for tentativa in range(max_tentativas):
        api_key = get_next_valid_key() if pool_chaves else chave_provedor
        if not api_key:
            return {"erro": "🚨 Todas as chaves Gemini estao na geladeira (Cooldown 60min)."}

        try:
            genai.configure(api_key=api_key)

            config_forense = genai.types.GenerationConfig(
                temperature=0.0,
                top_p=1.0,
                top_k=1,
                max_output_tokens=int(max_out_cfg),
            )

            model = genai.GenerativeModel(
                model_name=modelo_config,
                generation_config=config_forense
            )

            if tentativa > 0:
                st.warning(f"🔄 Tentativa {tentativa+1}: Chave anterior falhou. Puxando reserva final **...{api_key[-4:]}**")
            else:
                st.caption(f"🔑 Autenticado na Nuvem com a chave principal final **...{api_key[-4:]}**")
                st.caption(f"⚙️ max_output_tokens = {max_out_cfg}")

            arquivos_ia_alvo = []
            arquivos_ia_treino = {}
            arquivos_temp_norm = []

            for idx, img_path in enumerate(recortes):
                mime_t, _ = mimetypes.guess_type(img_path)
                if not mime_t: mime_t = "image/jpeg"
                arq_fatia = genai.upload_file(path=img_path, display_name=f"ALVO_FATIA_{idx}", mime_type=mime_t)
                arquivos_ia_alvo.append(arq_fatia)

            pasta_treino = os.path.join("banco_contexto", "treino_visao")
            pasta_temp_norm = pasta_sessao

            if os.path.exists(pasta_treino):
                for arq_treino in os.listdir(pasta_treino):
                    nome_sem_ext = os.path.splitext(arq_treino)[0]
                    if nome_sem_ext in ARQUIVOS_CALIBRAGEM:
                        caminho_original = os.path.join(pasta_treino, arq_treino)

                        caminho_norm = normalizar_referencia_opencv(caminho_original, pasta_temp_norm)
                        if caminho_norm != caminho_original:
                            arquivos_temp_norm.append(caminho_norm)

                        mime_t_treino, _ = mimetypes.guess_type(caminho_norm)
                        if not mime_t_treino: mime_t_treino = "image/jpeg"

                        uploaded_treino = genai.upload_file(path=caminho_norm, display_name=f"TREINO_{nome_sem_ext}", mime_type=mime_t_treino)
                        arquivos_ia_treino[nome_sem_ext] = uploaded_treino

            st.write("☁️ Subindo lote normalizado...")
            aguardar_processamento(arquivos_ia_alvo + list(arquivos_ia_treino.values()))

            telemetria_total = {"in": 0, "out": 0, "cache": 0, "brl": 0.0}

            st.markdown("---")
            st.write("### 👁️ Leitura Dinâmica")

            estado_final_frases = {f: False for f in lista_oficial_plana}

            # Le o prompt-PAI configurado para este provedor (vazio = sem reforco)
            prompt_pai_gemini = get_prompt_reforco(modelo_str, estrategia="modo1_6fatias")

            conteudo_prompt = []

            # Se ha prompt-PAI customizado, injeta como DIRETIVA SUPREMA antes de tudo
            if prompt_pai_gemini:
                conteudo_prompt.extend([
                    "⛔ DIRETIVA SUPREMA — PRECEDÊNCIA ABSOLUTA SOBRE TUDO QUE VEM A SEGUIR ⛔",
                    prompt_pai_gemini,
                    "⛔ FIM DA DIRETIVA SUPREMA — agora siga rigorosamente as instruções abaixo, sempre respeitando a diretiva acima quando houver conflito ⛔",
                    "",
                ])
                st.caption(f"🎯 Prompt-PAI ATIVO: {len(prompt_pai_gemini)} caracteres injetados como diretiva suprema")

            conteudo_prompt.extend([
                "Você é um Transcritor Forense.",
                "Sua tarefa é ler um formulário em fatias e dizer se o estudante sinalizou as frases."
            ])

            if arquivos_ia_treino:
                conteudo_prompt.append("\n--- CALIBRAGEM ---")
                for key in ARQUIVOS_CALIBRAGEM.keys():
                    if key in arquivos_ia_treino:
                        conteudo_prompt.append(ARQUIVOS_CALIBRAGEM[key])
                        conteudo_prompt.append(arquivos_ia_treino[key])

            conteudo_prompt.append("\n--- GABARITO OFICIAL DE FRASES ---")
            conteudo_prompt.append("⚠️ OBRIGATÓRIO: Use EXATAMENTE as frases desta lista na sua resposta. Não mude NENHUMA palavra.")
            for f_oficial in lista_oficial_plana:
                conteudo_prompt.append(f"- {f_oficial}")

            conteudo_prompt.extend([
                "\n--- TAREFA REAL ---",
                "Agora avalie as fatias do documento real anexadas abaixo.",
                "",
                "🚨 ATENÇÃO MÁXIMA: ARMADILHA VISUAL DETECTADA 🚨",
                "Temos um problema severo de 'falso vazio'. Traços feitos a lápis que são muito fracos, curvos, ou que apenas raspam a quina inferior do quadrado estão sendo ignorados pela sua visão porque se camuflam no texto que vaza do verso da folha (bleed-through).",
                "",
                "Para combater isso, você DEVE forçar o seu raciocínio visual passo a passo ANTES de dar a resposta.",
                "",
                "⚠️ PASSO 1: LOG DE INSPEÇÃO VISUAL (MODO ROBÓTICO) ⚠️",
                "Você está PROIBIDO de justificar ou escrever frases longas.",
                "Antes do gabarito, crie um log analisando o quadrado de cada frase.",
                "Para cada item, você deve escrever APENAS UMA destas 3 frases padrões (máximo 3 palavras):",
                "1. 'Totalmente limpo.'",
                "2. 'Apenas mancha.' (Use se for sujeira do verso da folha)",
                "3. 'Traço detectado.' (Use se houver qualquer linha de lápis/caneta)",
                "Exemplo Exato do Log:",
                "- Frase X: Totalmente limpo.",
                "- Frase Y: Apenas mancha.",
                "- Frase Z: Traço detectado.",
                "",
                "⚠️ PASSO 2: A REGRA IMPLACÁVEL DO [X] ⚠️",
                "Se no Passo 1 você classificou como 'Traço detectado.', você É OBRIGADO a marcar [X] no Passo 3. Se classificou como 'Totalmente limpo.' ou 'Apenas mancha.', marque [ ].",
                "⚠️ PASSO 3: GABARITO FINAL ⚠️",
                "Após o seu raciocínio, gere a lista final abaixo:",
                "### RESULTADOS",
                f"A lista DEVE conter EXATAMENTE {qtd_frases_gabarito} avaliações.",
                "[X] Frase do Gabarito",
                "[ ] Frase do Gabarito",
                "",
                "Transcreva TODAS as frases do Gabarito Oficial fornecido anteriormente. Não omita nenhuma."
            ])

            conteudo_prompt.extend(arquivos_ia_alvo)

            try:
                log_container = st.container(border=True)
                log_container.caption("📝 Transcrição em andamento...")
                texto_transcrito = ""

                response = model.generate_content(conteudo_prompt, stream=True)
                log_placeholder = log_container.empty()

                for chunk in response:
                    texto_transcrito += chunk.text
                    log_placeholder.code(texto_transcrito, language="markdown")

                try:
                    t_in = response.usage_metadata.prompt_token_count
                    t_out = response.usage_metadata.candidates_token_count
                    telemetria_total["in"] = t_in
                    telemetria_total["out"] = t_out
                    try:
                        telemetria_total["cache"] = int(getattr(response.usage_metadata, "cached_content_token_count", 0) or 0)
                    except Exception:
                        pass
                except:
                    pass

                _parse_transcricao(texto_transcrito, estado_final_frases)

            except Exception as e:
                st.error(f"Erro na extração ancorada: {e}")

            try:
                custos = get_custos_provedor(modelo_str)
                dolar = obter_dolar_persistido() or 5.25
                tokens_in_full = max(0, telemetria_total["in"] - telemetria_total["cache"])
                tokens_cache   = telemetria_total["cache"]
                custo_usd = (
                    (tokens_in_full          / 1_000_000) * custos.get("in_usd_1M",    0.0) +
                    (telemetria_total["out"] / 1_000_000) * custos.get("out_usd_1M",   0.0) +
                    (tokens_cache            / 1_000_000) * custos.get("cache_usd_1M", 0.0)
                )
                telemetria_total["brl"] = custo_usd * dolar
            except Exception:
                telemetria_total["brl"] = 0.0

            st.write("↳ ✅ Leitura concluída e interpretada!")

            resultado_final = {cat: [] for cat in mapeamento_fidedigno.keys()}
            for categoria, perguntas in mapeamento_fidedigno.items():
                for frase in perguntas:
                    marcado_final = estado_final_frases.get(frase, False)
                    resultado_final[categoria].append({
                        "pergunta": frase,
                        "marcado":  marcado_final,
                        "escala":   4 if marcado_final else 0
                    })

            def faxina_com_status_sidebar(arquivos_cloud, pasta_local, pdf_local):
                for arq in arquivos_cloud:
                    try: genai.delete_file(arq.name)
                    except: pass
                try:
                    if os.path.exists(pasta_local): shutil.rmtree(pasta_local)
                except: pass
                try:
                    if os.path.exists(pdf_local): os.remove(pdf_local)
                except: pass

            lixo_nuvem = arquivos_ia_alvo + list(arquivos_ia_treino.values())
            qtd_nuvem = len(lixo_nuvem)
            qtd_local = len(recortes) + len(arquivos_temp_norm) + 1

            with st.sidebar:
                st.markdown("---")
                st.subheader("🧹 Faxina de Cache")
                st.info(f"Limpando sessão: **{id_sessao}**")
                st.warning("Faxina iniciada...")
                st.caption(f"☁️ Nuvem: **{qtd_nuvem}** arquivos sendo apagados.")
                st.caption(f"💻 Local: **{qtd_local}** arquivos sendo removidos.")

            thread_limpeza = threading.Thread(
                target=faxina_com_status_sidebar,
                args=(lixo_nuvem, pasta_sessao, caminho_pdf)
            )
            thread_limpeza.daemon = True
            thread_limpeza.start()

            tempo_gasto = round(time.time() - tempo_inicio, 2)
            st.success(f"✅ Leitura concluída em {tempo_gasto}s!")

            try:
                registrar_consumo(
                    f"{_compactar_modelo(modelo_str)} + Modo1",
                    modelo_str,
                    telemetria_total["in"] + telemetria_total["out"],
                    telemetria_total["brl"],
                    tempo_execucao=tempo_gasto,
                    provedor="gemini",
                    tokens_in=telemetria_total["in"],
                    tokens_out=telemetria_total["out"],
                    tokens_cache=telemetria_total["cache"],
                )
            except Exception:
                pass

            return {
                "sucesso": True,
                "dados":   resultado_final,
                "telemetria": {
                    "modelo":         modelo_str,
                    "provedor":       "gemini",
                    "in":             telemetria_total["in"],
                    "out":            telemetria_total["out"],
                    "cache":          telemetria_total["cache"],
                    "brl":            telemetria_total["brl"],
                    "tempo_segundos": tempo_gasto
                }
            }

        except Exception as e:
            erro_str = str(e).lower()
            erros_google = ["503", "429", "500", "quota", "exhausted", "403", "400", "invalid", "service unavailable", "internal server error"]
            if any(erro in erro_str for erro in erros_google):
                if pool_chaves:
                    mark_key_as_standby(api_key)
                try:
                    if 'arquivos_ia_alvo' in locals():
                        for arq in arquivos_ia_alvo:
                            genai.delete_file(arq.name)
                except: pass
                st.toast(f"A chave ...{api_key[-4:]} falhou no Google. Puxando reserva!", icon="⚠️")
                continue
            else:
                return {"erro": f"Falha Critica (nao relacionada a cota): {str(e)}"}

    return {"erro": "🚨 TODAS AS CHAVES FALHARAM. Servidor Google indisponivel."}


def _analisar_http_direto(caminho_pdf, provedor_ativo, modelo_str, api_key, base_url, max_out_cfg, tempo_inicio, molde_nome=None):
    """Para provedores nao-Gemini — usa POST HTTP direto ao endpoint nativo com base64 inline."""
    provedor = provedor_ativo.get("provedor", "")
    # GABARITO DINÂMICO via molde (fallback = hardcoded antigo)
    mapeamento_fidedigno, _gab_lista, _coords = _carregar_mapeamento_do_molde(molde_nome)
    lista_oficial_plana = [frase for sublist in mapeamento_fidedigno.values() for frase in sublist]
    qtd_frases_gabarito = len(lista_oficial_plana)

    id_sessao = int(time.time())
    pasta_sessao = f"temp_fatias_{id_sessao}"

    st.write("⚙️ Fatiando PDF para alta resolução (OpenCV/PyMuPDF)...")
    sucesso_fatias, recortes = fatiar_pdf_com_opencv(caminho_pdf, pasta_sessao)
    if not sucesso_fatias:
        return {"erro": recortes}

    treinos_data_url = {}
    pasta_treino = os.path.join("banco_contexto", "treino_visao")
    if os.path.exists(pasta_treino):
        for arq_treino in os.listdir(pasta_treino):
            nome_sem_ext = os.path.splitext(arq_treino)[0]
            if nome_sem_ext in ARQUIVOS_CALIBRAGEM:
                caminho_original = os.path.join(pasta_treino, arq_treino)
                caminho_norm = normalizar_referencia_opencv(caminho_original, pasta_sessao)
                data_url = _imagem_para_data_url(caminho_norm)
                if data_url:
                    treinos_data_url[nome_sem_ext] = data_url

    fatias_data_url = []
    for path in recortes:
        data_url = _imagem_para_data_url(path)
        if data_url:
            fatias_data_url.append(data_url)

    # Le o prompt-PAI configurado para este provedor (vazio = sem reforco)
    prompt_pai_http = get_prompt_reforco(modelo_str, estrategia="modo1_6fatias")

    partes_prompt = []

    # Se ha prompt-PAI customizado, injeta como DIRETIVA SUPREMA antes de tudo
    if prompt_pai_http:
        partes_prompt.extend([
            "⛔ DIRETIVA SUPREMA — PRECEDÊNCIA ABSOLUTA SOBRE TUDO QUE VEM A SEGUIR ⛔",
            prompt_pai_http,
            "⛔ FIM DA DIRETIVA SUPREMA — agora siga rigorosamente as instruções abaixo, sempre respeitando a diretiva acima quando houver conflito ⛔",
            "",
        ])
        st.caption(f"🎯 Prompt-PAI ATIVO: {len(prompt_pai_http)} caracteres injetados como diretiva suprema")

    partes_prompt.extend([
        "Você é um Transcritor Forense.",
        "Sua tarefa é ler um formulário em fatias e dizer se o estudante sinalizou as frases.",
    ])
    if treinos_data_url:
        partes_prompt.append("\n--- CALIBRAGEM ---")
        for k in ARQUIVOS_CALIBRAGEM.keys():
            if k in treinos_data_url:
                partes_prompt.append(ARQUIVOS_CALIBRAGEM[k])

    partes_prompt.append("\n--- GABARITO OFICIAL DE FRASES ---")
    partes_prompt.append("⚠️ OBRIGATÓRIO: Use EXATAMENTE as frases desta lista na sua resposta. Não mude NENHUMA palavra.")
    for f_oficial in lista_oficial_plana:
        partes_prompt.append(f"- {f_oficial}")

    partes_prompt.extend([
        "\n--- TAREFA REAL ---",
        "Agora avalie as fatias do documento real anexadas abaixo.",
        "",
        "🚨 ATENÇÃO MÁXIMA: ARMADILHA VISUAL DETECTADA 🚨",
        "Temos um problema severo de 'falso vazio'. Traços feitos a lápis que são muito fracos, curvos, ou que apenas raspam a quina inferior do quadrado estão sendo ignorados pela sua visão porque se camuflam no texto que vaza do verso da folha (bleed-through).",
        "",
        "Para combater isso, você DEVE forçar o seu raciocínio visual passo a passo ANTES de dar a resposta.",
        "",
        "⚠️ PASSO 1: LOG DE INSPEÇÃO VISUAL (MODO ROBÓTICO) ⚠️",
        "Você está PROIBIDO de justificar ou escrever frases longas.",
        "Antes do gabarito, crie um log analisando o quadrado de cada frase.",
        "Para cada item, você deve escrever APENAS UMA destas 3 frases padrões (máximo 3 palavras):",
        "1. 'Totalmente limpo.'",
        "2. 'Apenas mancha.' (Use se for sujeira do verso da folha)",
        "3. 'Traço detectado.' (Use se houver qualquer linha de lápis/caneta)",
        "Exemplo Exato do Log:",
        "- Frase X: Totalmente limpo.",
        "- Frase Y: Apenas mancha.",
        "- Frase Z: Traço detectado.",
        "",
        "⚠️ PASSO 2: A REGRA IMPLACÁVEL DO [X] ⚠️",
        "Se no Passo 1 você classificou como 'Traço detectado.', você É OBRIGADO a marcar [X] no Passo 3. Se classificou como 'Totalmente limpo.' ou 'Apenas mancha.', marque [ ].",
        "⚠️ PASSO 3: GABARITO FINAL ⚠️",
        "Após o seu raciocínio, gere a lista final abaixo:",
        "### RESULTADOS",
        f"A lista DEVE conter EXATAMENTE {qtd_frases_gabarito} avaliações.",
        "[X] Frase do Gabarito",
        "[ ] Frase do Gabarito",
        "",
        "Transcreva TODAS as frases do Gabarito Oficial fornecido anteriormente. Não omita nenhuma."
    ])
    prompt_texto = "\n".join(partes_prompt)

    content = [{"type": "text", "text": prompt_texto}]
    if treinos_data_url:
        for k in ARQUIVOS_CALIBRAGEM.keys():
            if k in treinos_data_url:
                content.append({"type": "text", "text": ARQUIVOS_CALIBRAGEM[k]})
                content.append({"type": "image_url", "image_url": {"url": treinos_data_url[k]}})
    for data_url in fatias_data_url:
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    messages = [{"role": "user", "content": content}]

    st.caption(f"🔑 Provedor: **{provedor}** · Modelo: **{modelo_str}**")
    st.caption(f"⚙️ max_output_tokens = {max_out_cfg}")
    st.write(f"☁️ Enviando lote multimodal HTTP direto para o servidor do **{provedor}**...")

    telemetria_total = {"in": 0, "out": 0, "cache": 0, "brl": 0.0}
    texto_transcrito = ""

    try:
        ok, dados_resp, msg_resp = enviar_completion_http(
            provedor    = provedor,
            modelo_str  = modelo_str,
            messages    = messages,
            api_key     = api_key,
            base_url    = base_url,
            temperature = 0.0,
            max_tokens  = int(max_out_cfg),
            timeout     = 240,
        )

        if not ok:
            return {"erro": f"Falha na chamada ao servidor de '{provedor}' ({modelo_str}): {msg_resp}"}

        texto_transcrito         = dados_resp.get("texto", "") or ""
        telemetria_total["in"]   = int(dados_resp.get("tokens_in",    0) or 0)
        telemetria_total["out"]  = int(dados_resp.get("tokens_out",   0) or 0)
        telemetria_total["cache"]= int(dados_resp.get("tokens_cache", 0) or 0)
        finish_reason            = dados_resp.get("finish_reason", "") or ""

        endpoint_usado = dados_resp.get("endpoint", "")
        if endpoint_usado:
            st.caption(f"🌐 Endpoint: `{endpoint_usado}`")

        if finish_reason.upper() in ("MAX_TOKENS", "LENGTH"):
            st.error(
                f"⚠️ **Resposta TRUNCADA pelo provedor!** finish_reason = `{finish_reason}` — "
                f"aumente o `max_output_tokens` no Painel 1 (atual: {max_out_cfg})."
            )

        log_container = st.container(border=True)
        log_container.caption(f"📝 Transcrição — finish_reason: `{finish_reason or '?'}`")
        log_container.code(texto_transcrito, language="markdown")

    except Exception as e:
        return {"erro": f"Falha critica na chamada ao servidor de '{provedor}': {str(e)[:400]}"}

    estado_final_frases = {f: False for f in lista_oficial_plana}
    _parse_transcricao(texto_transcrito, estado_final_frases)

    try:
        custos = get_custos_provedor(modelo_str)
        dolar = obter_dolar_persistido() or 5.25
        tokens_in_full = max(0, telemetria_total["in"] - telemetria_total["cache"])
        tokens_cache   = telemetria_total["cache"]
        custo_usd = (
            (tokens_in_full          / 1_000_000) * custos.get("in_usd_1M",    0.0) +
            (telemetria_total["out"] / 1_000_000) * custos.get("out_usd_1M",   0.0) +
            (tokens_cache            / 1_000_000) * custos.get("cache_usd_1M", 0.0)
        )
        telemetria_total["brl"] = custo_usd * dolar
    except Exception:
        telemetria_total["brl"] = 0.0

    resultado_final = {cat: [] for cat in mapeamento_fidedigno.keys()}
    for categoria, perguntas in mapeamento_fidedigno.items():
        for frase in perguntas:
            marcado_final = estado_final_frases.get(frase, False)
            resultado_final[categoria].append({
                "pergunta": frase,
                "marcado":  marcado_final,
                "escala":   4 if marcado_final else 0
            })

    def faxina_local(pasta_local, pdf_local):
        try:
            if os.path.exists(pasta_local): shutil.rmtree(pasta_local)
        except: pass
        try:
            if os.path.exists(pdf_local): os.remove(pdf_local)
        except: pass

    qtd_local = len(recortes) + len(treinos_data_url) + 1
    with st.sidebar:
        st.markdown("---")
        st.subheader("🧹 Faxina de Cache")
        st.info(f"Limpando sessão: **{id_sessao}**")
        st.caption(f"💻 Local: **{qtd_local}** arquivos sendo removidos.")
        st.caption("☁️ Nuvem: 0 (HTTP direto usa base64 inline)")

    threading.Thread(target=faxina_local, args=(pasta_sessao, caminho_pdf), daemon=True).start()

    tempo_gasto = round(time.time() - tempo_inicio, 2)
    st.success(f"✅ Leitura concluída em {tempo_gasto}s via **{provedor}**!")

    try:
        registrar_consumo(
            f"{_compactar_modelo(modelo_str)} + Modo1",
            modelo_str,
            telemetria_total["in"] + telemetria_total["out"],
            telemetria_total["brl"],
            tempo_execucao=tempo_gasto,
            provedor=provedor,
            tokens_in=telemetria_total["in"],
            tokens_out=telemetria_total["out"],
            tokens_cache=telemetria_total["cache"],
        )
    except Exception:
        pass

    return {
        "sucesso": True,
        "dados":   resultado_final,
        "telemetria": {
            "modelo":         modelo_str,
            "provedor":       provedor,
            "in":             telemetria_total["in"],
            "out":            telemetria_total["out"],
            "cache":          telemetria_total["cache"],
            "brl":            telemetria_total["brl"],
            "tempo_segundos": tempo_gasto,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ESTEIRA "MICRO-VISION CROP" — APENAS para provedores LOCAIS (Ollama/vLLM/LMStudio)
# ═══════════════════════════════════════════════════════════════════════════════
# Filosofia: enviar imagens GIGANTES (fatias de 1700×300 px) para um Llama Vision
# rodando em VRAM limitada (8–12GB) causa HTTP 500 / OOM. A solução é localizar
# CADA frase do gabarito no PDF original (via pdfplumber, motor de OCR coordenado),
# recortar APENAS o mini-quadrado de marcação à esquerda (~40×40 px), e perguntar
# binariamente ao Llama: "MARCADO ou NAO_MARCADO?" — uma micro-imagem por frase.
#
# Payload por inferência: <2KB vs ~500KB das fatias (redução de 250×).
# Resultado final entra no MESMO formato esperado pelo app (mapeamento_fidedigno).
# Fluxos Gemini e HTTP-cloud permanecem 100% intactos — bifurcação cirúrgica.
# ═══════════════════════════════════════════════════════════════════════════════





def _renderizar_pagina_para_cv(caminho_pdf, num_pagina=0, dpi=200):
    """Rasteriza uma página do PDF em imagem OpenCV (BGR).
    Retorna (img_cv, fator_escala_x, fator_escala_y, altura_pdf_pt, largura_pdf_pt).
    Os fatores convertem coordenadas pdfplumber (pontos PDF) → pixels da imagem."""
    doc = fitz.open(caminho_pdf)
    pagina = doc.load_page(num_pagina)
    largura_pdf_pt = pagina.rect.width
    altura_pdf_pt  = pagina.rect.height

    pix = pagina.get_pixmap(dpi=dpi)
    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        img_cv = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
    else:
        img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

    doc.close()
    escala_x = pix.w / largura_pdf_pt
    escala_y = pix.h / altura_pdf_pt
    return img_cv, escala_x, escala_y, altura_pdf_pt, largura_pdf_pt


def _extrair_linhas_com_posicao(caminho_pdf):
    """Lê o PDF com pdfplumber e devolve linhas+posições:
    [(num_pag, texto_linha, x0_pdf, top_pdf, x1_pdf, bottom_pdf), ...]
    Motor de OCR coordenado usado para localizar onde cada frase do gabarito
    mora no documento físico."""
    if not PDFPLUMBER_ATIVO:
        return []

    linhas_indexadas = []
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            for num_pag, page in enumerate(pdf.pages):
                palavras = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
                if not palavras:
                    continue

                palavras_ordenadas = sorted(palavras, key=lambda w: (w["top"], w["x0"]))
                grupos = []
                grupo_atual = []
                top_atual = None
                for w in palavras_ordenadas:
                    if top_atual is None or abs(w["top"] - top_atual) <= 4.0:
                        grupo_atual.append(w)
                        if top_atual is None:
                            top_atual = w["top"]
                    else:
                        grupos.append(grupo_atual)
                        grupo_atual = [w]
                        top_atual = w["top"]
                if grupo_atual:
                    grupos.append(grupo_atual)

                for g in grupos:
                    if not g:
                        continue
                    texto = " ".join(w["text"] for w in g).strip()
                    if not texto:
                        continue
                    x0  = min(w["x0"]     for w in g)
                    x1  = max(w["x1"]     for w in g)
                    top = min(w["top"]    for w in g)
                    bot = max(w["bottom"] for w in g)
                    linhas_indexadas.append((num_pag, texto, x0, top, x1, bot))
    except Exception as e:
        try:
            st.warning(f"⚠️ pdfplumber falhou: {str(e)[:200]}")
        except Exception:
            pass
        return []

    return linhas_indexadas


def _localizar_frases_oficiais(linhas_pdf, lista_frases_oficiais, limiar=0.72):
    """Para cada frase do gabarito, acha a LINHA do PDF mais parecida via
    SequenceMatcher >= limiar. Retorna:
       [(frase_oficial, num_pag, x0, top, x1, bot, similaridade), ...]
    Frase não localizada → entrada com posições None (cai em 'não marcada')."""
    resultado = []
    for frase_of in lista_frases_oficiais:
        melhor_score = 0.0
        melhor_linha = None
        for num_pag, texto, x0, top, x1, bot in linhas_pdf:
            ratio = difflib.SequenceMatcher(
                None,
                frase_of.lower().strip(),
                texto.lower().strip()
            ).ratio()
            if ratio > melhor_score:
                melhor_score = ratio
                melhor_linha = (num_pag, x0, top, x1, bot)

        if melhor_linha and melhor_score >= limiar:
            np_, x0_, t_, x1_, b_ = melhor_linha
            resultado.append((frase_of, np_, x0_, t_, x1_, b_, round(melhor_score, 3)))
        else:
            resultado.append((frase_of, None, None, None, None, None, round(melhor_score, 3)))
    return resultado


def _recortar_checkbox_da_linha(img_cv, x0_pdf, top_pdf, bot_pdf,
                                 escala_x, escala_y,
                                 largura_busca_pt=38,
                                 padding_vertical_pt=2):
    """Recorta a região à ESQUERDA do início da frase, onde costuma ficar o
    quadrado de marcação. Heurística geométrica: ~38pt à esquerda de x0_pdf,
    com altura ≈ altura do texto. Retorna (recorte numpy, bbox_px)."""
    altura_img, largura_img = img_cv.shape[:2]

    x_busca_dir_pdf = max(0.0, x0_pdf - 2.0)
    x_busca_esq_pdf = max(0.0, x_busca_dir_pdf - largura_busca_pt)
    y_busca_top_pdf = max(0.0, top_pdf - padding_vertical_pt)
    y_busca_bot_pdf = min(bot_pdf + padding_vertical_pt, top_pdf + 30)

    x1_px = max(0, int(x_busca_esq_pdf * escala_x))
    x2_px = min(largura_img, int(x_busca_dir_pdf * escala_x))
    y1_px = max(0, int(y_busca_top_pdf * escala_y))
    y2_px = min(altura_img, int(y_busca_bot_pdf * escala_y))

    if x2_px <= x1_px or y2_px <= y1_px:
        return None, (0, 0, 0, 0)

    recorte_amplo = img_cv[y1_px:y2_px, x1_px:x2_px]
    return recorte_amplo, (x1_px, y1_px, x2_px, y2_px)


def _refinar_recorte_no_quadrado(recorte_amplo):
    """Tenta refinar o recorte amplo encontrando o contorno quadrado do checkbox.
    Filtro: aspect ratio 0.65-1.55, área plausível. Fallback: retorna o recorte amplo."""
    if recorte_amplo is None or recorte_amplo.size == 0:
        return recorte_amplo
    h, w = recorte_amplo.shape[:2]
    if h < 4 or w < 4:
        return recorte_amplo

    try:
        cinza = cv2.cvtColor(recorte_amplo, cv2.COLOR_BGR2GRAY)
        _, bin_img = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        contornos, _ = cv2.findContours(bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        melhor_box = None
        melhor_area_diff = 1e9
        area_alvo = (min(h, w) * 0.7) ** 2

        for c in contornos:
            x, y, cw, ch = cv2.boundingRect(c)
            if cw < 4 or ch < 4:
                continue
            aspect = cw / float(ch)
            if aspect < 0.65 or aspect > 1.55:
                continue
            area = cw * ch
            if area < 36 or area > h * w * 0.9:
                continue
            diff = abs(area - area_alvo)
            if diff < melhor_area_diff:
                melhor_area_diff = diff
                melhor_box = (x, y, cw, ch)

        if melhor_box is None:
            return recorte_amplo

        x, y, cw, ch = melhor_box
        pad = 2
        x1 = max(0, x - pad); y1 = max(0, y - pad)
        x2 = min(w, x + cw + pad); y2 = min(h, y + ch + pad)
        return recorte_amplo[y1:y2, x1:x2]
    except Exception:
        return recorte_amplo


def _micro_crop_para_base64_png(recorte_cv):
    """Converte recorte numpy → base64 PNG puro (sem prefixo data:)."""
    import base64
    if recorte_cv is None or recorte_cv.size == 0:
        return ""
    ok, buffer = cv2.imencode(".png", recorte_cv)
    if not ok:
        return ""
    return base64.b64encode(buffer.tobytes()).decode("utf-8")


def _calcular_densidade_miolo(img_cv_pagina, x, y, w, h, margem_px=4, erode_px=3):
    """
    OPÇÃO B — TRIAGEM DETERMINÍSTICA POR DENSIDADE DO MIOLO (v5 — CROP FIXO).

    A versão anterior usava cv2.erode para remover a borda do checkbox, mas o
    kernel 7×7 (raio 3) APAGAVA TAMBÉM o X de caneta (linhas finas de 2-3 px),
    causando classificação errada de TODOS os marcados como vazios.

    Nova estratégia: CROP FÍSICO da margem. Recorta `margem_px` pixels de cada
    lado do bbox ANTES de binarizar. A borda do checkbox tem 1-3 px de espessura
    e fica fora do crop. O X (mesmo fino) fica preservado no miolo.

    Pipeline:
      1. Recorta o bbox (x,y,w,h) da página rasterizada
      2. CROP FIXO: remove margem_px pixels de cada lado (4 px cobre bordas
         de até 3px de espessura com folga)
      3. Binariza o miolo (Adaptive Gaussian Threshold + INV)
      4. Calcula densidade = pixels_pretos_no_miolo / area_miolo

    Interpretação (calibrada para crop de 4 px sobre quadrado de 20-50 px):
      • miolo < 0.05  → checkbox VAZIO (miolo limpo, sem nada dentro)
      • miolo 0.05–0.18 → ZONA CINZENTA (sombra leve, fragmento de traço)
      • miolo > 0.18  → MARCADO (X, riscado, preenchimento)

    Retorna (densidade_miolo: float, miolo_array: np.ndarray | None).
    """
    if img_cv_pagina is None or img_cv_pagina.size == 0:
        return 0.0, None

    h_img, w_img = img_cv_pagina.shape[:2]
    x1 = max(0, x); y1 = max(0, y)
    x2 = min(w_img, x + w); y2 = min(h_img, y + h)
    if x2 <= x1 or y2 <= y1:
        return 0.0, None

    bbox = img_cv_pagina[y1:y2, x1:x2]
    bh, bw = bbox.shape[:2]

    # ── CROP FIXO da margem (substitui o erode) ──
    # Garante que o miolo tenha pelo menos 6×6 px (evita degenerar em quadrados muito pequenos)
    margem_efetiva = min(margem_px, max(1, min(bh, bw) // 4))
    miolo_bbox = bbox[
        margem_efetiva : bh - margem_efetiva,
        margem_efetiva : bw - margem_efetiva,
    ]
    if miolo_bbox is None or miolo_bbox.size == 0:
        return 0.0, None

    cinza = cv2.cvtColor(miolo_bbox, cv2.COLOR_BGR2GRAY)
    # Adaptive threshold com blockSize menor (o miolo é pequeno)
    block = max(3, (min(miolo_bbox.shape[:2]) // 2) * 2 + 1)  # ímpar
    if block < 3:
        block = 3
    bin_miolo = cv2.adaptiveThreshold(
        cinza, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=block,
        C=4
    )

    densidade = float(cv2.countNonZero(bin_miolo)) / float(bin_miolo.size)
    return densidade, bin_miolo


def _expandir_crop_para_llm(img_cv_pagina, x, y, w, h, tamanho_final=120, padding_branco_px=15):
    """
    OPÇÃO B — FALLBACK CIRÚRGICO PARA A IA.

    Quando a densidade do miolo cai na ZONA CINZENTA (0.10–0.35), entregamos
    o caso para a IA de visão. Mas micro-imagens 30×30 px causam alucinação
    no Llama Vision (responde !!!!!!!! quando o input é menor que um patch
    do ViT encoder).

    Esta função:
      1. Recorta uma janela MAIOR ao redor do checkbox (incluindo contexto
         da página — folha, espaço em branco, possivelmente parte da frase)
      2. Se a janela ficar menor que `tamanho_final`, faz padding com
         margem BRANCA (cv2.copyMakeBorder) — branco porque é a cor do
         papel/folha, então a IA vê uma "ilha" do checkbox.
      3. Devolve uma imagem com pelo menos `tamanho_final` x `tamanho_final` px

    Retorna numpy.ndarray BGR.
    """
    if img_cv_pagina is None or img_cv_pagina.size == 0:
        return None

    h_img, w_img = img_cv_pagina.shape[:2]
    centro_x = x + w // 2
    centro_y = y + h // 2

    # Janela inicial: 2x o tamanho do checkbox em torno do centro
    raio_x = max(tamanho_final // 2, w + padding_branco_px)
    raio_y = max(tamanho_final // 2, h + padding_branco_px)

    x1 = max(0, centro_x - raio_x)
    y1 = max(0, centro_y - raio_y)
    x2 = min(w_img, centro_x + raio_x)
    y2 = min(h_img, centro_y + raio_y)

    crop = img_cv_pagina[y1:y2, x1:x2]
    if crop is None or crop.size == 0:
        return None

    # Padding branco para atingir tamanho_final mínimo
    ch, cw = crop.shape[:2]
    if ch < tamanho_final or cw < tamanho_final:
        top    = max(0, (tamanho_final - ch) // 2)
        bottom = max(0, tamanho_final - ch - top)
        left   = max(0, (tamanho_final - cw) // 2)
        right  = max(0, tamanho_final - cw - left)
        crop = cv2.copyMakeBorder(
            crop, top, bottom, left, right,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255)   # branco BGR
        )

    return crop


def _perguntar_ollama_micro(modelo_str, base_url, imagem_b64_png, frase_ctx, timeout=45):
    """UMA inferência ao Ollama com a micro-imagem do checkbox.
    Endpoint: POST {base}/api/generate (nativo Ollama com campo 'images').
    Retorna (sucesso, marcado, resposta_raw, tokens_estimados)."""
    if not _requests_micro:
        return False, False, "Biblioteca 'requests' ausente.", 0
    if not imagem_b64_png:
        return False, False, "Micro-recorte vazio.", 0

    base = (base_url or "http://localhost:11434").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    if base.endswith("/api"):
        base = base[:-4]
    url = f"{base}/api/generate"

    modelo_ollama = modelo_str
    if modelo_ollama.lower().startswith("ollama/"):
        modelo_ollama = modelo_ollama[len("ollama/"):]

    prompt = (
        "Você é um inspetor visual binário ultra-rigoroso.\n"
        "Examine APENAS este mini-quadrado (checkbox de formulário escolar).\n"
        "\n"
        "REGRAS:\n"
        " • MARCADO  = há um X, traço diagonal, riscado, preenchimento ou rabisco INTENCIONAL dentro do quadrado.\n"
        " • NAO_MARCADO = quadrado vazio, só com a borda, ou apenas com mancha clara do verso da folha (bleed-through fantasma).\n"
        "\n"
        "IMPORTANTE: falso positivo (marcar [X] sem haver traço) é PIOR que falso negativo. "
        "Na dúvida absoluta, responda NAO_MARCADO.\n"
        "\n"
        f"Frase associada (apenas contexto, NÃO influencia a decisão): \"{frase_ctx}\"\n"
        "\n"
        "Responda com UMA ÚNICA palavra, em maiúsculas, sem ponto final, sem nada mais:\n"
        "MARCADO\n"
        "NAO_MARCADO"
    )

    payload = {
        "model":   modelo_ollama,
        "prompt":  prompt,
        "images":  [imagem_b64_png],
        "stream":  False,
        "options": {
            "temperature": 0.0,
            "top_p":       1.0,
            "num_predict": 8,
        },
    }

    try:
        r = _requests_micro.post(url, json=payload, timeout=timeout)
        if r.status_code != 200:
            return False, False, f"HTTP {r.status_code}: {r.text[:200]}", 0
        data = r.json()
        resposta_raw = (data.get("response", "") or "").strip().upper()

        tokens_in_est  = int(data.get("prompt_eval_count", 0) or 0)
        tokens_out_est = int(data.get("eval_count",        0) or 0)
        tokens_total   = tokens_in_est + tokens_out_est

        if "NAO_MARCADO" in resposta_raw or "NÃO MARCADO" in resposta_raw or "NAO MARCADO" in resposta_raw:
            return True, False, resposta_raw, tokens_total
        if "NAO" in resposta_raw and "MARC" in resposta_raw:
            return True, False, resposta_raw, tokens_total
        if "MARCADO" in resposta_raw or "MARCADA" in resposta_raw:
            return True, True, resposta_raw, tokens_total
        return True, False, f"[AMBIGUO] {resposta_raw}", tokens_total
    except Exception as e:
        return False, False, f"Falha HTTP: {str(e)[:200]}", 0


def _perguntar_llm_micro_universal(provedor, modelo_str, api_key, base_url,
                                    imagem_b64_png, frase_ctx, timeout=60):
    """
    ADAPTADOR UNIVERSAL para o fallback de ZONA CINZENTA da esteira Micro-Vision.
    Roteia para o provedor certo com base no nome do provedor / prefixo do modelo:

      • GEMINI       → genai.GenerativeModel.generate_content (mesma SDK do Modo 1,
                       reaproveita o carrossel de chaves se houver)
      • OLLAMA/LOCAL → POST {base}/api/generate (formato nativo Ollama com 'images')
      • OPENAI-COMPAT→ POST {base}/v1/chat/completions com image_url base64 inline
                       (OpenAI, Anthropic, Groq, Alibaba, Kimi, etc.)

    Retorna (sucesso: bool, marcado: bool, resposta_raw: str, tokens_estimados: int).
    """
    prov_lower = (provedor or "").lower()
    modelo_lower = (modelo_str or "").lower()

    eh_gemini_p = ("gemini" in prov_lower) or modelo_lower.startswith("gemini/")
    eh_local_p  = (
        "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower
        or modelo_lower.startswith("ollama/")
    )

    # ── BRANCH 1: Ollama / vLLM / LM Studio local ──
    if eh_local_p:
        return _perguntar_ollama_micro(modelo_str, base_url, imagem_b64_png, frase_ctx, timeout=timeout)

    prompt_texto = (
        "Você é um inspetor visual binário ultra-rigoroso.\n"
        "Examine APENAS o quadrado de marcação (checkbox) presente nesta imagem.\n"
        "\n"
        "REGRAS:\n"
        " • MARCADO     = há um X, traço diagonal, riscado, preenchimento ou rabisco INTENCIONAL dentro do quadrado.\n"
        " • NAO_MARCADO = quadrado vazio, só com a borda, ou apenas com mancha clara do verso da folha (bleed-through).\n"
        "\n"
        "IMPORTANTE: falso positivo é PIOR que falso negativo. Na dúvida absoluta, responda NAO_MARCADO.\n"
        "\n"
        f"Frase associada (contexto, NÃO influencia a decisão): \"{frase_ctx}\"\n"
        "\n"
        "Responda com UMA ÚNICA palavra em maiúsculas, sem ponto, sem nada mais:\n"
        "MARCADO\n"
        "NAO_MARCADO"
    )

    # ── BRANCH 2: GEMINI cloud (genai SDK — mesma do Modo 1) ──
    if eh_gemini_p:
        if not genai:
            return False, False, "google-generativeai ausente", 0

        modelo_config = modelo_str[len("gemini/"):] if modelo_str.startswith("gemini/") else modelo_str

        # Tenta o carrossel de chaves primeiro; cai na api_key do provedor se vazio
        chave = None
        try:
            chave = get_next_valid_key() or api_key
        except Exception:
            chave = api_key
        if not chave:
            return False, False, "sem chave Gemini disponível (pool vazio)", 0

        try:
            import base64 as _b64
            genai.configure(api_key=chave)
            modelo_obj = genai.GenerativeModel(
                model_name=modelo_config,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0, top_p=1.0, top_k=1, max_output_tokens=16,
                ),
            )
            img_bytes = _b64.b64decode(imagem_b64_png)
            partes = [
                prompt_texto,
                {"mime_type": "image/png", "data": img_bytes},
            ]
            resp = modelo_obj.generate_content(partes, stream=False)
            resposta_raw = ""
            try:
                resposta_raw = (resp.text or "").strip().upper()
            except Exception:
                try:
                    cands = resp.candidates or []
                    if cands and cands[0].content and cands[0].content.parts:
                        resposta_raw = (cands[0].content.parts[0].text or "").strip().upper()
                except Exception:
                    pass

            # Telemetria Gemini (best effort)
            tokens_in_est = 0
            tokens_out_est = 0
            try:
                if hasattr(resp, "usage_metadata"):
                    tokens_in_est  = int(getattr(resp.usage_metadata, "prompt_token_count", 0) or 0)
                    tokens_out_est = int(getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
            except Exception:
                pass

            if "NAO_MARCADO" in resposta_raw or "NÃO MARCADO" in resposta_raw or "NAO MARCADO" in resposta_raw:
                return True, False, resposta_raw, tokens_in_est + tokens_out_est
            if "MARCADO" in resposta_raw or "MARCADA" in resposta_raw:
                return True, True, resposta_raw, tokens_in_est + tokens_out_est
            return True, False, f"[AMBIGUO] {resposta_raw}", tokens_in_est + tokens_out_est
        except Exception as e:
            return False, False, f"Falha Gemini: {str(e)[:200]}", 0

    # ── BRANCH 3: OpenAI-compatible (Anthropic, Groq, Alibaba, Kimi, etc.) ──
    # Reusa enviar_completion_http (já testado no fluxo HTTP direto).
    try:
        data_url = f"data:image/png;base64,{imagem_b64_png}"
        messages = [{
            "role": "user",
            "content": [
                {"type": "text",      "text": prompt_texto},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        }]
        ok, dados, msg = enviar_completion_http(
            provedor    = provedor,
            modelo_str  = modelo_str,
            messages    = messages,
            api_key     = api_key,
            base_url    = base_url,
            temperature = 0.0,
            max_tokens  = 16,
            timeout     = timeout,
        )
        if not ok:
            return False, False, f"HTTP falhou: {msg}", 0

        resposta_raw = (dados.get("texto", "") or "").strip().upper()
        toks = int(dados.get("tokens_in", 0) or 0) + int(dados.get("tokens_out", 0) or 0)

        if "NAO_MARCADO" in resposta_raw or "NÃO MARCADO" in resposta_raw or "NAO MARCADO" in resposta_raw:
            return True, False, resposta_raw, toks
        if "MARCADO" in resposta_raw or "MARCADA" in resposta_raw:
            return True, True, resposta_raw, toks
        return True, False, f"[AMBIGUO] {resposta_raw}", toks
    except Exception as e:
        return False, False, f"Falha HTTP cloud: {str(e)[:200]}", 0


def _detectar_checkboxes_por_contornos(img_cv, limite_x_pct=0.20,
                                       lado_min=20, lado_max=65,
                                       densidade_max=0.85,
                                       vertices_min=4, vertices_max=8):
    """
    FALLBACK para PDFs escaneados (sem camada de texto): detecta quadrados de
    checkbox na imagem rasterizada, sem depender de OCR.

    Filtros CALIBRADOS (v3 — pós-análise: scanner com skew, x_min=115 e x_max=396):
      • POSIÇÃO HORIZONTAL: centro_x nos primeiros 20% da largura
        (mira laser na margem esquerda — descarta watermarks/bleed-through do CamScanner).
      • TAMANHO RESILIENTE: largura E altura entre 20 e 65 px (DPI=200).
      • ASPECT RATIO: 0,82–1,22 (quadrado real, não retângulo).
      • POLÍGONO: 4–8 vértices (tolera borrões e curvas falsas do scanner).
      • DENSIDADE DE PRETO: o quadrado deve ter borda fina + interior majoritário
        em branco. Se > 85% do bbox for preto, é uma letra negrito ou bullet
        sólido — descarta.
      • DEDUPE: centros próximos (< 15 px) viram um só.

    Retorna lista [(x, y, w, h), ...] ORDENADA top-down, depois left-right
    com agrupamento por banda horizontal (tolerância 15 px).
    """
    if img_cv is None or img_cv.size == 0:
        return []

    altura_img, largura_img = img_cv.shape[:2]
    x_max_aceito = largura_img * float(limite_x_pct)

    cinza = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

    # Adaptive Gaussian threshold — melhor para iluminação irregular de scanner
    bin_img = cv2.adaptiveThreshold(
        cinza, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=15,
        C=4
    )
    # Fecha pequenos gaps na borda do quadrado
    kernel = np.ones((2, 2), np.uint8)
    bin_img = cv2.morphologyEx(bin_img, cv2.MORPH_CLOSE, kernel, iterations=1)

    contornos, _ = cv2.findContours(bin_img, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    candidatos = []  # aprovados
    rejeitados = {   # debug — contagem por motivo
        "tamanho": 0, "aspect": 0, "vertices": 0,
        "posicao_x": 0, "densidade": 0, "duplicado": 0,
    }

    for c in contornos:
        x, y, w, h = cv2.boundingRect(c)

        # ── FILTRO 1: TAMANHO ESTRITO (25-50 px) ──
        if w < lado_min or w > lado_max:
            rejeitados["tamanho"] += 1; continue
        if h < lado_min or h > lado_max:
            rejeitados["tamanho"] += 1; continue

        # ── FILTRO 2: ASPECT RATIO (quadrado real) ──
        aspect = w / float(h)
        if aspect < 0.82 or aspect > 1.22:
            rejeitados["aspect"] += 1; continue

        # ── FILTRO 3: POSIÇÃO HORIZONTAL (margem esquerda) ──
        centro_x = x + w / 2.0
        if centro_x > x_max_aceito:
            rejeitados["posicao_x"] += 1; continue

        # ── FILTRO 4: APROXIMAÇÃO POLIGONAL ──
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)
        if len(approx) < vertices_min or len(approx) > vertices_max:
            rejeitados["vertices"] += 1; continue

        # ── FILTRO 5: DENSIDADE DE PRETO (descarta sólidos) ──
        # Conta pixels brancos da bin_img dentro do bbox (lembrando que
        # adaptiveThreshold inverteu: branco = traço/preto original).
        bbox_bin = bin_img[y:y+h, x:x+w]
        if bbox_bin.size == 0:
            rejeitados["densidade"] += 1; continue
        densidade = float(cv2.countNonZero(bbox_bin)) / float(bbox_bin.size)
        if densidade > densidade_max:
            rejeitados["densidade"] += 1; continue

        candidatos.append((x, y, w, h, round(densidade, 3)))

    # ── DEDUPLICAÇÃO por centro próximo ──
    candidatos.sort(key=lambda c: (c[1], c[0]))
    dedup = []
    for cand in candidatos:
        x1, y1, w1, h1, _d1 = cand
        cx1, cy1 = x1 + w1 / 2.0, y1 + h1 / 2.0
        duplicado = False
        for ex in dedup:
            x2, y2, w2, h2, _d2 = ex
            cx2, cy2 = x2 + w2 / 2.0, y2 + h2 / 2.0
            if abs(cx1 - cx2) < 15 and abs(cy1 - cy2) < 15:
                duplicado = True
                rejeitados["duplicado"] += 1
                break
        if not duplicado:
            dedup.append(cand)

    if not dedup:
        return [], rejeitados

    # ── ORDENAÇÃO ESTRITA: top-down (y) → left-right (x) ──
    # Sem agrupamento por banda — o caller (_coletar_...) já garante a ordem por página.
    dedup.sort(key=lambda c: (c[1], c[0]))
    return dedup, rejeitados


def _coletar_checkboxes_de_todas_as_paginas(caminho_pdf):
    """
    Rasteriza CADA página (DPI=200), aplica _detectar_checkboxes_por_contornos,
    e devolve:
      • lista_checkboxes_globais: [(num_pag, x, y, w, h, densidade), ...] em ORDEM de leitura
      • cache_paginas:            {num_pag: img_cv}
      • rejeitados_agregados:     dict com contagem por motivo (todas as páginas somadas)
    """
    cache_paginas = {}
    lista_checkboxes_globais = []
    rejeitados_agregados = {"tamanho": 0, "aspect": 0, "vertices": 0,
                             "posicao_x": 0, "densidade": 0, "duplicado": 0}

    doc = fitz.open(caminho_pdf)
    num_paginas = len(doc)
    doc.close()

    for npag in range(num_paginas):
        try:
            img_cv, _ex, _ey, _, _ = _renderizar_pagina_para_cv(caminho_pdf, num_pagina=npag, dpi=200)
        except Exception as e:
            try:
                st.warning(f"⚠️ Falha ao rasterizar página {npag}: {e}")
            except Exception:
                pass
            continue

        cache_paginas[npag] = img_cv
        boxes, rej = _detectar_checkboxes_por_contornos(img_cv)
        for tup in boxes:
            x, y, w, h, dens = tup
            lista_checkboxes_globais.append((npag, x, y, w, h, dens))
        for k in rejeitados_agregados.keys():
            rejeitados_agregados[k] += rej.get(k, 0)

    # ── Garantia: ordenação ESTRITA por (página, y, x) ──
    lista_checkboxes_globais.sort(key=lambda t: (t[0], t[2], t[1]))
    return lista_checkboxes_globais, cache_paginas, rejeitados_agregados


def _carregar_template_referencia_branco(pasta_treino=None):
    """Carrega o template referencia_branco.jpg para template matching de localização."""
    if pasta_treino is None:
        pasta_treino = os.path.join("banco_contexto", "treino_visao")
    path = os.path.join(pasta_treino, "referencia_branco.jpg")
    if not os.path.exists(path):
        return None
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE)


def _localizar_checkboxes_via_template(img_cv_pagina, template_gs,
                                        threshold=0.60, x_max_pct=0.20,
                                        nms_raio=25, escalas=None):
    """
    LOCALIZA checkboxes na página usando multi-scale template matching com
    o template referencia_branco. Mais robusto que detector por contorno porque
    NÃO confunde letras de título com checkbox.

    Retorna lista [(x, y, w, h, score), ...] ordenada top-down, left-right.
    """
    if img_cv_pagina is None or template_gs is None:
        return []
    if escalas is None:
        escalas = [0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.7]

    # Converte página para grayscale se ainda não estiver
    if len(img_cv_pagina.shape) == 3:
        prova_gs = cv2.cvtColor(img_cv_pagina, cv2.COLOR_BGR2GRAY)
    else:
        prova_gs = img_cv_pagina

    h_pag, w_pag = prova_gs.shape[:2]
    x_max = int(w_pag * x_max_pct)

    matches = []
    for escala in escalas:
        nw = int(template_gs.shape[1] * escala)
        nh = int(template_gs.shape[0] * escala)
        if nw < 20 or nh < 18 or nw > 60 or nh > 50:
            continue
        tpl = cv2.resize(template_gs, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
        res = cv2.matchTemplate(prova_gs, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        for y, x in zip(ys, xs):
            if x > x_max:
                continue
            matches.append((int(x), int(y), int(nw), int(nh), float(res[y, x])))

    # NMS por proximidade de centro
    matches.sort(key=lambda m: -m[4])
    keep = []
    for m in matches:
        cx = m[0] + m[2] / 2.0
        cy = m[1] + m[3] / 2.0
        dup = False
        for k in keep:
            kcx = k[0] + k[2] / 2.0
            kcy = k[1] + k[3] / 2.0
            if abs(cx - kcx) < nms_raio and abs(cy - kcy) < nms_raio:
                dup = True
                break
        if not dup:
            keep.append(m)

    # Ordena top-down, left-right (estrita)
    keep.sort(key=lambda m: (m[1], m[0]))
    return keep


def _extrair_linha_inteira_do_checkbox(img_cv_pagina, x, y, w, h,
                                        padding_y=8, padding_x_esq=8,
                                        largura_linha_max=None):
    """
    Recorta a LINHA INTEIRA onde o checkbox está, para mandar ao LLM.
    A linha contém: o checkbox à esquerda + a frase escrita à direita.

    Retorna numpy array BGR.
    """
    if img_cv_pagina is None or img_cv_pagina.size == 0:
        return None
    h_pag, w_pag = img_cv_pagina.shape[:2]

    y1 = max(0, y - padding_y)
    y2 = min(h_pag, y + h + padding_y)
    x1 = max(0, x - padding_x_esq)
    if largura_linha_max is None:
        x2 = w_pag
    else:
        x2 = min(w_pag, x1 + largura_linha_max)

    if x2 <= x1 or y2 <= y1:
        return None
    return img_cv_pagina[y1:y2, x1:x2]


def _classificar_e_associar_via_llm(provedor, modelo_str, api_key, base_url,
                                     img_linha_bgr, lista_frases_oficiais,
                                     timeout=60):
    """
    Envia a LINHA INTEIRA (checkbox + frase escrita) ao LLM e pede para
    classificar marcado/vazio E identificar qual frase do gabarito está ali.

    Resposta esperada (JSON): {"frase_id": 0-N, "marcado": true|false}
      • frase_id = 0      → linha não corresponde a nenhuma frase (descartar)
      • frase_id = 1..N   → índice 1-based na lista de frases_oficiais
      • marcado           → bool indicando se o checkbox está marcado

    Retorna tupla (sucesso, frase_id, marcado, resposta_raw, tokens_in, tokens_out).
    """
    import base64 as _b64

    if img_linha_bgr is None or img_linha_bgr.size == 0:
        return False, 0, False, "Imagem da linha vazia", 0, 0

    # Codifica imagem em PNG base64
    ok, buf = cv2.imencode(".png", img_linha_bgr)
    if not ok:
        return False, 0, False, "Falha ao codificar PNG", 0, 0
    img_b64 = _b64.b64encode(buf.tobytes()).decode("utf-8")

    # Monta lista numerada das frases (compacta)
    linhas_gabarito = []
    for i, frase in enumerate(lista_frases_oficiais):
        linhas_gabarito.append(f"{i+1}. {frase}")
    gabarito_str = "\n".join(linhas_gabarito)

    prompt_texto = (
        "Você é um analisador binário de formulários escolares preenchidos a mão.\n"
        "Esta imagem mostra UMA LINHA do formulário: à esquerda um quadrado (checkbox) "
        "e à direita o texto escrito da frase.\n"
        "\n"
        "SUA TAREFA — responda em JSON puro:\n"
        '  {"frase_id": <NÚMERO>, "marcado": <true ou false>}\n'
        "\n"
        "REGRAS:\n"
        " • frase_id = 0 SE a linha não corresponde a NENHUMA frase abaixo (ignorar)\n"
        " • frase_id = 1 a 46 conforme a lista abaixo, escolhendo a MAIS PARECIDA\n"
        " • marcado = true SE o quadrado tem X, traço, riscado ou preenchimento INTENCIONAL dentro\n"
        " • marcado = false SE o quadrado está vazio, só com borda, ou apenas com mancha/bleed-through\n"
        " • ATENÇÃO: falso positivo (dizer marcado sem haver traço) é PIOR que falso negativo. Na dúvida, marcado=false.\n"
        "\n"
        "FRASES POSSÍVEIS (responda com o NÚMERO):\n"
        f"{gabarito_str}\n"
        "\n"
        "Responda APENAS o JSON, sem markdown, sem explicação, sem ```:"
    )

    prov_lower = (provedor or "").lower()
    modelo_lower = (modelo_str or "").lower()
    eh_gemini_p = ("gemini" in prov_lower) or modelo_lower.startswith("gemini/")
    eh_local_p  = (
        "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower
        or modelo_lower.startswith("ollama/")
    )

    resposta_raw = ""
    tokens_total = 0

    # ── BRANCH GEMINI nativo (mesma SDK do Modo 1) ──
    if eh_gemini_p:
        if not genai:
            return False, 0, False, "google-generativeai ausente", 0, 0
        modelo_config = modelo_str[len("gemini/"):] if modelo_str.startswith("gemini/") else modelo_str

        chave = None
        try:
            chave = get_next_valid_key() or api_key
        except Exception:
            chave = api_key
        if not chave:
            return False, 0, False, "sem chave Gemini disponível", 0, 0

        try:
            genai.configure(api_key=chave)
            modelo_obj = genai.GenerativeModel(
                model_name=modelo_config,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0, top_p=1.0, top_k=1, max_output_tokens=64,
                ),
            )
            img_bytes = _b64.b64decode(img_b64)
            resp = modelo_obj.generate_content(
                [prompt_texto, {"mime_type": "image/png", "data": img_bytes}],
                stream=False,
            )
            try:
                resposta_raw = (resp.text or "").strip()
            except Exception:
                try:
                    cands = resp.candidates or []
                    if cands and cands[0].content and cands[0].content.parts:
                        resposta_raw = (cands[0].content.parts[0].text or "").strip()
                except Exception:
                    pass
            tok_in_gemini  = 0
            tok_out_gemini = 0
            try:
                if hasattr(resp, "usage_metadata"):
                    tok_in_gemini  = int(getattr(resp.usage_metadata, "prompt_token_count", 0) or 0)
                    tok_out_gemini = int(getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
            except Exception:
                pass
            tokens_in_branch  = tok_in_gemini
            tokens_out_branch = tok_out_gemini
        except Exception as e:
            return False, 0, False, f"Falha Gemini: {str(e)[:200]}", 0, 0

    # ── BRANCH OLLAMA / vLLM / LM Studio local ──
    elif eh_local_p:
        if not _requests_micro:
            return False, 0, False, "requests ausente", 0, 0
        base = (base_url or "http://localhost:11434").rstrip("/")
        if base.endswith("/v1"): base = base[:-3]
        if base.endswith("/api"): base = base[:-4]
        url = f"{base}/api/generate"
        modelo_ollama = modelo_str[7:] if modelo_str.lower().startswith("ollama/") else modelo_str
        payload = {
            "model":  modelo_ollama,
            "prompt": prompt_texto,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.0, "top_p": 1.0, "num_predict": 64},
        }
        try:
            r = _requests_micro.post(url, json=payload, timeout=timeout)
            if r.status_code != 200:
                return False, 0, False, f"HTTP {r.status_code}: {r.text[:200]}", 0, 0
            data = r.json()
            resposta_raw = (data.get("response", "") or "").strip()
            tokens_in_branch  = int(data.get("prompt_eval_count", 0) or 0)
            tokens_out_branch = int(data.get("eval_count", 0) or 0)
        except Exception as e:
            return False, 0, False, f"Falha Ollama: {str(e)[:200]}", 0, 0

    # ── BRANCH OpenAI-compatible (Anthropic, Groq, Alibaba, etc.) ──
    else:
        try:
            data_url = f"data:image/png;base64,{img_b64}"
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_texto},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }]
            ok2, dados, msg = enviar_completion_http(
                provedor=provedor, modelo_str=modelo_str, messages=messages,
                api_key=api_key, base_url=base_url,
                temperature=0.0, max_tokens=64, timeout=timeout,
            )
            if not ok2:
                return False, 0, False, f"HTTP falhou: {msg}", 0, 0
            resposta_raw = (dados.get("texto", "") or "").strip()
            tokens_in_branch  = int(dados.get("tokens_in",  0) or 0)
            tokens_out_branch = int(dados.get("tokens_out", 0) or 0)
        except Exception as e:
            return False, 0, False, f"Falha HTTP cloud: {str(e)[:200]}", 0, 0

    # ── Parse JSON da resposta ──
    if not resposta_raw:
        return False, 0, False, "resposta vazia", tokens_in_branch, tokens_out_branch

    import re as _re
    txt = resposta_raw.strip()
    if "```" in txt:
        m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", txt, flags=_re.DOTALL)
        if m: txt = m.group(1)
    m2 = _re.search(r"\{[^{}]*\}", txt, flags=_re.DOTALL)
    if m2: txt = m2.group(0)

    try:
        obj = json.loads(txt)
        frase_id = int(obj.get("frase_id", 0) or 0)
        marcado  = bool(obj.get("marcado", False))
        return True, frase_id, marcado, resposta_raw, tokens_in_branch, tokens_out_branch
    except Exception:
        m_id = _re.search(r'"?frase_id"?\s*:\s*(\d+)', resposta_raw)
        m_mk = _re.search(r'"?marcado"?\s*:\s*(true|false)', resposta_raw, flags=_re.IGNORECASE)
        if m_id:
            fid = int(m_id.group(1))
            mk = (m_mk.group(1).lower() == "true") if m_mk else False
            return True, fid, mk, resposta_raw, tokens_in_branch, tokens_out_branch
        return False, 0, False, f"JSON inválido: {resposta_raw[:120]}", tokens_in_branch, tokens_out_branch


def _aplicar_clahe_preprocessing(img_bgr, clip_limit=2.5, tile_size=8):
    """
    Aplica CLAHE (Contrast Limited Adaptive Histogram Equalization) à imagem
    para REVIVER marcações tênues a lápis que o CamScanner clareou.

    CLAHE é melhor que equalização global porque:
      • Trabalha em tiles locais (8×8 px) — não satura a página inteira
      • clipLimit=2.5 evita amplificar ruído / bleed-through
      • Marcações fracas voltam a ter contraste contra o fundo branco
      • Borda do checkbox e texto da frase ficam mais nítidos

    Retorna imagem BGR realçada (mesma dimensão da entrada).
    """
    if img_bgr is None or img_bgr.size == 0:
        return img_bgr
    try:
        # Trabalha no canal L do LAB (preserva cor, melhora contraste)
        lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
        l_canal, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=float(clip_limit),
                                tileGridSize=(int(tile_size), int(tile_size)))
        l_realcado = clahe.apply(l_canal)
        lab_realcado = cv2.merge((l_realcado, a, b))
        return cv2.cvtColor(lab_realcado, cv2.COLOR_LAB2BGR)
    except Exception:
        # Fallback: aplica em grayscale e devolve em BGR
        try:
            cinza = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=float(clip_limit),
                                    tileGridSize=(int(tile_size), int(tile_size)))
            realcado = clahe.apply(cinza)
            return cv2.cvtColor(realcado, cv2.COLOR_GRAY2BGR)
        except Exception:
            return img_bgr


def _anotar_quadrados_na_pagina(img_bgr, bboxes, ids_globais,
                                  cor_texto=(180, 60, 0),
                                  fonte_escala=0.85, fonte_espessura=2):
    """
    Anota cada bbox com seu número global [#N] em AZUL-MARINHO à esquerda do
    quadrado (sem cobrir o checkbox), para o LLM identificar cada quadrado
    pela numeração visual SEM confundir com a marcação.

    Estratégia anti-confusão:
      • NÃO desenha retângulo cobrindo o quadrado (preserva X intocado).
      • [#N] em azul-marinho (cor distinta de caneta preta/azul de marcação).
      • Posiciona à ESQUERDA do checkbox, no espaço da margem da página.
      • Fundo branco no texto para garantir contraste.

    Retorna a imagem ANOTADA (cópia, não muta a original).
    """
    img_out = img_bgr.copy()
    h_img, w_img = img_out.shape[:2]

    for (x, y, w, h), n_global in zip(bboxes, ids_globais):
        label = f"[#{n_global}]"
        # Calcula tamanho do texto
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                       fonte_escala, fonte_espessura)
        # Posiciona à ESQUERDA do quadrado (na margem branca da página)
        x_texto = max(5, x - tw - 12)
        y_texto = max(th + 4, y + h // 2 + th // 2)
        # Fundo branco com pequena borda azul para destacar
        cv2.rectangle(img_out,
                      (x_texto - 3, y_texto - th - 5),
                      (x_texto + tw + 3, y_texto + 4),
                      (255, 255, 255), -1)
        cv2.rectangle(img_out,
                      (x_texto - 3, y_texto - th - 5),
                      (x_texto + tw + 3, y_texto + 4),
                      cor_texto, 1)
        cv2.putText(img_out, label, (x_texto, y_texto),
                    cv2.FONT_HERSHEY_SIMPLEX, fonte_escala, cor_texto,
                    fonte_espessura, cv2.LINE_AA)
    return img_out


def _classificar_lote_batch_via_llm(provedor, modelo_str, api_key, base_url,
                                     imagens_anotadas_bgr, lista_frases_oficiais,
                                     qtd_quadrados_total, timeout=120):
    """
    LOTE ÚNICO — 1 chamada Gemini com as 4 páginas anotadas + gabarito.
    Output ULTRA-COMPACTO: lista CSV de frase_ids que foram MARCADAS.

    Exemplo de resposta esperada: "1,3,7,14,16,17,22,25,26,28"

    Retorna (sucesso, set_ids_marcados, resposta_raw, tokens_in, tokens_out).
    """
    import base64 as _b64

    if not imagens_anotadas_bgr:
        return False, set(), "Sem imagens", 0, 0

    # Codifica cada imagem em PNG base64
    imagens_b64 = []
    for img in imagens_anotadas_bgr:
        if img is None: continue
        ok, buf = cv2.imencode(".png", img)
        if not ok: continue
        imagens_b64.append(_b64.b64encode(buf.tobytes()).decode("utf-8"))

    if not imagens_b64:
        return False, set(), "Falha ao codificar imagens", 0, 0

    # Monta gabarito numerado
    linhas_gabarito = []
    for i, frase in enumerate(lista_frases_oficiais):
        linhas_gabarito.append(f"{i+1}. {frase}")
    gabarito_str = "\n".join(linhas_gabarito)
    n_frases = len(lista_frases_oficiais)

    prompt_texto = (
        "Você é um analisador de formulários escolares preenchidos a mão.\n"
        f"Estas {len(imagens_b64)} páginas mostram um formulário com vários quadrados (checkboxes) numerados [#N].\n"
        f"O total de quadrados detectados é {qtd_quadrados_total}.\n"
        "\n"
        "SUA TAREFA — identifique quais frases do GABARITO foram MARCADAS:\n"
        " • Um quadrado está MARCADO se há um X, traço, riscado ou preenchimento INTENCIONAL dentro dele.\n"
        " • Um quadrado está VAZIO se está limpo, só com borda, ou apenas com mancha do verso.\n"
        " • Falso positivo (dizer marcado sem haver traço) é PIOR que falso negativo. Na dúvida, NÃO inclua.\n"
        " • Quadrados [#N] que não correspondem a nenhuma frase do gabarito → ignore (não inclua).\n"
        "\n"
        f"GABARITO (1 a {n_frases}):\n"
        f"{gabarito_str}\n"
        "\n"
        "FORMATO DE RESPOSTA — responda APENAS uma lista CSV dos IDs do gabarito que foram MARCADOS.\n"
        "Sem texto explicativo, sem markdown, sem JSON. Apenas números separados por vírgula.\n"
        "Exemplo válido: 1,3,7,14,22,28\n"
        "Se nenhuma frase foi marcada, responda: 0\n"
        "\n"
        "Responda agora:"
    )

    prov_lower = (provedor or "").lower()
    modelo_lower = (modelo_str or "").lower()
    eh_gemini_p = ("gemini" in prov_lower) or modelo_lower.startswith("gemini/")
    eh_local_p  = (
        "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower
        or modelo_lower.startswith("ollama/")
    )

    resposta_raw = ""
    tok_in = 0
    tok_out = 0

    # ── BRANCH GEMINI nativo ──
    if eh_gemini_p:
        if not genai:
            return False, set(), "google-generativeai ausente", 0, 0
        modelo_config = modelo_str[len("gemini/"):] if modelo_str.startswith("gemini/") else modelo_str
        chave = None
        try:
            chave = get_next_valid_key() or api_key
        except Exception:
            chave = api_key
        if not chave:
            return False, set(), "sem chave Gemini disponível", 0, 0
        try:
            genai.configure(api_key=chave)
            modelo_obj = genai.GenerativeModel(
                model_name=modelo_config,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0, top_p=1.0, top_k=1, max_output_tokens=512,
                ),
            )
            partes = [prompt_texto]
            for b64 in imagens_b64:
                partes.append({"mime_type": "image/png", "data": _b64.b64decode(b64)})
            resp = modelo_obj.generate_content(partes, stream=False)
            try:
                resposta_raw = (resp.text or "").strip()
            except Exception:
                try:
                    cands = resp.candidates or []
                    if cands and cands[0].content and cands[0].content.parts:
                        resposta_raw = (cands[0].content.parts[0].text or "").strip()
                except Exception:
                    pass
            try:
                if hasattr(resp, "usage_metadata"):
                    tok_in  = int(getattr(resp.usage_metadata, "prompt_token_count", 0) or 0)
                    tok_out = int(getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
            except Exception:
                pass
        except Exception as e:
            return False, set(), f"Falha Gemini: {str(e)[:200]}", 0, 0

    # ── BRANCH OLLAMA local ──
    elif eh_local_p:
        if not _requests_micro:
            return False, set(), "requests ausente", 0, 0
        base = (base_url or "http://localhost:11434").rstrip("/")
        if base.endswith("/v1"): base = base[:-3]
        if base.endswith("/api"): base = base[:-4]
        url = f"{base}/api/generate"
        modelo_ollama = modelo_str[7:] if modelo_str.lower().startswith("ollama/") else modelo_str
        payload = {
            "model":  modelo_ollama,
            "prompt": prompt_texto,
            "images": imagens_b64,
            "stream": False,
            "options": {"temperature": 0.0, "top_p": 1.0, "num_predict": 256},
        }
        try:
            r = _requests_micro.post(url, json=payload, timeout=timeout)
            if r.status_code != 200:
                return False, set(), f"HTTP {r.status_code}: {r.text[:200]}", 0, 0
            data = r.json()
            resposta_raw = (data.get("response", "") or "").strip()
            tok_in  = int(data.get("prompt_eval_count", 0) or 0)
            tok_out = int(data.get("eval_count", 0) or 0)
        except Exception as e:
            return False, set(), f"Falha Ollama: {str(e)[:200]}", 0, 0

    # ── BRANCH OpenAI-compatible ──
    else:
        try:
            content = [{"type": "text", "text": prompt_texto}]
            for b64 in imagens_b64:
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"}})
            messages = [{"role": "user", "content": content}]
            ok2, dados, msg = enviar_completion_http(
                provedor=provedor, modelo_str=modelo_str, messages=messages,
                api_key=api_key, base_url=base_url,
                temperature=0.0, max_tokens=512, timeout=timeout,
            )
            if not ok2:
                return False, set(), f"HTTP falhou: {msg}", 0, 0
            resposta_raw = (dados.get("texto", "") or "").strip()
            tok_in  = int(dados.get("tokens_in", 0) or 0)
            tok_out = int(dados.get("tokens_out", 0) or 0)
        except Exception as e:
            return False, set(), f"Falha HTTP cloud: {str(e)[:200]}", 0, 0

    # ── Parse CSV da resposta ──
    if not resposta_raw:
        return False, set(), "resposta vazia", tok_in, tok_out

    import re as _re
    # Limpa markdown se vier
    txt = resposta_raw.strip()
    if "```" in txt:
        m = _re.search(r"```(?:csv|text)?\s*([\d,\s]+?)\s*```", txt, flags=_re.DOTALL)
        if m: txt = m.group(1)

    # Extrai todos os números inteiros da resposta
    numeros = _re.findall(r"\d+", txt)
    set_ids_marcados = set()
    for n in numeros:
        try:
            v = int(n)
            if 1 <= v <= n_frases:
                set_ids_marcados.add(v)
        except Exception:
            continue
    return True, set_ids_marcados, resposta_raw, tok_in, tok_out


def _classificar_pagina_individual_via_llm(provedor, modelo_str, api_key, base_url,
                                            imagem_anotada_bgr, lista_frases_oficiais,
                                            num_pag, ids_dessa_pagina, timeout=90):
    """
    Versão "uma página por vez" do batch — 1 chamada Gemini com 1 imagem só.
    O foco numa única página dá Gemini mais atenção e evita degradação multi-img.

    Retorna (sucesso, set_ids_marcados, resposta_raw, tok_in, tok_out).
    """
    import base64 as _b64

    if imagem_anotada_bgr is None or imagem_anotada_bgr.size == 0:
        return False, set(), "Sem imagem", 0, 0

    ok, buf = cv2.imencode(".png", imagem_anotada_bgr)
    if not ok:
        return False, set(), "Falha ao codificar PNG", 0, 0
    img_b64 = _b64.b64encode(buf.tobytes()).decode("utf-8")

    n_frases = len(lista_frases_oficiais)
    linhas_gabarito = []
    for i, frase in enumerate(lista_frases_oficiais):
        linhas_gabarito.append(f"{i+1}. {frase}")
    gabarito_str = "\n".join(linhas_gabarito)

    range_ids = f"[#{min(ids_dessa_pagina)}] a [#{max(ids_dessa_pagina)}]" if ids_dessa_pagina else "(nenhum)"

    prompt_texto = (
        "Você é um analisador de formulários escolares preenchidos a mão.\n"
        f"Esta é a PÁGINA {num_pag+1} de um formulário com checkboxes numerados {range_ids}.\n"
        "Cada quadrado tem ao lado um número entre colchetes em azul (ex: [#1], [#25]) — IGNORE essa numeração, é só minha referência visual.\n"
        "\n"
        "🎯 SUA TAREFA: identifique quais frases do GABARITO foram MARCADAS pelo aluno NESTA PÁGINA.\n"
        "\n"
        "⚠️ REGRA DE OURO — SEJA INCLUSIVO COM MARCAÇÕES:\n"
        " • INCLUA todo quadrado com QUALQUER traço, X, riscado, marca diagonal, preenchimento parcial, rabisco, ponto grosso ou borda preenchida dentro do quadrado.\n"
        " • MARCAÇÕES A LÁPIS PODEM ESTAR TÊNUES (o scan apagou contraste) — mesmo X fraco, X incompleto, X só com 1 traço, ou meio-X CONTAM como MARCADO.\n"
        " • Quadrado só é VAZIO se estiver TOTALMENTE limpo por dentro, igual a uma caixinha em branco recém-impressa.\n"
        " • Manchas claras vindas do verso da folha (bleed-through) NÃO são marcação — só conta se for traço/tinta DEFINIDA dentro do quadrado.\n"
        " • FALSO NEGATIVO (perder uma marcação real) é o ERRO MAIS GRAVE. Quando estiver na dúvida entre 'marcado' e 'vazio', PREFIRA marcado.\n"
        " • Quadrados [#N] sem frase legível ao lado (ruído de detecção) → simplesmente não inclua na resposta.\n"
        "\n"
        f"📋 GABARITO COMPLETO (frases 1 a {n_frases}):\n"
        f"{gabarito_str}\n"
        "\n"
        "📤 FORMATO DA RESPOSTA — APENAS lista CSV dos IDs do gabarito MARCADOS nesta página.\n"
        "Sem texto explicativo, sem JSON, sem markdown. Apenas números separados por vírgula.\n"
        "Exemplos válidos: 1,3,4,5,7,11,12,13\n"
        "Se realmente nenhuma frase foi marcada nesta página, responda: 0\n"
        "\n"
        "Examine COM CUIDADO cada quadrado da página e responda agora:"
    )

    prov_lower = (provedor or "").lower()
    modelo_lower = (modelo_str or "").lower()
    eh_gemini_p = ("gemini" in prov_lower) or modelo_lower.startswith("gemini/")
    eh_local_p  = (
        "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower
        or modelo_lower.startswith("ollama/")
    )

    resposta_raw = ""
    tok_in = 0
    tok_out = 0

    if eh_gemini_p:
        if not genai:
            return False, set(), "google-generativeai ausente", 0, 0
        modelo_config = modelo_str[len("gemini/"):] if modelo_str.startswith("gemini/") else modelo_str
        chave = None
        try:
            chave = get_next_valid_key() or api_key
        except Exception:
            chave = api_key
        if not chave:
            return False, set(), "sem chave Gemini disponível", 0, 0
        try:
            genai.configure(api_key=chave)
            modelo_obj = genai.GenerativeModel(
                model_name=modelo_config,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0, top_p=1.0, top_k=1, max_output_tokens=256,
                ),
            )
            partes = [prompt_texto, {"mime_type": "image/png", "data": _b64.b64decode(img_b64)}]
            resp = modelo_obj.generate_content(partes, stream=False)
            try:
                resposta_raw = (resp.text or "").strip()
            except Exception:
                try:
                    cands = resp.candidates or []
                    if cands and cands[0].content and cands[0].content.parts:
                        resposta_raw = (cands[0].content.parts[0].text or "").strip()
                except Exception:
                    pass
            try:
                if hasattr(resp, "usage_metadata"):
                    tok_in  = int(getattr(resp.usage_metadata, "prompt_token_count", 0) or 0)
                    tok_out = int(getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
            except Exception:
                pass
        except Exception as e:
            return False, set(), f"Falha Gemini: {str(e)[:200]}", 0, 0

    elif eh_local_p:
        if not _requests_micro:
            return False, set(), "requests ausente", 0, 0
        base = (base_url or "http://localhost:11434").rstrip("/")
        if base.endswith("/v1"): base = base[:-3]
        if base.endswith("/api"): base = base[:-4]
        url = f"{base}/api/generate"
        modelo_ollama = modelo_str[7:] if modelo_str.lower().startswith("ollama/") else modelo_str
        payload = {
            "model":  modelo_ollama,
            "prompt": prompt_texto,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.0, "top_p": 1.0, "num_predict": 128},
        }
        try:
            r = _requests_micro.post(url, json=payload, timeout=timeout)
            if r.status_code != 200:
                return False, set(), f"HTTP {r.status_code}: {r.text[:200]}", 0, 0
            data = r.json()
            resposta_raw = (data.get("response", "") or "").strip()
            tok_in  = int(data.get("prompt_eval_count", 0) or 0)
            tok_out = int(data.get("eval_count", 0) or 0)
        except Exception as e:
            return False, set(), f"Falha Ollama: {str(e)[:200]}", 0, 0

    else:
        try:
            content = [
                {"type": "text", "text": prompt_texto},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ]
            messages = [{"role": "user", "content": content}]
            ok2, dados, msg = enviar_completion_http(
                provedor=provedor, modelo_str=modelo_str, messages=messages,
                api_key=api_key, base_url=base_url,
                temperature=0.0, max_tokens=256, timeout=timeout,
            )
            if not ok2:
                return False, set(), f"HTTP falhou: {msg}", 0, 0
            resposta_raw = (dados.get("texto", "") or "").strip()
            tok_in  = int(dados.get("tokens_in", 0) or 0)
            tok_out = int(dados.get("tokens_out", 0) or 0)
        except Exception as e:
            return False, set(), f"Falha HTTP cloud: {str(e)[:200]}", 0, 0

    if not resposta_raw:
        return False, set(), "resposta vazia", tok_in, tok_out

    import re as _re
    txt = resposta_raw.strip()
    if "```" in txt:
        m = _re.search(r"```(?:csv|text)?\s*([\d,\s]+?)\s*```", txt, flags=_re.DOTALL)
        if m: txt = m.group(1)
    numeros = _re.findall(r"\d+", txt)
    set_ids = set()
    for n in numeros:
        try:
            v = int(n)
            if 1 <= v <= n_frases:
                set_ids.add(v)
        except Exception:
            continue
    return True, set_ids, resposta_raw, tok_in, tok_out


def _calcular_stddev_faixa_direita(img_gs, x, y, w, h, largura_faixa=250):
    """
    Mede o desvio padrão da faixa horizontal à direita do checkbox.

    Bleed-through (texto fantasma do verso da folha): stddev BAIXO (cinza uniforme).
    Frase real (texto preto sobre fundo branco): stddev ALTO (alta variação).

    Threshold empírico: stddev < 20 → bleed-through (descartar).
                        stddev > 50 → frase real (manter).
    """
    if img_gs is None or img_gs.size == 0:
        return 0.0
    h_img, w_img = img_gs.shape[:2]
    x1 = min(w_img, x + w + 10)
    x2 = min(w_img, x1 + largura_faixa)
    y1 = max(0, y - 3)
    y2 = min(h_img, y + h + 3)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    faixa = img_gs[y1:y2, x1:x2]
    if faixa.size == 0:
        return 0.0
    return float(faixa.std())


def _filtrar_candidatos_cirurgico(candidatos, paginas_gs,
                                   limiar_stddev=20.0, limiar_score=0.675):
    """
    FILTRO DUPLO CIRÚRGICO — elimina falsos positivos do template matching.

    candidatos: lista de (pag, x, y, w, h, score)
    paginas_gs: dict {pag: imagem_grayscale}

    Aplica 2 filtros:
      (A) stddev >= limiar_stddev → descarta bleed-through fantasma
      (B) score  >= limiar_score  → descarta títulos e ruído com baixa similaridade

    Retorna lista filtrada de (pag, x, y, w, h, score, stddev).
    """
    sobreviventes = []
    for (pag, x, y, w, h, sc) in candidatos:
        img_gs = paginas_gs.get(pag)
        if img_gs is None:
            continue
        std = _calcular_stddev_faixa_direita(img_gs, x, y, w, h)
        if std < limiar_stddev:
            continue
        if sc < limiar_score:
            continue
        sobreviventes.append((pag, x, y, w, h, sc, std))
    return sobreviventes


def _montar_grid_micro(candidatos_filtrados, paginas_bgr_clahe,
                        cols=3, rows=16, slot_w=500, slot_h=140,
                        gap=6, cor_label=(180, 60, 0)):
    """
    Monta uma imagem GRID com todos os micro-recortes numerados [#1] a [#N].
    Cada slot mostra: [#N] em azul + recorte (checkbox + parte da frase ao lado).

    Layout 3×16 (48 slots) cabe perfeitamente 46 candidatos.

    Retorna (imagem_grid_bgr, ids_globais).
    """
    grid_w = cols * slot_w + (cols + 1) * gap
    grid_h = rows * slot_h + (rows + 1) * gap
    grid = np.ones((grid_h, grid_w, 3), dtype=np.uint8) * 255

    ids_globais = []
    for i, cand in enumerate(candidatos_filtrados):
        pag, x, y, w, h = cand[0], cand[1], cand[2], cand[3], cand[4]
        n = i + 1
        ids_globais.append(n)
        row = i // cols
        col = i % cols
        if row >= rows:
            break  # estoura grid

        x_slot = gap + col * (slot_w + gap)
        y_slot = gap + row * (slot_h + gap)

        # Borda fina do slot
        cv2.rectangle(grid, (x_slot, y_slot),
                      (x_slot + slot_w, y_slot + slot_h),
                      (200, 200, 200), 1)

        # Label [#N] em azul-marinho
        label = f"[#{n}]"
        cv2.putText(grid, label, (x_slot + 5, y_slot + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, cor_label, 2, cv2.LINE_AA)

        # Recorte: checkbox + ~320 px à direita (parte da frase)
        img_pag = paginas_bgr_clahe.get(pag)
        if img_pag is None:
            continue
        h_pag, w_pag = img_pag.shape[:2]
        x1 = max(0, x - 5)
        y1 = max(0, y - 5)
        x2 = min(w_pag, x + 320)
        y2 = min(h_pag, y + h + 5)
        rec = img_pag[y1:y2, x1:x2]
        if rec.size == 0:
            continue
        rh, rw = rec.shape[:2]
        util_w = slot_w - 10
        util_h = slot_h - 40
        scale = min(util_w / rw, util_h / rh)
        new_w, new_h = int(rw * scale), int(rh * scale)
        if new_w < 10 or new_h < 10:
            continue
        rec_r = cv2.resize(rec, (new_w, new_h), interpolation=cv2.INTER_AREA)

        x_rec = x_slot + (slot_w - new_w) // 2
        y_rec = y_slot + 30 + (util_h - new_h) // 2
        try:
            grid[y_rec:y_rec + new_h, x_rec:x_rec + new_w] = rec_r
        except Exception:
            pass

    return grid, ids_globais


def _classificar_grid_via_llm_binario(provedor, modelo_str, api_key, base_url,
                                        imagem_grid_bgr, qtd_slots, timeout=120):
    """
    GRID-MINIMAL — 1 chamada Gemini com a imagem grid completa.
    Output ULTRA-COMPACTO: sequência de qtd_slots caracteres (M ou V), em ordem.

    Exemplo de resposta esperada (46 slots): "MVMMVMMVMVMVMMMVMVMVVMVVMVMMMMMMMVMVMVMVMMMVMM"

    Retorna (sucesso, lista_bool_marcados, resposta_raw, tok_in, tok_out).
    """
    import base64 as _b64

    if imagem_grid_bgr is None or imagem_grid_bgr.size == 0:
        return False, [], "Imagem do grid vazia", 0, 0

    ok_e, buf = cv2.imencode(".png", imagem_grid_bgr)
    if not ok_e:
        return False, [], "Falha ao codificar PNG", 0, 0
    img_b64 = _b64.b64encode(buf.tobytes()).decode("utf-8")

    prompt_texto = (
        "Você é um analisador binário de formulários escolares preenchidos a mão.\n"
        f"Esta imagem é um GRID com {qtd_slots} slots numerados [#1] a [#{qtd_slots}].\n"
        "Cada slot contém UM quadrado (checkbox) à esquerda e parte de uma frase à direita.\n"
        "\n"
        "🎯 SUA ÚNICA TAREFA — para cada slot [#N], decida se o QUADRADO está MARCADO ou VAZIO:\n"
        " • MARCADO = há X, traço, riscado, preenchimento, rabisco INTENCIONAL dentro do quadrado.\n"
        " • VAZIO = quadrado completamente limpo por dentro, igual a uma caixinha em branco.\n"
        " • Marcações a lápis podem estar TÊNUES — mesmo X fraco, traço incompleto, meio-X CONTAM como MARCADO.\n"
        " • Manchas claras vindas do verso da folha NÃO contam — só conta traço dentro do quadrado.\n"
        " • IGNORE o texto da frase ao lado — só importa o estado do quadrado.\n"
        " • IGNORE a numeração [#N] em azul — é só referência minha.\n"
        "\n"
        f"📤 FORMATO DA RESPOSTA — sequência de EXATAMENTE {qtd_slots} caracteres em ordem.\n"
        " • Caractere 'M' para MARCADO, 'V' para VAZIO.\n"
        " • Sem espaços, sem vírgulas, sem números, sem JSON, sem markdown, sem explicação.\n"
        f"Exemplo (formato): MVMMVMMVMVMVMMM... (total {qtd_slots} letras)\n"
        "\n"
        f"Examine cuidadosamente cada slot [#1] a [#{qtd_slots}] na ordem e responda agora:"
    )

    prov_lower = (provedor or "").lower()
    modelo_lower = (modelo_str or "").lower()
    eh_gemini_p = ("gemini" in prov_lower) or modelo_lower.startswith("gemini/")
    eh_local_p  = (
        "custom" in prov_lower or "local" in prov_lower or "ollama" in prov_lower
        or modelo_lower.startswith("ollama/")
    )

    resposta_raw = ""
    tok_in = 0
    tok_out = 0

    if eh_gemini_p:
        if not genai:
            return False, [], "google-generativeai ausente", 0, 0
        modelo_config = modelo_str[len("gemini/"):] if modelo_str.startswith("gemini/") else modelo_str
        chave = None
        try:
            chave = get_next_valid_key() or api_key
        except Exception:
            chave = api_key
        if not chave:
            return False, [], "sem chave Gemini", 0, 0
        try:
            genai.configure(api_key=chave)
            modelo_obj = genai.GenerativeModel(
                model_name=modelo_config,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0, top_p=1.0, top_k=1,
                    max_output_tokens=max(128, qtd_slots * 2),
                ),
            )
            partes = [prompt_texto, {"mime_type": "image/png", "data": _b64.b64decode(img_b64)}]
            resp = modelo_obj.generate_content(partes, stream=False)
            try:
                resposta_raw = (resp.text or "").strip()
            except Exception:
                try:
                    cands = resp.candidates or []
                    if cands and cands[0].content and cands[0].content.parts:
                        resposta_raw = (cands[0].content.parts[0].text or "").strip()
                except Exception:
                    pass
            try:
                if hasattr(resp, "usage_metadata"):
                    tok_in  = int(getattr(resp.usage_metadata, "prompt_token_count", 0) or 0)
                    tok_out = int(getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
            except Exception:
                pass
        except Exception as e:
            return False, [], f"Falha Gemini: {str(e)[:200]}", 0, 0

    elif eh_local_p:
        if not _requests_micro:
            return False, [], "requests ausente", 0, 0
        base = (base_url or "http://localhost:11434").rstrip("/")
        if base.endswith("/v1"): base = base[:-3]
        if base.endswith("/api"): base = base[:-4]
        url = f"{base}/api/generate"
        modelo_ollama = modelo_str[7:] if modelo_str.lower().startswith("ollama/") else modelo_str
        payload = {
            "model":  modelo_ollama,
            "prompt": prompt_texto,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": max(128, qtd_slots * 2)},
        }
        try:
            r = _requests_micro.post(url, json=payload, timeout=timeout)
            if r.status_code != 200:
                return False, [], f"HTTP {r.status_code}: {r.text[:200]}", 0, 0
            data = r.json()
            resposta_raw = (data.get("response", "") or "").strip()
            tok_in  = int(data.get("prompt_eval_count", 0) or 0)
            tok_out = int(data.get("eval_count", 0) or 0)
        except Exception as e:
            return False, [], f"Falha Ollama: {str(e)[:200]}", 0, 0

    else:
        try:
            content = [
                {"type": "text", "text": prompt_texto},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ]
            messages = [{"role": "user", "content": content}]
            ok2, dados, msg = enviar_completion_http(
                provedor=provedor, modelo_str=modelo_str, messages=messages,
                api_key=api_key, base_url=base_url,
                temperature=0.0, max_tokens=max(128, qtd_slots * 2), timeout=timeout,
            )
            if not ok2:
                return False, [], f"HTTP falhou: {msg}", 0, 0
            resposta_raw = (dados.get("texto", "") or "").strip()
            tok_in  = int(dados.get("tokens_in", 0) or 0)
            tok_out = int(dados.get("tokens_out", 0) or 0)
        except Exception as e:
            return False, [], f"Falha HTTP cloud: {str(e)[:200]}", 0, 0

    if not resposta_raw:
        return False, [], "resposta vazia", tok_in, tok_out

    # ── Parse: extrai SOMENTE M e V da resposta, em ordem ──
    import re as _re
    txt = resposta_raw.upper()
    txt = _re.sub(r"[^MV]", "", txt)  # remove tudo que não é M ou V

    lista_bool = []
    for c in txt[:qtd_slots]:
        lista_bool.append(c == "M")

    # Se a resposta veio incompleta, preenche o resto com False
    while len(lista_bool) < qtd_slots:
        lista_bool.append(False)

    return True, lista_bool, resposta_raw, tok_in, tok_out


def _analisar_micro_vision_crop(caminho_pdf, provedor_ativo, modelo_str, api_key, base_url, tempo_inicio, molde_nome=None, estrategia_origem="modo2_microvision"):
    """
    ════════════════════════════════════════════════════════════════════════════
    ESTEIRA OTIMIZADA PARA OLLAMA / vLLM / LM STUDIO — com FALLBACK PURO-VISÃO
    ════════════════════════════════════════════════════════════════════════════
    Modo A (PRIMÁRIO): PDF com camada de texto
      • pdfplumber extrai linhas+coords
      • Fuzzy-match frase oficial → coord (x,y)
      • Recorta checkbox à esquerda da frase
      • Envia micro-imagem ao Ollama

    Modo B (FALLBACK): PDF escaneado / só imagem
      • OpenCV detecta TODOS os quadrados via contornos (sem OCR)
      • Ordena top-down, left-right
      • Mapeia N-ésimo checkbox detectado → N-ésima frase do molde fidedigno
        (ordem das 49 frases é FIXA no _carregar_mapeamento_fidedigno)
      • Envia micro-imagem ao Ollama

    Ambos os modos: payload por inferência ~1-2 KB · custo R$ 0 · saída binária.
    """
    provedor = provedor_ativo.get("provedor", "") or "custom/local"

    if not VISAO_ATIVA:
        return {"erro": "PyMuPDF/OpenCV não instalados. Rode: pip install pymupdf opencv-python"}
    if not _requests_micro:
        return {"erro": "Biblioteca 'requests' ausente. Rode: pip install requests"}

    # GABARITO DINÂMICO via molde — também devolve coordenadas se disponíveis
    mapeamento_fidedigno, _gab_lista, coords_do_molde = _carregar_mapeamento_do_molde(molde_nome)
    lista_oficial_plana = [frase for sublist in mapeamento_fidedigno.values() for frase in sublist]
    qtd_frases_gabarito = len(lista_oficial_plana)

    # TEMPLATE DE LAYOUT — controla crop horizontal por tipo de formulário.
    # Fallback BLINDADO: molde sem template → 'hibrido_sem_corte' (full-width).
    template_cfg = _carregar_template_cfg_do_molde(molde_nome)
    try:
        st.caption(
            f"🧩 Template de layout: **{template_cfg.get('layout', 'hibrido_sem_corte')}** "
            f"(id={template_cfg.get('margem_id_px', MODO2_TEMPLATE_MARGEM_ID_PX)}px · "
            f"marca={template_cfg.get('margem_marca_px', MODO2_TEMPLATE_MARGEM_MARCA_PX)}px)"
        )
    except Exception:
        pass

    # K por estratégia — BLINDAGEM crítica do Modo 1 Turbo (Gemini):
    # • modo1_turbo → K=5 (calibrado 100% no Gemini cloud, não tocar)
    # • modo2_microvision → K=1 (Llama 11B homogeneíza fatias com K>=2)
    # Qualquer outra estratégia → K=5 (default histórico)
    _k_fatias_efetivo = MODO2_K_FATIAS_LOCAL if estrategia_origem == "modo2_microvision" else MODO2_K_FATIAS_TURBO
    try:
        st.caption(
            f"🍰 K (checkboxes por fatia): **{_k_fatias_efetivo}** "
            f"({'1 decisão atômica — Llama-friendly' if _k_fatias_efetivo == 1 else 'modo agrupado'})"
        )
    except Exception:
        pass

    id_sessao = int(time.time())
    # PASTA SESSÃO — agora dentro de moldes/ (mais previsível que CWD do Streamlit)
    # e usando path absoluto para evitar surpresas de CWD diferente.
    pasta_sessao_rel = os.path.join("moldes", f"temp_microcrops_{id_sessao}")
    pasta_sessao    = os.path.abspath(pasta_sessao_rel)
    try:
        os.makedirs(pasta_sessao, exist_ok=True)
    except Exception as _e_mkdir:
        st.error(f"❌ Falha ao criar pasta de debug: {pasta_sessao} · erro: {_e_mkdir}")

    # Diagnóstico de gravação: testa escrita ANTES do loop
    _debug_pasta_ok = False
    if MODO2_DEBUG_FATIAS:
        _teste_path = os.path.join(pasta_sessao, "_teste_escrita.txt")
        try:
            with open(_teste_path, "w", encoding="utf-8") as _ft:
                _ft.write(f"OK · {time.strftime('%Y-%m-%d %H:%M:%S')}")
            _debug_pasta_ok = os.path.exists(_teste_path)
            st.caption(
                f"🔍 **DEBUG ATIVO** · pasta de fatias: `{pasta_sessao}` · "
                f"escrita testada: {'✅ OK' if _debug_pasta_ok else '❌ FALHOU'}"
            )
        except Exception as _e_test:
            st.error(f"❌ Não consegui escrever em `{pasta_sessao}`: {_e_test}")
            _debug_pasta_ok = False

    # ── Inicialização de contadores compartilhados (Modo A e Modo B) ──
    tokens_total_in   = 0
    tokens_total_out  = 0
    qtd_inferidas     = 0
    qtd_achadas       = 0   # usado no Modo A (frases localizadas via pdfplumber)
    falhas_inferencia = 0
    _pngs_gravados    = 0   # contador para confirmar gravação no fim
    _pngs_falhados    = 0

    # Label do modo, baseado na origem
    _label_modo_ui = {
        "modo1_turbo":       "🚀 **Modo 1 TURBO - EXP** (v7 Gemini cloud)",
        "modo2_microvision": "🅱️ **Modo 2 v7** (esteira para LLMs locais)",
    }.get(estrategia_origem, "🔬 **Esteira Micro-Vision Crop** (v7)")
    st.write(f"{_label_modo_ui} ativada.")
    st.caption(f"📍 Provedor: `{provedor}` · Modelo: `{modelo_str}` · Endpoint: `{base_url or 'http://localhost:11434'}`")

    # Telemetria do prompt-PAI (mostra se foi injetado em cada fatia)
    try:
        _pai_texto = get_prompt_reforco(modelo_str, estrategia=estrategia_origem) or ""
        if _pai_texto:
            st.caption(
                f"🎯 **Prompt-PAI ATIVO**: {len(_pai_texto)} caracteres "
                f"injetados em CADA fatia como diretiva suprema."
            )
        else:
            st.caption(
                "ℹ️ Prompt-PAI vazio para este provedor — fatias usarão apenas o prompt da tarefa. "
                "Considere cadastrar um Prompt-PAI no Painel 1 LiteLLM para melhor calibragem."
            )
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────
    # BYPASS DO MODO A — quando há molde OU estratégia forçada
    # ─────────────────────────────────────────────────────────────
    # Regra: se temos coords do molde (treinado pelo usuário) OU a estratégia
    # foi forçada para "modo2_microvision" no Painel 1, NÃO tentamos o Modo A
    # via pdfplumber. Vamos direto pro Modo B v7 — fatias adaptativas guiadas
    # pelo molde. Isso elimina o risco de 46 chamadas individuais ao LLM.
    try:
        estrategia_forcada = (get_estrategia_ocr(modelo_str, default="auto") == "modo2_microvision")
    except Exception:
        estrategia_forcada = False
    bypass_modo_a = bool(coords_do_molde) or estrategia_forcada

    modo_ativo = None
    cache_paginas = {}    # estrutura {npag: (img_cv, ex, ey)} no modo A; {npag: img_cv} no modo B
    plano_inferencias = []  # lista de tuplas (frase, recorte_amplo) pronta para o loop

    if bypass_modo_a:
        st.info(
            "⚡ **Bypass Modo A ativado** — molde presente ou estratégia forçada. "
            "Pulando pdfplumber, indo direto para Modo B v7 (fatias guiadas pelo molde)."
        )
        linhas_pdf = []
    elif PDFPLUMBER_ATIVO:
        st.write("📄 Tentando extrair linhas com posição (pdfplumber)...")
        linhas_pdf = _extrair_linhas_com_posicao(caminho_pdf)
    else:
        linhas_pdf = []
        st.caption("⚠️ pdfplumber não instalado — pulando direto para detecção pura.")

    if linhas_pdf:
        st.caption(f"✅ {len(linhas_pdf)} linhas de texto localizadas no PDF.")
        st.write("🎯 Cruzando gabarito oficial com posições reais (fuzzy match)...")
        frases_localizadas = _localizar_frases_oficiais(linhas_pdf, lista_oficial_plana, limiar=0.72)
        qtd_achadas_modoA = sum(1 for f in frases_localizadas if f[1] is not None)

        # Critério para usar Modo A: pelo menos 30% das frases localizadas
        if qtd_achadas_modoA >= max(3, int(qtd_frases_gabarito * 0.30)):
            modo_ativo = "A_pdfplumber"
            st.success(f"🅰️ **MODO A ativado**: {qtd_achadas_modoA}/{qtd_frases_gabarito} frases localizadas via OCR coordenado (pdfplumber).")

            # Rasteriza páginas necessárias
            paginas_unicas = sorted({f[1] for f in frases_localizadas if f[1] is not None})
            for npag in paginas_unicas:
                try:
                    img_cv, ex, ey, _, _ = _renderizar_pagina_para_cv(caminho_pdf, num_pagina=npag, dpi=200)
                    cache_paginas[npag] = (img_cv, ex, ey)
                except Exception as e:
                    st.warning(f"⚠️ Falha ao rasterizar página {npag}: {e}")

            # Monta plano: (frase, recorte_amplo) por ordem do gabarito
            for (frase, npag, x0, top, x1, bot, score) in frases_localizadas:
                if npag is None or npag not in cache_paginas:
                    plano_inferencias.append((frase, None, score, "nao_localizada"))
                    continue
                img_cv, ex, ey = cache_paginas[npag]
                recorte_amplo, _bbox = _recortar_checkbox_da_linha(img_cv, x0, top, bot, ex, ey)
                plano_inferencias.append((frase, recorte_amplo, score, "modoA"))
        else:
            st.warning(f"⚠️ Modo A com baixa cobertura ({qtd_achadas_modoA}/{qtd_frases_gabarito}) — pulando para Modo B (detecção pura).")

    # ─────────────────────────────────────────────────────────────
    # MODO B (FALLBACK): detecção pura por contornos OpenCV
    # ─────────────────────────────────────────────────────────────
    if modo_ativo is None:
        # ═══════════════════════════════════════════════════════════════════════
        # MODO B v7 — FATIAS ADAPTATIVAS GUIADAS PELO MOLDE
        # ═══════════════════════════════════════════════════════════════════════
        # Estratégia:
        #   1. Para cada PÁGINA, agrupa checkboxes do molde em blocos de K=5
        #   2. Calcula envelope (x=0, y=min(y)-margem, w=pag_w, h=...) com
        #      anti-corte (expande se borda atravessar checkbox)
        #   3. Crop horizontal + CLAHE + anotação [#frase_id] na margem
        #   4. 1 chamada LLM por fatia → CSV "ID:M,ID:V,..."
        #   5. Parse → estado_final_frases[frase] = True/False
        #
        # Para 46 checkboxes com K=5: ~10 chamadas, contexto natural preservado,
        # zero alucinação (LLM vê só K checkboxes por vez com frase ao lado).
        if not coords_do_molde:
            return {
                "erro": (
                    "❌ Modo 2 exige um molde treinado (com coordenadas dos checkboxes). "
                    "Vá em Treinamento de Molde, crie/edite o molde da sua prova, e tente novamente."
                )
            }

        st.success(
            f"🅱️ **MODO B v7 — Fatias Adaptativas** ({len(coords_do_molde)} quadrados do molde · K={_k_fatias_efetivo})"
        )

        # ── 1. Rasteriza páginas ──
        doc_temp = fitz.open(caminho_pdf)
        num_paginas = len(doc_temp)
        doc_temp.close()

        # ── 1a. ALTA NITIDEZ: rasteriza em DPI maior + escala coords/margens ──
        # Fator dinâmico: ex. render 400 / molde 200 = 2.0 → tudo dobra.
        _fator_render = float(MODO2_RENDER_DPI) / float(MODO2_MOLDE_DPI)
        try:
            st.caption(
                f"🎨 Renderização em **DPI {MODO2_RENDER_DPI}** "
                f"(escala {_fator_render:.1f}× sobre molde DPI {MODO2_MOLDE_DPI}) — "
                f"checkbox chega ao LLM em alta nitidez nativa, sem upscale interpolado."
            )
        except Exception:
            pass

        cache_paginas_bgr = {}
        for npag in range(num_paginas):
            try:
                img_cv, _ex, _ey, _, _ = _renderizar_pagina_para_cv(
                    caminho_pdf, num_pagina=npag, dpi=MODO2_RENDER_DPI
                )
                cache_paginas_bgr[npag] = img_cv
            except Exception as e:
                st.warning(f"⚠️ Falha ao rasterizar pag {npag}: {e}")

        # ── 2. Agrupa coords do molde POR PÁGINA (já ESCALADAS ao DPI de render) ──
        coords_por_pag = {}
        for q in coords_do_molde:
            q_esc = {
                "pag":      q["pag"],
                "x":        int(round(q["x"] * _fator_render)),
                "y":        int(round(q["y"] * _fator_render)),
                "w":        int(round(q["w"] * _fator_render)),
                "h":        int(round(q["h"] * _fator_render)),
                "id":       q.get("id", 0),
                "frase":    q.get("frase", ""),
                "frase_id": q.get("frase_id", 0),
                "secao":    q.get("secao", ""),
            }
            coords_por_pag.setdefault(q_esc["pag"], []).append(q_esc)
        # Garante ordem visual (y, x) dentro de cada página
        for npag in coords_por_pag:
            coords_por_pag[npag].sort(key=lambda c: (c["y"], c["x"]))

        # ── 2a. Escala dinâmica das margens (que estão calibradas em DPI 200) ──
        _margem_y_esc      = int(round(MODO2_MARGEM_Y_PX     * _fator_render))
        _margem_extra_esc  = int(round(MODO2_ANTI_CORTE_PX   * _fator_render))
        _template_cfg_esc  = dict(template_cfg or {})
        if _template_cfg_esc.get("layout") not in (None, "hibrido_sem_corte", "full", "full_width", ""):
            _template_cfg_esc["margem_id_px"] = int(round(
                _template_cfg_esc.get("margem_id_px", MODO2_TEMPLATE_MARGEM_ID_PX) * _fator_render
            ))
            _template_cfg_esc["margem_marca_px"] = int(round(
                _template_cfg_esc.get("margem_marca_px", MODO2_TEMPLATE_MARGEM_MARCA_PX) * _fator_render
            ))

        # ── 3. Inicializa estado + loop por página > bloco > fatia ──
        estado_final_frases = {f: False for f in lista_oficial_plana}
        qtd_marcadas    = 0
        qtd_fatias_tot  = 0
        log_acumulado   = []

        progress_placeholder = st.empty()

        for npag in sorted(coords_por_pag.keys()):
            if npag not in cache_paginas_bgr:
                st.warning(f"⚠️ Página {npag} sem imagem rasterizada — pulando.")
                continue

            img_pag    = cache_paginas_bgr[npag]
            pag_h, pag_w = img_pag.shape[:2]
            quads_pag  = coords_por_pag[npag]

            # Agrupa em blocos de K
            blocos = _agrupar_coords_em_blocos(quads_pag, k=_k_fatias_efetivo)
            qtd_fatias_tot += len(blocos)

            st.write(f"📄 **Página {npag+1}** — {len(quads_pag)} checkboxes em {len(blocos)} fatia(s)")

            for idx_bloco, bloco in enumerate(blocos):
                # Usa margens E template_cfg JÁ ESCALADOS para o DPI de render.
                # Sem isso, a anti-contração e o crop horizontal ficariam pequenos
                # demais em relação à página renderizada em alta resolução.
                envelope = _calcular_envelope_com_anticorte(
                    bloco, quads_pag, pag_h, pag_w,
                    margem_y=_margem_y_esc,
                    margem_extra=_margem_extra_esc,
                    template_cfg=_template_cfg_esc,
                )
                img_fatia, ids_globais, frases_fatia, dim_orig, dim_fin, dim_padding = _recortar_e_anotar_fatia(
                    img_pag, envelope, bloco,
                    usar_clahe=MODO2_USAR_CLAHE,
                    estrategia_origem=estrategia_origem,
                )

                if img_fatia is None:
                    st.warning(f"⚠️ Fatia pag{npag+1}-bloco{idx_bloco+1} vazia — pulando.")
                    falhas_inferencia += 1
                    continue

                # Debug: salva PNG da fatia anotada (já normalizada e com resize)
                if MODO2_DEBUG_FATIAS:
                    _png_path = os.path.join(
                        pasta_sessao,
                        f"fatia_pag{npag+1}_bloco{idx_bloco+1}.png"
                    )
                    try:
                        _ok_w = cv2.imwrite(
                            _png_path, img_fatia,
                            [cv2.IMWRITE_PNG_COMPRESSION, 6],
                        )
                        if _ok_w and os.path.exists(_png_path):
                            _pngs_gravados += 1
                        else:
                            _pngs_falhados += 1
                            st.warning(
                                f"⚠️ cv2.imwrite retornou False ou arquivo não existe: `{_png_path}`"
                            )
                    except Exception as _e_save:
                        _pngs_falhados += 1
                        st.warning(f"⚠️ Erro ao gravar PNG `{_png_path}`: {_e_save}")

                # Log de dimensões — diagnóstico crítico para Llama Vision
                # Mostra: dim_original → padding (se houve) → resize final
                partes = [f"{dim_orig[0]}×{dim_orig[1]}"]
                if dim_padding != dim_orig:
                    partes.append(f"padding {dim_padding[0]}×{dim_padding[1]}")
                if dim_fin != dim_padding:
                    partes.append(f"resize {dim_fin[0]}×{dim_fin[1]}")
                dim_label = " → ".join(partes)

                # Telemetria de economia (crop horizontal) — só exibe quando
                # o template realmente cortou: largura da fatia < largura da página.
                _ratio_largura = dim_orig[0] / max(1, pag_w)
                if _ratio_largura < 0.95:
                    _economia_pct = int(round((1.0 - _ratio_largura) * 100))
                    _eco_label = (
                        f" · ✂️ crop horizontal: {dim_orig[0]}/{pag_w}px "
                        f"= **{int(round(_ratio_largura*100))}%** da largura · "
                        f"economia ~{_economia_pct}%"
                    )
                else:
                    _eco_label = ""

                progress_placeholder.info(
                    f"📡 Enviando fatia {idx_bloco+1}/{len(blocos)} da página {npag+1} · "
                    f"{dim_label}{_eco_label} · IDs {ids_globais} ao LLM..."
                )

                ok, dict_id_bool, resp_raw, tin, tout = _classificar_fatia_via_llm(
                    provedor, modelo_str, api_key, base_url,
                    img_fatia, ids_globais, frases_fatia,
                    timeout=90,
                    estrategia_origem=estrategia_origem,
                )
                tokens_total_in  += tin
                tokens_total_out += tout
                qtd_inferidas    += 1

                log_acumulado.append({
                    "pag":     npag + 1,
                    "bloco":   idx_bloco + 1,
                    "ids":     ids_globais,
                    "ok":      ok,
                    "resposta": (resp_raw or "")[:500],
                    "resultado": dict_id_bool,
                })

                if not ok:
                    falhas_inferencia += 1
                    st.warning(f"⚠️ Fatia pag{npag+1}-bloco{idx_bloco+1}: parse falhou — `{(resp_raw or '')[:80]}`")
                    continue

                # Aplica resultado: para cada ID marcado, achar frase original via frase_id
                for frase_id, marcado_b in dict_id_bool.items():
                    if not marcado_b:
                        continue
                    # Acha a frase do quadrado com esse frase_id NESSE bloco
                    for q in bloco:
                        if (q.get("frase_id") or q.get("id")) == frase_id:
                            frase_oficial = q.get("frase", "") or ""
                            if frase_oficial and frase_oficial in estado_final_frases:
                                estado_final_frases[frase_oficial] = True
                                qtd_marcadas += 1
                            break

        progress_placeholder.empty()
        # modo_ativo identifica a esteira + origem na telemetria
        modo_ativo = f"B_v7_fatias_{estrategia_origem or 'modo2_microvision'}"

        # ── 4. UI: banner com resumo ──
        with st.container(border=True):
            st.markdown(f"##### 📊 Esteira Modo B v7 — fatias adaptativas")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📐 Origem", "Molde")
            c2.metric("🍰 Fatias", qtd_fatias_tot)
            c3.metric("🟥 Marcadas", qtd_marcadas)
            c4.metric("📡 Chamadas LLM", qtd_inferidas)
            st.caption(
                f"🔢 Tokens · IN={tokens_total_in:,} · OUT={tokens_total_out:,} · "
                f"K={_k_fatias_efetivo} · falhas={falhas_inferencia}"
            )

        # Log expandível com respostas brutas
        log_box = st.expander(f"🔍 Log das fatias — modo {modo_ativo}", expanded=False)
        for item in log_acumulado:
            status_emo = "✅" if item["ok"] else "❌"
            log_box.write(
                f"{status_emo} pag{item['pag']}-bloco{item['bloco']} · IDs {item['ids']}"
            )
            log_box.code(item["resposta"], language="text")


    # ─────────────────────────────────────────────────────────────
    # COMPILAÇÃO no formato MASTER esperado pelo app
    # ─────────────────────────────────────────────────────────────
    resultado_final = {cat: [] for cat in mapeamento_fidedigno.keys()}
    for categoria, perguntas in mapeamento_fidedigno.items():
        for frase in perguntas:
            marcado_final = estado_final_frases.get(frase, False)
            resultado_final[categoria].append({
                "pergunta": frase,
                "marcado":  marcado_final,
                "escala":   4 if marcado_final else 0,
            })

    tempo_gasto = round(time.time() - tempo_inicio, 2)
    qtd_marcadas = sum(1 for v in estado_final_frases.values() if v)
    st.success(
        f"✅ Micro-Vision ({modo_ativo}) concluído em {tempo_gasto}s · "
        f"{qtd_marcadas}/{qtd_frases_gabarito} marcadas · "
        f"{qtd_inferidas} inferências · {falhas_inferencia} falhas locais · custo R$ 0,00"
    )

    # ── Faxina automática + sidebar de info da sessão (RESTAURADO) ──
    # Em DEBUG_FATIAS=True, os PNGs são preservados pra inspeção visual.
    # Apenas o PDF temporário é apagado em background.
    def _faxina(pasta, pdf):
        try:
            if not MODO2_DEBUG_FATIAS:
                try:
                    if os.path.exists(pasta):
                        shutil.rmtree(pasta)
                except Exception:
                    pass
            try:
                if os.path.exists(pdf):
                    os.remove(pdf)
            except Exception:
                pass
        except Exception:
            pass

    try:
        with st.sidebar:
            st.markdown("---")
            st.subheader("🧹 Faxina Micro-Vision")
            st.info(f"Sessão local: **{id_sessao}** · modo {modo_ativo}")
            st.caption(f"💻 {qtd_inferidas} micro-crops processados.")
            st.caption("☁️ Nuvem: 0 (tudo rodou local).")
            if MODO2_DEBUG_FATIAS:
                st.warning(
                    f"🔍 **DEBUG ATIVO** — PNGs das fatias preservados em:\n\n"
                    f"`{os.path.abspath(pasta_sessao)}`"
                )
    except Exception:
        pass

    try:
        threading.Thread(
            target=_faxina,
            args=(pasta_sessao, caminho_pdf),
            daemon=True,
        ).start()
    except Exception:
        pass

    # ── Cálculo de custo REAL via tabela de preços do storage_litellm ──
    custo_brl = 0.0
    try:
        custos = get_custos_provedor(modelo_str) or {}
        dolar  = obter_dolar_persistido() or 5.25
        custo_usd = (
            (tokens_total_in  / 1_000_000.0) * float(custos.get("in_usd_1M",  0.0)) +
            (tokens_total_out / 1_000_000.0) * float(custos.get("out_usd_1M", 0.0))
        )
        custo_brl = round(custo_usd * dolar, 4)
    except Exception:
        custo_brl = 0.0

    try:
        st.info(f"💰 Custo desta execução: **R$ {custo_brl:.4f}**  (IN={tokens_total_in:,} · OUT={tokens_total_out:,} · dólar={dolar:.2f})")
    except Exception:
        pass

    try:
        registrar_consumo(
            f"{_compactar_modelo(modelo_str)} + {_label_modo(estrategia_origem)}",
            modelo_str,
            tokens_total_in + tokens_total_out,
            custo_brl,
            tempo_execucao=tempo_gasto,
            provedor=provedor,
            tokens_in=tokens_total_in,
            tokens_out=tokens_total_out,
            tokens_cache=0,
        )
    except Exception:
        pass

    return {
        "sucesso": True,
        "dados":   resultado_final,
        "telemetria": {
            "modelo":         modelo_str,
            "provedor":       provedor,
            "in":             tokens_total_in,
            "out":            tokens_total_out,
            "cache":          0,
            "brl":            custo_brl,
            "tempo_segundos": tempo_gasto,
            "estrategia":     f"micro_vision_crop_{modo_ativo}",
            "qtd_inferidas":  qtd_inferidas,
            "falhas_inferencia": falhas_inferencia,
        },
    }
