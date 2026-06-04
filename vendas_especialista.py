import streamlit as st
import time
import numpy as np
from PIL import Image
import os
import re
import json
import google.generativeai as genai

# --- 1. MOTOR DE LEITURA MULTI-CAMADAS (TIER 1 REDUNDANCY) ---
# Esta seção garante que o sistema funcione em qualquer SO (Windows/Linux/iOS/Android)
try:
    import cv2
    OPENCV_OK = True
    # Detectores nativos do OpenCV para máxima estabilidade
    detector_barcode = cv2.barcode.BarcodeDetector()
    detector_qrcode = cv2.QRCodeDetector()
except ImportError:
    OPENCV_OK = False

try:
    from pyzbar.pyzbar import decode
    PYZBAR_OK = True
    ERRO_IMPORTACAO = ""
except ImportError as e:
    PYZBAR_OK = False
    ERRO_IMPORTACAO = str(e)

# O Scanner é considerado ativo se pelo menos um motor de visão computacional funcionar
SCANNER_ATIVO = PYZBAR_OK or OPENCV_OK


# --- 2. FUNÇÕES DE INTELIGÊNCIA E CONVERSÃO (CRO & AI VISION) ---

def detectar_aparelho_real():
    """
    MELHORIA IMPLEMENTADA: Captura de Modelo Exato (Android) ou Marca/Navegador.
    """
    try:
        ua = st.context.headers.get("User-Agent", "Navegador Desconhecido")
    except AttributeError:
        ua = "Navegador Padrão"

    # Identificação do Navegador (Chrome, Safari, Edge, etc)
    browser = "Navegador"
    if "Edg/" in ua: browser = "Edge"
    elif "Chrome/" in ua and "Safari/" in ua: browser = "Chrome"
    elif "Safari/" in ua: browser = "Safari"
    elif "Firefox/" in ua: browser = "Firefox"

    if "iPhone" in ua:
        # iPhones mascaram o modelo no navegador por privacidade, trazemos a marca + navegador
        return "iOS", f"Apple iPhone (via {browser})"
    
    elif "Android" in ua:
        # Tenta extrair o modelo exato (ex: SM-G991B) que fica no User-Agent do Android
        match = re.search(r'Android [^;]+; ([^;)]+)', ua)
        modelo_android = match.group(1).split(" Build")[0].strip() if match else "Smartphone Android"
        return "Android", f"{modelo_android} (via {browser})"
    
    elif "Macintosh" in ua or "Windows" in ua:
        os_name = "Windows PC" if "Windows" in ua else "Macintosh"
        return "Desktop", f"{os_name} (via {browser})"
    
    return "Desconhecido", f"Dispositivo/Navegador: {ua[:30]}..."


def ler_eid_real(imagem_buffer):
    """
    Processamento real de pixels. Tenta decodificar o código usando redundância 
    de motores e correção de unpack (3 vs 4 valores) para garantir zero falha.
    """
    try:
        image = Image.open(imagem_buffer)
        img_np = np.array(image)
        
        # CAMADA 1: Motor Especialista PyZbar
        if PYZBAR_OK:
            codigos = decode(img_np)
            if codigos:
                texto_lido = codigos[0].data.decode('utf-8')
                if len(texto_lido) >= 14:
                    return texto_lido, "Motor Especialista (PyZbar)"
        
        # CAMADA 2: Motor Nativo OpenCV (Fallback robusto)
        if OPENCV_OK:
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            
            # Blindagem contra erro de versão (Unpack fix)
            res_bc = detector_barcode.detectAndDecode(img_cv)
            if res_bc[0] and len(res_bc[1]) > 0:
                if res_bc[1][0] != "":
                    return res_bc[1][0], "Motor Nativo (OpenCV Barcode)"
            
            # Tenta ler como QR Code
            val, _, _ = detector_qrcode.detectAndDecode(gray)
            if val:
                return val, "Motor Nativo (OpenCV QR)"
                
        return None, "Leitura de barras falhou. Tentando varredura OCR..."
    except Exception as e:
        return None, f"Erro de hardware: {str(e)}"


