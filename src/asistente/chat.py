"""
Asistente conversacional — explica los resultados calculados del usuario y
responde dudas generales sobre financiamiento hipotecario en México.

Capa de USO/interfaz, no de modelación: el LLM nunca recalcula tasas ni montos.
Todos los números que puede citar vienen ya calculados por el motor de reglas
(src/motor_reglas/) y la capa predictiva (src/modelos/forecast_tasas.py) —
se le pasan como contexto de solo lectura en el system prompt.
"""
from __future__ import annotations

import os

SYSTEM_PROMPT_BASE = """Eres el asistente de Radar Hipotecario, una herramienta educativa \
que ayuda a personas en México a entender sus opciones de crédito para comprar vivienda.

Reglas estrictas:
1. NUNCA inventes ni recalcules tasas, montos o mensualidades. Usa ÚNICAMENTE los \
números que se te dan en "Resultados calculados del usuario" más abajo.
2. Si el usuario pregunta algo que requeriría un número que no está en ese contexto \
(por ejemplo, otra ciudad, otro salario), dile que puede recalcularlo cambiando los \
datos en el panel izquierdo de la app — no lo estimes tú.
3. Puedes responder preguntas GENERALES sobre crédito hipotecario en México (qué es \
Infonavit, cómo funciona el Cofinavit, qué es la UMA, etc.) con tu conocimiento general.
4. Siempre deja claro que esto es información educativa, no asesoría financiera \
personalizada ni una precalificación oficial de Infonavit o de ningún banco.
5. Responde en español, tono claro y directo, sin tecnicismos innecesarios.
6. Respuestas breves — este es un chat de apoyo dentro de una app, no un ensayo.
"""


def _formatear_contexto(perfil: dict, resultados: dict) -> str:
    """Convierte el perfil del usuario y los resultados ya calculados en texto
    legible para el system prompt. No agrega ni infiere nada nuevo."""
    partes = ["Resultados calculados del usuario (fuente de verdad, no recalcular):", ""]

    partes.append(f"Perfil: ingreso mensual ${perfil.get('ingreso', 0):,.0f} MXN, "
                   f"edad {perfil.get('edad')}, ciudad {perfil.get('ciudad')}, "
                   f"{'cotiza' if perfil.get('formal') else 'no cotiza'} al IMSS.")
    partes.append("")

    if resultados.get("infonavit"):
        e = resultados["infonavit"]
        if e.get("elegible"):
            partes.append(f"Infonavit: tasa {e['tasa_anual']:.2%}, capacidad total "
                           f"${e['capacidad_total']:,.0f}, mensualidad ${e['mensualidad_estimada']:,.0f}, "
                           f"plazo {e['plazo_anios']} años.")
        else:
            partes.append(f"Infonavit: no elegible — {e.get('motivo', 'sin especificar')}.")

    if resultados.get("banco"):
        e = resultados["banco"]
        partes.append(f"Banco: tasa referencia {e['tasa_anual']:.2%}, capacidad total "
                       f"${e['capacidad_total']:,.0f}, mensualidad ${e['mensualidad_estimada']:,.0f}, "
                       f"plazo {e['plazo_anios']} años.")

    if resultados.get("cofinavit") and resultados["cofinavit"].get("elegible"):
        e = resultados["cofinavit"]
        partes.append(f"Cofinavit: capacidad total combinada ${e['capacidad_total']:,.0f}.")

    if resultados.get("semaforo"):
        s = resultados["semaforo"]
        partes.append(f"Semáforo de mercado: {s['senal']} — tasa actual {s['tasa_actual']:.2%}, "
                       f"proyectada a 12 meses {s['tasa_proyectada']:.2%} ({s['delta_pp']:+.2f} pp). "
                       f"Razón: {s['razon']}")

    return "\n".join(partes)


def responder(pregunta: str, historial: list[dict], perfil: dict, resultados: dict) -> str:
    """
    Envía la pregunta del usuario a Claude, con el contexto de sus resultados
    calculados como system prompt. `historial` es una lista de mensajes previos
    en formato [{"role": "user"/"assistant", "content": "..."}].
    """
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ("⚠️ Falta configurar ANTHROPIC_API_KEY en el archivo .env para activar "
                "el asistente. Regístrate en console.anthropic.com para obtener una key.")

    client = Anthropic(api_key=api_key)
    system_prompt = SYSTEM_PROMPT_BASE + "\n\n" + _formatear_contexto(perfil, resultados)

    mensajes = historial + [{"role": "user", "content": pregunta}]

    respuesta = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=500,
        system=system_prompt,
        messages=mensajes,
    )
    bloques_texto = [b.text for b in respuesta.content if b.type == "text"]
    return "".join(bloques_texto) if bloques_texto else "⚠️ El modelo no devolvió texto en la respuesta."