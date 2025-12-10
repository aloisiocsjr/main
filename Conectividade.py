import streamlit as st
import requests
import pandas as pd
import unicodedata
from pathlib import Path
import plotly.express as px
import time

# =======================================
# CONFIGURAÇÃO DO APP
# =======================================
st.set_page_config(page_title="Conectividade – UNICEF & SIMET", layout="wide")

st.title("📡 Dashboard de Conectividade – SIMET / UNICEF")

st.markdown("""
Sistema automático para:
- Carregamento direto da API SIMET/NIC.br
- Processamento das escolas municipais
- Identificação de medidores instalados (status ATIVO)
- Cálculo dos municípios com 50%, 70%, 80% e 100% das escolas conectadas
- Download das bases em CSV
- Base final consolidada
""")

# =======================================
# CONFIGS DE ARQUIVOS
# =======================================
CAMINHO_ADESOES = Path("bases/adesoes_2025_2028.xlsx")
URL_API = "https://api.simet.nic.br/school-measures/v1/getStatusandSchoolInfoUNICEF"

ARQ70 = "bases/municipios_com_70_medidores_instalados.csv"
ARQ100 = "bases/municipios_com_100_medidores_instalados.csv"

# =======================================
# FUNÇÕES AUXILIARES
# =======================================

def normalizar_texto(valor):
    """Remove acentos, espaços extras e converte para maiúsculas."""
    if pd.isna(valor):
        return ""
    valor = str(valor)
    valor = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode("utf-8")
    return valor.strip().upper()


# FUNÇÃO ROBUSTA – API COM RE-TENTATIVA
def carregar_dados_api():
    tentativas = 3
    for tentativa in range(1, tentativas + 1):
        try:
            st.write(f"🔄 Tentativa {tentativa} de {tentativas} para acessar a API...")
            r = requests.get(URL_API, timeout=180)
            r.raise_for_status()
            data = r.json()

            # Encontrar lista dentro do JSON
            lista = None
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        lista = v
                        break
            else:
                lista = data

            return pd.DataFrame(lista)

        except Exception as e:
            if tentativa < tentativas:
                st.warning("⚠️ Falha ao acessar API. Tentando novamente em 5 segundos...")
                time.sleep(5)
            else:
                st.error(f"❌ Erro ao acessar API após {tentativas} tentativas: {e}")
                return None


@st.cache_data(show_spinner=True)
def carregar_lista_unica():
    return pd.read_excel(CAMINHO_ADESOES, sheet_name="Lista única")


# =======================================
# CARREGAMENTO AUTOMÁTICO
# =======================================
st.info("🔄 Carregando dados automaticamente...")

df_api = carregar_dados_api()
df_lista = carregar_lista_unica()

if df_api is None or df_lista is None:
    st.stop()

# =======================================
# NORMALIZAÇÃO
# =======================================
df_api["co_municipio"] = pd.to_numeric(df_api["co_municipio"], errors="coerce")
df_lista["co_municipio"] = pd.to_numeric(df_lista["co_municipio"], errors="coerce")

df_api["tp_dependencia_norm"] = df_api["tp_dependencia"].apply(normalizar_texto).replace({
    "MUNICIPIO": "MUNICIPAL",
    "REDE MUNICIPAL": "MUNICIPAL"
})

df_api["in_internet_norm"] = df_api["in_internet"].apply(normalizar_texto).replace({
    "YES": "SIM",
    "Y": "SIM",
    "TRUE": "SIM"
})

df_api["status_norm"] = df_api["status"].apply(normalizar_texto).replace({
    "INSTALADO": "ATIVO",
    "INSTALLED": "ATIVO",
    "ACTIVE": "ATIVO",
    "TRUE": "ATIVO"
})

# =======================================
# FILTRAR SOMENTE MUNICIPAIS COM INTERNET
# =======================================
df_filtrado = df_api[
    (df_api["tp_dependencia_norm"] == "MUNICIPAL") &
    (df_api["in_internet_norm"] == "SIM")
].copy()