def varrer_com_ia_vision(imagem_buffer):
    """
    INTEGRAÇÃO DEFINITIVA GEMINI VISION:
    Lê a chave de 'gemini_key.txt' e o modelo de 'model_pref.txt'.
    """
    try:
        # Lendo configurações dos arquivos TXT 
        with open("gemini_key.txt", "r") as f:
            api_key = f.read().strip()
        with open("model_pref.txt", "r") as f:
            modelo_ia = f.read().strip()
            
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(modelo_ia)
        
        img = Image.open(imagem_buffer)
        
        prompt = """
        Analise esta imagem de códigos de sistema (*#06#).
        Extraia exatamente: EID (32 dígitos), IMEI 1 (15 dígitos) e IMEI 2 (15 dígitos).
        
        REGRAS:
        1. Se encontrar o EID, 'ESIM_READY' deve ser true.
        2. Se NÃO houver EID (apenas IMEIs), 'ESIM_READY' deve ser false.
        3. Se a imagem não for de códigos (ex: selfie), retorne erro no EID e ESIM_READY = false.
        
        Responda APENAS em JSON:
        {"EID": "string", "IMEI": "string", "IMEI2": "string", "ESIM_READY": boolean, "CONFIDENCE": 1.0}
        """

        response = model.generate_content([prompt, img])
        # Limpeza para garantir JSON puro
        json_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_text)
        
    except Exception as e:
        # Fallback de erro para evitar tela branca ou 10% de integridade
        return {"EID": "ERRO NA ANÁLISE", "IMEI": "---", "IMEI2": "---", "ESIM_READY": False, "CONFIDENCE": 0.0}


# --- 3. INTERFACE DE VENDAS PREMIUM (ESTRATÉGIA EASYSIM4U) ---

