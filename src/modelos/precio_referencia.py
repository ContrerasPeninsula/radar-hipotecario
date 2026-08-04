"""
Posicionamiento de capacidad de crédito contra el mercado real de cada entidad —
100% oficial SHF (config/shf_nacional.json), cero dependencia del scraper.

Reemplaza el archivo separado shf_percentiles_ciudades.json (3 ciudades) — ahora
una sola fuente de verdad (shf_nacional.json) alimenta tanto esto como el K-Means
en src/modelos/segmentacion_ciudades.py, para las 32 entidades federativas.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import CIUDADES, DIR_CONFIG


def _cargar_nacional() -> dict:
    ruta = DIR_CONFIG / "shf_nacional.json"
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def percentiles_ciudad(ciudad: str) -> dict | None:
    """Devuelve P25/mediana/P75 de una ciudad (clave interna, ej. 'cdmx')."""
    entidad = CIUDADES.get(ciudad)
    if entidad is None:
        return None
    data = _cargar_nacional()
    info = data["estados"].get(entidad)
    if info is None:
        return None
    return {"p25": info["p25"], "mediana": info["mediana"], "p75": info["p75"]}


def posicion_mercado(ciudad: str, capacidad_total: float) -> dict | None:
    """
    Ubica la capacidad de crédito del usuario contra los percentiles P25/mediana/P75
    de precio de vivienda en esa entidad (SHF). Devuelve tier, percentiles y mensaje.
    """
    pct = percentiles_ciudad(ciudad)
    if pct is None:
        return None

    p25, mediana, p75 = pct["p25"], pct["mediana"], pct["p75"]

    if capacidad_total < p25:
        tier = "por debajo del 25% más accesible"
        mensaje = "Tu capacidad está por debajo del 25% de las viviendas más económicas de esta entidad."
    elif capacidad_total < mediana:
        tier = "en el rango accesible (25%-50%)"
        mensaje = "Tu capacidad te ubica en el segmento accesible del mercado — por debajo de la mediana."
    elif capacidad_total < p75:
        tier = "en el rango medio-alto (50%-75%)"
        mensaje = "Tu capacidad supera la mediana del mercado — accedes a una porción amplia de la oferta."
    else:
        tier = "en el 25% superior"
        mensaje = "Tu capacidad te ubica en el segmento más alto del mercado de esta entidad."

    return {
        "tier": tier,
        "mensaje": mensaje,
        "p25": p25,
        "mediana": mediana,
        "p75": p75,
    }