"""
Asistente conversacional — explica resultados, RECALCULA escenarios vía function
calling (tool use de Claude), y genera resúmenes estructurados (structured outputs).

Equivalentes usados (Anthropic vs. lo visto en el notebook de referencia del profesor,
que usa OpenAI):
  - Function calling  → Anthropic "tool use": el modelo decide invocar una tool con
    input_schema definido; nosotros ejecutamos la función real y regresamos el resultado.
  - Structured outputs → Anthropic tool use FORZADO (tool_choice fijo a una sola tool):
    el modelo no puede responder texto libre, solo llenar el schema.

Principio de seguridad que se mantiene: el LLM nunca inventa un número financiero.
En el modo chat, los resultados ya calculados van en el contexto (solo lectura).
En el modo tool use, cualquier recálculo pasa por src/motor_reglas/ real — el LLM
decide QUÉ calcular, pero el motor de reglas determinista calcula el CÓMO.

Dos tools disponibles:
  - recalcular_escenarios_credito: sentido directo (ingreso → capacidad). Para
    escenarios hipotéticos donde el usuario da un ingreso distinto.
  - ingreso_necesario_para_precio: sentido inverso (precio objetivo → ingreso).
    Resuelto por búsqueda binaria en Python sobre el motor de reglas real — NO por
    el modelo adivinando ingresos y llamando recalcular_escenarios_credito varias
    veces (eso agota el presupuesto de tokens/turnos antes de producir texto).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DIR_SNAPSHOTS
from src.modelos.precio_referencia import ETIQUETAS_PERCENTIL
from src.motor_reglas.bancario import escenario_bancario, escenario_cofinavit
from src.motor_reglas.infonavit import escenario_infonavit

SYSTEM_PROMPT_BASE = """Eres el asistente de Radar Hipotecario, una herramienta educativa \
que ayuda a personas en México a entender sus opciones de crédito para comprar vivienda.

