import streamlit as st
import requests
import pandas as pd
import unicodedata
from pathlib import Path
import plotly.express as px
import time

# ============================================================
# CONFIGURAÇÃO DO APP
# ============================================================

st.set_page_config(page_title="Conectividade – UNICEF & SIMET", layout="wide")

st.title("📡 Dashboard de Conectividade – SIMET / UNICEF")

st.markdown("""
Sistema otimizado para:
- Usar cache local da API (carregamento instantâneo)
- Atualizar os dados quando o usuário solicitar
- Processar escolas municipais
- Calcular municípios com 50%, 70%, 80% e 100%
- Gerar tabelas, gráficos e downloads
""")

# ============================================================
# ARQUIVOS LOCAIS
# ============================================================

CAMINHO_CACHE = Path("bases/api_cache.csv")
CAMINHO_ADESOES = Path("bases/adesoes.csv")
URL_API = "https://api.simet.nic.br/school-measures/v1/getStatusandSchoolInfoUNICEF"


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def normalizar(v):
    if pd.isna(v):
        return ""
    v = str(v)
    v = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode("utf-8")
    return v.strip().upper()


def atualizar_api():
    """Baixa a API e salva em api_cache.csv."""
    try:
        with st.spinner("🔄 Atualizando dados diretamente da API SIMET..."):
            r = requests.get(URL_API, timeout=300)
            r.raise_for_status()
            data = r.json()

            lista = None
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        lista = v
                        break
            else:
                lista = data

            df = pd.DataFrame(lista)
            df.to_csv(CAMINHO_CACHE, index=False, encoding="utf-8")

        st.success("✔ Dados atualizados com sucesso!")
        return df

    except Exception as e:
        st.error(f"❌ Erro ao atualizar API: {e}")
        return None


@st.cache_data(show_spinner=False)
def carregar_cache():
    return pd.read_csv(CAMINHO_CACHE)


@st.cache_data(show_spinner=False)
def carregar_lista_unica():

    # Detecta separador automaticamente
    df = pd.read_csv(CAMINHO_ADESOES, dtype=str, sep=None, engine="python")

    # Remove BOM invisível e espaços
    df.columns = df.columns.str.replace("\ufeff", "", regex=False)
    df.columns = df.columns.str.strip()

    # Conferir se coluna existe
    if "co_municipio" not in df.columns:
        st.error(f"Colunas encontradas no CSV: {df.columns.tolist()}")
        st.stop()

    df["co_municipio"] = pd.to_numeric(df["co_municipio"], errors="coerce")
    return df


# ============================================================
# BOTÃO DE ATUALIZAÇÃO DA API
# ============================================================

st.subheader("🔧 Atualização de Dados")

if st.button("🔃 Atualizar Dados da API (SIMET)"):
    df_api = atualizar_api()
    if df_api is not None:
        st.session_state["api_atualizada"] = True


# ============================================================
# CARREGAMENTO DO CACHE
# ============================================================

if not CAMINHO_CACHE.exists():
    st.warning("⚠ O arquivo api_cache.csv ainda não existe. Clique no botão acima para gerar os dados.")
    st.stop()

df_api = carregar_cache()
df_lista = carregar_lista_unica()


# ============================================================
# PROCESSAMENTO DOS DADOS
# ============================================================

df_api["co_municipio"] = pd.to_numeric(df_api["co_municipio"], errors="coerce")

# Normalização vetorizada
df_api["tp_dependencia_norm"] = df_api["tp_dependencia"].astype(str).str.upper()
df_api["in_internet_norm"] = df_api["in_internet"].astype(str).str.upper()
df_api["status_norm"] = df_api["status"].astype(str).str.upper()

df_api["status_norm"] = df_api["status_norm"].replace({
    "INSTALADO": "ATIVO",
    "INSTALLED": "ATIVO",
    "ACTIVE": "ATIVO",
    "TRUE": "ATIVO"
})

