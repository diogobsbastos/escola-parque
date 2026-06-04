# Tests do innova_bridge

Os testes "ao vivo" do F1 acontecem dentro do Streamlit, no botao
"Conexao SQL real via asyncpg" do expander Diagnostico tecnico
(pagina_config_bd.py).

Quando F2 chegar (Pydantic + consolidate.py), aqui virao:
  - test_consolidate_csv.py   (CSV do Forms -> canonical dict)
  - test_pai_schema.py        (validacao Pydantic do PAI v1.0)
  - test_paridade_react.py    (PAI gerado em Python == PAI gerado no Next.js)
