# conectividade.py
# ============================================================
# Projeto: Conectividade – SIMET / UNICEF
# METODOLOGIA: IDÊNTICA AO POWER BI
#
# Base:
# - Dependência Administrativa = Municipal
# - Internet = Sim
#
# Município é 100% se:
# - Todas as escolas municipais com internet
# - já tiveram pelo menos UMA medição com STATUS = "ativo"
#
# Municípios ≥70%:
# - Perc_Escolas_Ativas >= 0.7 (INCLUI 100%)
# ============================================================

import time
from pathlib import Path
from io import BytesIO

import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

# ============================================================
# CONFIGURAÇÕES
# ============================================================

st.set_page_config(page_title="Conectividade – SIMET / UNICEF", layout="wide")
st.title("📡 Conectividade – SIMET / UNICEF")

BASES = Path("bases")
BASES.mkdir(exist_ok=True)

URL_API = "https://api.simet.nic.br/school-measures/v1/getStatusandSchoolInfoUNICEF"

ARQ_ADESOES = BASES / "adesoes_2025_2028.xlsx"
ABA_LISTA = "Lista única"

CACHE_API = BASES / "api_cache.parquet"

TIMEOUT = 120
RETRIES = 3

COL_MUN = "co_municipio"

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def fmt(n):
    return f"{int(n):,}".replace(",", ".")

def baixar_excel(df, nome_arquivo, nome_aba):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=nome_aba)
    buffer.seek(0)
    return buffer

if "cache_limpo" not in st.session_state:
    try:
        st.cache_data.clear()
    except Exception:
        pass
    st.session_state["cache_limpo"] = True

# ============================================================
# LISTA ÚNICA
# ============================================================

@st.cache_data
def carregar_lista():
    df = pd.read_excel(
        ARQ_ADESOES,
        sheet_name=ABA_LISTA,
        dtype={COL_MUN: str}
    )
    df[COL_MUN] = df[COL_MUN].astype(str).str.strip()
    return df.drop_duplicates(subset=[COL_MUN])

# ============================================================
# API SIMET
# ============================================================

def carregar_api(forcar=False):
    if CACHE_API.exists() and not forcar:
        return pd.read_parquet(CACHE_API)

    for _ in range(RETRIES):
        try:
            r = requests.get(URL_API, timeout=TIMEOUT)
            r.raise_for_status()
            df = pd.DataFrame(r.json())
            df.to_parquet(CACHE_API, index=False)
            return df
        except Exception:
            time.sleep(3)

    raise RuntimeError("Erro ao acessar a API SIMET")

# ============================================================
# PROCESSAMENTO – IGUAL AO POWER BI
# ============================================================

def processar_powerbi(df_api, df_lista):

    df_api["co_municipio"] = df_api["co_municipio"].astype(str).str.strip()

    # Total de escolas únicas (universo)
    total_escolas_unicas = df_api["co_entidade"].nunique()

    # BASE = Municipal + Internet = Sim
    base = df_api[
        (df_api["tp_dependencia"] == "Municipal") &
        (df_api["in_internet"] == "Sim")
    ].copy()

    # Apenas municípios da Lista Única
    base = base[base["co_municipio"].isin(df_lista["co_municipio"])]

    # Denominador
    qtd_escolas = (
        base
        .groupby("co_municipio")["co_entidade"]
        .nunique()
        .rename("Qtd_Escolas")
        .reset_index()
    )

    # Numerador
    qtd_escolas_ativas = (
        base[base["status"] == "ativo"]
        .groupby("co_municipio")["co_entidade"]
        .nunique()
        .rename("Qtd_Escolas_Ativas")
        .reset_index()
    )

    df_mun = qtd_escolas.merge(
        qtd_escolas_ativas,
        on="co_municipio",
        how="left"
    ).fillna(0)

    df_mun["Qtd_Escolas_Ativas"] = df_mun["Qtd_Escolas_Ativas"].astype(int)
    df_mun["Perc_Escolas_Ativas"] = (
        df_mun["Qtd_Escolas_Ativas"] / df_mun["Qtd_Escolas"]
    )

    def faixa(p):
        if p == 1:
            return "100%"
        elif p >= 0.8:
            return "80% - 99%"
        elif p >= 0.7:
            return "70% - 79%"
        elif p >= 0.5:
            return "50% - 69%"
        elif p > 0:
            return "<50%"
        else:
            return "0%"

    df_mun["Faixa_Cobertura"] = df_mun["Perc_Escolas_Ativas"].apply(faixa)

    df_mun = df_mun.merge(
        df_lista[["co_municipio", "UF", "Município"]],
        on="co_municipio",
        how="left"
    )

    return df_mun, base, total_escolas_unicas

