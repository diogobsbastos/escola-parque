"""
═══════════════════════════════════════════════════════════════════════════════
BACKEND_MOLDE.PY — Gerenciamento de moldes de provas
═══════════════════════════════════════════════════════════════════════════════
Camada de I/O para a Página de Treinamento de Molde.

Cada molde é um arquivo JSON em `moldes/<nome>.json` contendo:
  • coordenadas exatas dos 46 checkboxes (x, y, w, h por página)
  • mapeamento Q1..Q46 → frase do gabarito + seção
  • âncoras fiduciais (cabeçalhos de seção) para alinhar provas novas
  • metadados (nome, criação, qtd de quadrados, fonte_pdf)

Persistência (P0 — 2026-06-16):
  • Fonte primária: tabela `moldes` no PostgreSQL local (asyncpg via innova_bridge)
  • Fallback: disco local `moldes/` (mantido durante transição, nunca apagado auto.)
  • Migração automática one-shot: ao detectar BD vazio + disco com moldes,
    `migrar_disco_para_bd()` é chamada automaticamente por `listar_moldes()`.

Funções principais:
  listar_moldes()  → ["Prova_Padrao_v1", ...]
  carregar_molde(nome) → dict
  salvar_molde(nome, dados) → (bool, str, str)
  detectar_candidatos_para_molde(pdf_path) → {pag: [{x,y,w,h,score,stddev}, ...]}
  rasterizar_pagina(pdf_path, num_pag, dpi=200) → numpy BGR
  migrar_disco_para_bd() → {"importados": N, "erros": [...]}
═══════════════════════════════════════════════════════════════════════════════
"""
import os
import json
import time
from typing import Dict, List, Optional, Tuple

try:
    import fitz       # PyMuPDF
    import cv2
    import numpy as np
    VISAO_OK = True
except ImportError:
    VISAO_OK = False

# ── BD: asyncpg via innova_bridge ──────────────────────────────────────────
try:
    from innova_bridge.db.client import run_async, get_pool
    _BD_IMPORT_OK = True
except ImportError:
    _BD_IMPORT_OK = False


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════════════════════════
PASTA_MOLDES = "moldes"
TEMPLATE_DEFAULT = os.path.join("banco_contexto", "treino_visao", "referencia_branco.jpg")
DPI_PADRAO = 200

# Gabarito fidedigno (mesmo do backend_ocr.py)
GABARITO_OFICIAL = {
    "SEÇÃO 2 - LINGUAGEM E COMPREENSÃO": [
        "Tem dificuldade para entender enunciados longos",
        "Confunde o que a questão está pedindo",
        "Precisa reler várias vezes para compreender",
        "Tem dificuldade com linguagem indireta ou figurada",
        "Entende melhor quando o comando está destacado",
        "Se perde quando há múltiplas instruções na mesma questão",
        "Compreende melhor quando as instruções estão numeradas",
    ],
    "SEÇÃO 3 - ATENÇÃO E FUNÇÃO EXECUTIVA": [
        "Distrai-se facilmente com estímulos ao redor",
        "Começa a prova bem, mas perde foco ao longo do tempo",
        "Responde impulsivamente e erra por desatenção",
        "Tem dificuldade para organizar a resposta",
        "Se perde quando precisa seguir vários passos",
        "Apresenta melhora quando a tarefa é dividida em partes menores",
    ],
    "SEÇÃO 4 - MEMÓRIA E CARGA COGNITIVA": [
        "Demonstra dificuldade para manter várias informações na mente ao mesmo tempo",
        "Esquece parte das instruções ao longo da execução",
        "Tem desempenho melhor quando pode consultar novamente o enunciado",
    ],
    "SEÇÃO 5 - PRODUÇÃO ESCRITA E REGISTRO": [
        "Escreve lentamente",
        "Demonstra cansaço ao escrever por períodos mais longos",
        "Tem dificuldade na organização espacial da escrita",
        "Perde pontos por não conseguir registrar tudo a tempo",
        "Apresenta melhora quando há espaço delimitado para resposta",
    ],
    "SEÇÃO 6 - ORGANIZAÇÃO VISUAL E ESPACIAL": [
        "Se perde em tabelas ou gráficos densos",
        "Comete erros por desalinhamento (colunas, casas decimais etc.)",
        "Apresenta melhora quando usa quadriculado ou linhas-guia",
        "Demonstra dificuldade em organizar informações no espaço da folha",
    ],
    "SEÇÃO 7 - PROCESSAMENTO EM MATEMÁTICA / DISCIPLINAS DE EXATAS": [
        "Confunde sinais matemáticos (+, -, x, ÷)",
        "Troca a ordem de números em operações",
        "Demonstra dificuldade em organizar contas no papel",
        "Tem dificuldade em interpretar problemas matemáticos escritos",
        "Apresenta melhora quando a operação é visualmente organizada",
        "Comete erros por desorganização espacial, não por desconhecimento do conteúdo",
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
        "Outro (campo curto)",
    ],
    "SEÇÃO 9 - LIMITES IMPORTANTES": [
        "Simplificar o conteúdo",
        "Dar pistas ou respostas",
        "Alterar o objetivo da questão",
        "Infantilizar a linguagem",
        "Separar enunciado das alternativas",
    ],
}

LISTA_FRASES_GABARITO = [
    f for sub in GABARITO_OFICIAL.values() for f in sub
]
QTD_FRASES_GABARITO = len(LISTA_FRASES_GABARITO)   # 46

# Mapa frase → seção
SECAO_POR_FRASE = {}
for sec, frases in GABARITO_OFICIAL.items():
    for f in frases:
        SECAO_POR_FRASE[f] = sec

