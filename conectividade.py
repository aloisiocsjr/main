import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import time
from pathlib import Path
from datetime import datetime


# ============================================================
# LIMPEZA DE CACHE (APENAS NA PRIMEIRA EXECUÇÃO)
# ============================================================

if "cache_limpo" not in st.session_state:
    st.cache_data.clear()
    st.session_state["cache_limpo"] = True


# ============================================================
# CONFIGURAÇÕES
# ============================================================

st.set_page_config(
    page_title="Conectividade – SIMET / UNICEF",
    layout="wide"
)

API_URL = "https://api.simet.nic.br/school-measures/v1/getStatusandSchoolInfoUNICEF"

BASES = Path("bases")
BASES.mkdir(exist_ok=True)

ARQ_API = BASES / "simet_unicef_raw.csv"
ARQ_ADESOES = BASES / "adesoes_2025_2028.xlsx"
ABA_ADESOES = "Lista única"

COL_ESCOLA = "co_entidade"
COL_MUNICIPIO = "co_municipio"
COL_UF = "UF"
COL_MUNICIPIO_NOME = "Município"


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def fmt(n):
    """Formata inteiro com separador de milhar pt-BR."""
    return f"{int(n):,}".replace(",", ".")


def baixar_api_com_retry():
    tentativas = 3
    timeout = 300

    for _ in range(tentativas):
        try:
            response = requests.get(API_URL, timeout=timeout)
            response.raise_for_status()
            return pd.DataFrame(response.json())
        except requests.exceptions.ReadTimeout:
            time.sleep(5)

    raise RuntimeError("Não foi possível acessar a API SIMET.")


@st.cache_data(show_spinner=False)
def carregar_api():
    if ARQ_API.exists():
        df = pd.read_csv(ARQ_API, dtype={COL_MUNICIPIO: str})
        origem = "📁 Cache local"
    else:
        df = baixar_api_com_retry()
        df.to_csv(ARQ_API, index=False)
        origem = "🌐 API SIMET"
    return df, origem


@st.cache_data(show_spinner=False)
def carregar_adesoes():
    if not ARQ_ADESOES.exists():
        st.error(
            "❌ Arquivo de adesões não encontrado.\n\n"
            "O arquivo **adesoes_2025_2028.xlsx** precisa estar no GitHub em:\n\n"
            "`bases/adesoes_2025_2028.xlsx`\n\n"
            "👉 Faça upload do arquivo e o app funcionará automaticamente."
        )
        st.stop()

    return pd.read_excel(
        ARQ_ADESOES,
        sheet_name=ABA_ADESOES,
        dtype={COL_MUNICIPIO: str}
    )


def normalizar_municipio(df):
    df[COL_MUNICIPIO] = (
        df[COL_MUNICIPIO]
        .astype(str)
        .str.strip()
        .str.zfill(7)
    )
    return df


def criar_gauge(valor, total, titulo, cor):
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=int(valor),
            number={"font": {"size": 22}},
            title={"text": titulo, "font": {"size": 14}},
            gauge={
                "axis": {"range": [0, int(total)]},
                "bar": {"color": cor},
            },
        )
    )
    fig.update_layout(height=220, margin=dict(t=30, b=0, l=0, r=0))
    return fig


# ============================================================
# INTERFACE
# ============================================================

st.title("📡 Projeto Conectividade")
st.caption("Base SIMET / UNICEF • Municípios com adesão 2025–2028")

# ---------------- BOTÃO UPDATE ----------------
colA, colB = st.columns(2)

with colA:
    atualizar = st.button("🔄 Atualizar dados da API")

