import os
import time
import json
import mimetypes
import difflib  
import streamlit as st

# --- BLINDAGEM E DEPENDÊNCIAS DE VISÃO (Regra de Ouro 3) ---
try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    import fitz  # PyMuPDF para converter PDF em Imagem
    import cv2   # OpenCV para fatiar e NORMALIZAR imagens
    import numpy as np
    VISAO_ATIVA = True
except ImportError:
    VISAO_ATIVA = False

try:
    from funcoes_fla import load_key, registrar_consumo
except ImportError:
    def load_key(provider="gemini"): return ""
    def registrar_consumo(p, m, t, c): pass

try:
    from funcoes_lab import load_model_pref
except ImportError:
    def load_model_pref(): return "gemini-2.5-flash"


def aguardar_processamento(arquivos_genai):
    for arq in arquivos_genai:
        tentativas = 0
        while arq.state.name == "PROCESSING" and tentativas < 15:
            time.sleep(2)
            arq = genai.get_file(arq.name)
            tentativas += 1
    return True

# --- MOTOR DE VISÃO COMPUTACIONAL (OPENCV) ---
def fatiar_pdf_com_opencv(caminho_pdf):
    if not VISAO_ATIVA:
        return False, "Bibliotecas PyMuPDF ou OpenCV não instaladas."
    
    caminhos_recortes = []
    pasta_temp = "temp_fatias"
    os.makedirs(pasta_temp, exist_ok=True)
    
    try:
        doc = fitz.open(caminho_pdf)
        for num_pag in range(len(doc)):
            pagina = doc.load_page(num_pag)
            pix = pagina.get_pixmap(dpi=200) 
            
            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR) if pix.n == 4 else cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                
            altura, largura = img_cv.shape[:2]
            num_fatias = 6  
            
            # OVERLAP DE 25% MANTIDO
            passo_y = altura // num_fatias
            margem_overlap = int(passo_y * 0.25)
            
            for i in range(num_fatias):
                y_inicio = max(0, (i * passo_y) - margem_overlap)
                y_fim = min(altura, ((i + 1) * passo_y) + margem_overlap)
                
                recorte = img_cv[y_inicio:y_fim, 0:int(largura * 0.8)]
                
                nome_recorte = os.path.join(pasta_temp, f"pag{num_pag}_fatia{i}.jpg")
                cv2.imwrite(nome_recorte, recorte)
                caminhos_recortes.append(nome_recorte)
                
        doc.close()
        return True, caminhos_recortes
    except Exception as e:
        return False, f"Erro no fatiamento OpenCV: {str(e)}"

# --- NORMALIZAÇÃO DO GOLDEN DATASET ---
def normalizar_referencia_opencv(caminho_original, pasta_temp):
    if not VISAO_ATIVA: return caminho_original
    
    try:
        nome_arquivo = os.path.basename(caminho_original)
        nome_sem_ext = os.path.splitext(nome_arquivo)[0]
        caminho_normalizado = os.path.join(pasta_temp, f"norm_{nome_sem_ext}.jpg")
        
        img = cv2.imread(caminho_original)
        
        # Mantendo proporção original (Escala 1:1) e aplicando contraste leve
        img_contrast = cv2.convertScaleAbs(img, alpha=1.5, beta=0) 
        
        cv2.imwrite(caminho_normalizado, img_contrast)
        return caminho_normalizado
    except Exception as e:
        return caminho_original

# --- FLUXO PRINCIPAL: OCR TRANSCRICIONAL COM FEW-SHOT E STREAMING ---
def extrair_texto_pdf(arquivo_pdf):
    try:
        caminho_temp = f"temp_upload_{int(time.time())}.pdf"
        with open(caminho_temp, "wb") as f:
            f.write(arquivo_pdf.getbuffer())
        return caminho_temp
    except Exception as e:
        return f"ERRO FÍSICO: {str(e)}"