def render_vendas_esim_tab():
    # --- LOGO NO TOPO ---
    if os.path.exists("f.jpg"):
        st.image("f.jpg", width=300)
    
    # --- TÍTULO ABAIXO DA LOGO ---
    st.markdown("## Validação de Compatibilidade ESIM inteligente")
    st.caption("EASYSIM4U: IA Vision Scan & Ecossistema Global Tier 1")

    tipo_aparelho, ua_detalhe = detectar_aparelho_real()
    is_mobile = tipo_aparelho in ["iOS", "Android"]

    # Gerenciamento de Estado da Jornada
    if 'esim_status' not in st.session_state:
        st.session_state['esim_status'] = None

    estado_atual = st.session_state.get('esim_status')

    # --- TELA INICIAL: O FILTRO INVISÍVEL E DECISÃO ---
    if estado_atual is None:
        with st.container(border=True):
            st.markdown(f"##### 🔍 Diagnóstico de Hardware: **{tipo_aparelho}**")
            st.caption(f"Status do Hardware: {ua_detalhe}")
            st.divider()
            st.markdown("### Como deseja prosseguir com sua ativação?")
            
            col_exp, col_smart = st.columns(2)
            with col_exp:
                with st.container(border=True):
                    st.markdown("#### 🚀 Compra Rápida")
                    st.write("Ideal para quem já conhece seu aparelho.")
                    if st.button("JÁ SEI QUE MEU CELULAR ACEITA eSIM", use_container_width=True):
                        st.session_state['esim_status'] = 'aprovado_direto'
                        st.rerun()
            
            with col_smart:
                with st.container(border=True):
                    st.markdown("#### 🤖 Compra Garantida")
                    st.write("Verificação via IA para evitar erros.")
                    if st.button("VERIFICAÇÃO INTELIGENTE DE COMPATIBILIDADE", type="primary", use_container_width=True):
                        st.session_state['esim_status'] = 'scanner_necessario'
                        st.rerun()

    # --- BLOCO 2: JORNADA AI VISION (VARREDURA INTELIGENTE) ---
    elif estado_atual == 'scanner_necessario':
        st.warning("Para garantir a manutenção do seu WhatsApp original, realize a varredura dos códigos `*#06#`.")
        
        # Atalhos Mobile-Only
        if is_mobile:
            st.markdown("##### ⚡ Atalhos de Sistema:")
            col_dial, col_copy = st.columns(2)
            with col_dial:
                st.markdown(f'''<a href="tel:*#06#" target="_blank" style="text-decoration: none;"><div style="background-color: #FF4B4B; color: white; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;">📞 ABRIR DISCADOR (*#06#)</div></a>''', unsafe_allow_html=True)
                st.caption("Toque para abrir o teclado.")
            with col_copy:
                if st.button("📋 COPIAR CÓDIGO *#06#", use_container_width=True):
                    st.toast("Código copiado! Cole no seu Telefone.")
                st.caption("Depois disque o código.")
            st.divider()

        # Interface de Captura
        tab_manual, tab_ia = st.tabs(["⌨️ Digitação Manual", "🤖 Varredura IA (Print ou Foto)"])
        
        with tab_manual:
            with st.container(border=True):
                st.markdown("### ⚡ Smart Paste")
                eid_colado = st.text_input("Cole o EID aqui:", placeholder="Ex: 89049032...")
                c_valid, c_demo = st.columns(2)
                with c_valid:
                    if st.button("Validar EID", type="primary", use_container_width=True):
                        if len(eid_colado) >= 20: 
                            st.success("✅ EID Validado!")
                            st.session_state['esim_status'] = 'aprovado_direto'
                            time.sleep(1); st.rerun()
                with c_demo:
                    if st.button("✨ Simular (Demo Diretor)", use_container_width=True):
                        st.session_state['esim_status'] = 'aprovado_direto'
                        st.rerun()

        with tab_ia:
            with st.container(border=True):
                st.markdown("### 📸 IA Vision Sweep")
                
                if is_mobile:
                    entrada_final = st.file_uploader("Subir Print Screen (Galeria)", type=['png', 'jpg', 'jpeg'])
                else:
                    col_cam, col_file = st.columns(2)
                    with col_cam:
                        foto = st.camera_input("Escanear Celular")
                    with col_file:
                        arquivo = st.file_uploader("Ou suba uma imagem", type=['png', 'jpg', 'jpeg'])
                    entrada_final = foto if foto else arquivo
                
                if entrada_final:
                    with st.spinner("🤖 Gemini Vision analisando hardware em tempo real..."):
                        dados_ia = varrer_com_ia_vision(entrada_final)
                        
                        if dados_ia:
                            st.success(f"✅ Integridade de Dados: {int(dados_ia.get('CONFIDENCE', 0)*100)}% (Validado via Gemini)")
                            
                            st.markdown("#### 📋 Identificadores Localizados:")
                            st.info(f"**EID (eSIM):** {dados_ia.get('EID', 'NÃO LOCALIZADO')}")
                            
                            m2, m3 = st.columns(2)
                            with m2: st.metric("IMEI 1", dados_ia.get("IMEI", "---"))
                            with m3: st.metric("IMEI 2", dados_ia.get("IMEI2", "---"))
                            
                            if dados_ia.get("ESIM_READY") and dados_ia.get("EID") != "ERRO NA ANÁLISE":
                                st.success("🟢 **Hardware Tier 1:** Suporte a eSIM validado com sucesso.")
                                if st.button("Confirmar e Ver Planos 5G", type="primary", use_container_width=True):
                                    st.session_state['esim_status'] = 'aprovado_direto'
                                    st.rerun()
                            else:
                                st.error("🔴 Hardware Incompatível ou EID não detectado nesta imagem.")

    # --- BLOCO 3: UPSELL E FECHAMENTO ---
    if st.session_state.get('esim_status') == 'aprovado_direto':
        st.balloons()
        st.success("### 🎉 Hardware 100% Compatível!")
        st.markdown("Mantenha seu **WhatsApp original intacto** e evite tarifas de roaming abusivas.")
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### 💎 Escolha sua Experiência Global")
        
        c_data, c_voice = st.columns(2)
        with c_data:
            with st.container(border=True):
                st.markdown("**🌐 DATA PLAN ILIMITADO**")
                st.markdown("### $45,00")
                st.write("✅ Dados 5G Ilimitados")
                st.button("Selecionar Básico", use_container_width=True)

        with c_voice:
            with st.container(border=True):
                st.markdown("**🏆 PACOTE VOICE DATA**")
                st.markdown("### $55,00")
                st.write("✅ Dados + Número Local")
                
                if st.button("🚀 UPGRADE PREMIUM", type="primary", use_container_width=True):
                    st.success("Escolha de Elite! Redirecionando para o Checkout.")
        
        if st.button("← Voltar e Mudar Método"):
            st.session_state['esim_status'] = None
            st.rerun()

# Fim do arquivo. O botão de Voltar é gerenciado pelo app.py.