Reglas estrictas:
1. NUNCA inventes ni calcules a mano tasas, montos o mensualidades. Si el usuario pregunta \
un escenario distinto al que ya tienes en contexto (otro salario, otra ciudad, otro enganche), \
usa la tool `recalcular_escenarios_credito` — no lo estimes tú.
1.5. Si el usuario pregunta lo INVERSO — "¿cuál debería ser mi ingreso para alcanzar tal \
precio/capacidad?" — usa la tool `ingreso_necesario_para_precio` en UNA sola llamada. \
NUNCA intentes converger a mano llamando `recalcular_escenarios_credito` varias veces con \
ingresos adivinados — eso es lento, impreciso y puede dejarte sin espacio para responder.
2. Los "Resultados calculados del usuario" que se te dan abajo son el escenario ACTUAL en \
pantalla — úsalos para explicar, y usa las tools solo para escenarios HIPOTÉTICOS distintos. \
El perfil completo (ingreso, edad, sexo, ciudad, IMSS, SSV, enganche) ya está en ese bloque — \
NUNCA vuelvas a pedirle al usuario un dato que ya aparece ahí; solo pide lo que falte \
genuinamente (ej. un precio objetivo) o lo que el usuario quiera cambiar explícitamente.
2.5. El impacto de esperar 12 meses se calcula por separado para Banco y para la porción \
bancaria de Cofinavit — pueden diferir entre sí. Cítalos según cuál pregunte el usuario.
3. Puedes responder preguntas GENERALES sobre crédito hipotecario en México (qué es \
Infonavit, cómo funciona el Cofinavit, qué es la UMA, etc.) con tu conocimiento general.
4. Siempre deja claro que esto es información educativa, no asesoría financiera \
personalizada ni una precalificación oficial de Infonavit o de ningún banco.
5. Responde en español, tono claro y directo, sin tecnicismos innecesarios, y breve.
6. Al hablar de percentiles de precio de vivienda, usa SIEMPRE el lenguaje plano ya \
usado en el contexto — "entrada al mercado" (no "P25"), "precio típico" (no "mediana" \
sola, aunque puedes decir "precio típico (mediana)" si ayuda), "gama alta" (no "P75"). \
Nunca uses las siglas P25/P75 ni la palabra "percentil" al hablarle al usuario.
"""


def _tasa_bancaria_actual() -> float:
    ruta = DIR_SNAPSHOTS / "latest" / "series_banxico.parquet"
    series = pd.read_parquet(ruta)
    if "tasa_hipotecaria_promedio" in series["serie"].unique():
        return series.loc[series["serie"] == "tasa_hipotecaria_promedio", "valor"].iloc[-1] / 100
    tiie = series.loc[series["serie"] == "tiie_28", "valor"].iloc[-1] / 100
    return tiie + 0.035


def _formatear_impacto(nombre: str, im: dict) -> str:
    conclusion = "conviene ESPERAR" if im["neto_12m"] > 0 else "conviene COMPRAR AHORA"
    return (
        f"Impacto de esperar 12 meses ({nombre}): ahorro en pagos ${im['ahorro_12m']:,.0f} − "
        f"aumento de precio estimado ${im['costo_precio_12m']:,.0f} = neto ${im['neto_12m']:,.0f} "
        f"→ {conclusion}."
    )


def _formatear_contexto(perfil: dict, resultados: dict) -> str:
    partes = ["Resultados calculados del usuario (escenario ACTUAL en pantalla):", ""]
    partes.append(f"Perfil: ingreso mensual ${perfil.get('ingreso', 0):,.0f} MXN, "
                   f"edad {perfil.get('edad')}, sexo {perfil.get('sexo', 'no especificado')}, "
                   f"ciudad {perfil.get('ciudad')}, "
                   f"{'cotiza' if perfil.get('formal') else 'no cotiza'} al IMSS, "
                   f"subcuenta de vivienda (SSV) ${perfil.get('ssv', 0):,.0f} MXN, "
                   f"enganche disponible ${perfil.get('enganche', 0):,.0f} MXN.")
    partes.append("")

    if resultados.get("infonavit"):
        e = resultados["infonavit"]
        if e.get("elegible"):
            partes.append(f"Infonavit: tasa {e['tasa_anual']:.2%}, capacidad total "
                           f"${e['capacidad_total']:,.0f}, mensualidad ${e['mensualidad_estimada']:,.0f}.")
        else:
            partes.append(f"Infonavit: no elegible — {e.get('motivo', '')}.")

    if resultados.get("banco"):
        e = resultados["banco"]
        partes.append(f"Banco: tasa {e['tasa_anual']:.2%}, capacidad total "
                       f"${e['capacidad_total']:,.0f}, mensualidad ${e['mensualidad_estimada']:,.0f}.")

    if resultados.get("cofinavit") and resultados["cofinavit"].get("elegible"):
        e = resultados["cofinavit"]
        partes.append(f"Cofinavit: capacidad total combinada ${e['capacidad_total']:,.0f}.")

    if resultados.get("semaforo"):
        s = resultados["semaforo"]
        partes.append(f"Tasa bancaria — señal aislada: {s['senal']} — {s['razon']}")

    if resultados.get("posicion_mercado"):
        pm = resultados["posicion_mercado"]
        partes.append(f"Posición vs. mercado (SHF): {pm['mensaje']} "
                       f"({ETIQUETAS_PERCENTIL['p25']} ${pm['p25']:,.0f}, "
                       f"{ETIQUETAS_PERCENTIL['mediana']} ${pm['mediana']:,.0f}, "
                       f"{ETIQUETAS_PERCENTIL['p75']} ${pm['p75']:,.0f}).")

    if resultados.get("impacto_banco"):
        partes.append(_formatear_impacto("crédito bancario", resultados["impacto_banco"]))

    if resultados.get("impacto_cofinavit"):
        partes.append(_formatear_impacto("porción bancaria de Cofinavit", resultados["impacto_cofinavit"]))

    return "\n".join(partes)


# ── Motor de búsqueda inversa (precio objetivo → ingreso necesario) ──────
_SALARIO_MIN = 5_000.0
_SALARIO_MAX = 500_000.0
_ITERACIONES_BISECCION = 40  # converge a << $0.01 de precisión en salario


def _capacidad_para_salario(via: str, salario: float, edad: int, sexo: str,
                             formal: bool, ssv: float, enganche: float, tasa_banco: float) -> float | None:
    """Regresa la capacidad_total del motor de reglas real para un salario dado,
    o None si esa vía no es elegible para este perfil (independientemente del salario)."""
    if via == "banco":
        return escenario_bancario(salario, enganche, tasa_anual=tasa_banco)["capacidad_total"]

    if not formal:
        return None  # Infonavit y Cofinavit requieren IMSS, sin importar el ingreso

    if via == "infonavit":
        e = escenario_infonavit(salario, edad, sexo, ssv=ssv)
        return e["capacidad_total"] if e.get("elegible") else 0.0

    if via == "cofinavit":
        e = escenario_cofinavit(salario, edad, sexo, ssv, enganche, tasa_banco)
        return e["capacidad_total"] if e.get("elegible") else 0.0

    raise ValueError(f"Vía desconocida: {via}")


def _ingreso_necesario(precio_objetivo: float, via: str, edad: int, sexo: str,
                        formal: bool, ssv: float, enganche: float, tasa_banco: float) -> dict:
    """Búsqueda binaria del salario mínimo tal que capacidad_total >= precio_objetivo,
    usando el motor de reglas real en cada evaluación (determinista, sin LLM)."""
    capacidad_no_elegible = _capacidad_para_salario(via, _SALARIO_MIN, edad, sexo, formal, ssv, enganche, tasa_banco)
    if capacidad_no_elegible is None:
        return {"elegible_via": False, "motivo": "Esta vía requiere cotizar al IMSS"}

    lo, hi = _SALARIO_MIN, _SALARIO_MAX
    capacidad_max = _capacidad_para_salario(via, hi, edad, sexo, formal, ssv, enganche, tasa_banco)
    if capacidad_max < precio_objetivo:
        return {
            "elegible_via": True,
            "alcanzable": False,
            "motivo": f"Ni con ${_SALARIO_MAX:,.0f}/mes esta vía alcanza el precio objetivo",
            "capacidad_con_salario_maximo": round(capacidad_max, 2),
        }

    for _ in range(_ITERACIONES_BISECCION):
        mid = (lo + hi) / 2
        capacidad_mid = _capacidad_para_salario(via, mid, edad, sexo, formal, ssv, enganche, tasa_banco)
        if capacidad_mid >= precio_objetivo:
            hi = mid
        else:
            lo = mid

    ingreso_necesario = round(hi, 2)
    capacidad_final = round(_capacidad_para_salario(via, ingreso_necesario, edad, sexo, formal, ssv, enganche, tasa_banco), 2)
    return {
        "elegible_via": True,
        "alcanzable": True,
        "ingreso_mensual_necesario": ingreso_necesario,
        "capacidad_total_resultante": capacidad_final,
    }


# ── Function calling (tool use) ──────────────────────────────────────────
TOOLS = [
    {
        "name": "recalcular_escenarios_credito",
        "description": (
            "Recalcula los tres escenarios de crédito (Infonavit, banco, Cofinavit) "
            "para un salario, edad, sexo, enganche y subcuenta de vivienda DISTINTOS "
            "a los del escenario actual en pantalla. Usa el motor de reglas real — "
            "nunca estimes estos números tú mismo. Para preguntas del tipo 'cuál "
            "ingreso necesito para alcanzar X precio', usa en cambio "
            "`ingreso_necesario_para_precio` — no llames esta tool varias veces "
            "adivinando salarios para converger."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "salario_mensual": {"type": "number", "description": "Ingreso mensual en MXN"},
                "edad": {"type": "integer", "description": "Edad de la persona"},
                "sexo": {"type": "string", "enum": ["Hombre", "Mujer"]},
                "cotiza_imss": {"type": "boolean", "description": "Si cotiza al IMSS (empleo formal)"},
                "ssv": {"type": "number", "description": "Subcuenta de vivienda aproximada en MXN, default 0"},
                "enganche": {"type": "number", "description": "Enganche disponible en MXN, default 0"},
            },
            "required": ["salario_mensual", "edad", "sexo", "cotiza_imss"],
        },
    },
    {
        "name": "ingreso_necesario_para_precio",
        "description": (
            "Calcula, en una sola llamada, el ingreso mensual MÍNIMO necesario para "
            "alcanzar una capacidad total de crédito objetivo (ej. el precio de una "
            "vivienda o una referencia de mercado como la mediana SHF), para UNA vía "
            "de crédito específica (banco, infonavit o cofinavit). Se resuelve por "
            "búsqueda binaria sobre el motor de reglas real — exacto y en una sola "
            "llamada. Si necesitas comparar las tres vías, llama esta tool tres veces "
            "(una por vía), no adivines ni interpoles a mano."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "precio_objetivo": {"type": "number", "description": "Capacidad total / precio de vivienda objetivo en MXN"},
                "via": {"type": "string", "enum": ["banco", "infonavit", "cofinavit"]},
                "edad": {"type": "integer", "description": "Edad de la persona"},
                "sexo": {"type": "string", "enum": ["Hombre", "Mujer"]},
                "cotiza_imss": {"type": "boolean", "description": "Si cotiza al IMSS (empleo formal)"},
                "ssv": {"type": "number", "description": "Subcuenta de vivienda aproximada en MXN, default 0"},
                "enganche": {"type": "number", "description": "Enganche disponible en MXN, default 0"},
            },
            "required": ["precio_objetivo", "via", "edad", "sexo", "cotiza_imss"],
        },
    },
]


def _ejecutar_tool(nombre: str, entrada: dict) -> dict:
    if nombre == "recalcular_escenarios_credito":
        salario = entrada["salario_mensual"]
        edad = entrada["edad"]
        sexo = entrada["sexo"][0]
        formal = entrada["cotiza_imss"]
        ssv = entrada.get("ssv", 0)
        enganche = entrada.get("enganche", 0)

        salida = {}
        if formal:
            salida["infonavit"] = escenario_infonavit(salario, edad, sexo, ssv=ssv)
            tasa_banco = _tasa_bancaria_actual()
            salida["cofinavit"] = escenario_cofinavit(salario, edad, sexo, ssv, enganche, tasa_banco)
        else:
            salida["infonavit"] = {"elegible": False, "motivo": "No cotiza al IMSS"}

        tasa_banco = _tasa_bancaria_actual()
        salida["banco"] = escenario_bancario(salario, enganche, tasa_anual=tasa_banco)
        return salida

    if nombre == "ingreso_necesario_para_precio":
        edad = entrada["edad"]
        sexo = entrada["sexo"][0]
        formal = entrada["cotiza_imss"]
        ssv = entrada.get("ssv", 0)
        enganche = entrada.get("enganche", 0)
        tasa_banco = _tasa_bancaria_actual()
        return _ingreso_necesario(
            entrada["precio_objetivo"], entrada["via"], edad, sexo, formal, ssv, enganche, tasa_banco,
        )

    return {"error": f"Tool desconocida: {nombre}"}


def responder(pregunta: str, historial: list[dict], perfil: dict, resultados: dict) -> str:
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ("⚠️ Falta configurar ANTHROPIC_API_KEY en el archivo .env. "
                "Regístrate en console.anthropic.com para obtener una key.")

    client = Anthropic(api_key=api_key)
    system_prompt = SYSTEM_PROMPT_BASE + "\n\n" + _formatear_contexto(perfil, resultados)
    mensajes = historial + [{"role": "user", "content": pregunta}]

    MAX_VUELTAS = 4
    for _ in range(MAX_VUELTAS):
        respuesta = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=3000,
            output_config={"effort": "medium"},  # este caso de uso (orquestar tools + explicar)
                                                   # no necesita el default "high"; alto effort +
                                                   # thinking adaptativo puede agotar max_tokens
                                                   # solo en thinking antes de responder texto
            system=system_prompt,
            tools=TOOLS,
            messages=mensajes,
        )

        if respuesta.stop_reason != "tool_use":
            bloques_texto = [b.text for b in respuesta.content if b.type == "text"]
            if bloques_texto:
                return "".join(bloques_texto)
            if respuesta.stop_reason == "max_tokens":
                return ("⚠️ La respuesta se cortó antes de generar texto (límite de tokens). "
                        "Intenta reformular tu pregunta de forma más específica o directa.")
            return "⚠️ Sin respuesta de texto."

        mensajes.append({"role": "assistant", "content": respuesta.content})
        resultados_tools = []
        for bloque in respuesta.content:
            if bloque.type == "tool_use":
                resultado = _ejecutar_tool(bloque.name, bloque.input)
                resultados_tools.append({
                    "type": "tool_result",
                    "tool_use_id": bloque.id,
                    "content": json.dumps(resultado, ensure_ascii=False, default=str),
                })
        mensajes.append({"role": "user", "content": resultados_tools})

    return "⚠️ El asistente no logró completar la respuesta tras varios intentos de cálculo."


def generar_resumen_estructurado(perfil: dict, resultados: dict) -> dict:
    """
    Devuelve un resumen del caso en un JSON validado por schema — equivalente a
    Structured Outputs de OpenAI. Se fuerza con tool_choice a una sola tool.
    """
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "Falta ANTHROPIC_API_KEY en .env"}

    client = Anthropic(api_key=api_key)
    contexto = _formatear_contexto(perfil, resultados)

    schema_resumen = {
        "name": "registrar_resumen",
        "description": "Registra un resumen estructurado del caso de crédito del usuario.",
        "input_schema": {
            "type": "object",
            "properties": {
                "resumen": {"type": "string", "description": "Resumen del caso en 2-3 frases, en español, tono cercano"},
                "mejor_opcion": {
                    "type": "string",
                    "enum": ["infonavit", "banco", "cofinavit", "ninguna_elegible"],
                    "description": "La vía de crédito con mayor capacidad total entre las elegibles",
                },
                "riesgo_principal": {"type": "string", "description": "El riesgo o limitante más importante del caso, una frase"},
                "siguiente_paso": {"type": "string", "description": "Una acción concreta recomendada, una frase"},
            },
            "required": ["resumen", "mejor_opcion", "riesgo_principal", "siguiente_paso"],
        },
    }

    respuesta = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=800,
        output_config={"effort": "medium"},
        system=SYSTEM_PROMPT_BASE + "\n\n" + contexto,
        tools=[schema_resumen],
        tool_choice={"type": "tool", "name": "registrar_resumen"},
        messages=[{"role": "user", "content": "Genera el resumen de este caso, en tono cercano y sencillo."}],
    )

    bloque = next((b for b in respuesta.content if b.type == "tool_use"), None)
    if bloque is None:
        return {"error": "El modelo no devolvió el resumen estructurado."}
    return bloque.input