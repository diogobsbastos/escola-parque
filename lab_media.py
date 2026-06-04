import os
import glob
import time
import streamlit as st
import yt_dlp
import ffmpeg

# --- UTILITY ---
def limpar_pasta_downloads(pasta_especifica=None):
    """Limpa arquivos temporários da raiz ou de uma pasta específica."""
    extensoes = ["*.mp3", "*.mp4", "*.part", "temp_*.mp3"]
    diretorio = pasta_especifica if pasta_especifica else "."
    
    if os.path.exists(diretorio):
        for ext in extensoes:
            caminho_busca = os.path.join(diretorio, ext)
            files = glob.glob(caminho_busca)
            for f in files:
                try: 
                    os.remove(f)
                except: 
                    pass # Ignora se o arquivo estiver bloqueado no momento

def download_progress_hook(d):
    """Atualiza a barra de progresso do Streamlit em tempo real."""
    if d['status'] == 'downloading':
        # O yt-dlp armazena metadados extras no info_dict
        pbar = d.get('info_dict', {}).get('progress_bar_widget')
        
        if pbar:
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes')
            
            if total and downloaded:
                percent = int(downloaded / total * 100)
                msg = f"📥 Baixando: {percent}% ({downloaded / (1024*1024):.1f}MB de {total / (1024*1024):.1f}MB)"
                pbar.progress(percent, text=msg)
                
                # MELHORIA: Pequena pausa para forçar o Streamlit a atualizar a UI
                time.sleep(0.01)

def baixar_audio_yt_dlp(entrada_usuario: str, progress_widget=None, pasta_destino="downloads_setlist"):
    """
    Versão com Limpeza Agressiva e Timestamp para evitar WinError 32.
    """
    # 1. Garante que a pasta existe
    if not os.path.exists(pasta_destino):
        os.makedirs(pasta_destino)
    
    # 2. LIMPEZA AGRESSIVA: Tenta remover restos de downloads falhos antes de começar
    try:
        for f in os.listdir(pasta_destino):
            # Remove arquivos .part ou .mp4 temporários que travam o Windows
            if f.endswith(".part") or f.endswith(".mp4") or f.endswith(".mp3"):
                caminho_full = os.path.join(pasta_destino, f)
                try:
                    os.remove(caminho_full)
                except:
                    pass # Se falhar aqui, o Windows realmente travou o processo
    except:
        pass
        
    eh_link = "http" in entrada_usuario
    
    # Adicionamos um timestamp ao nome do arquivo para evitar conflitos de processo
    # caso o usuário tente baixar o mesmo link seguidamente.
    timestamp = int(time.time())
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'retries': 10,
        'outtmpl': os.path.join(pasta_destino, f'%(id)s_{timestamp}.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ffmpeg_location': os.getcwd(),
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
    }
    
    if progress_widget:
        ydl_opts['progress_hooks'] = [download_progress_hook]
        ydl_opts['info_dict'] = {'progress_bar_widget': progress_widget}

    if not eh_link: 
        ydl_opts['default_search'] = 'ytsearch1'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(entrada_usuario, download=True)
            video = info['entries'][0] if 'entries' in info else info
            
            arquivo_base = ydl.prepare_filename(video)
            arquivo_mp3 = os.path.splitext(arquivo_base)[0] + ".mp3"
            
            # Pausa técnica para o Windows liberar o descritor do arquivo pós-conversão
            time.sleep(2.0) 
            
            if os.path.exists(arquivo_mp3):
                return {
                    "titulo": video.get('title', 'Desconhecido'),
                    "link": video.get('webpage_url', entrada_usuario),
                    "arquivo": arquivo_mp3,
                    "thumb": video.get('thumbnail', None)
                }
    except Exception as e:
        st.error(f"Erro download: {e}")
        return None

def baixar_audio_youtube(entrada_usuario: str, progress_widget=None):
    return baixar_audio_yt_dlp(entrada_usuario, progress_widget, pasta_destino=".")

def cortar_audio_ffmpeg(input_path: str, output_path: str, start_time: str, end_time: str) -> bool:
    try:
        def time_to_seconds(t_str):
            if ':' in t_str:
                parts = list(map(int, t_str.split(':')))
                if len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
                elif len(parts) == 2: return parts[0] * 60 + parts[1]
            return int(t_str)

        start_sec = time_to_seconds(start_time)
        end_sec = time_to_seconds(end_time)
        duration_sec = max(0, end_sec - start_sec)

        if duration_sec < 5: return False

        (
            ffmpeg
            .input(input_path, ss=start_time, t=duration_sec)
            .output(output_path, acodec='libmp3lame', audio_bitrate='192k')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return os.path.exists(output_path)
    except: 
        return False