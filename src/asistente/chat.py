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
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DIR_SNAPSHOTS
from src.motor_reglas.bancario import escenario_bancario, escenario_cofinavit
from src.motor_reglas.infonavit import escenario_infonavit

SYSTEM_PROMPT_BASE = """Eres el asistente de Radar Hipotecario, una herramienta educativa \
que ayuda a personas en México a entender sus opciones de crédito para comprar vivienda.

Reglas estrictas:
1. NUNCA inventes ni calcules a mano tasas, montos o mensualidades. Si el usuario pregunta \
un escenario distinto al que ya tienes en contexto (otro salario, otra ciudad, otro enganche), \
usa la tool `recalcular_escenarios_credito` — no lo estimes tú.
2. Los "Resultados calculados del usuario" que se te dan abajo son el escenario ACTUAL en \
pantalla — úsalos para explicar, y usa la tool solo para escenarios HIPOTÉTICOS distintos.
2.5. El impacto de esperar 12 meses se calcula por separado para Banco y para la porción \
bancaria de Cofinavit — pueden diferir entre sí. Cítalos según cuál pregunte el usuario.
3. Puedes responder preguntas GENERALES sobre crédito hipotecario en México (qué es \
Infonavit, cómo funciona el Cofinavit, qué es la UMA, etc.) con tu conocimiento general.
4. Siempre deja claro que esto es información educativa, no asesoría financiera \
personalizada ni una precalificación oficial de Infonavit o de ningún banco.
5. Responde en español, tono claro y directo, sin tecnicismos innecesarios, y breve.
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
                   f"edad {perfil.get('edad')}, ciudad {perfil.get('ciudad')}, "
                   f"{'cotiza' if perfil.get('formal') else 'no cotiza'} al IMSS.")
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
                       f"(P25 ${pm['p25']:,.0f}, Mediana ${pm['mediana']:,.0f}, P75 ${pm['p75']:,.0f}).")

    if resultados.get("impacto_banco"):
        partes.append(_formatear_impacto("crédito bancario", resultados["impacto_banco"]))

    if resultados.get("impacto_cofinavit"):
        partes.append(_formatear_impacto("porción bancaria de Cofinavit", resultados["impacto_cofinavit"]))

    return "\n".join(partes)


# ── Function calling (tool use) ──────────────────────────────────────────
TOOLS = [
    {
        "name": "recalcular_escenarios_credito",
        "description": (
            "Recalcula los tres escenarios de crédito (Infonavit, banco, Cofinavit) "
            "para un salario, edad, sexo, enganche y subcuenta de vivienda DISTINTOS "
            "a los del escenario actual en pantalla. Usa el motor de reglas real — "
            "nunca estimes estos números tú mismo."
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
    }
]


def _ejecutar_tool(nombre: str, entrada: dict) -> dict:
    if nombre != "recalcular_escenarios_credito":
        return {"error": f"Tool desconocida: {nombre}"}

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
            max_tokens=800,
            system=system_prompt,
            tools=TOOLS,
            messages=mensajes,
        )

        if respuesta.stop_reason != "tool_use":
            bloques_texto = [b.text for b in respuesta.content if b.type == "text"]
            return "".join(bloques_texto) if bloques_texto else "⚠️ Sin respuesta de texto."

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
        max_tokens=500,
        system=SYSTEM_PROMPT_BASE + "\n\n" + contexto,
        tools=[schema_resumen],
        tool_choice={"type": "tool", "name": "registrar_resumen"},
        messages=[{"role": "user", "content": "Genera el resumen de este caso, en tono cercano y sencillo."}],
    )

    bloque = next((b for b in respuesta.content if b.type == "tool_use"), None)
    if bloque is None:
        return {"error": "El modelo no devolvió el resumen estructurado."}
    return bloque.input