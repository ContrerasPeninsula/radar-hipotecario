"""
Ingesta de series del SIE de Banxico.
Salida: DataFrame largo (fecha, serie, valor) listo para snapshot en Parquet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import BANXICO_BASE, BANXICO_TOKEN, SERIES_BANXICO


def _headers() -> dict:
    if not BANXICO_TOKEN:
        raise RuntimeError("BANXICO_TOKEN no definido. Regístralo gratis en el SIE y agrégalo a .env")
    return {"Bmx-Token": BANXICO_TOKEN}


def metadatos(serie_ids: list[str]) -> pd.DataFrame:
    """Consulta metadatos para validar título, unidad y periodicidad ANTES de persistir."""
    url = f"{BANXICO_BASE}/series/{','.join(serie_ids)}"
    r = requests.get(url, headers=_headers(), timeout=30)
    r.raise_for_status()
    series = r.json()["bmx"]["series"]
    return pd.DataFrame(series)


def descargar_series(fecha_ini: str, fecha_fin: str, series: dict | None = None) -> pd.DataFrame:
    """
    Descarga las series configuradas en formato largo.

    Args:
        fecha_ini: 'AAAA-MM-DD'
        fecha_fin: 'AAAA-MM-DD'
        series: dict {nombre_negocio: serie_id}; default SERIES_BANXICO
    """
    series = series or SERIES_BANXICO
    ids = ",".join(series.values())
    url = f"{BANXICO_BASE}/series/{ids}/datos/{fecha_ini}/{fecha_fin}"
    r = requests.get(url, headers=_headers(), timeout=60)
    r.raise_for_status()

    id_a_nombre = {v: k for k, v in series.items()}
    filas = []
    for s in r.json()["bmx"]["series"]:
        nombre = id_a_nombre.get(s["idSerie"], s["idSerie"])
        for d in s.get("datos", []):
            valor = d["dato"].replace(",", "")
            if valor in ("N/E", ""):
                continue
            filas.append({
                "fecha": pd.to_datetime(d["fecha"], format="%d/%m/%Y"),
                "serie": nombre,
                "serie_id": s["idSerie"],
                "valor": float(valor),
            })

    df = pd.DataFrame(filas)
    if df.empty:
        raise ValueError("Banxico no devolvió datos — revisar IDs de serie y rango de fechas")
    return df.sort_values(["serie", "fecha"]).reset_index(drop=True)


if __name__ == "__main__":
    print(metadatos(list(SERIES_BANXICO.values()))[["idSerie", "titulo", "periodicidad", "unidad"]])
