"""
Radar Hipotecario — UI Streamlit.
Lee snapshots Parquet del repo (nunca APIs en vivo) + motores de reglas.
Cobertura: 32 entidades federativas, 100% oficiales SHF (config/shf_nacional.json).
Despliegue: Streamlit Community Cloud (sin secrets necesarios para servir la parte
determinista; ANTHROPIC_API_KEY se necesita solo para el asistente).
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import CIUDADES, DIR_SNAPSHOTS
from src.asistente.chat import generar_resumen_estructurado, responder
from src.modelos.forecast_tasas import proyectar_tasa_hipotecaria, semaforo
from src.modelos.precio_referencia import percentiles_ciudad, posicion_mercado
from src.modelos.segmentacion_ciudades import cargar_variacion_shf, obtener_arquetipos
from src.motor_reglas.bancario import escenario_bancario, escenario_cofinavit
from src.motor_reglas.infonavit import _mensualidad, escenario_infonavit

st.set_page_config(page_title="Radar Hipotecario", page_icon="🏠", layout="wide")


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


def procedencia_datos(series: pd.DataFrame) -> str:
    fecha_series = series["fecha"].max()
    return f"Series Banxico al {fecha_series:%d %b %Y} · Precios de vivienda: SHF T1 2026 (32 entidades)"


def _escapar_dolar(texto: str) -> str:
    """Escapa '$' para que Streamlit no lo interprete como delimitador de LaTeX.
    Necesario para cualquier texto generado por el LLM que pueda mencionar montos."""
    return texto.replace("$", "\\$") if texto else texto


def _calcular_impacto(mensualidad_actual: float, monto: float, plazo_anios: int,
                       tasa_proyectada: float, precio_mediana: float, variacion_pct: float) -> dict:
    """Simula el impacto de esperar 12 meses para un escenario bancario dado
    (mismo monto de crédito, tasa hoy vs. proyectada) y lo compara contra el
    aumento estimado del precio de vivienda en la entidad."""
    mensualidad_proyectada = _mensualidad(monto, tasa_proyectada, plazo_anios)
    diff = mensualidad_proyectada - mensualidad_actual
    ahorro_12m = -diff * 12
    ahorro_total = -diff * plazo_anios * 12
    costo_precio_12m = precio_mediana * (variacion_pct / 100)
    neto_12m = ahorro_12m - costo_precio_12m
    return {
        "mensualidad_actual": mensualidad_actual,
        "mensualidad_proyectada": mensualidad_proyectada,
        "ahorro_12m": ahorro_12m,
        "ahorro_total": ahorro_total,
        "costo_precio_12m": costo_precio_12m,
        "neto_12m": neto_12m,
    }


def _mostrar_bloque_impacto(titulo: str, impacto: dict) -> None:
    neto = impacto["neto_12m"]
    if neto > 0:
        st.success(f"#### 🟢 {titulo}: conviene ESPERAR — \\${neto:,.0f} netos a tu favor en 12 meses")
    else:
        st.error(f"#### 🔴 {titulo}: conviene COMPRAR AHORA — esperar costaría \\${-neto:,.0f} netos en 12 meses")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Mensualidad hoy", f"${impacto['mensualidad_actual']:,.0f}")
    m2.metric("Mensualidad proyectada (12m)", f"${impacto['mensualidad_proyectada']:,.0f}",
              delta=f"${impacto['mensualidad_proyectada'] - impacto['mensualidad_actual']:,.0f}",
              delta_color="inverse")
    m3.metric("Ahorro en pagos (12m)", f"${impacto['ahorro_12m']:,.0f}")
    m4.metric("Impacto neto", f"${neto:,.0f}")

    with st.expander(f"Ver detalle — {titulo}"):
        st.markdown(
            f"Ahorro en pagos (12m): \\${impacto['ahorro_12m']:,.0f} — Aumento estimado del precio "
            f"de vivienda: \\${impacto['costo_precio_12m']:,.0f} → neto: \\${neto:,.0f}.\n\n"
            f"Ahorro total a lo largo del crédito (si la tasa se mantuviera proyectada): "
            f"\\${impacto['ahorro_total']:,.0f}."
        )


st.title("Radar Hipotecario")
st.caption("¿Es buen momento para comprar casa — y por cuál vía de crédito te conviene?")

series = cargar_series()
arquetipos = cargar_arquetipos()

st.caption(f"📅 {procedencia_datos(series)}")

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
    ciudad = st.selectbox("Entidad", list(CIUDADES.keys()), format_func=lambda c: CIUDADES[c])
    if ciudad in arquetipos:
        st.caption(f"Mercado: **{arquetipos[ciudad]}**")

tasa_banco = tasa_bancaria_referencia(series)
nombre_ciudad = CIUDADES[ciudad]

resultados = {
    "infonavit": None, "banco": None, "cofinavit": None, "semaforo": None,
    "posicion_mercado": None, "impacto_banco": None, "impacto_cofinavit": None,
    "por_debajo_p25": None,
}

tab_escenario, tab_semaforo, tab_resumen, tab_asistente = st.tabs(
    ["📊 Tu escenario", "📈 Semáforo de mercado", "📝 En pocas palabras", "💬 Asistente"]
)

with tab_escenario:
    pct_ciudad = percentiles_ciudad(ciudad)
    if pct_ciudad:
        st.caption(
            f"📊 Referencia de mercado en {nombre_ciudad} (SHF): "
            f"P25 \\${pct_ciudad['p25']:,.0f} · Mediana \\${pct_ciudad['mediana']:,.0f} · "
            f"P75 \\${pct_ciudad['p75']:,.0f}"
        )

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
                pos = posicion_mercado(ciudad, e["capacidad_total"])
                if pos:
                    st.caption(f"📊 {pos['mensaje']}")
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
        pos = posicion_mercado(ciudad, e["capacidad_total"])
        resultados["posicion_mercado"] = pos
        if pos:
            st.caption(f"📊 {pos['mensaje']}")
        st.caption("ℹ️ Ve a **Semáforo de mercado** para saber si conviene actuar ya o esperar.")

    with col3:
        st.subheader("🤝 Cofinavit")
        if formal:
            resultados["cofinavit"] = escenario_cofinavit(ingreso, edad, sexo[0], ssv, enganche, tasa_banco)
            e = resultados["cofinavit"]
            if e["elegible"]:
                st.metric("Capacidad total", f"${e['capacidad_total']:,.0f}")
                st.metric("Mensualidad", f"${e['mensualidad_total']:,.0f}")
                st.caption(
                    f"Infonavit \\${e['componente_infonavit']['mensualidad_estimada']:,.0f} + "
                    f"Banco \\${e['componente_bancario']['mensualidad']:,.0f} "
                    "· Infonavit + banco combinados"
                )
                st.caption(
                    "💡 No es la suma directa de tu capacidad total: se reparte tu capacidad de pago "
                    "(40% del ingreso) entre ambos créditos — Infonavit consume su mensualidad primero, "
                    "el banco cubre el resto del presupuesto disponible."
                )
                pos = posicion_mercado(ciudad, e["capacidad_total"])
                if pos:
                    st.caption(f"📊 {pos['mensaje']}")
            else:
                st.info(e["motivo"])
        else:
            st.info("Requiere cotizar al IMSS")

with tab_semaforo:
    st.caption(
        "Compara el impacto de esperar 12 meses en la porción bancaria de tu crédito "
        "(Infonavit no aplica aquí — su tasa depende de tu nivel salarial, no de la TIIE)."
    )

    with st.spinner("Calculando impacto de mercado..."):
        try:
            proyeccion = proyectar_tasa_hipotecaria(horizonte_dias=365)
            resultado_semaforo = semaforo(proyeccion)
            resultados["semaforo"] = resultado_semaforo
            tasa_proyectada = resultado_semaforo["tasa_proyectada"]

            precio_mediana = None
            variacion_pct = None
            pct_ciudad = percentiles_ciudad(ciudad)
            var_ciudad = cargar_variacion_shf()
            fila = var_ciudad[var_ciudad["ciudad"] == ciudad]
            if pct_ciudad and not fila.empty:
                precio_mediana = pct_ciudad["mediana"]
                variacion_pct = fila["variacion_anual_pct"].iloc[0]

            if resultados.get("banco"):
                capacidades_elegibles = [resultados["banco"]["capacidad_total"]]
                if resultados.get("infonavit") and resultados["infonavit"].get("elegible"):
                    capacidades_elegibles.append(resultados["infonavit"]["capacidad_total"])
                if resultados.get("cofinavit") and resultados["cofinavit"].get("elegible"):
                    capacidades_elegibles.append(resultados["cofinavit"]["capacidad_total"])
                mejor_capacidad = max(capacidades_elegibles)
                pos_mejor = posicion_mercado(ciudad, mejor_capacidad)
                if pos_mejor:
                    resultados["por_debajo_p25"] = mejor_capacidad < pos_mejor["p25"]

            if resultados.get("por_debajo_p25"):
                st.warning(
                    "⚠️ Ni con tu mejor opción de crédito alcanzas el 25% de las viviendas más "
                    f"económicas de {nombre_ciudad} hoy. Lo que sigue indica **cuándo** conviene "
                    "actuar en cuanto tengas la capacidad suficiente — no que ya puedas comprar."
                )

            m1, m2 = st.columns(2)
            m1.metric("Tasa bancaria actual", f"{resultado_semaforo['tasa_actual']:.2%}")
            m2.metric("Tasa proyectada (12m)", f"{resultado_semaforo['tasa_proyectada']:.2%}",
                      delta=f"{resultado_semaforo['delta_pp']:.2f} pp")

            forecast = proyeccion["forecast_completo"]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=forecast["ds"], y=forecast["yhat"] / 100 + 0.035,
                name="Tasa hipotecaria proyectada", mode="lines", line=dict(color="#C1662F"),
            ))
            fig.add_trace(go.Scatter(
                x=list(forecast["ds"]) + list(forecast["ds"][::-1]),
                y=list(forecast["yhat_upper"] / 100 + 0.035) + list(forecast["yhat_lower"][::-1] / 100 + 0.035),
                fill="toself", fillcolor="rgba(193,102,47,0.15)", line=dict(width=0),
                name="Intervalo de confianza", showlegend=True,
            ))
            fig.update_layout(
                title="Tendencia de la tasa hipotecaria (histórico + proyección 12 meses)",
                xaxis_title="Fecha", yaxis_title="Tasa", yaxis_tickformat=".1%",
                height=300, margin=dict(t=40, b=20, l=20, r=20),
            )
            st.plotly_chart(fig, use_container_width=True)

            st.divider()

            if resultados.get("banco") and precio_mediana is not None:
                banco = resultados["banco"]
                impacto_banco = _calcular_impacto(
                    banco["mensualidad_estimada"], banco["monto_max"], banco["plazo_anios"],
                    tasa_proyectada, precio_mediana, variacion_pct,
                )
                _mostrar_bloque_impacto("Crédito bancario", impacto_banco)
                resultados["impacto_banco"] = impacto_banco

            st.divider()

            if resultados.get("cofinavit") and resultados["cofinavit"].get("elegible") and precio_mediana is not None:
                cofi = resultados["cofinavit"]
                comp_banco = cofi["componente_bancario"]
                if comp_banco["monto"] > 0:
                    impacto_cofi = _calcular_impacto(
                        comp_banco["mensualidad"], comp_banco["monto"], 20,
                        tasa_proyectada, precio_mediana, variacion_pct,
                    )
                    _mostrar_bloque_impacto("Cofinavit (solo porción bancaria)", impacto_cofi)
                    resultados["impacto_cofinavit"] = impacto_cofi
                    st.caption(
                        "La porción Infonavit del Cofinavit no cambia con esta proyección — "
                        "su tasa depende de tu nivel salarial, no de la TIIE."
                    )
                else:
                    st.info("En este escenario, Cofinavit no tiene componente bancario adicional.")

        except Exception as e:
            st.warning(f"No se pudo calcular el semáforo: {e}")

with tab_resumen:
    st.caption("Un resumen breve de tu situación, escrito por el asistente.")
    if st.button("Generar mi resumen"):
        with st.spinner("Armando tu resumen..."):
            resumen = generar_resumen_estructurado(
                {"ingreso": ingreso, "edad": edad, "ciudad": nombre_ciudad, "formal": formal},
                resultados,
            )
        if "error" in resumen:
            st.warning(resumen["error"])
        else:
            st.info(_escapar_dolar(resumen["resumen"]))
            c1, c2, c3 = st.columns(3)
            c1.metric("Mejor opción", resumen["mejor_opcion"].replace("_", " ").title())
            c2.write(f"**Riesgo principal**\n\n{_escapar_dolar(resumen['riesgo_principal'])}")
            c3.write(f"**Siguiente paso**\n\n{_escapar_dolar(resumen['siguiente_paso'])}")

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
                st.write(_escapar_dolar(mensaje["content"]))

    pregunta = st.chat_input("Ej. ¿Y si mi ingreso fuera de $25,000?")
    if pregunta:
        st.session_state.historial_chat.append({"role": "user", "content": pregunta})
        with st.chat_message("user"):
            st.write(pregunta)

        perfil = {"ingreso": ingreso, "edad": edad, "ciudad": nombre_ciudad, "formal": formal}
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                respuesta = responder(pregunta, st.session_state.historial_chat[:-1], perfil, resultados)
                st.write(_escapar_dolar(respuesta))
        st.session_state.historial_chat.append({"role": "assistant", "content": respuesta})

st.divider()
st.caption(
    "🏠 Radar Hipotecario ofrece información educativa basada en reglas públicas y datos "
    "oficiales SHF — no es asesoría financiera ni una precalificación oficial de Infonavit "
    "o de ningún banco."
)