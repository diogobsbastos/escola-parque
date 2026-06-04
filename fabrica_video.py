import os
import textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from proglog import ProgressBarLogger # <--- IMPORTAÇÃO ADICIONADA
from moviepy.editor import (
    VideoFileClip, 
    ImageClip, 
    AudioFileClip, 
    CompositeVideoClip, 
    ColorClip, 
    vfx
)

# --- CLASSE DE LOGGER CUSTOMIZADO (ADICIONADA) ---
class StreamlitLogger(ProgressBarLogger):
    def __init__(self, callback_func):
        super().__init__()
        self.callback_func = callback_func
    
    def callback(self, **changes):
        for (parameter, value) in changes.items():
            pass 

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar == 't': # 't' é a barra de tempo principal
            total = self.bars[bar]['total']
            if total > 0:
                porcentagem = (value / total) * 100
                # [ALTERADO] Envia apenas o NÚMERO (float) para o frontend criar a barra
                self.callback_func(porcentagem)

# --- CONFIGURAÇÕES ---
RESOLUCAO_VERTICAL = (1080, 1920) # 9:16
FPS_PADRAO = 30

def carregar_midia_segura(caminho_arquivo, duracao_padrao=10.0):
    """
    [NOVO] Função blindada contra erros de FFmpeg.
    Se o arquivo fingir ser vídeo mas for imagem (erro 'pipe'), carrega como imagem.
    """
    if not os.path.exists(caminho_arquivo):
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_arquivo}")

    try:
        # Tenta carregar como vídeo
        clip = VideoFileClip(caminho_arquivo)
        
        # Validação Crítica: Se duração for None ou 0, o FFmpeg falhou
        if clip.duration is None or clip.duration == 0:
            clip.close()
            raise ValueError("Duração inválida detectada (provável imagem estática).")
            
        return clip

    except Exception as e:
        print(f"⚠️ Aviso: Falha ao ler vídeo '{caminho_arquivo}'. Tentando fallback para imagem. Erro: {e}")
        try:
            # Fallback: Carrega como imagem estática
            img_clip = ImageClip(caminho_arquivo)
            img_clip = img_clip.set_duration(duracao_padrao).set_fps(FPS_PADRAO)
            return img_clip
        except Exception as e_img:
            raise Exception(f"❌ FALHA FATAL: Arquivo corrompido ou formato desconhecido. {e_img}")

def criar_imagem_texto_pil(texto, tamanho=(1080, 1920), fontsize=60):
    """
    [SEU CÓDIGO] Cria imagem de texto transparente via PIL.
    """
    img = Image.new('RGBA', tamanho, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    try:
        # Tenta Arial, senão usa default
        font = ImageFont.truetype("arial.ttf", fontsize)
    except:
        font = ImageFont.load_default()

    largura_max_chars = 25
    linhas = []
    for paragrafo in texto.split('\n'):
        linhas.extend(textwrap.wrap(paragrafo, width=largura_max_chars))
    
    texto_formatado = "\n".join(linhas)
    
    # Desenha centralizado com âncora 'mm' (middle-middle)
    w, h = tamanho
    draw.multiline_text(
        (w/2, h/2), 
        texto_formatado, 
        font=font, 
        fill="white", 
        align="center", 
        anchor="mm",
        stroke_width=2, 
        stroke_fill="black" # Adicionei borda preta para legibilidade
    )
    
    return np.array(img)

def renderizar_video_com_texto(audio_path, texto_overlay, fundo_path, output_path, callback_progresso=None):
    """
    Motor Principal: Junta Áudio + Fundo (Seguro) + Texto (PIL)
    Args:
        callback_progresso (function): Função opcional para enviar status para a tela.
    """
    # Função interna para atualizar o status
    def avisar(mensagem):
        if callback_progresso:
            callback_progresso(mensagem)
        print(f"STATUS: {mensagem}")

    try:
        avisar(f"🎬 Iniciando motor de renderização: {output_path}")

        # 1. Carregar Áudio
        avisar("📥 Carregando áudio...")
        if not os.path.exists(audio_path):
            return False, f"Áudio não encontrado: {audio_path}"
            
        audio = AudioFileClip(audio_path)
        duracao = audio.duration
        
        # 2. Configurar Fundo (USANDO O CARREGADOR SEGURO)
        avisar("🖼️ Processando mídia de fundo (Crop & Resize)...")
        
        # Se não houver caminho de fundo, cria cor sólida
        if fundo_path and os.path.exists(fundo_path):
            clip_fundo = carregar_midia_segura(fundo_path, duracao_padrao=duracao)
        else:
            clip_fundo = ColorClip(size=RESOLUCAO_VERTICAL, color=(20, 20, 20)).set_duration(duracao).set_fps(FPS_PADRAO)

        # Ajuste de Loop/Corte do fundo
        if clip_fundo.duration < duracao:
            clip_fundo = clip_fundo.loop(duration=duracao)
        else:
            clip_fundo = clip_fundo.subclip(0, duracao)

        # Crop/Resize 9:16 Inteligente
        w, h = RESOLUCAO_VERTICAL
        fw, fh = clip_fundo.size
        
        # Lógica de Crop Centralizado
        if (fw/fh) > (w/h):
            new_w = int(fh * (w/h))
            clip_fundo = clip_fundo.crop(x1=fw/2 - new_w/2, width=new_w, height=fh)
        else:
            new_h = int(fw / (w/h))
            clip_fundo = clip_fundo.crop(y1=fh/2 - new_h/2, width=fw, height=new_h)
            
        clip_fundo = clip_fundo.resize(RESOLUCAO_VERTICAL)
        clip_fundo = clip_fundo.fx(vfx.colorx, 0.6) # Escurece um pouco para o texto brilhar

        # 3. Criar Texto (Via PIL)
        avisar("✍️ Desenhando legendas (Engine: Pillow)...")
        
        # Limpa o texto para evitar caracteres ruins
        linhas_limpas = [l for l in texto_overlay.split('\n') if l.strip() and not l.startswith('[')]
        texto_limpo = "\n".join(linhas_limpas[:15]) # Limita tamanho para não estourar tela
        
        imagem_texto_array = criar_imagem_texto_pil(texto_limpo, tamanho=RESOLUCAO_VERTICAL)
        txt_clip = ImageClip(imagem_texto_array).set_duration(duracao)

        # 4. Composição
        avisar("🔨 Montando timeline final...")
        video_final = CompositeVideoClip([clip_fundo, txt_clip])
        video_final = video_final.set_audio(audio)
        
        # 5. Renderização Otimizada
        avisar("🚀 RENDERIZANDO ARQUIVO FINAL (Aguarde o processamento)...")
        
        # --- CRIA O LOGGER CUSTOMIZADO ---
        meu_logger = StreamlitLogger(avisar)

        video_final.write_videofile(
            output_path, 
            fps=FPS_PADRAO, 
            codec='libx264', 
            audio_codec='aac', 
            preset='ultrafast', # Rápido para testes
            threads=4,
            logger=meu_logger   # <--- USA O LOGGER AQUI
        )
        
        # Limpeza de recursos
        avisar("✨ Finalizando e limpando memória...")
        audio.close()
        clip_fundo.close()
        video_final.close()
        
        return True, "Vídeo renderizado com sucesso!"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Erro Fatal na Renderização: {str(e)}"