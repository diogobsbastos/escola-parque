# ARQUIVO: backend_diagnostico.py
import os

def verificar_integridade():
    """Verifica se os arquivos vitais da Escola Parque estão presentes."""
    # REDES SOCIAIS BANIDAS: Lista atualizada apenas com os módulos pedagógicos.
    arquivos_vitais = [
        'app.py', 
        'funcoes_fla.py', 
        'funcoes_lab.py', 
        'backend_infra.py',
        'pagina_alunos.py',
        'pagina_treinamento.py',
        'pagina_motor.py' # Novo motor que vamos criar
    ]
    status = {arq: os.path.exists(arq) for arq in arquivos_vitais}
    return status

def checar_credenciais():
    """Verifica se os arquivos de configuração locais existem."""
    # Removidos tokens de YouTube e visual_config. Vamos focar nos BDs.
    chaves = ['db_config.json', 'mcp_config.json']
    return {chave: os.path.exists(chave) for chave in chaves}