# ============================================================
# EXECUÇÃO
# ============================================================

atualizar = st.button("🔄 Atualizar dados")

df_lista = carregar_lista()
df_api = carregar_api(atualizar)

with st.spinner("Processando dados (metodologia Power BI)..."):
    df_mun, base, total_escolas_unicas = processar_powerbi(df_api, df_lista)

# ============================================================
# CARDS
# ============================================================

total_escolas_com_internet = base["co_entidade"].nunique()
total_escolas_ativas = base[base["status"] == "ativo"]["co_entidade"].nunique()
total_escolas_sem_medidor = total_escolas_com_internet - total_escolas_ativas

municipios_total = df_mun["co_municipio"].nunique()
municipios_100 = df_mun[df_mun["Faixa_Cobertura"] == "100%"]
municipios_70_mais = df_mun[df_mun["Perc_Escolas_Ativas"] >= 0.7]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🏫 Total de Escolas", fmt(total_escolas_unicas))
c2.metric("🌐 Escolas com Internet", fmt(total_escolas_com_internet))
c3.metric("📟 Internet + Medidor", fmt(total_escolas_ativas))
c4.metric("🚫 Internet sem Medidor", fmt(total_escolas_sem_medidor))
c5.metric("🏙️ Municípios 100%", fmt(len(municipios_100)))

st.divider()

# ============================================================
# VELOCÍMETROS
# ============================================================

fig1 = go.Figure(go.Indicator(
    mode="gauge+number",
    value=total_escolas_com_internet,
    gauge={"axis": {"range": [0, total_escolas_unicas]}},
    title={"text": "Escolas com Internet / Total de Escolas"}
))
fig1.update_layout(height=260)

fig2 = go.Figure(go.Indicator(
    mode="gauge+number",
    value=len(municipios_100),
    gauge={"axis": {"range": [0, municipios_total]}},
    title={"text": "Municípios 100% (Power BI)"}
))
fig2.update_layout(height=260)

g1, g2 = st.columns(2)
g1.plotly_chart(fig1, use_container_width=True)
g2.plotly_chart(fig2, use_container_width=True)

st.divider()

# ============================================================
# GRÁFICO POR UF
# ============================================================

uf_100 = (
    municipios_100
    .groupby("UF", as_index=False)
    .agg(qtd=("co_municipio", "nunique"))
    .sort_values("qtd", ascending=False)
)

fig = px.bar(
    uf_100,
    x="UF",
    y="qtd",
    text="qtd",
    title="Municípios 100% – Metodologia Power BI"
)
fig.update_traces(textposition="outside")
fig.update_layout(height=420)

st.plotly_chart(fig, use_container_width=True)

st.divider()

# ============================================================
# TABELAS + DOWNLOAD (COLUNAS AJUSTADAS)
# ============================================================

colunas_tabela = [
    "co_municipio",
    "Município",
    "UF",
    "Qtd_Escolas",
    "Qtd_Escolas_Ativas",
    "Perc_Escolas_Ativas",
    "Faixa_Cobertura"
]

tabela_100 = municipios_100[colunas_tabela]
tabela_70 = municipios_70_mais[colunas_tabela]

st.subheader("🏙️ Municípios 100% (Power BI)")
st.dataframe(tabela_100, use_container_width=True)

st.download_button(
    "📥 Baixar municípios 100% (Excel)",
    baixar_excel(tabela_100, "municipios_100_powerbi.xlsx", "Municipios_100"),
    file_name="municipios_100_powerbi.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

st.subheader("🏙️ Municípios ≥ 70% (Power BI)")
st.dataframe(tabela_70, use_container_width=True)

st.download_button(
    "📥 Baixar municípios ≥ 70% (Excel)",
    baixar_excel(tabela_70, "municipios_70_mais_powerbi.xlsx", "Municipios_70_mais"),
    file_name="municipios_70_mais_powerbi.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)