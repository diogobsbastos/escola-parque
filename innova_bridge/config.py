"""
innova_bridge/config.py - Configuracao de conexao com o BD ativo do carrossel.

Le sempre do storage_bancos.get_active_bd_decifrado() — assim, trocar o BD
ativo no Streamlit reflete automaticamente aqui (next call).
"""

from __future__ import annotations

from typing import Optional


class ConfigError(Exception):
    """Erro de configuracao do innova_bridge (ex: nenhum BD ativo)."""
    pass


def get_bd_ativo() -> dict:
    """Retorna o dict do BD ativo do carrossel (campos decifrados).

    Levanta ConfigError se nenhum BD estiver marcado como is_primary=True
    no bancos_pool.json, ou se faltar database_url.
    """
    # Import tardio pra evitar ciclo e pra nao quebrar se storage_bancos
    # nao estiver disponivel no momento do import do innova_bridge.
    import storage_bancos as sb

    bd = sb.get_active_bd_decifrado()
    if bd is None:
        raise ConfigError(
            "Nenhum BD marcado como EM USO no carrossel. "
            "Abra Configuracoes -> Banco de Dados (Innova V2) e ative um."
        )
    if not bd.get("database_url"):
        raise ConfigError(
            f"BD '{bd.get('label')}' nao tem database_url cadastrada. "
            "Edite o BD no carrossel e cole o postgresql://... do pooler."
        )
    return bd


def get_database_url() -> str:
    """Atalho: retorna so a database_url do BD ativo."""
    return get_bd_ativo()["database_url"]


def get_service_role() -> Optional[str]:
    """Atalho: retorna a service_role JWT do BD ativo (pode ser vazia)."""
    return get_bd_ativo().get("service_role") or None


def get_label_ativo() -> str:
    """Atalho: label amigavel do BD ativo (pra mostrar na UI)."""
    return get_bd_ativo().get("label", "(sem label)")


def get_region_ativo() -> str:
    """Atalho: regiao do BD ativo (pra logging)."""
    return get_bd_ativo().get("region", "-")
