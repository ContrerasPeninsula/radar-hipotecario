"""
Posicionamiento de capacidad de crédito contra el mercado real de cada ciudad —
SIN depender del scraper. Usa percentiles de precio derivados del Índice SHF
(datos oficiales de avalúos hipotecarios), escalados desde el ancla nacional
publicada por SHF hacia cada ciudad según su índice relativo.

Reemplaza pct_inventario_alcanzable() como fuente principal de la señal
"¿me alcanza en esta ciudad?" — el scraper (src/modelos/inventario.py) queda
como pieza secundaria/exploratoria, no como base de esta decisión, dado el
sesgo hacia anuncios "Destacado" ya documentado.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DIR_CONFIG


def _cargar_percentiles() -> dict:
    ruta = DIR_CONFIG / "shf_percentiles_ciudades.json"
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def posicion_mercado(ciudad: str, capacidad_total: float) -> dict | None:
    """
    Ubica la capacidad de crédito del usuario contra los percentiles P25/mediana/P75
    de precio de vivienda en esa ciudad (SHF). Devuelve tier, percentiles y mensaje.
    """
    data = _cargar_percentiles()
    info = data["ciudades"].get(ciudad)
    if info is None:
        return None

    p25, mediana, p75 = info["p25"], info["mediana"], info["p75"]

    if capacidad_total < p25:
        tier = "por debajo del 25% más accesible"
        mensaje = "Tu capacidad está por debajo del 25% de las viviendas más económicas de esta ciudad."
    elif capacidad_total < mediana:
        tier = "en el rango accesible (25%-50%)"
        mensaje = "Tu capacidad te ubica en el segmento accesible del mercado — por debajo de la mediana."
    elif capacidad_total < p75:
        tier = "en el rango medio-alto (50%-75%)"
        mensaje = "Tu capacidad supera la mediana del mercado — accedes a una porción amplia de la oferta."
    else:
        tier = "en el 25% superior"
        mensaje = "Tu capacidad te ubica en el segmento más alto del mercado de esta ciudad."

    return {
        "tier": tier,
        "mensaje": mensaje,
        "p25": p25,
        "mediana": mediana,
        "p75": p75,
    }