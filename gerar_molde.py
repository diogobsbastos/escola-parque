"""
═══════════════════════════════════════════════════════════════════════════════
GERAR_MOLDE.PY — Cria o gabarito de coordenadas da prova oficial
═══════════════════════════════════════════════════════════════════════════════
Uso:
    python gerar_molde.py <caminho_para_pdf> [--saida molde_prova_oficial.json]

O script:
  1. Rasteriza cada página do PDF em DPI=200
  2. Roda template matching (referencia_branco.jpg) para localizar checkboxes
  3. Aplica filtro duplo (stddev≥20 + score≥0.675) para eliminar falsos positivos
  4. Ordena por (página, y, x) → ordem visual = ordem do gabarito
  5. Detecta âncoras fiduciais (cabeçalhos de seção via template/heurística)
  6. Salva JSON com 46 quadrados + frases + seções + âncoras

Não depende de Streamlit (pode rodar standalone via terminal).
═══════════════════════════════════════════════════════════════════════════════
"""
import os
import sys
import json
import argparse

try:
    import fitz       # PyMuPDF
    import cv2
    import numpy as np
except ImportError as e:
    print(f"ERRO: biblioteca ausente: {e}. Rode: pip install pymupdf opencv-python numpy")
    sys.exit(1)


# ── GABARITO FIDEDIGNO (mesmo do backend_ocr.py) ──────────────────────────────
MAPEAMENTO_FIDEDIGNO = {
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

# Lista plana ordenada de todas as 46 frases (ordem do gabarito)
LISTA_OFICIAL_PLANA = [
    f for sublist in MAPEAMENTO_FIDEDIGNO.values() for f in sublist
]


def renderizar_pagina(pdf_path, num_pagina, dpi=200):
    """Rasteriza uma página do PDF em imagem OpenCV BGR."""
    doc = fitz.open(pdf_path)
    pagina = doc.load_page(num_pagina)
    pix = pagina.get_pixmap(dpi=dpi)
    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        img_cv = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
    else:
        img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    doc.close()
    return img_cv


def localizar_via_template(img_gs, template_gs,
                            threshold=0.60, x_max_pct=0.20, nms_raio=25):
    """Multi-scale template matching com NMS."""
    h, w = img_gs.shape[:2]
    x_max = int(w * x_max_pct)
    matches = []
    for esc in [0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.7]:
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


def stddev_faixa_direita(img_gs, x, y, w, h, largura_faixa=250):
    """Mede stddev da faixa horizontal à direita do checkbox (anti-bleed)."""
    h_img, w_img = img_gs.shape[:2]
    x1 = min(w_img, x + w + 10)
    x2 = min(w_img, x1 + largura_faixa)
    y1 = max(0, y - 3)
    y2 = min(h_img, y + h + 3)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    faixa = img_gs[y1:y2, x1:x2]
    return float(faixa.std()) if faixa.size > 0 else 0.0


def filtrar_cirurgico(candidatos, paginas_gs, lim_stddev=20.0, lim_score=0.675):
    """Aplica filtro duplo (anti-bleed + anti-título)."""
    sobreviventes = []
    for (pag, x, y, w, h, sc) in candidatos:
        img_gs = paginas_gs.get(pag)
        if img_gs is None: continue
        std = stddev_faixa_direita(img_gs, x, y, w, h)
        if std < lim_stddev: continue
        if sc < lim_score: continue
        sobreviventes.append((pag, x, y, w, h, sc, std))
    return sobreviventes


def detectar_ancoras_fiduciais(paginas_bgr):
    """
    Detecta cabeçalhos de seção como âncoras fiduciais para alinhamento.
    Usa contornos pretos largos (cabeçalhos têm fontes grandes).

    Retorna: { num_pag: [{nome, x, y, w, h}, ...] }
    """
    ancoras_por_pag = {}
    for npag, img in paginas_bgr.items():
        cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Threshold para pegar regiões muito escuras (cabeçalhos pretos)
        _, bin_img = cv2.threshold(cinza, 80, 255, cv2.THRESH_BINARY_INV)
        # Morfologia: junta letras próximas em blocos
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 8))
        bin_dilatado = cv2.dilate(bin_img, kernel, iterations=1)
        contornos, _ = cv2.findContours(bin_dilatado, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidatos = []
        for c in contornos:
            x, y, w, h = cv2.boundingRect(c)
            # Cabeçalhos: largos (>300px) e baixos (20-60px), na margem esquerda
            if w > 300 and 20 < h < 70 and x < 200:
                candidatos.append((x, y, w, h))
        # Ordena por y (top-down)
        candidatos.sort(key=lambda c: c[1])
        ancoras_por_pag[npag] = [
            {"nome": f"cabecalho_pag{npag}_{i}", "x": c[0], "y": c[1], "w": c[2], "h": c[3]}
            for i, c in enumerate(candidatos[:5])  # top 5 cabeçalhos
        ]
    return ancoras_por_pag


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path", help="Caminho do PDF da prova (oficial preenchida ou em branco)")
    parser.add_argument("--saida", default="molde_prova_oficial.json", help="Caminho do JSON de saída")
    parser.add_argument("--template", default="banco_contexto/treino_visao/referencia_branco.jpg",
                        help="Caminho do template_referencia_branco.jpg")
    args = parser.parse_args()

    pdf_path = args.pdf_path
    saida_path = args.saida
    tpl_path = args.template

    if not os.path.exists(pdf_path):
        print(f"❌ PDF não encontrado: {pdf_path}")
        sys.exit(1)
    if not os.path.exists(tpl_path):
        print(f"❌ Template não encontrado: {tpl_path}")
        sys.exit(1)

    print(f"📄 Lendo PDF: {pdf_path}")
    print(f"📐 Template: {tpl_path}")

    template_gs = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
    if template_gs is None:
        print("❌ Falha ao carregar template")
        sys.exit(1)

    # Rasteriza todas as páginas
    doc = fitz.open(pdf_path)
    num_paginas = len(doc)
    largura_pdf_pt = doc.load_page(0).rect.width
    altura_pdf_pt  = doc.load_page(0).rect.height
    doc.close()
    print(f"📊 PDF: {num_paginas} página(s) · {largura_pdf_pt:.0f}×{altura_pdf_pt:.0f} pt")

    paginas_bgr = {}
    paginas_gs  = {}
    for npag in range(num_paginas):
        img_bgr = renderizar_pagina(pdf_path, npag, dpi=200)
        paginas_bgr[npag] = img_bgr
        paginas_gs[npag]  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        print(f"   Pag {npag}: {img_bgr.shape[1]}×{img_bgr.shape[0]} px")

    # Localiza candidatos em todas as páginas
    candidatos = []
    for npag, img_gs in paginas_gs.items():
        for (x, y, w, h, sc) in localizar_via_template(img_gs, template_gs):
            candidatos.append((npag, x, y, w, h, sc))
    print(f"🔍 Candidatos brutos: {len(candidatos)}")

    # Filtro duplo
    sobreviventes = filtrar_cirurgico(candidatos, paginas_gs)
    print(f"✅ Após filtro cirúrgico: {len(sobreviventes)}")

    # Ordena
    sobreviventes.sort(key=lambda t: (t[0], t[2], t[1]))

    if len(sobreviventes) != len(LISTA_OFICIAL_PLANA):
        print(f"⚠️  ATENÇÃO: localizamos {len(sobreviventes)} quadrados mas gabarito tem {len(LISTA_OFICIAL_PLANA)}.")
        print(f"    O molde será gerado mesmo assim, mas pode precisar ajuste manual.")

    # Mapeia cada Q ao gabarito (N-ésimo Q = N-ésima frase)
    quadrados_por_pag = {}
    secao_por_frase = {}
    for secao, frases in MAPEAMENTO_FIDEDIGNO.items():
        for f in frases:
            secao_por_frase[f] = secao

    for i, (pag, x, y, w, h, sc, std) in enumerate(sobreviventes):
        if i >= len(LISTA_OFICIAL_PLANA):
            break
        frase = LISTA_OFICIAL_PLANA[i]
        secao = secao_por_frase[frase]
        q = {
            "id":    i + 1,
            "frase": frase,
            "secao": secao,
            "x": x, "y": y, "w": w, "h": h,
            "score":  round(sc,  3),
            "stddev": round(std, 1),
        }
        quadrados_por_pag.setdefault(pag, []).append(q)

    # Detecta âncoras fiduciais
    print("🎯 Detectando âncoras fiduciais (cabeçalhos)...")
    ancoras_por_pag = detectar_ancoras_fiduciais(paginas_bgr)
    qtd_anc = sum(len(v) for v in ancoras_por_pag.values())
    print(f"   {qtd_anc} âncoras detectadas em {len(ancoras_por_pag)} páginas")

    # Monta JSON final
    molde = {
        "versao": "1.0",
        "dpi_referencia": 200,
        "fonte_pdf": os.path.basename(pdf_path),
        "qtd_quadrados": len(sobreviventes),
        "qtd_frases_gabarito": len(LISTA_OFICIAL_PLANA),
        "paginas": {},
    }

    for npag in sorted(paginas_bgr.keys()):
        img = paginas_bgr[npag]
        molde["paginas"][str(npag)] = {
            "altura_px":  img.shape[0],
            "largura_px": img.shape[1],
            "ancoras_fiduciais": ancoras_por_pag.get(npag, []),
            "quadrados": quadrados_por_pag.get(npag, []),
        }

    # Salva
    with open(saida_path, "w", encoding="utf-8") as f:
        json.dump(molde, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Molde salvo em: {saida_path}")
    print(f"   {molde['qtd_quadrados']} quadrados · {qtd_anc} âncoras · {len(molde['paginas'])} páginas")


if __name__ == "__main__":
    main()