# ═══════════════════════════════════════════════════════════════════════════
# GABARITO DINÂMICO POR MOLDE (v2)
# ═══════════════════════════════════════════════════════════════════════════
# A constante GABARITO_OFICIAL acima é só o TEMPLATE PADRÃO.
# Cada molde pode ter seu próprio gabarito de frases (dinâmico).
# As helpers abaixo geram/manipulam essas listas.
# ═══════════════════════════════════════════════════════════════════════════

def gabarito_padrao_como_lista() -> List[Dict]:
    """Devolve o GABARITO_OFICIAL como lista de dicts {id, frase, secao}.
    Usado como ponto de partida quando o usuário aperta "Carregar padrão"."""
    lista = []
    i = 1
    for secao, frases in GABARITO_OFICIAL.items():
        for fr in frases:
            lista.append({"id": i, "frase": fr, "secao": secao})
            i += 1
    return lista


def normalizar_gabarito_frases(gabarito) -> List[Dict]:
    """Recebe lista de strings OU lista de dicts e devolve sempre lista de dicts
    {id, frase, secao}. IDs são renumerados sequencialmente (1, 2, 3...)."""
    if not gabarito:
        return []
    saida = []
    for i, item in enumerate(gabarito, start=1):
        if isinstance(item, dict):
            saida.append({
                "id":    i,
                "frase": str(item.get("frase", "")).strip(),
                "secao": str(item.get("secao", "")).strip(),
            })
        else:
            saida.append({"id": i, "frase": str(item).strip(), "secao": ""})
    return saida


def parse_gabarito_arquivo(conteudo_bytes: bytes, nome_arquivo: str):
    """Faz parse de um arquivo enviado pelo usuário (.json / .csv / .txt / .md)
    e devolve uma lista de dicts {id, frase, secao} pronta para o session_state.

    Aceita:
      JSON:   lista de strings  →  [{id, frase, secao=""}]
              lista de dicts    →  copia frase/secao quando existirem
              dict bruto        →  {seção: [frases...]} no mesmo formato do GABARITO_OFICIAL
      CSV:    cabeçalho com colunas Frase, Secao (case-insensitive); ou
              sem cabeçalho com 1 ou 2 colunas (frase | frase,secao)
      TXT/MD: uma frase por linha (linhas vazias ignoradas)

    Retorna tupla:
        (ok: bool, lista_frases_dict: List[Dict], mensagem: str)
    """
    if not conteudo_bytes:
        return False, [], "Arquivo vazio."
    try:
        texto = conteudo_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            texto = conteudo_bytes.decode("latin-1")
        except Exception as e:
            return False, [], f"Não consegui decodificar o arquivo: {e}"

    nome_lower = (nome_arquivo or "").lower()

    # ── JSON ──
    if nome_lower.endswith(".json"):
        try:
            obj = json.loads(texto)
        except Exception as e:
            return False, [], f"JSON inválido: {e}"

        if isinstance(obj, list):
            lista = normalizar_gabarito_frases(obj)
            return True, lista, f"{len(lista)} frase(s) carregada(s) do JSON."

        if isinstance(obj, dict):
            # Formato {seção: [frases]} OU {gabarito_frases: [...]}
            if "gabarito_frases" in obj and isinstance(obj["gabarito_frases"], list):
                lista = normalizar_gabarito_frases(obj["gabarito_frases"])
                return True, lista, f"{len(lista)} frase(s) carregada(s) (chave gabarito_frases)."
            # Tenta interpretar como {seção: [frases]}
            saida = []
            i = 1
            for sec, frases in obj.items():
                if isinstance(frases, list):
                    for fr in frases:
                        saida.append({"id": i, "frase": str(fr).strip(), "secao": str(sec).strip()})
                        i += 1
            if saida:
                return True, saida, f"{len(saida)} frase(s) carregada(s) (estrutura por seção)."
            return False, [], "JSON com estrutura desconhecida (esperado lista ou dict de seções)."

        return False, [], "JSON com tipo raiz não suportado (use lista ou dicionário)."

    # ── CSV ──
    if nome_lower.endswith(".csv"):
        import csv as _csv
        from io import StringIO as _SIO
        try:
            buffer = _SIO(texto)
            # Detecta delimitador (auto). Se falhar, usa vírgula.
            try:
                amostra = texto[:2048]
                dialect = _csv.Sniffer().sniff(amostra, delimiters=",;\t|")
                buffer.seek(0)
                reader = _csv.reader(buffer, dialect)
            except Exception:
                buffer.seek(0)
                reader = _csv.reader(buffer)
            linhas = [r for r in reader if any((c or "").strip() for c in r)]
        except Exception as e:
            return False, [], f"Erro lendo CSV: {e}"
        if not linhas:
            return False, [], "CSV sem conteúdo útil."

        cabecalho = [c.strip().lower() for c in linhas[0]]
        idx_frase, idx_secao = None, None
        if any(h in ("frase", "frases", "enunciado", "sentenca", "sentença") for h in cabecalho):
            for j, h in enumerate(cabecalho):
                if h in ("frase", "frases", "enunciado", "sentenca", "sentença"):
                    idx_frase = j
                if h in ("secao", "seção", "secção", "categoria", "grupo"):
                    idx_secao = j
            dados = linhas[1:]
        else:
            # Sem cabeçalho — assume col0 = frase, col1 (se houver) = seção
            idx_frase = 0
            idx_secao = 1 if len(linhas[0]) >= 2 else None
            dados = linhas

        saida = []
        i = 1
        for row in dados:
            if idx_frase is None or idx_frase >= len(row):
                continue
            frase = (row[idx_frase] or "").strip()
            if not frase:
                continue
            secao = ""
            if idx_secao is not None and idx_secao < len(row):
                secao = (row[idx_secao] or "").strip()
            saida.append({"id": i, "frase": frase, "secao": secao})
            i += 1
        if not saida:
            return False, [], "CSV sem frases válidas (cheque cabeçalho/colunas)."
        return True, saida, f"{len(saida)} frase(s) carregada(s) do CSV."

    # ── XLSX / XLS (planilha Excel — mesma semântica do CSV) ──
    if nome_lower.endswith(".xlsx") or nome_lower.endswith(".xls"):
        try:
            import pandas as _pd
            from io import BytesIO as _BIO
            _engine = "openpyxl" if nome_lower.endswith(".xlsx") else "xlrd"
            try:
                df = _pd.read_excel(_BIO(conteudo_bytes), sheet_name=0,
                                    dtype=str, engine=_engine, header=None)
            except ImportError:
                falta = "xlrd" if _engine == "xlrd" else "openpyxl"
                return False, [], (
                    f"Biblioteca '{falta}' nao instalada. "
                    f"Rode `pip install {falta}` (ou `pip install -r requirements.txt`)."
                )
            except Exception as e:
                return False, [], f"Erro lendo Excel: {e}"
        except ImportError:
            return False, [], "pandas nao disponivel para ler Excel."

        if df is None or df.empty:
            return False, [], "Planilha vazia."

        df = df.fillna("").astype(str)
        primeira_linha = [str(c).strip().lower() for c in df.iloc[0].tolist()]
        _COLS_FRASE = ("frase", "frases", "enunciado", "sentenca")
        _COLS_SECAO = ("secao", "categoria", "grupo")
        cabecalho_reconhecido = any(h in _COLS_FRASE for h in primeira_linha)

        idx_frase, idx_secao = None, None
        if cabecalho_reconhecido:
            for j, h in enumerate(primeira_linha):
                if h in _COLS_FRASE:
                    idx_frase = j
                if h in _COLS_SECAO:
                    idx_secao = j
            dados_iter = df.iloc[1:].itertuples(index=False, name=None)
        else:
            idx_frase = 0
            idx_secao = 1 if df.shape[1] >= 2 else None
            dados_iter = df.itertuples(index=False, name=None)

        saida = []
        i = 1
        for row in dados_iter:
            if idx_frase is None or idx_frase >= len(row):
                continue
            frase = (str(row[idx_frase]) or "").strip()
            if not frase:
                continue
            secao = ""
            if idx_secao is not None and idx_secao < len(row):
                secao = (str(row[idx_secao]) or "").strip()
            saida.append({"id": i, "frase": frase, "secao": secao})
            i += 1
        if not saida:
            return False, [], "Excel sem frases validas (cheque cabecalho/colunas)."
        rotulo = "XLSX" if nome_lower.endswith(".xlsx") else "XLS"
        return True, saida, f"{len(saida)} frase(s) carregada(s) do {rotulo}."

    # ── TXT / MD (uma frase por linha) ──
    if nome_lower.endswith(".txt") or nome_lower.endswith(".md") or nome_lower == "":
        frases = []
        for ln in texto.splitlines():
            limpa = ln.strip()
            # Ignora linhas vazias, separadores markdown e comentários "#"
            if not limpa:
                continue
            if limpa.startswith("---") or limpa.startswith("==="):
                continue
            if limpa.startswith("#"):
                # Trata como seção markdown? — por simplicidade ignora cabeçalhos
                continue
            # Remove marcadores comuns (-, *, número.)
            for prefix in ("- ", "* ", "• "):
                if limpa.startswith(prefix):
                    limpa = limpa[len(prefix):].strip()
                    break
            # Remove "1. ", "2) " etc.
            import re as _re
            limpa = _re.sub(r"^\d+[\.\)]\s*", "", limpa)
            if limpa:
                frases.append(limpa)
        if not frases:
            return False, [], "Arquivo de texto sem frases válidas."
        saida = [{"id": i, "frase": fr, "secao": ""} for i, fr in enumerate(frases, start=1)]
        return True, saida, f"{len(saida)} frase(s) carregada(s) do texto."

    return False, [], f"Extensao '{nome_lower}' nao suportada. Use .json, .csv, .xlsx, .xls, .txt ou .md."


