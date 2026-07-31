"""
Motor de originación bancaria estándar + cofinanciamiento (Cofinavit).
La tasa de referencia viene del último snapshot (Banxico/CNBV), nunca hardcodeada.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import RANGO_TASA_HIPOTECARIA
from src.motor_reglas.infonavit import _mensualidad, escenario_infonavit


def escenario_bancario(
    ingreso_mensual: float,
    enganche: float,
    plazo_anios: int = 20,
    tasa_anual: float | None = None,
    pct_ingreso_max: float = 0.35,
) -> dict:
    """
    Escenario de crédito hipotecario bancario estándar.

    Args:
        tasa_anual: tasa de referencia del snapshot vigente (obligatoria en producción;
                    el caller la obtiene del último Parquet de series).
    """
    if tasa_anual is None:
        raise ValueError("tasa_anual es obligatoria — obtenerla del snapshot de series Banxico/CNBV")
    if not (RANGO_TASA_HIPOTECARIA[0] <= tasa_anual <= RANGO_TASA_HIPOTECARIA[1]):
        raise ValueError(f"Tasa {tasa_anual:.2%} fuera del rango sanity {RANGO_TASA_HIPOTECARIA}")

    pago_max = ingreso_mensual * pct_ingreso_max
    i, n = tasa_anual / 12, plazo_anios * 12
    monto_max = pago_max * ((1 + i) ** n - 1) / (i * (1 + i) ** n)

    return {
        "elegible": True,
        "tasa_anual": tasa_anual,
        "monto_max": round(monto_max, 2),
        "plazo_anios": plazo_anios,
        "mensualidad_estimada": round(_mensualidad(monto_max, tasa_anual, plazo_anios), 2),
        "enganche": enganche,
        "capacidad_total": round(monto_max + enganche, 2),
    }


def escenario_cofinavit(
    salario_mensual: float,
    edad: int,
    sexo: str,
    ssv: float,
    enganche: float,
    tasa_bancaria: float,
    plazo_anios: int = 20,
) -> dict:
    """
    Cofinanciamiento: Infonavit aporta crédito base + SSV; el banco complementa.
    La capacidad de pago se reparte para no exceder el % de ingreso total.
    """
    info = escenario_infonavit(salario_mensual, edad, sexo, ssv=ssv, plazo_anios=plazo_anios)
    if not info["elegible"]:
        return {"elegible": False, "motivo": info.get("motivo", "No elegible Infonavit")}

    # El pago Infonavit ya consume ~30% del ingreso; el banco evalúa sobre el remanente
    pago_disponible_banco = max(salario_mensual * 0.40 - info["mensualidad_estimada"], 0)
    i, n = tasa_bancaria / 12, plazo_anios * 12
    monto_banco = pago_disponible_banco * ((1 + i) ** n - 1) / (i * (1 + i) ** n) if pago_disponible_banco > 0 else 0

    return {
        "elegible": True,
        "componente_infonavit": info,
        "componente_bancario": {
            "tasa_anual": tasa_bancaria,
            "monto": round(monto_banco, 2),
            "mensualidad": round(_mensualidad(monto_banco, tasa_bancaria, plazo_anios), 2) if monto_banco else 0,
        },
        "capacidad_total": round(info["capacidad_total"] + monto_banco + enganche, 2),
    }
