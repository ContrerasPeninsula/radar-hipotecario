"""
Cruce inventario real × capacidad de crédito.

Usa el detalle de anuncios (no el agregado del K-Means) para calcular qué
porcentaje de la oferta real en una ciudad es alcanzable con la capacidad
de crédito de cada escenario (Infonavit/banco/Cofinavit). Esta es la pieza
de "gancho visual" definida desde el diseño original del proyecto.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DIR_DATA

MUESTRA_MINIMA = 10  # por debajo de esto, el % no es confiable para mostrar sin advertencia

def cargar_listados(ciudad: str, ruta_parquet: Path | None = None) -> pd.DataFrame:
    ruta = ruta_parquet or (DIR_DATA / "oferta_inmuebles24.parquet")
    if not ruta.exists():
        return pd.DataFrame()
    detalle = pd.read_parquet(ruta)
    return detalle[detalle["ciudad"] == ciudad]


def pct_inventario_alcanzable(ciudad: str, capacidad_total: float) -> dict | None:
    """
    Devuelve {pct, n_alcanzables, n_total} o None si no hay datos de esa ciudad.
    "Alcanzable" = precio total del anuncio <= capacidad_total del escenario.
    """
    listados = cargar_listados(ciudad)
    if listados.empty:
        return None

    n_total = len(listados)
    n_alcanzables = int((listados["precio"] <= capacidad_total).sum())
    return {
        "pct": round(100 * n_alcanzables / n_total, 1),
        "n_alcanzables": n_alcanzables,
        "n_total": n_total,
        "muestra_pequena": n_total < MUESTRA_MINIMA,
    }