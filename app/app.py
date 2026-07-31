"""
Radar Hipotecario — UI Streamlit.
Lee snapshots Parquet del repo (nunca APIs en vivo) + motores de reglas.
Despliegue: Streamlit Community Cloud (sin secrets necesarios para servir).
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import CIUDADES, DIR_SNAPSHOTS
from src.motor_reglas.bancario import escenario_bancario, escenario_cofinavit
from src.motor_reglas.infonavit import escenario_infonavit

st.set_page_config(page_title="Radar Hipotecario", page_icon="📡", layout="wide")


@st.cache_data
def cargar_series() -> pd.DataFrame:
    ruta = DIR_SNAPSHOTS / "latest" / "series_banxico.parquet"
    if not ruta.exists():
        st.error("No hay snapshot. Corre `python scripts/ingesta_completa.py` primero.")
        st.stop()
    return pd.read_parquet(ruta)


def tasa_bancaria_referencia(series: pd.DataFrame) -> float:
    """Última tasa hipotecaria del snapshot; fallback temporal a TIIE + spread típico."""
    if "tasa_hipotecaria_promedio" in series["serie"].unique():
        return series.loc[series["serie"] == "tasa_hipotecaria_promedio", "valor"].iloc[-1] / 100
    tiie = series.loc[series["serie"] == "tiie_28", "valor"].iloc[-1] / 100
    return tiie + 0.035  # spread provisional — sustituir al integrar CF815/CNBV


st.title("📡 Radar Hipotecario")
st.caption("¿Es buen momento para comprar casa — y por cuál vía de crédito te conviene?")

series = cargar_series()

with st.sidebar:
    st.header("Tu perfil")
    ingreso = st.number_input("Ingreso mensual (MXN)", 5000, 500000, 18000, step=1000)
    edad = st.number_input("Edad", 18, 69, 32)
    sexo = st.radio("Sexo", ["Hombre", "Mujer"], horizontal=True)
    formal = st.toggle("Cotizo al IMSS (empleo formal)", value=True)
    ssv = st.number_input("Subcuenta de vivienda aprox. (MXN)", 0, 2000000, 0, step=10000,
                          disabled=not formal)
    enganche = st.number_input("Enganche disponible (MXN)", 0, 5000000, 100000, step=10000)
    ciudad = st.selectbox("Ciudad", list(CIUDADES.keys()), format_func=lambda c: c.replace("_", " ").title())

tasa_banco = tasa_bancaria_referencia(series)

col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🏛️ Infonavit")
    if formal:
        e = escenario_infonavit(ingreso, edad, sexo[0], ssv=ssv)
        if e["elegible"]:
            st.metric("Capacidad total", f"${e['capacidad_total']:,.0f}")
            st.metric("Mensualidad", f"${e['mensualidad_estimada']:,.0f}")
            st.caption(f"Tasa {e['tasa_anual']:.2%} · {e['plazo_anios']} años")
            if e.get("advertencia"):
                st.warning(e["advertencia"])
        else:
            st.info(e["motivo"])
    else:
        st.info("Requiere cotizar al IMSS")

with col2:
    st.subheader("🏦 Banco")
    e = escenario_bancario(ingreso, enganche, tasa_anual=tasa_banco)
    st.metric("Capacidad total", f"${e['capacidad_total']:,.0f}")
    st.metric("Mensualidad", f"${e['mensualidad_estimada']:,.0f}")
    st.caption(f"Tasa ref. {e['tasa_anual']:.2%} · {e['plazo_anios']} años")

with col3:
    st.subheader("🤝 Cofinavit")
    if formal:
        e = escenario_cofinavit(ingreso, edad, sexo[0], ssv, enganche, tasa_banco)
        if e["elegible"]:
            st.metric("Capacidad total", f"${e['capacidad_total']:,.0f}")
            st.caption("Infonavit + banco combinados")
        else:
            st.info(e["motivo"])
    else:
        st.info("Requiere cotizar al IMSS")

st.divider()
st.subheader("📈 Semáforo de mercado")
st.info("TODO: proyecciones Prophet (tasas y precios) + recomendación COMPRA_AHORA / ESPERA / NEGOCIA")