# ═══════════════════════════════════════════════════════════════════════════
# CAMADA BD — asyncpg (privado)
# ═══════════════════════════════════════════════════════════════════════════

def _bd_disponivel() -> bool:
    """Retorna True se a conexão com o PostgreSQL está operacional."""
    if not _BD_IMPORT_OK:
        return False
    try:
        pool = run_async(get_pool())
        return pool is not None
    except Exception:
        return False


# ── helpers async internos ──────────────────────────────────────────────────

async def _async_listar(pool) -> List[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT nome FROM moldes ORDER BY nome")
        return [r["nome"] for r in rows]


async def _async_carregar(pool, nome: str) -> Optional[Dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT dados_json FROM moldes WHERE nome = $1", nome
        )
        if row is None:
            return None
        val = row["dados_json"]
        # asyncpg pode devolver dict ou str dependendo do codec registrado
        if isinstance(val, str):
            return json.loads(val)
        return dict(val)


async def _async_salvar(pool, nome: str, dados: Dict,
                         pdf_bytes: Optional[bytes] = None) -> None:
    versao         = str(dados.get("versao", "2.0"))
    criado_em      = int(dados.get("criado_em", int(time.time())))
    fonte_pdf      = str(dados.get("fonte_pdf", ""))
    dpi_referencia = int(dados.get("dpi_referencia", DPI_PADRAO))
    qtd_quadrados  = int(dados.get("qtd_quadrados", 0))
    qtd_frases     = int(dados.get("qtd_frases_gabarito", 0))
    template_layout = str(dados.get("template_layout", "multipla_escolha_esquerda"))
    dados_str      = json.dumps(dados, ensure_ascii=False)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO moldes
                (nome, versao, criado_em, fonte_pdf, dpi_referencia,
                 qtd_quadrados, qtd_frases, template_layout, dados_json, pdf_bytes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
            ON CONFLICT (nome) DO UPDATE SET
                versao          = EXCLUDED.versao,
                criado_em       = EXCLUDED.criado_em,
                atualizado_em   = now(),
                fonte_pdf       = EXCLUDED.fonte_pdf,
                dpi_referencia  = EXCLUDED.dpi_referencia,
                qtd_quadrados   = EXCLUDED.qtd_quadrados,
                qtd_frases      = EXCLUDED.qtd_frases,
                template_layout = EXCLUDED.template_layout,
                dados_json      = EXCLUDED.dados_json,
                pdf_bytes       = COALESCE(EXCLUDED.pdf_bytes, moldes.pdf_bytes)
            """,
            nome, versao, criado_em, fonte_pdf, dpi_referencia,
            qtd_quadrados, qtd_frases, template_layout, dados_str, pdf_bytes,
        )


async def _async_atualizar_pdf(pool, nome: str, pdf_bytes: bytes) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE moldes SET pdf_bytes = $2, atualizado_em = now() WHERE nome = $1",
            nome, pdf_bytes,
        )


async def _async_get_pdf(pool, nome: str) -> Optional[bytes]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT pdf_bytes FROM moldes WHERE nome = $1", nome
        )
        if row and row["pdf_bytes"]:
            return bytes(row["pdf_bytes"])
        return None


async def _async_deletar(pool, nome: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM moldes WHERE nome = $1", nome
        )
        return result != "DELETE 0"


# ── wrappers síncronos (chamados pelas funções públicas) ───────────────────

def _bd_listar() -> List[str]:
    """SELECT nome FROM moldes. Retorna [] em caso de erro."""
    try:
        pool = run_async(get_pool())
        return run_async(_async_listar(pool))
    except Exception:
        return []


def _bd_carregar(nome: str) -> Optional[Dict]:
    """Busca molde no BD pelo nome. Retorna None se não existir ou em erro."""
    try:
        pool = run_async(get_pool())
        return run_async(_async_carregar(pool, nome))
    except Exception:
        return None


def _bd_salvar(nome: str, dados: Dict,
               pdf_bytes: Optional[bytes] = None) -> Tuple[bool, str]:
    """INSERT / UPDATE do molde no BD. Retorna (ok, mensagem)."""
    try:
        pool = run_async(get_pool())
        run_async(_async_salvar(pool, nome, dados, pdf_bytes))
        return True, "Molde salvo no BD."
    except Exception as e:
        return False, f"BD erro: {type(e).__name__}: {e}"


def _bd_atualizar_pdf(nome: str, pdf_bytes: bytes) -> None:
    """Atualiza só a coluna pdf_bytes de um molde já existente. Best-effort."""
    try:
        pool = run_async(get_pool())
        run_async(_async_atualizar_pdf(pool, nome, pdf_bytes))
    except Exception:
        pass


def _bd_get_pdf(nome: str) -> Optional[bytes]:
    """Recupera os bytes do PDF de referência do BD. Retorna None se ausente."""
    try:
        pool = run_async(get_pool())
        return run_async(_async_get_pdf(pool, nome))
    except Exception:
        return None


def _bd_deletar(nome: str) -> bool:
    """DELETE do molde no BD. Retorna True se deletou algo."""
    try:
        pool = run_async(get_pool())
        return run_async(_async_deletar(pool, nome))
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# MIGRAÇÃO DISCO → BD (one-shot, idempotente)
# ═══════════════════════════════════════════════════════════════════════════

def migrar_disco_para_bd() -> Dict:
    """Importa todos os moldes do disco local para o PostgreSQL.

    Idempotente: usa ON CONFLICT(nome) DO NOTHING implícito via _bd_salvar
    (que usa ON CONFLICT DO UPDATE, mas é seguro rodar N vezes — só atualiza).
    Lê o PDF de referência correspondente (se existir) e salva como bytea.

    Retorna:
        {"importados": N, "sem_pdf": M, "erros": ["nome: mensagem", ...]}
    """
    garantir_pasta_moldes()
    resultado = {"importados": 0, "sem_pdf": 0, "erros": []}

    arquivos_json = [
        f for f in os.listdir(PASTA_MOLDES)
        if f.lower().endswith(".json") and not f.startswith(".")
    ]

    if not arquivos_json:
        return resultado

    for arquivo in sorted(arquivos_json):
        nome = arquivo[:-5]  # remove .json
        caminho_json = os.path.join(PASTA_MOLDES, arquivo)

        # Lê o JSON do molde
        try:
            with open(caminho_json, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except Exception as e:
            resultado["erros"].append(f"{nome}: falha ao ler JSON — {e}")
            continue

        # Lê o PDF de referência (se existir)
        pdf_bytes = None
        caminho_pdf = molde_pdf_path(nome)
        if os.path.exists(caminho_pdf):
            try:
                with open(caminho_pdf, "rb") as f:
                    pdf_bytes = f.read()
            except Exception as e:
                resultado["erros"].append(f"{nome}: PDF existe mas falhou ao ler — {e}")
        else:
            resultado["sem_pdf"] += 1

        # Salva no BD
        ok, msg = _bd_salvar(nome, dados, pdf_bytes)
        if ok:
            resultado["importados"] += 1
        else:
            resultado["erros"].append(f"{nome}: {msg}")

    return resultado


# ═══════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS DE I/O DE MOLDES (disco)
# ═══════════════════════════════════════════════════════════════════════════
def garantir_pasta_moldes() -> str:
    """Cria a pasta moldes/ se não existir. Retorna o caminho absoluto."""
    if not os.path.exists(PASTA_MOLDES):
        os.makedirs(PASTA_MOLDES, exist_ok=True)
    return os.path.abspath(PASTA_MOLDES)


def _sanitizar_nome_filesystem(nome: str) -> str:
    """Normaliza nome para ser SEGURO em filesystem cross-platform (Win/Linux/Mac).

    Passos:
      1. Strip whitespace.
      2. Normalize Unicode NFKD e descarta combining marks (remove acentos:
         Ç→C, Ã→A, Õ→O, ç→c, ã→a, õ→o, á→a, é→e, í→i, ó→o, ú→u, etc.).
      3. Mantém apenas [a-zA-Z0-9._-]; qualquer outro caractere (incluindo
         espaços, caixa alta de não-latinos, símbolos) vira "_".
      4. Colapsa "__" repetidos em "_" para evitar filenames feios.
      5. Remove "_" do início/fim.

    Exemplos:
      'PROVA GRAVAÇAÕ'  → 'PROVA_GRAVACAO'
      'Avaliação 5ª Série' → 'Avaliacao_5a_Serie'
      'Math/Eng' → 'Math_Eng'
    """
    import unicodedata as _ud
    import re as _re
    if not nome:
        return ""
    # 1+2: NFKD + descarta combining
    nfd = _ud.normalize("NFKD", nome.strip())
    ascii_str = "".join(c for c in nfd if not _ud.combining(c))
    # 3: substitui qualquer não-[a-zA-Z0-9._-] por "_"
    seguro = "".join(c if (c.isascii() and c.isalnum()) or c in "._-" else "_"
                     for c in ascii_str)
    # 4+5: colapsa "_" e remove edges
    seguro = _re.sub(r"_+", "_", seguro).strip("_")
    return seguro or "molde_sem_nome"


def molde_path(nome: str) -> str:
    """Devolve o caminho completo do JSON do molde com nome dado.
    O nome é SANITIZADO via _sanitizar_nome_filesystem antes de virar filename."""
    nome_limpo = _sanitizar_nome_filesystem(nome)
    if not nome_limpo.lower().endswith(".json"):
        nome_limpo += ".json"
    return os.path.join(PASTA_MOLDES, nome_limpo)


def molde_pdf_path(nome: str) -> str:
    """Caminho do PDF de referência associado ao molde (mesma pasta, mesma base).
    O nome é SANITIZADO via _sanitizar_nome_filesystem antes de virar filename."""
    nome_limpo = _sanitizar_nome_filesystem(nome)
    if nome_limpo.lower().endswith(".json"):
        nome_limpo = nome_limpo[:-5]
    return os.path.join(PASTA_MOLDES, nome_limpo + ".pdf")


# ═══════════════════════════════════════════════════════════════════════════
# FUNÇÕES PÚBLICAS DE I/O — BD-first com fallback para disco
# ═══════════════════════════════════════════════════════════════════════════

def listar_moldes() -> List[str]:
    """Lista nomes (sem .json) dos moldes disponíveis.

    Estratégia:
      1. Lê o disco para detectar moldes não migrados (fallback sempre ativo).
      2. Se BD disponível: consulta tabela moldes.
         • One-shot migration: BD vazio + disco com moldes → migra automaticamente.
      3. Retorna união de BD + disco (deduplicado, ordenado).
    """
    garantir_pasta_moldes()

    # ── Disco (fallback garantido) ──────────────────────────────────────
    disco: set = set()
    for f in os.listdir(PASTA_MOLDES):
        if f.lower().endswith(".json") and not f.startswith("."):
            disco.add(f[:-5])

    # ── BD ──────────────────────────────────────────────────────────────
    bd_nomes: set = set()
    if _bd_disponivel():
        bd_nomes = set(_bd_listar())

        # Migração automática one-shot
        if len(bd_nomes) == 0 and len(disco) > 0:
            migrar_disco_para_bd()
            bd_nomes = set(_bd_listar())

    return sorted(bd_nomes | disco)


def carregar_molde(nome: str) -> Optional[Dict]:
    """Carrega um molde pelo nome.

    Estratégia: BD first → fallback disco legado.
    """
    # ── BD first ────────────────────────────────────────────────────────
    if _bd_disponivel():
        dados = _bd_carregar(nome)
        if dados is not None:
            return dados

    # ── Fallback: disco ──────────────────────────────────────────────────
    path = molde_path(nome)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def salvar_molde(nome: str, dados: Dict) -> Tuple[bool, str, str]:
    """Salva molde no BD + disco (disco mantido durante a transição).

    Retorna tupla (sucesso: bool, mensagem: str, path_absoluto: str).
    """
    garantir_pasta_moldes()
    path = molde_path(nome)
    path_abs = os.path.abspath(path)

    # ── BD ──────────────────────────────────────────────────────────────
    bd_ok = False
    bd_msg = "BD indisponível"
    if _bd_disponivel():
        bd_ok, bd_msg = _bd_salvar(nome, dados)

    # ── Disco (mantém compatibilidade) ──────────────────────────────────
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        if os.path.exists(path):
            tamanho = os.path.getsize(path)
            sufixo = " + BD ✓" if bd_ok else f" (BD: {bd_msg})"
            return True, f"OK · {tamanho} bytes gravados{sufixo}", path_abs
        else:
            return False, "Arquivo não existe após gravação", path_abs
    except PermissionError as e:
        return False, f"Sem permissão: {e}", path_abs
    except OSError as e:
        return False, f"Erro de I/O: {e}", path_abs
    except Exception as e:
        return False, f"Exceção inesperada: {type(e).__name__}: {e}", path_abs


def deletar_molde(nome: str) -> bool:
    """Remove o molde do BD e do disco. Retorna True se removeu de algum lugar."""
    # ── BD ──────────────────────────────────────────────────────────────
    bd_ok = False
    if _bd_disponivel():
        bd_ok = _bd_deletar(nome)

    # ── Disco ────────────────────────────────────────────────────────────
    path_json = molde_path(nome)
    path_pdf  = molde_pdf_path(nome)
    disco_ok = False
    if os.path.exists(path_json):
        try:
            os.remove(path_json)
            disco_ok = True
        except Exception:
            pass
    if os.path.exists(path_pdf):
        try:
            os.remove(path_pdf)
        except Exception:
            pass

    return bd_ok or disco_ok


def salvar_pdf_referencia(nome: str, pdf_path_origem: str) -> Tuple[bool, str, str]:
    """Copia o PDF temporário para moldes/<nome>.pdf E salva bytes no BD.

    Retorna tupla (sucesso, mensagem, path_destino).
    """
    import shutil
    garantir_pasta_moldes()
    destino = molde_pdf_path(nome)
    destino_abs = os.path.abspath(destino)
    try:
        if not os.path.exists(pdf_path_origem):
            return False, f"PDF origem não existe: {pdf_path_origem}", destino_abs
        shutil.copy2(pdf_path_origem, destino)
        if not os.path.exists(destino):
            return False, "Falha desconhecida na cópia", destino_abs

        tamanho = os.path.getsize(destino)

        # ── Salva bytes no BD (best-effort) ─────────────────────────────
        bd_sufixo = ""
        if _bd_disponivel():
            try:
                with open(destino, "rb") as f:
                    pdf_bytes = f.read()
                _bd_atualizar_pdf(nome, pdf_bytes)
                bd_sufixo = " + BD ✓"
            except Exception as e:
                bd_sufixo = f" (BD PDF falhou: {type(e).__name__})"

        return True, f"PDF copiado · {tamanho} bytes{bd_sufixo}", destino_abs
    except Exception as e:
        return False, f"Exceção: {type(e).__name__}: {e}", destino_abs


def existe_pdf_referencia(nome: str) -> bool:
    """Verifica se há PDF de referência: disco OU BD."""
    if os.path.exists(molde_pdf_path(nome)):
        return True
    if _bd_disponivel():
        pdf = _bd_get_pdf(nome)
        return pdf is not None
    return False


# ═══════════════════════════════════════════════════════════════════════════
# RASTERIZAÇÃO E DETECÇÃO
# ═══════════════════════════════════════════════════════════════════════════
def rasterizar_pagina(pdf_path: str, num_pag: int = 0, dpi: int = DPI_PADRAO):
    """Rasteriza uma página do PDF em imagem OpenCV (BGR).
    Retorna numpy.ndarray (H, W, 3) ou None se falhar."""
    if not VISAO_OK or not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        if num_pag >= len(doc):
            doc.close()
            return None
        pagina = doc.load_page(num_pag)
        pix = pagina.get_pixmap(dpi=dpi)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        if pix.n == 4:
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
        else:
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        doc.close()
        return img_bgr
    except Exception:
        return None


def rasterizar_todas(pdf_path: str, dpi: int = DPI_PADRAO) -> Dict[int, "np.ndarray"]:
    """Rasteriza TODAS as páginas. Retorna {num_pag: img_bgr}."""
    if not VISAO_OK or not os.path.exists(pdf_path):
        return {}
    paginas = {}
    try:
        doc = fitz.open(pdf_path)
        num_paginas = len(doc)
        doc.close()
    except Exception:
        return {}
    for n in range(num_paginas):
        img = rasterizar_pagina(pdf_path, n, dpi)
        if img is not None:
            paginas[n] = img
    return paginas


def _localizar_via_template(img_gs, template_gs,
                             threshold=0.60, x_max_pct=0.20, nms_raio=25,
                             escalas=None):
    """Multi-scale template matching com NMS. Idêntica à do backend_ocr.py."""
    if escalas is None:
        escalas = [0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.7]
    h, w = img_gs.shape[:2]
    x_max = int(w * x_max_pct)
    matches = []
    for esc in escalas:
        nw = int(template_gs.shape[1] * esc)
        nh = int(template_gs.shape[0] * esc)
        if nw < 20 or nh < 18 or nw > 60 or nh > 50:
            continue
        tpl = cv2.resize(template_gs, (nw, nh), interpolation=cv2.INTER_CUBIC)
        res = cv2.matchTemplate(img_gs, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        for y, x in zip(ys, xs):
            if x > x_max:
                continue
            matches.append((int(x), int(y), int(nw), int(nh), float(res[y, x])))
    matches.sort(key=lambda m: -m[4])
    keep = []
    for m in matches:
        cx = m[0] + m[2] / 2.0
        cy = m[1] + m[3] / 2.0
        dup = False
        for k in keep:
            if abs(cx - (k[0] + k[2] / 2.0)) < nms_raio and abs(cy - (k[1] + k[3] / 2.0)) < nms_raio:
                dup = True
                break
        if not dup:
            keep.append(m)
    return keep


def _stddev_faixa_direita(img_gs, x, y, w, h, largura=250):
    """Stddev da faixa horizontal à direita do checkbox (anti-bleed)."""
    h_img, w_img = img_gs.shape[:2]
    x1 = min(w_img, x + w + 10)
    x2 = min(w_img, x1 + largura)
    y1 = max(0, y - 3)
    y2 = min(h_img, y + h + 3)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    faixa = img_gs[y1:y2, x1:x2]
    return float(faixa.std()) if faixa.size > 0 else 0.0


def detectar_candidatos_para_molde(pdf_path: str,
                                    template_path: str = None,
                                    dpi: int = DPI_PADRAO,
                                    x_max_pct: float = 0.20,
                                    threshold: float = 0.60) -> Dict:
    """
    Detecta TODOS os candidatos (sem filtro) usando template matching.
    Retorna dict com:
      {
        "paginas_imagens": {0: img_bgr, 1: img_bgr, ...},
        "candidatos": [{pag, x, y, w, h, score, stddev}, ...]
      }

    x_max_pct: fração da largura da página até onde a busca por caixas é feita.
               Default 0.20 (20% — comportamento original). Use 0.98 para
               detecção híbrida em toda a largura da página.
    threshold: limiar mínimo de correlação para aceitar um match (0.0–1.0).
               Default 0.60. Valores mais altos reduzem falsos-positivos de letras.
    """
    if not VISAO_OK:
        return {"erro": "OpenCV/PyMuPDF/NumPy ausentes"}

    tpl_path = template_path or TEMPLATE_DEFAULT
    if not os.path.exists(tpl_path):
        return {"erro": f"Template não encontrado: {tpl_path}"}

    template_gs = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
    if template_gs is None:
        return {"erro": "Falha ao carregar template"}

    # Rasteriza todas as páginas
    paginas_bgr = rasterizar_todas(pdf_path, dpi=dpi)
    if not paginas_bgr:
        return {"erro": "Falha ao rasterizar PDF"}

    # Detecta candidatos
    candidatos = []
    for npag, img_bgr in paginas_bgr.items():
        img_gs = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        for (x, y, w, h, sc) in _localizar_via_template(img_gs, template_gs,
                                                          x_max_pct=x_max_pct,
                                                          threshold=threshold):
            std = _stddev_faixa_direita(img_gs, x, y, w, h)
            candidatos.append({
                "pag": int(npag), "x": int(x), "y": int(y),
                "w": int(w), "h": int(h),
                "score": round(float(sc), 3),
                "stddev": round(float(std), 1),
            })

    # Ordena por (pag, y, x) — ordem natural de leitura
    candidatos.sort(key=lambda c: (c["pag"], c["y"], c["x"]))

    return {
        "paginas_imagens": paginas_bgr,
        "candidatos": candidatos,
        "qtd_paginas": len(paginas_bgr),
        "qtd_candidatos": len(candidatos),
    }


# ═══════════════════════════════════════════════════════════════════════════
# MONTAGEM E SALVAMENTO DO MOLDE FINAL
# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# AUTODETECÇÃO DE TEMPLATE DE LAYOUT (calibrado 2026-05-25)
# ═══════════════════════════════════════════════════════════════════════════
def detectar_template_layout(quadrados_ordenados: List[Dict],
                              dimensoes_pag: Optional[Dict] = None,
                              threshold_estreito: float = 0.25) -> str:
    """Sugere automaticamente o template_layout ideal baseado na disposição
    horizontal dos checkboxes detectados na prova.

    Lógica:
      • Calcula a faixa horizontal ocupada pelos checkboxes (min X a max X+W).
      • Se essa faixa ocupa < threshold_estreito (25%) da largura média das
        páginas → todos os checkboxes estão concentrados em coluna estreita
        (típico de questionários com alternativas à esquerda) → sugere
        'multipla_escolha_esquerda' (crop horizontal agressivo, economia
        ~89% de tokens, performance superior em Gemini/Modo 1 Turbo).
      • Se a faixa > 25% → checkboxes espalhados em colunas variáveis (layout
        misto) → sugere 'hibrido_sem_corte' (full-width, conservador).

    Args:
      quadrados_ordenados: lista de dicts com {pag, x, y, w, h}.
      dimensoes_pag: dict opcional {pag_int: {h, w}}. Se ausente, assume
                     largura 1654 (DPI 200, A4 portrait padrão).
      threshold_estreito: limiar de proporção. Default 0.25 (25%).

    Returns:
      'multipla_escolha_esquerda' ou 'hibrido_sem_corte'.
    """
    if not quadrados_ordenados:
        return "multipla_escolha_esquerda"   # default novo (calibrado 2026-05-25)

    if dimensoes_pag:
        larguras = [d.get("w", 0) for d in dimensoes_pag.values() if d.get("w", 0) > 0]
        largura_media = sum(larguras) / len(larguras) if larguras else 1654
    else:
        largura_media = 1654

    if largura_media <= 0:
        largura_media = 1654

    x_mins = [q.get("x", 0) for q in quadrados_ordenados]
    x_maxs = [q.get("x", 0) + q.get("w", 35) for q in quadrados_ordenados]
    faixa = max(x_maxs) - min(x_mins)
    proporcao = faixa / largura_media

    if proporcao < threshold_estreito:
        return "multipla_escolha_esquerda"
    return "hibrido_sem_corte"


def montar_molde_final(nome: str,
                        fonte_pdf: str,
                        quadrados_ordenados: List[Dict],
                        ancoras_por_pag: Optional[Dict] = None,
                        dimensoes_pag: Optional[Dict] = None,
                        dpi: int = DPI_PADRAO,
                        gabarito_frases: Optional[List] = None,
                        template_layout: Optional[str] = None,
                        config_template: Optional[Dict] = None) -> Dict:
    """
    Monta o dicionário do molde final pronto para `salvar_molde`.

    quadrados_ordenados: lista com {pag, x, y, w, h, score?, stddev?, manual?, frase_id?}
                         ordem importa — Q1 = primeiro, Q2 = segundo, etc.
    gabarito_frases:     lista DINÂMICA de frases para esse molde. Aceita:
                          - lista de dicts {id, frase, secao}
                          - lista de strings
                         Se None → usa o GABARITO_OFICIAL padrão (compatibilidade).
    """
    # ── Gabarito DINÂMICO ──────────────────────────────────────────────
    if gabarito_frases is None:
        gabarito_lista = gabarito_padrao_como_lista()
    else:
        gabarito_lista = normalizar_gabarito_frases(gabarito_frases)

    n_frases = len(gabarito_lista)
    # Mapa rápido: id → {frase, secao}
    mapa_id_frase = {g["id"]: g for g in gabarito_lista}

    # ── Enriquece cada quadrado com frase associada ───────────────────
    quadrados_enriquecidos = []
    for i, q in enumerate(quadrados_ordenados):
        q_id = i + 1
        # Se o quadrado já traz frase_id explícito, respeita; senão usa ordem ordinal
        frase_id = int(q.get("frase_id", q_id))
        if frase_id < 1 or frase_id > n_frases:
            frase_id = min(q_id, n_frases) if n_frases > 0 else q_id

        item_frase = mapa_id_frase.get(frase_id, {})
        frase_txt  = item_frase.get("frase", "")
        secao_txt  = item_frase.get("secao", "")

        quadrados_enriquecidos.append({
            "id":       q_id,
            "frase_id": frase_id,
            "frase":    frase_txt,
            "secao":    secao_txt,
            "pag":      int(q.get("pag", 0)),
            "x":        int(q.get("x", 0)),
            "y":        int(q.get("y", 0)),
            "w":        int(q.get("w", 35)),
            "h":        int(q.get("h", 30)),
            "score":    float(q.get("score", 0.0)),
            "stddev":   float(q.get("stddev", 0.0)),
            "manual":   bool(q.get("manual", False)),
        })

    # Organiza por página
    paginas_dict = {}
    for q in quadrados_enriquecidos:
        npag = q["pag"]
        if str(npag) not in paginas_dict:
            paginas_dict[str(npag)] = {
                "altura_px":  (dimensoes_pag or {}).get(npag, {}).get("h", 0),
                "largura_px": (dimensoes_pag or {}).get(npag, {}).get("w", 0),
                "ancoras_fiduciais": (ancoras_por_pag or {}).get(npag, []),
                "quadrados": [],
            }
        paginas_dict[str(npag)]["quadrados"].append(q)

    # ── Template de layout (CALIBRADO 2026-05-25) ───────────────────────
    # Se não foi passado explicitamente, autodetecta. Default seguro é
    # multipla_escolha_esquerda (evidência empírica do projeto).
    _layout_final = template_layout
    if not _layout_final:
        _layout_final = detectar_template_layout(quadrados_ordenados,
                                                  dimensoes_pag)
    _cfg_template_final = config_template or {
        "margem_id_px":    90,   # px à ESQUERDA do checkbox p/ caber o [#N]
        "margem_marca_px": 60,   # px à DIREITA p/ folga do "X" extrapolado
    }

    return {
        "versao":              "2.0",
        "nome":                nome,
        "criado_em":           int(time.time()),
        "fonte_pdf":           os.path.basename(fonte_pdf) if fonte_pdf else "",
        "dpi_referencia":      dpi,
        "qtd_quadrados":       len(quadrados_enriquecidos),
        "qtd_frases_gabarito": n_frases,
        "template_layout":     _layout_final,
        "config_template":     _cfg_template_final,
        "gabarito_frases":     gabarito_lista,
        "paginas":             paginas_dict,
    }

def carregar_para_edicao(nome: str):
    """
    Carrega um molde existente + seu PDF de referência para edição.

    Retorna dict:
      {
        "molde":      <dict do JSON>,
        "paginas":    {0: img_bgr, 1: img_bgr, ...},
        "quadrados":  [{pag, x, y, w, h, manual, ...}, ...],
        "frases":     {str(id): frase, ...},
        "pdf_path":   <path absoluto do PDF de referência>,
      }
    OU {"erro": "..."} se algo falhar.
    """
    molde = carregar_molde(nome)
    if not molde:
        return {"erro": f"Molde '{nome}' não encontrado."}

    pdf_ref = molde_pdf_path(nome)

    # Se o PDF não estiver em disco, tenta recuperar do BD e gravar temporariamente
    if not os.path.exists(pdf_ref) and _bd_disponivel():
        pdf_bytes = _bd_get_pdf(nome)
        if pdf_bytes:
            try:
                garantir_pasta_moldes()
                with open(pdf_ref, "wb") as f:
                    f.write(pdf_bytes)
            except Exception:
                pdf_ref = None  # falhou ao escrever — continuará dando erro abaixo

    if not pdf_ref or not os.path.exists(pdf_ref):
        return {"erro": f"PDF de referência não encontrado em '{molde_pdf_path(nome)}'. Suba o PDF original novamente."}

    # Rasteriza as páginas do PDF de referência
    paginas_bgr = rasterizar_todas(pdf_ref, dpi=molde.get("dpi_referencia", DPI_PADRAO))
    if not paginas_bgr:
        return {"erro": f"Falha ao rasterizar PDF de referência: {pdf_ref}"}

    # Reconstrói lista de quadrados a partir do JSON
    quadrados = []
    frases_custom = {}
    for pag_str, pag_data in (molde.get("paginas") or {}).items():
        for q in (pag_data.get("quadrados") or []):
            quadrados.append({
                "pag":    int(q.get("pag", int(pag_str))),
                "x":      int(q.get("x", 0)),
                "y":      int(q.get("y", 0)),
                "w":      int(q.get("w", 35)),
                "h":      int(q.get("h", 30)),
                "score":  float(q.get("score", 1.0)),
                "stddev": float(q.get("stddev", 0.0)),
                "manual": bool(q.get("manual", True)),
            })
            qid = q.get("id")
            qfr = q.get("frase")
            if qid and qfr:
                frases_custom[str(qid)] = qfr

    quadrados.sort(key=lambda c: (c["pag"], c["y"], c["x"]))

    return {
        "molde":      molde,
        "paginas":    paginas_bgr,
        "quadrados":  quadrados,
        "frases":     frases_custom,
        "pdf_path":   os.path.abspath(pdf_ref),
    }