with colB:
    if ARQ_API.exists():
        st.caption(
            "Última atualização: "
            + datetime.fromtimestamp(ARQ_API.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
        )

if atualizar:
    with st.spinner("Atualizando base da API..."):
        df_api = baixar_api_com_retry()
        df_api.to_csv(ARQ_API, index=False)
        st.success("Base atualizada!")
        st.rerun()

# ---------------- CARGA ----------------
df_api, origem = carregar_api()
df_api = normalizar_municipio(df_api)

df_adesoes = normalizar_municipio(carregar_adesoes())

st.caption(f"Fonte dos dados: {origem}")

# ---------------- FILTRO MUNICÍPIOS ----------------
municipios_comuns = set(df_api[COL_MUNICIPIO]) & set(df_adesoes[COL_MUNICIPIO])
df = df_api[df_api[COL_MUNICIPIO].isin(municipios_comuns)]

# ---------------- CARDS ----------------
escolas_unicas = df[COL_ESCOLA].nunique()
escolas_com_internet = df[df["in_internet"] == "Sim"][COL_ESCOLA].nunique()
escolas_internet_medidor = df[
    (df["in_internet"] == "Sim") & (df["status"] == "ativo")
][COL_ESCOLA].nunique()
escolas_internet_sem_medidor = df[
    (df["in_internet"] == "Sim") & (df["status"] != "ativo")
][COL_ESCOLA].nunique()

c1, c2, c3, c4 = st.columns(4)
c1.metric("🏫 Escolas únicas", fmt(escolas_unicas))
c2.metric("🌐 Escolas com internet", fmt(escolas_com_internet))
c3.metric("📡 Internet + Medidor", fmt(escolas_internet_medidor))
c4.metric("⚠️ Internet sem medidor", fmt(escolas_internet_sem_medidor))

st.divider()

# ============================================================
# CÁLCULO POR MUNICÍPIO
# ============================================================

df_mun = (
    df.groupby(COL_MUNICIPIO)
    .agg(
        escolas_internet=("in_internet", lambda x: (x == "Sim").sum()),
        escolas_internet_medidor=(
            "status",
            lambda x: ((df.loc[x.index, "in_internet"] == "Sim") & (x == "ativo")).sum()
        )
    )
    .reset_index()
)

df_mun["percentual"] = df_mun["escolas_internet_medidor"] / df_mun["escolas_internet"]

df_mun = df_mun.merge(
    df_adesoes[[COL_MUNICIPIO, COL_MUNICIPIO_NOME, COL_UF]],
    on=COL_MUNICIPIO,
    how="left"
)

# ============================================================
# GRÁFICOS
# ============================================================

g1 = criar_gauge(
    escolas_com_internet,
    escolas_unicas,
    "Escolas com Internet",
    "#0794FF"
)

g2 = criar_gauge(
    (df_mun["percentual"] == 1).sum(),
    len(df_mun),
    "Municípios 100%",
    "#2ECC71"
)

df_uf = (
    df_mun[df_mun["percentual"] == 1]
    .groupby(COL_UF)[COL_MUNICIPIO]
    .nunique()
    .reset_index(name="Municipios_100")
    .sort_values("Municipios_100", ascending=False)
)

y_max = int(df_uf["Municipios_100"].max() * 1.15) if not df_uf.empty else 1

fig_bar = px.bar(
    df_uf,
    x=COL_UF,
    y="Municipios_100",
    text=df_uf["Municipios_100"].apply(fmt),
    title="Municípios 100% Conectados por UF"
)

fig_bar.update_traces(textposition="outside")
fig_bar.update_layout(
    height=280,
    margin=dict(t=60),
    yaxis=dict(range=[0, y_max]),
    xaxis=dict(categoryorder="array", categoryarray=df_uf[COL_UF].tolist())
)

colg1, colg2, colg3 = st.columns([1, 1, 2])
colg1.plotly_chart(g1, use_container_width=True)
colg2.plotly_chart(g2, use_container_width=True)
colg3.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# ============================================================
# TABELAS POR FAIXA
# ============================================================

def tabela_faixa(df_base, limite, titulo):
    df_f = df_base[df_base["percentual"] >= limite].copy()
    df_f["Percentual (%)"] = (df_f["percentual"] * 100).round(1)

    cols = [
        COL_MUNICIPIO,
        COL_MUNICIPIO_NOME,
        COL_UF,
        "escolas_internet",
        "escolas_internet_medidor",
        "Percentual (%)",
    ]

    st.subheader(titulo)
    st.dataframe(df_f[cols], use_container_width=True)

    st.download_button(
        f"⬇️ Baixar {titulo} (CSV)",
        df_f[cols].to_csv(index=False, sep=";"),
        file_name=f"municipios_{int(limite*100)}_porcento.csv",
        mime="text/csv"
    )


tabela_faixa(df_mun, 1.0, "📋 Municípios com 100% das escolas conectadas e com medidor")
tabela_faixa(df_mun, 0.7, "📋 Municípios com ≥ 70% das escolas conectadas e com medidor")
tabela_faixa(df_mun, 0.5, "📋 Municípios com ≥ 50% das escolas conectadas e com medidor")

st.success("Aplicação carregada com sucesso 🚀")
st.caption("Projeto Conectividade • SIMET / UNICEF")
