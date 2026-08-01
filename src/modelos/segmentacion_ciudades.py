"""
Segmentación no supervisada de ciudades — arquetipos de mercado inmobiliario.

v2 — datos 100% REALES: precio/m² viene del scraper de Inmuebles24
(data/oferta_inmuebles24.parquet), agregado por mediana por ciudad.
Ya NO se usan marcadores sintéticos — el alcance de ciudades (config.CIUDADES)
coincide exactamente con la cobertura real del scraper: CDMX, Estado de
México, Guadalajara.

Feature única por ahora: precio_m2 (mediana de anuncios reales). Variables
adicionales (variación anual, absorción) quedan pendientes de una fuente
real confirmada para las 3 ciudades — se agregan cuando existan, no se
inventan mientras tanto.

Capa NO SUPERVISADA, complementaria a:
  - src/modelos/forecast_tasas.py  → supervisado / series de tiempo (Prophet)
  - src/motor_reglas/*.py          → determinista (reglas Infonavit/banco)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import CIUDADES, DIR_DATA

FEATURES_DEFAULT = ["precio_m2"]


def cargar_desde_scraping(ruta_parquet: Path | None = None) -> pd.DataFrame:
    """
    Agrega el detalle de anuncios (oferta_inmuebles24.parquet) a nivel ciudad:
    mediana de precio/m² — mediana, no promedio, por las colas largas típicas
    del mercado inmobiliario (mansiones, remates).
    """
    ruta = ruta_parquet or (DIR_DATA / "oferta_inmuebles24.parquet")
    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe {ruta}. Corre `python3 src/ingesta/scraper_inmuebles24.py` primero."
        )
    detalle = pd.read_parquet(ruta)
    resumen = (
        detalle.groupby("ciudad")
        .agg(precio_m2=("precio_m2", "median"), n_anuncios=("precio_m2", "count"))
        .reset_index()
    )
    return resumen


def cargar_datos_mercado(df: pd.DataFrame, features: list[str] | None = None) -> pd.DataFrame:
    """
    Valida cobertura completa de CIUDADES antes de clusterizar — mismo criterio
    estricto que la v1: sin datos completos, no hay corrida.
    """
    features = features or FEATURES_DEFAULT
    faltantes = set(CIUDADES.keys()) - set(df["ciudad"])
    if faltantes:
        raise ValueError(
            f"Faltan datos de mercado para: {faltantes}. "
            "Corre el scraper o ajusta config.CIUDADES para que coincida con la cobertura real."
        )
    if df[features].isna().any().any():
        raise ValueError(f"Hay valores nulos en {features} — revisar el parquet de origen.")
    return df[["ciudad"] + features].copy()


def elegir_k(df: pd.DataFrame, features: list[str] | None = None, k_max: int | None = None) -> dict:
    """k tope = n_ciudades // 3, mínimo 2 (mismo criterio ya usado en el M3 de Valora AI)."""
    features = features or FEATURES_DEFAULT
    n = len(df)
    k_tope = max(2, n // 3) if k_max is None else k_max
    k_tope = min(k_tope, n - 1)

    inercias = {}
    for k in range(2, k_tope + 1):
        X = StandardScaler().fit_transform(df[features])
        modelo = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        inercias[k] = modelo.inertia_

    return {"k_sugerido": k_tope, "inercias_por_k": inercias, "n_ciudades": n}


def entrenar_kmeans(df: pd.DataFrame, k: int, features: list[str] | None = None) -> pd.DataFrame:
    features = features or FEATURES_DEFAULT
    X = StandardScaler().fit_transform(df[features])
    modelo = KMeans(n_clusters=k, random_state=42, n_init=10)
    df = df.copy()
    df["cluster"] = modelo.fit_predict(X)
    return df


def perfilar_clusters(df: pd.DataFrame, features: list[str] | None = None) -> pd.DataFrame:
    features = features or FEATURES_DEFAULT
    perfil = df.groupby("cluster")[features].mean()
    perfil["ciudades"] = df.groupby("cluster")["ciudad"].apply(list)
    perfil["n_ciudades"] = df.groupby("cluster")["ciudad"].count()
    return perfil.reset_index()


def nombrar_arquetipos(perfil: pd.DataFrame) -> dict[int, str]:
    """Con una sola feature real (precio_m2), la heurística se simplifica a
    tier de precio — ampliar cuando haya más features reales confirmadas."""
    mediana_global = perfil["precio_m2"].median()
    nombres = {}
    for _, fila in perfil.iterrows():
        nombre = "Premium" if fila["precio_m2"] >= mediana_global else "Accesible"
        nombres[int(fila["cluster"])] = nombre
    return nombres


if __name__ == "__main__":
    print("Cargando datos REALES del scraper de Inmuebles24...\n")

    df_real = cargar_desde_scraping()
    print("Precio/m² mediano por ciudad (datos reales):")
    print(df_real.to_string(index=False))

    df_prep = cargar_datos_mercado(df_real)
    sugerencia = elegir_k(df_prep)
    print(f"\nK sugerido: {sugerencia['k_sugerido']} (n_ciudades={sugerencia['n_ciudades']})")
    print(f"Inercias por k: {sugerencia['inercias_por_k']}")

    k = sugerencia["k_sugerido"]
    df_clusters = entrenar_kmeans(df_prep, k=k)
    perfil = perfilar_clusters(df_clusters)
    nombres = nombrar_arquetipos(perfil)

    print("\nPerfil de clusters:")
    print(perfil.to_string(index=False))
    print("\nArquetipos:")
    for cluster_id, nombre in nombres.items():
        ciudades = perfil.loc[perfil["cluster"] == cluster_id, "ciudades"].iloc[0]
        print(f"  Cluster {cluster_id} — {nombre}: {ciudades}")