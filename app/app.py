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
from config.settings import CIUDADES, DIR_DATA, DIR_SNAPSHOTS
from src.asistente.chat import generar_resumen_estructurado, responder
from src.modelos.forecast_tasas import proyectar_tasa_hipotecaria, semaforo
from src.modelos.precio_referencia import posicion_mercado
from src.modelos.segmentacion_ciudades import obtener_arquetipos
from src.motor_reglas.bancario import escenario_bancario, escenario_cofinavit
from src.motor_reglas.infonavit import escenario_infonavit

st.set_page_config(page_title="Radar Hipotecario", page_icon="🏠", layout="wide")

ADVERTENCIAS = [
    "La tasa bancaria de referencia usa un spread provisional sobre la TIIE "
    "(0.035) mientras se integra el cuadro CF815 de Banxico o datos de CNBV.",
    "El posicionamiento de mercado usa percentiles oficiales SHF escalados por "
    "índice de ciudad (no listados de portales) — más robusto que una muestra "
    "de anuncios, pero es una estimación derivada, no un conteo de inventario real.",
    "El K-Means usa precio/m² (scraper) y variación anual (SHF oficial) — "
    "la absorción/velocidad de venta sigue pendiente de una fuente confirmada.",
    "El semáforo de tasas es una capa de reglas sobre la proyección de Prophet "
    "(MAE ≈0.87pp en backtest) — no es una garantía de movimiento de mercado.",
]


@st.cache_data
def cargar_series() -> pd.DataFrame:
    ruta = DIR_SNAPSHOTS / "latest" / "series_banxico.parquet"
    if not ruta.exists():
        st.error("No hay snapshot. Corre `python scripts/ingesta_completa.py` primero.")
        st.stop()
    return pd.read_parquet(ruta)


@st.cache_data
def cargar_arquetipos() -> dict:
    try:
        return obtener_arquetipos()
    except FileNotFoundError:
        return {}


def tasa_bancaria_referencia(series: pd.DataFrame) -> float:
    if "tasa_hipotecaria_promedio" in series["serie"].unique():
        return series.loc[series["serie"] == "tasa_hipotecaria_promedio", "valor"].iloc[-1] / 100
    tiie = series.loc[series["serie"] == "tiie_28", "valor"].iloc[-1] / 100
    return tiie + 0.035


def mostrar_posicion_mercado(ciudad: str, capacidad_total: float) -> None:
    """Ubica la capacidad del usuario contra percentiles oficiales SHF —
    reemplaza al scraper como fuente de esta señal (ver decisión documentada)."""
    pos = posicion_mercado(ciudad, capacidad_total)
    if not pos:
        return
    st.caption(f"📊 {pos['mensaje']}")
    st.caption(f"Referencia {ciudad.replace('_', ' ').title()} (SHF): "
               f"P25 ${pos['p25']:,.0f} · Mediana ${pos['mediana']:,.0f} · P75 ${pos['p75']:,.0f}")


def procedencia_datos(series: pd.DataFrame) -> str:
    fecha_series = series["fecha"].max()
    partes = [f"Series Banxico al {fecha_series:%d %b %Y}"]

    ruta_oferta = DIR_DATA / "oferta_inmuebles24.parquet"
    if ruta_oferta.exists():
        oferta = pd.read_parquet(ruta_oferta)
        fecha_scrape = pd.to_datetime(oferta["fecha_scrape"]).max()
        partes.append(f"oferta inmobiliaria scrapeada {fecha_scrape:%d %b %Y}")

    return " · ".join(partes)


st.title("Radar Hipotecario")
st.caption("¿Es buen momento para comprar casa — y por cuál vía de crédito te conviene?")

series = cargar_series()
arquetipos = cargar_arquetipos()

st.caption(f"📅 {procedencia_datos(series)}")
with st.expander("⚠️ Advertencias y limitaciones conocidas"):
    for item in ADVERTENCIAS:
        st.markdown(f"- {item}")

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
    if ciudad in arquetipos:
        st.caption(f"Mercado: **{arquetipos[ciudad]}**")

tasa_banco = tasa_bancaria_referencia(series)

resultados = {"infonavit": None, "banco": None, "cofinavit": None, "semaforo": None}

tab_escenario, tab_semaforo, tab_resumen, tab_asistente = st.tabs(
    ["📊 Tu escenario", "📈 Semáforo de mercado", "📋 Resumen ejecutivo", "💬 Asistente"]
)

with tab_escenario:
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
                mostrar_posicion_mercado(ciudad, e["capacidad_total"])
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
        mostrar_posicion_mercado(ciudad, e["capacidad_total"])

    with col3:
        st.subheader("🤝 Cofinavit")
        if formal:
            resultados["cofinavit"] = escenario_cofinavit(ingreso, edad, sexo[0], ssv, enganche, tasa_banco)
            e = resultados["cofinavit"]
            if e["elegible"]:
                st.metric("Capacidad total", f"${e['capacidad_total']:,.0f}")
                st.caption("Infonavit + banco combinados")
                mostrar_posicion_mercado(ciudad, e["capacidad_total"])
            else:
                st.info(e["motivo"])
        else:
            st.info("Requiere cotizar al IMSS")

with tab_semaforo:
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

with tab_resumen:
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

with tab_asistente:
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