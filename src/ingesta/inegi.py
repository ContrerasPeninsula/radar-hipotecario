"""
Ingesta de indicadores del Banco de Indicadores INEGI (API v2.0).

Formato de URL confirmado:
https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR/{clave}/{idioma}/{area}/{reciente}/{fuente}/2.0/{TOKEN}?type=json

A diferencia de Banxico, el token va pegado en la ruta, no como header.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import INEGI_BASE, INEGI_TOKEN

# ── Indicadores ──────────────────────────────────────────────────────────
# PENDIENTE DE VALIDAR: confirmar cada clave en el Constructor de Consultas
# https://www.inegi.org.mx/app/querybuilder2/default.html?2.0=
# antes de usar en producción. No se hardcodea ningún ID sin validar_indicador() primero.
INDICADORES = {
    "inpc_general": "628194",  # INPC Mensual, general nacional — confirmar con validar_indicador()
}

FUENTE_DEFAULT = "BISE"  # Banco de Información Económica
AREA_NACIONAL = "00"  # Nacional


def _url(clave: str, reciente: str = "false", area: str = AREA_NACIONAL, fuente: str = FUENTE_DEFAULT) -> str:
    if not INEGI_TOKEN:
        raise RuntimeError("INEGI_TOKEN no definido. Regístralo y agrégalo a .env")
    return (
        f"{INEGI_BASE}/INDICATOR/{clave}/es/{area}/{reciente}/{fuente}/2.0/{INEGI_TOKEN}"
        "?type=json"
    )


def validar_indicador(clave: str) -> pd.DataFrame:
    """
    Descarga UNA observación reciente del indicador para confirmar que la clave
    es correcta antes de usarla en el pipeline. Imprime nombre, unidad y última fecha.
    """
    url = _url(clave, reciente="true")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    serie = data["Series"][0]
    obs = serie.get("OBSERVATIONS", [])
    return pd.DataFrame([{
        "indicador": serie.get("INDICADOR"),
        "freq": serie.get("FREQ"),
        "unidad": serie.get("UNIT"),
        "fuente": serie.get("SOURCE"),
        "ultima_actualizacion": serie.get("LASTUPDATE"),
        "ultimo_periodo": obs[-1]["TIME_PERIOD"] if obs else None,
        "ultimo_valor": obs[-1]["OBS_VALUE"] if obs else None,
    }])


def descargar_indicador(clave: str, nombre_negocio: str, area: str = AREA_NACIONAL) -> pd.DataFrame:
    """Descarga la serie histórica completa de un indicador."""
    url = _url(clave, reciente="false", area=area)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    data = r.json()

    serie = data["Series"][0]
    filas = []
    for o in serie.get("OBSERVATIONS", []):
        valor = o.get("OBS_VALUE")
        if valor in (None, ""):
            continue
        filas.append({
            "fecha": pd.to_datetime(o["TIME_PERIOD"], format="%Y/%m", errors="coerce"),
            "serie": nombre_negocio,
            "indicador_id": clave,
            "valor": float(valor),
        })

    df = pd.DataFrame(filas)
    if df.empty:
        raise ValueError(f"INEGI no devolvió datos para el indicador {clave} — revisar clave y parámetros")
    return df.sort_values("fecha").reset_index(drop=True)


def descargar_todos(indicadores: dict | None = None) -> pd.DataFrame:
    """Descarga todos los indicadores configurados y los concatena en formato largo."""
    indicadores = indicadores or INDICADORES
    if not indicadores:
        raise ValueError(
            "INDICADORES está vacío. Confirma las claves en el Constructor de Consultas "
            "(https://www.inegi.org.mx/app/querybuilder2/) y agrégalas a config/settings.py"
        )
    partes = [descargar_indicador(clave, nombre) for nombre, clave in indicadores.items()]
    return pd.concat(partes, ignore_index=True)

def debug_raw(clave: str, reciente: str = "true") -> None:
    """Imprime la respuesta cruda del servidor para diagnosticar errores."""
    url = _url(clave, reciente=reciente)
    print(f"URL: {url}")
    r = requests.get(url, timeout=30)
    print(f"Status code: {r.status_code}")
    print(f"Content-Type: {r.headers.get('Content-Type')}")
    print("Primeros 500 caracteres de la respuesta:")
    print(r.text[:500])


if __name__ == "__main__":
    clave = sys.argv[1] if len(sys.argv) > 1 else "1002000001"
    url = _url(clave, reciente="true")
    print(f"URL: {url}")
    r = requests.get(url, timeout=30)
    print(f"Status: {r.status_code}")
    print(f"Respuesta completa: {r.text}")