def analisar_com_treinamento(caminho_pdf):
    if not genai: return {"erro": "Biblioteca Vision ausente."}
    
    api_key = load_key("gemini")
    modelo_config = load_model_pref()

    mapeamento_fidedigno = {
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

    try:
        genai.configure(api_key=api_key)
        
        # LOBOTOMIA DE CRIATIVIDADE
        config_forense = genai.types.GenerationConfig(
            temperature=0.0,
            top_p=1.0,
            top_k=1
        )
        
        model = genai.GenerativeModel(
            model_name=modelo_config,
            generation_config=config_forense
        )

        st.write("⚙️ Fatiando PDF para alta resolução...")
        sucesso_fatias, recortes = fatiar_pdf_com_opencv(caminho_pdf)
        if not sucesso_fatias: return {"erro": recortes}

        arquivos_ia_alvo = []
        arquivos_ia_treino = {}
        arquivos_temp_norm = [] 
        
        for idx, img_path in enumerate(recortes):
            mime_t, _ = mimetypes.guess_type(img_path)
            if not mime_t: mime_t = "image/jpeg"
            arq_fatia = genai.upload_file(path=img_path, display_name=f"ALVO_FATIA_{idx}", mime_type=mime_t)
            arquivos_ia_alvo.append(arq_fatia)

        pasta_treino = os.path.join("banco_contexto", "treino_visao")
        pasta_temp_norm = "temp_fatias"
        
        # AS 7 ÂNCORAS VISUAIS DE TREINAMENTO
        arquivos_esperados = {
            "referencia_branco": "BASELINE 0: Fundo vazio.",
            "exemplo_marcado_fraco": "LIMITE MÍNIMO DE 1.",
            "exemplo_vazado": "LIMITE DE BORDA DE 1.",
            "exemplo_linha_fina": "LIMITE DE PRESSA.",
            "exemplo_passou_longe": "O HUMANO PREGUIÇOSO.",
            "exemplo_preguicoso_fraco": "O FANTASMA.",
            "referencia_raspa_fora": "O TANGENCIAL."
        }

        if os.path.exists(pasta_treino):
            for arq_treino in os.listdir(pasta_treino):
                nome_sem_ext = os.path.splitext(arq_treino)[0]
                if nome_sem_ext in arquivos_esperados:
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

        telemetria_total = {"in": 0, "out": 0, "brl": 0.0}

        st.markdown("---")
        st.write("### 👁️ Leitura Dinâmica")

        lista_oficial_plana = [frase for sublist in mapeamento_fidedigno.values() for frase in sublist]
        estado_final_frases = {f: False for f in lista_oficial_plana}
        qtd_frases_gabarito = len(lista_oficial_plana)

        conteudo_prompt = [
            "Você é um Transcritor Forense.",
            "Sua tarefa é ler um formulário em fatias e dizer se o estudante sinalizou as frases."
        ]

        if arquivos_ia_treino:
            conteudo_prompt.append("\n--- CALIBRAGEM ---")
            for key in arquivos_esperados.keys():
                if key in arquivos_ia_treino:
                    conteudo_prompt.append(arquivos_esperados[key])
                    conteudo_prompt.append(arquivos_ia_treino[key])

        conteudo_prompt.append("\n--- GABARITO OFICIAL DE FRASES ---")
        conteudo_prompt.append("⚠️ OBRIGATÓRIO: Use EXATAMENTE as frases desta lista na sua resposta. Não mude NENHUMA palavra, mesmo que o risco humano atravesse e borre o texto original da imagem.")
        for f_oficial in lista_oficial_plana:
            conteudo_prompt.append(f"- {f_oficial}")

        # --- SEU PROMPT ORIGINAL INTACTO (COM O LOG DE INSPEÇÃO) ---
        conteudo_prompt.extend([
            "\n--- TAREFA REAL ---",
            "Agora avalie as fatias do documento real anexadas abaixo.",
            "",
            "🚨 ATENÇÃO MÁXIMA: ARMADILHA VISUAL DETECTADA 🚨",
            "Temos um problema severo de 'falso vazio'. Traços feitos a lápis que são muito fracos, curvos, ou que apenas raspam a quina inferior do quadrado estão sendo ignorados pela sua visão porque se camuflam no texto que vaza do verso da folha (bleed-through).",
            "",
            "Para combater isso, você DEVE forçar o seu raciocínio visual passo a passo ANTES de dar a resposta.",
            "",
            "⚠️ PASSO 1: LOG DE INSPEÇÃO VISUAL ⚠️",
            "Antes de listar os [X] ou [ ], crie um bloco de texto descrevendo fisicamente a área do quadrado de cada frase.",
            "Exemplo de Log:",
            "- Frase X: O quadrado está limpo. O fundo tem manchas do verso, mas nenhum traço.",
            "- Frase Y: Há uma linha fina e curva tocando a base do quadrado e entrando na primeira letra.",
            "",
            "⚠️ PASSO 2: A REGRA IMPLACÁVEL DO [X] ⚠️",
            "Se no seu Log de Inspeção você descreveu QUALQUER linha (reta, curva, fio de cabelo, cinza fraco) que toque o quadrado ou suas quinas, você É OBRIGADO a marcar [X] no Passo 3. A intenção do aluno prevalece sobre a sujeira do fundo. Na dúvida com a sujeira, assuma que é um traço e marque [X].",
            "",
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
                telemetria_total["in"] += t_in
                telemetria_total["out"] += t_out
                telemetria_total["brl"] += (t_in + t_out) * 0.000001 * 5.25
            except:
                pass

            # --- A ÚNICA ALTERAÇÃO: O ZÍPER QUE LÊ O MARCADOR PERFEITAMENTE ---
            linhas = texto_transcrito.split('\n')
            for linha in linhas:
                linha_limpa = linha.strip()
                if not linha_limpa: continue
                
                marcado = False
                frase_lida = ""

                linha_upper = linha_limpa.upper()
                
                # Procura pelo [X] ou [ ] ignorando se a IA colocou hífens ou espaços antes
                if "[X]" in linha_upper or "(X)" in linha_upper:
                    marcado = True
                    frase_lida = linha_limpa.replace("[X]", "").replace("[x]", "").replace("(X)", "").replace("(x)", "").replace("-", "").replace("*", "").strip()
                elif "[ ]" in linha_upper or "( )" in linha_upper:
                    marcado = False
                    frase_lida = linha_limpa.replace("[ ]", "").replace("( )", "").replace("-", "").replace("*", "").strip()
                else: 
                    continue # Ignora o log visual na hora de contabilizar os níveis

                for f_oficial in estado_final_frases.keys():
                    similaridade = difflib.SequenceMatcher(None, f_oficial.lower(), frase_lida.lower()).ratio()
                    if similaridade >= 0.80:
                        if marcado: estado_final_frases[f_oficial] = True
                        break
                            
        except Exception as e:
            st.error(f"Erro na extração ancorada: {e}")

        # --- RECONSTRUÇÃO DOS DADOS ---
        resultado_final = {cat: [] for cat in mapeamento_fidedigno.keys()}
        for categoria, perguntas in mapeamento_fidedigno.items():
            for frase in perguntas:
                marcado_final = estado_final_frases.get(frase, False)
                resultado_final[categoria].append({
                    "pergunta": frase,
                    "marcado": marcado_final,
                    "escala": 4 if marcado_final else 0
                })

        st.write("🧹 Limpando cache de servidores...")
        registrar_consumo("OCR Transcricional (Muro Cego à Direita)", modelo_config, telemetria_total["in"] + telemetria_total["out"], telemetria_total["brl"])
        
        for arq in arquivos_ia_alvo + list(arquivos_ia_treino.values()):
            try: genai.delete_file(arq.name)
            except: pass
            
        for f in recortes + arquivos_temp_norm:
            try: os.remove(f)
            except: pass
        if os.path.exists(caminho_pdf): os.remove(caminho_pdf)

        return {
            "sucesso": True, 
            "dados": resultado_final, 
            "telemetria": {"modelo": modelo_config, "in": telemetria_total["in"], "out": telemetria_total["out"], "brl": telemetria_total["brl"]}
        }

    except Exception as e:
        return {"erro": f"Falha Crítica no Backend OCR: {str(e)}"}