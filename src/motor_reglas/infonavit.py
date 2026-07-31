"""
Motor de reglas Infonavit — determinista, sin ML.
Fuente de verdad: config/reglas_infonavit_v2026.json + config/uma.json.
Se documenta en el paper como 'motor de reglas de negocio', separado de la capa predictiva.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DIR_CONFIG


def _cargar_json(nombre: str) -> dict:
    with open(DIR_CONFIG / nombre, encoding="utf-8") as f:
        return json.load(f)


def uma_vigente(fecha: date | None = None) -> dict:
    """La UMA se resuelve por fecha de cálculo — enero usa la UMA del año previo."""
    fecha = fecha or date.today()
    for v in _cargar_json("uma.json")["valores"]:
        ini = date.fromisoformat(v["vigencia_inicio"])
        fin = date.fromisoformat(v["vigencia_fin"])
        if ini <= fecha <= fin:
            return v
    raise ValueError(f"Sin valor de UMA vigente para {fecha} — actualizar config/uma.json")


def _mensualidad(monto: float, tasa_anual: float, plazo_anios: int) -> float:
    """Amortización francesa estándar."""
    i = tasa_anual / 12
    n = plazo_anios * 12
    if i == 0:
        return monto / n
    return monto * (i * (1 + i) ** n) / ((1 + i) ** n - 1)


def escenario_infonavit(
    salario_mensual: float,
    edad: int,
    sexo: str,
    ssv: float = 0.0,
    plazo_anios: int | None = None,
    fecha: date | None = None,
) -> dict:
    """
    Calcula el escenario de crédito Infonavit individual.

    Returns dict con: elegible, motivo, tasa_anual, monto_max, plazo_anios,
    mensualidad_estimada, capacidad_total (monto + SSV), version_reglas.
    """
    reglas = _cargar_json("reglas_infonavit_v2026.json")
    uma = uma_vigente(fecha)

    if reglas["estado"] == "PENDIENTE_VALIDACION":
        # No bloquea la ejecución, pero toda salida queda marcada
        advertencia = "Reglas en borrador — pendiente validar tabla de tasas oficial"
    else:
        advertencia = None

    tope = reglas["plazo"]["tope_edad_mas_plazo"]["mujer" if sexo.lower().startswith("m") else "hombre"]
    plazo_max = min(reglas["plazo"]["max_anios"], tope - edad)
    if plazo_max < reglas["plazo"]["min_anios"]:
        return {"elegible": False, "motivo": f"Edad + plazo excede el tope de {tope} años"}

    plazo = min(plazo_anios or plazo_max, plazo_max)

    # ── Tasa ────────────────────────────────────────────────────────────
    # DECISION #1 pendiente: si existe tabla diferenciada validada, usarla;
    # mientras tanto, tasa única del producto estándar.
    tabla = reglas["tasas"]["tabla_diferenciada_por_uma"]
    if tabla:
        salario_en_umas = salario_mensual / uma["mensual"]
        tasa = next(
            (t["tasa"] for t in tabla if t["uma_min"] <= salario_en_umas < t["uma_max"]),
            reglas["tasas"]["tasa_unica_producto_estandar"],
        )
    else:
        tasa = reglas["tasas"]["tasa_unica_producto_estandar"]

    # ── Monto máximo ────────────────────────────────────────────────────
    # Capacidad de pago: descuento vía nómina; criterio conservador 30% del salario.
    pago_max = salario_mensual * 0.30
    i, n = tasa / 12, plazo * 12
    monto_por_capacidad = pago_max * ((1 + i) ** n - 1) / (i * (1 + i) ** n)
    monto = min(monto_por_capacidad, reglas["montos"]["maximo_compra_mxn"])

    return {
        "elegible": True,
        "advertencia": advertencia,
        "tasa_anual": tasa,
        "monto_max": round(monto, 2),
        "plazo_anios": plazo,
        "mensualidad_estimada": round(_mensualidad(monto, tasa, plazo), 2),
        "ssv_aplicado": ssv,
        "capacidad_total": round(monto + ssv, 2),
        "uma_usada": uma["mensual"],
        "version_reglas": reglas["version"],
    }


if __name__ == "__main__":
    from pprint import pprint
    pprint(escenario_infonavit(salario_mensual=18000, edad=32, sexo="H", ssv=150000))
