"""
paginas_extras.py — Registro dinâmico de páginas do Backend (Escola Parque V3)
------------------------------------------------------------------------------
ESTE é o arquivo onde páginas novas do backend entram. O app.py lê esta lista e
gera o botão na sidebar + o dispatch automaticamente. Assim o app.py (1.700+
linhas) fica CONGELADO: nunca mais precisa de push manual pra adicionar página.

Como adicionar uma página nova (fluxo 100% automático, sobe pela API do GitHub):
  1) criar o arquivo pagina_xxx.py com uma função render_pagina_xxx()
  2) importar aqui e adicionar um dict em PAGINAS_EXTRAS:
        {"view": "xxx", "label": "🔧 Minha Página", "render": render_pagina_xxx}
  3) pronto — o app.py já mostra o botão e renderiza, sem edição manual.

Cada item:
  view   -> chave única do view_mode (string, sem espaços)
  label  -> texto do botão na sidebar (pode ter emoji)
  render -> função que desenha a página (sem argumentos)
"""

# Imports tolerantes: se uma página tiver erro de import, ela é PULADA do
# registro (com um placeholder), sem derrubar o backend inteiro.
_PAGINAS = []


def _registrar(view, label, import_path, func_name):
    """Tenta importar func_name de import_path e registra a página. Se falhar,
    registra um placeholder que mostra o erro só naquela aba."""
    try:
        modulo = __import__(import_path, fromlist=[func_name])
        render = getattr(modulo, func_name)
    except Exception as e:  # noqa: BLE001
        _msg = f"{type(e).__name__}: {e}"

        def render(_m=_msg, _l=label):  # placeholder isolado
            import streamlit as st
            st.error(f"Página '{_l}' indisponível — {_m}")

    _PAGINAS.append({"view": view, "label": label, "render": render})


# ── PÁGINAS REGISTRADAS ──────────────────────────────────────────────────────
_registrar(
    view="email",
    label="✉️ Configurar E-mail",
    import_path="pagina_email",
    func_name="render_pagina_email",
)


PAGINAS_EXTRAS = _PAGINAS
