"""
Radar Hipotecario — UI Streamlit.
Lee snapshots Parquet del repo (nunca APIs en vivo) + motores de reglas.
Despliegue: Streamlit Community Cloud (sin secrets necesarios para servir la parte
determinista; ANTHROPIC_API_KEY se necesita solo para el asistente).
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import CIUDADES, DIR_SNAPSHOTS
from src.asistente.chat import generar_resumen_estructurado, responder
from src.modelos.forecast_tasas import proyectar_tasa_hipotecaria, semaforo
from src.motor_reglas.bancario import escenario_bancario, escenario_cofinavit
from src.motor_reglas.infonavit import escenario_infonavit

st.set_page_config(page_title="Radar Hipotecario", page_icon="🏠", layout="wide")


@st.cache_data
def cargar_series() -> pd.DataFrame:
    ruta = DIR_SNAPSHOTS / "latest" / "series_banxico.parquet"
    if not ruta.exists():
        st.error("No hay snapshot. Corre `python scripts/ingesta_completa.py` primero.")
        st.stop()
    return pd.read_parquet(ruta)


def tasa_bancaria_referencia(series: pd.DataFrame) -> float:
    if "tasa_hipotecaria_promedio" in series["serie"].unique():
        return series.loc[series["serie"] == "tasa_hipotecaria_promedio", "valor"].iloc[-1] / 100
    tiie = series.loc[series["serie"] == "tiie_28", "valor"].iloc[-1] / 100
    return tiie + 0.035


st.title("Radar Hipotecario")
st.caption("¿Es buen momento para comprar casa — y por cuál vía de crédito te conviene?")

series = cargar_series()

with st.sidebar:
    st.image("assets/logo_sidebar.svg", width=180)
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

resultados = {"infonavit": None, "banco": None, "cofinavit": None, "semaforo": None}

col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🏛️ Infonavit")
    if formal:
        resultados["infonavit"] = escenario_infonavit(ingreso, edad, sexo[0], ssv=ssv)
        e = resultados["infonavit"]
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
    resultados["banco"] = escenario_bancario(ingreso, enganche, tasa_anual=tasa_banco)
    e = resultados["banco"]
    st.metric("Capacidad total", f"${e['capacidad_total']:,.0f}")
    st.metric("Mensualidad", f"${e['mensualidad_estimada']:,.0f}")
    st.caption(f"Tasa ref. {e['tasa_anual']:.2%} · {e['plazo_anios']} años")

with col3:
    st.subheader("🤝 Cofinavit")
    if formal:
        resultados["cofinavit"] = escenario_cofinavit(ingreso, edad, sexo[0], ssv, enganche, tasa_banco)
        e = resultados["cofinavit"]
        if e["elegible"]:
            st.metric("Capacidad total", f"${e['capacidad_total']:,.0f}")
            st.caption("Infonavit + banco combinados")
        else:
            st.info(e["motivo"])
    else:
        st.info("Requiere cotizar al IMSS")

st.divider()
st.subheader("📈 Semáforo de mercado")

with st.spinner("Proyectando tasas a 12 meses..."):
    try:
        proyeccion = proyectar_tasa_hipotecaria(horizonte_dias=365)
        resultado_semaforo = semaforo(proyeccion)
        resultados["semaforo"] = resultado_semaforo

        color = {"COMPRA_AHORA": "🔴", "ESPERA": "🟢", "NEGOCIA": "🟡"}[resultado_semaforo["senal"]]
        st.markdown(f"### {color} {resultado_semaforo['senal'].replace('_', ' ')}")
        st.write(resultado_semaforo["razon"])

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Tasa hipotecaria actual", f"{resultado_semaforo['tasa_actual']:.2%}")
        col_b.metric("Proyección 12 meses", f"{resultado_semaforo['tasa_proyectada']:.2%}",
                     delta=f"{resultado_semaforo['delta_pp']:.2f} pp")
        col_c.metric("Fecha de proyección", proyeccion["fecha_proyeccion"].strftime("%b %Y"))

        with st.expander("Ver metodología"):
            st.caption(
                "Proyección vía Prophet sobre la serie TIIE 28 días de Banxico (10 años de historia), "
                "con backtest de 365 días. El semáforo es una capa de reglas aplicada sobre la "
                "proyección — no es parte del modelo predictivo."
            )
    except Exception as e:
        st.warning(f"No se pudo calcular el semáforo: {e}")

st.divider()
st.subheader("📋 Resumen ejecutivo")
st.caption("Genera un resumen estructurado (JSON validado por schema) del caso actual.")

if st.button("Generar resumen ejecutivo"):
    with st.spinner("Generando..."):
        resumen = generar_resumen_estructurado(
            {"ingreso": ingreso, "edad": edad, "ciudad": ciudad, "formal": formal},
            resultados,
        )
    if "error" in resumen:
        st.warning(resumen["error"])
    else:
        st.info(resumen["resumen"])
        c1, c2, c3 = st.columns(3)
        c1.metric("Mejor opción", resumen["mejor_opcion"].replace("_", " ").title())
        c2.write(f"**Riesgo principal**\n\n{resumen['riesgo_principal']}")
        c3.write(f"**Siguiente paso**\n\n{resumen['siguiente_paso']}")

st.divider()
st.subheader("💬 Pregúntale al asistente")
st.caption(
    "Explica tus resultados, responde dudas generales, o recalcula escenarios "
    "hipotéticos (ej. \"¿y si ganara $25,000?\") usando el motor de reglas real. "
    "No sustituye asesoría profesional."
)

if "historial_chat" not in st.session_state:
    st.session_state.historial_chat = []

for mensaje in st.session_state.historial_chat:
    if isinstance(mensaje["content"], str):
        with st.chat_message(mensaje["role"]):
            st.write(mensaje["content"])

pregunta = st.chat_input("Ej. ¿Y si mi ingreso fuera de $25,000?")
if pregunta:
    st.session_state.historial_chat.append({"role": "user", "content": pregunta})
    with st.chat_message("user"):
        st.write(pregunta)

    perfil = {"ingreso": ingreso, "edad": edad, "ciudad": ciudad, "formal": formal}
    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            respuesta = responder(pregunta, st.session_state.historial_chat[:-1], perfil, resultados)
            st.write(respuesta)
    st.session_state.historial_chat.append({"role": "assistant", "content": respuesta})