df_api["in_internet_norm"] = df_api["in_internet_norm"].replace({
    "YES": "SIM",
    "Y": "SIM",
    "TRUE": "SIM"
})

# Filtrar municipais com internet
df_filtrado = df_api[
    (df_api["tp_dependencia_norm"].str.contains("MUNICIPAL")) &
    (df_api["in_internet_norm"] == "SIM")
].copy()

# Criar ID único da escola
df_filtrado["id_escola_unica"] = (
    df_filtrado["co_municipio"].astype(str) + "_" +
    df_filtrado["co_entidade"].astype(str)
)

df_unicas = df_filtrado.drop_duplicates(subset="id_escola_unica")

# Merge com Lista Única
df_lista_red = df_lista[["UF", "Município", "co_municipio", "Regiao"]].drop_duplicates()
df_final = df_unicas.merge(df_lista_red, on="co_municipio", how="inner")

# Cálculo das metas
temp = df_final.groupby(["UF", "Município", "co_municipio"]).agg(
    total_escolas=("id_escola_unica", "nunique"),
    escolas_ativas=("status_norm", lambda s: (s == "ATIVO").sum())
).reset_index()

temp["percentual"] = (temp["escolas_ativas"] / temp["total_escolas"] * 100).round(2)

mun_50 = temp[temp["percentual"] >= 50]
mun_70 = temp[temp["percentual"] >= 70]
mun_80 = temp[temp["percentual"] >= 80]
mun_100 = temp[temp["percentual"] == 100]


# ============================================================
# CARDS (COM SEPARADOR DE MILHAR)
# ============================================================

fmt = lambda x: f"{x:,.0f}".replace(",", ".")

st.subheader("📊 Indicadores Gerais")
c0, c1, c2, c3, c4, c5 = st.columns(6)

total_escolas = df_api["co_entidade"].nunique()
total_internet = df_unicas["id_escola_unica"].nunique()
total_medidor = df_final[df_final["status_norm"] == "ATIVO"]["id_escola_unica"].nunique()
total_sem = df_final[df_final["status_norm"] != "ATIVO"]["id_escola_unica"].nunique()

c0.metric("Total de Escolas (Geral)", fmt(total_escolas))
c1.metric("Escolas c/ Internet", fmt(total_internet))
c2.metric("Escolas c/ Medidor Instalado", fmt(total_medidor))
c3.metric("Escolas Sem Medidor", fmt(total_sem))
c4.metric("Municípios ≥ 70%", fmt(len(mun_70)))
c5.metric("Municípios 100%", fmt(len(mun_100)))


# ============================================================
# DOWNLOADS
# ============================================================

st.subheader("📁 Downloads")

st.download_button(
    "📥 Municípios ≥ 70%",
    mun_70.to_csv(index=False).encode("utf-8"),
    "municipios_70.csv",
    mime="text/csv"
)

st.download_button(
    "📥 Municípios 100%",
    mun_100.to_csv(index=False).encode("utf-8"),
    "municipios_100.csv",
    mime="text/csv"
)

st.download_button(
    "📥 Base Final Completa",
    df_final.to_csv(index=False).encode("utf-8"),
    "base_final.csv",
    mime="text/csv"
)


# ============================================================
# GRÁFICO
# ============================================================

st.subheader("📊 Municípios 100% Conectados por UF")

if len(mun_100):
    g = mun_100.groupby("UF")["Município"].nunique().reset_index(name="qtd")
    g = g.sort_values("qtd", ascending=False)

    fig = px.bar(g, x="UF", y="qtd", text="qtd",
                 title="Municípios 100% Conectados por UF")
    fig.update_traces(textposition="outside")

    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Nenhum município 100% identificado.")


# ============================================================
# FINAL
# ============================================================

st.success("✅ Dashboard carregado com sucesso! Clique em 'Atualizar Dados' para atualizar quando quiser.")
