import streamlit as st
import pandas as pd
import json
import os

def renderizar():
    # ── Cabeçalho com título + botão ZERAR ──
    col_t, col_z = st.columns([4, 1])
    with col_t:
        st.title("💸 Gestão de Custos e Tokens")
        st.caption("Log financeiro detalhado por operação (Multi-Provider LiteLLM).")
    with col_z:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Zerar Histórico",
                      key="btn_zerar_historico",
                      type="secondary",
                      use_container_width=True,
                      help="Apaga TODO o histórico de consumo e reseta os totais. Não pode ser desfeito."):
            st.session_state["__confirmar_zerar_hist__"] = True

    arquivo_historico = "historico_consumo.json"

    # ── Diálogo de confirmação do ZERAR ──
    if st.session_state.get("__confirmar_zerar_hist__"):
        with st.container(border=True):
            st.warning(
                "⚠️ **Tem certeza que quer zerar TODO o histórico financeiro?**\n\n"
                "Essa ação apaga `historico_consumo.json` permanentemente. "
                "Os totais (tokens, gasto, tempo) voltam a zero. **Não dá pra desfazer.**"
            )
            cc1, cc2, _ = st.columns([1, 1, 3])
            with cc1:
                if st.button("✅ Sim, zerar", type="primary", key="btn_zerar_sim"):
                    try:
                        if os.path.exists(arquivo_historico):
                            os.remove(arquivo_historico)
                        st.success("✅ Histórico zerado. Recarregando...")
                        st.session_state.pop("__confirmar_zerar_hist__", None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Falha ao zerar: {e}")
            with cc2:
                if st.button("❌ Cancelar", key="btn_zerar_nao"):
                    st.session_state.pop("__confirmar_zerar_hist__", None)
                    st.rerun()
        return

    # ── Fonte primária: agent_run_logs do Supabase (mesma tabela que o frontend lê).
    #    Fallback: historico_consumo.json local (compat com runs antigos). ──
    fonte = "Supabase · agent_run_logs"
    dados = None
    try:
        from innova_bridge.repositories import agent_run_logs_repo
        dados = agent_run_logs_repo.listar_runs(limit=500)
    except Exception:
        dados = None

    if not dados:
        fonte = "Local · historico_consumo.json"
        if os.path.exists(arquivo_historico):
            try:
                with open(arquivo_historico, "r", encoding="utf-8") as f:
                    dados = json.load(f)
            except Exception:
                dados = None

    if not dados:
        st.info("📭 Nenhum dado financeiro registrado ainda (Supabase e local vazios).")
        return

    try:
        st.caption(f"Fonte: **{fonte}**")
        df = pd.DataFrame(dados)

        # ── Identificação dinâmica da coluna de tempo (compat com logs antigos) ──
        col_tempo_log = None
        for col in ["timestamp", "data", "data_hora", "hora", "date"]:
            if col in df.columns:
                col_tempo_log = col
                break

        if col_tempo_log:
            df = df.sort_values(by=col_tempo_log, ascending=False)

        # ── Garante todas as colunas (operações antigas não tinham granular) ──
        for c in ["provedor", "tokens_in", "tokens_out", "tokens_cache"]:
            if c not in df.columns:
                df[c] = 0 if c.startswith("tokens") else ""

        # Backfill: se tokens_in/out são 0 mas tokens (total) existe, usa total como input
        try:
            mask_vazio = (df["tokens_in"].fillna(0) == 0) & (df["tokens_out"].fillna(0) == 0) & (df.get("tokens", 0) > 0)
            df.loc[mask_vazio, "tokens_in"] = df.loc[mask_vazio, "tokens"]
        except Exception:
            pass

        # ── Totais agregados (resumo do topo) ──
        if "tokens" in df.columns:
            total_tokens = df["tokens"].fillna(0).sum()
        else:
            total_tokens = (df["tokens_in"].fillna(0).sum() + df["tokens_out"].fillna(0).sum())
        total_in    = df["tokens_in"].fillna(0).sum()
        total_out   = df["tokens_out"].fillna(0).sum()
        total_cache = df["tokens_cache"].fillna(0).sum()

        gasto_total = df["custo_brl"].fillna(0).sum() if "custo_brl" in df.columns else 0.0
        custo_medio = gasto_total / len(df) if len(df) > 0 else 0.0
        tempo_total = df["tempo_execucao"].fillna(0).sum() if "tempo_execucao" in df.columns else 0.0

        # ── Formatação brasileira ──
        def fmt_int(v): return f"{int(v):,}".replace(",", ".")
        def fmt_brl(v, casas=4):
            txt = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return txt
        def fmt_seg(v):
            return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        # ── Dashboard COMPACTO: 7 métricas em UMA única linha alinhada ──
        with st.container(border=True):
            ch1, ch2 = st.columns([3, 2])
            with ch1:
                st.markdown("##### 📊 Resumo Geral")
            with ch2:
                st.caption(f"📦 {len(df)} operação(ões) registrada(s)")

            cs = st.columns(7)
            cs[0].metric("📥 In",          fmt_int(total_in))
            cs[1].metric("📤 Out",         fmt_int(total_out))
            cs[2].metric("💾 Cache",       fmt_int(total_cache))
            cs[3].metric("🧮 Total",       fmt_int(total_tokens))
            cs[4].metric("💰 Gasto R$",    f"{fmt_brl(gasto_total, 2)}")
            cs[5].metric("📐 Médio R$",    f"{fmt_brl(custo_medio, 4)}")
            cs[6].metric("⏱️ Tempo (s)",   f"{fmt_seg(tempo_total)}")

        st.markdown("")

        # ── Log detalhado: uma linha por operação ──
        with st.container(border=True):
            st.markdown("##### 📜 Log Detalhado por Operação")
            st.caption("Cada linha representa uma chamada LLM — útil para comparar custo entre provedores manualmente.")

            colunas_desejadas = ["timestamp", "origem", "modelo", "processo",
                                 "tokens_in", "tokens_out", "tokens_cache",
                                 "custo_brl", "tempo_execucao"]

            # Garante presença de todas
            for c in colunas_desejadas:
                if c not in df.columns:
                    df[c] = ""

            df_log = df[colunas_desejadas].copy()
            df_log = df_log.rename(columns={
                "timestamp":      "Quando",
                "origem":         "🌐 Origem",
                "modelo":         "Modelo",
                "processo":       "Agente",
                "tokens_in":      "📥 In",
                "tokens_out":     "📤 Out",
                "tokens_cache":   "💾 Cache",
                "custo_brl":      "💰 R$",
                "tempo_execucao": "⏱️ s",
            })

            st.dataframe(df_log, use_container_width=True, hide_index=True, height=480)

        # ── Exportar CSV (atalho útil pra análise externa) ──
        try:
            csv = df_log.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Baixar log completo (CSV)",
                data=csv,
                file_name="historico_consumo_escola_parque.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except Exception:
            pass

    except Exception as e:
        st.error(f"Erro ao processar o painel financeiro: {str(e)}")