df_filtrado["id_escola_unica"] = (
    df_filtrado["co_municipio"].astype(str) + "_" + df_filtrado["co_entidade"].astype(str)
)

df_unicas = df_filtrado.drop_duplicates(subset="id_escola_unica")

# =======================================
# MERGE COM LISTA ÚNICA
# =======================================
df_lista_red = df_lista[["UF", "Município", "co_municipio", "Regiao"]].drop_duplicates()
df_final = df_unicas.merge(df_lista_red, on="co_municipio", how="inner")

# =======================================
# CÁLCULO DAS METAS
# =======================================
temp = df_final.groupby(["UF", "Município", "co_municipio"]).agg(
    total_escolas=("id_escola_unica", "nunique"),
    escolas_ativas=("status_norm", lambda s: (s == "ATIVO").sum())
).reset_index()

temp["percentual"] = ((temp["escolas_ativas"] / temp["total_escolas"]) * 100).round(2)

mun_50 = temp[temp["percentual"] >= 50]
mun_70 = temp[temp["percentual"] >= 70]
mun_80 = temp[temp["percentual"] >= 80]
mun_100 = temp[temp["percentual"] == 100]

# =======================================
# CARDS
# =======================================
st.subheader("📊 Indicadores Gerais")

# Agora serão 6 cards
c0, c1, c2, c3, c4, c5 = st.columns(6)

# Valores numéricos
total_escolas = df_api["co_entidade"].nunique()
total_escolas_internet = df_unicas["id_escola_unica"].nunique()
total_escolas_medidor = df_final[df_final["status_norm"] == "ATIVO"]["id_escola_unica"].nunique()
total_escolas_sem_medidor = df_final[df_final["status_norm"] != "ATIVO"]["id_escola_unica"].nunique()
qtd_70 = len(mun_70)
qtd_100 = len(mun_100)

# Formatação com separador de milhar
fmt = lambda x: f"{x:,.0f}".replace(",", ".")

# Exibir os cards com números formatados
c0.metric("Total de Escolas", fmt(total_escolas))
c1.metric("Escolas Municipais c/ Internet", fmt(total_escolas_internet))
c2.metric("Escolas c/ Medidor Instalado", fmt(total_escolas_medidor))
c3.metric("Escolas c/ Internet e SEM Medidor", fmt(total_escolas_sem_medidor))
c4.metric("Municípios ≥ 70%", fmt(qtd_70))
c5.metric("Municípios 100%", fmt(qtd_100))

# =======================================
# EXPORTAÇÃO CSV
# =======================================
Path("bases").mkdir(exist_ok=True)
mun_70.to_csv(ARQ70, index=False, encoding="utf-8")
mun_100.to_csv(ARQ100, index=False, encoding="utf-8")

st.subheader("📁 Download das Bases")

st.download_button(
    "📥 Download Municípios ≥ 70%",
    mun_70.to_csv(index=False).encode("utf-8"),
    "municipios_com_70_medidores_instalados.csv",
    mime="text/csv"
)

st.download_button(
    "📥 Download Municípios 100%",
    mun_100.to_csv(index=False).encode("utf-8"),
    "municipios_com_100_medidores_instalados.csv",
    mime="text/csv"
)

# =======================================
# GRÁFICO – MUNICÍPIOS 100% POR UF
# =======================================
st.subheader("📊 Municípios 100% Conectados por UF")

if not mun_100.empty:
    graf = mun_100.groupby("UF")["Município"].nunique().reset_index(name="qtd")
    graf = graf.sort_values("qtd", ascending=False)

    fig = px.bar(
        graf,
        x="UF",
        y="qtd",
        text="qtd",
        title="Municípios 100% Conectados por UF"
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Nenhum município 100% conectado identificado.")

# =======================================
# BASE FINAL CONSOLIDADA
# =======================================
st.subheader("📚 Base Final Consolidada")
st.dataframe(df_final)

st.download_button(
    "📥 Baixar Base Final Consolidada",
    df_final.to_csv(index=False).encode("utf-8"),
    "base_final_consolidada.csv",
    mime="text/csv"
)

st.success("✅ Dashboard carregado e bases geradas com sucesso!")