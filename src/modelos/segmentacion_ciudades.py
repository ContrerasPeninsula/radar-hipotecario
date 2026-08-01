"""
Segmentación no supervisada de ciudades — arquetipos de mercado inmobiliario.

v3 — DOS features 100% reales, cada una de su fuente más confiable posible:
  - precio_m2:            mediana de anuncios reales (data/oferta_inmuebles24.parquet)
  - variacion_anual_pct:  índice oficial SHF, basado en avalúos de créditos
                           hipotecarios reales (config/shf_variacion_ciudades.json)
                           — no depende del scraper, no tiene sesgo de "Destacado".

Con esto se cierra la limitación documentada en v2 (solo precio_m2 disponible).

Capa NO SUPERVISADA, complementaria a:
  - src/modelos/forecast_tasas.py  → supervisado / series de tiempo (Prophet)
  - src/motor_reglas/*.py          → determinista (reglas Infonavit/banco)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import CIUDADES, DIR_CONFIG, DIR_DATA

FEATURES_DEFAULT = ["precio_m2", "variacion_anual_pct"]


def cargar_precio_scraping(ruta_parquet: Path | None = None) -> pd.DataFrame:
    """Mediana de precio/m² por ciudad, del detalle de anuncios scrapeados."""
    ruta = ruta_parquet or (DIR_DATA / "oferta_inmuebles24.parquet")
    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe {ruta}. Corre `python3 src/ingesta/scraper_inmuebles24.py` primero."
        )
    detalle = pd.read_parquet(ruta)
    return (
        detalle.groupby("ciudad")
        .agg(precio_m2=("precio_m2", "median"), n_anuncios=("precio_m2", "count"))
        .reset_index()
    )


def cargar_variacion_shf(ruta_json: Path | None = None) -> pd.DataFrame:
    """Variación anual oficial SHF por ciudad — ver config/shf_variacion_ciudades.json."""
    ruta = ruta_json or (DIR_CONFIG / "shf_variacion_ciudades.json")
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}.")
    with open(ruta, encoding="utf-8") as f:
        data = json.load(f)
    filas = [
        {"ciudad": ciudad, "variacion_anual_pct": info["variacion_anual_pct"]}
        for ciudad, info in data["ciudades"].items()
    ]
    return pd.DataFrame(filas)


def construir_dataset_mercado() -> pd.DataFrame:
    """Une precio/m² (scraper) + variación anual (SHF) en un solo dataset real."""
    precios = cargar_precio_scraping()
    variacion = cargar_variacion_shf()
    return precios.merge(variacion, on="ciudad", how="inner")


def cargar_datos_mercado(df: pd.DataFrame, features: list[str] | None = None) -> pd.DataFrame:
    """Valida cobertura completa de CIUDADES antes de clusterizar."""
    features = features or FEATURES_DEFAULT
    faltantes = set(CIUDADES.keys()) - set(df["ciudad"])
    if faltantes:
        raise ValueError(
            f"Faltan datos de mercado para: {faltantes}. "
            "Verificar cobertura del scraper y del JSON de SHF."
        )
    if df[features].isna().any().any():
        raise ValueError(f"Hay valores nulos en {features} — revisar las fuentes de origen.")
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
    """Con dos features reales, restauramos la heurística de cuadrante
    precio × variación (igual que el diseño original)."""
    precio_mediana = perfil["precio_m2"].median()
    variacion_mediana = perfil["variacion_anual_pct"].median()

    nombres = {}
    for _, fila in perfil.iterrows():
        precio_alto = fila["precio_m2"] >= precio_mediana
        variacion_alta = fila["variacion_anual_pct"] >= variacion_mediana
        if precio_alto and variacion_alta:
            nombre = "Premium en expansión"
        elif precio_alto and not variacion_alta:
            nombre = "Premium consolidado"
        elif not precio_alto and variacion_alta:
            nombre = "Emergente"
        else:
            nombre = "Estable / rezagado"
        nombres[int(fila["cluster"])] = nombre
    return nombres


def obtener_arquetipos() -> dict[str, str]:
    """Pipeline completo listo para usar en la UI: {ciudad: nombre_arquetipo}."""
    df_real = construir_dataset_mercado()
    df_prep = cargar_datos_mercado(df_real)
    sugerencia = elegir_k(df_prep)
    df_clusters = entrenar_kmeans(df_prep, k=sugerencia["k_sugerido"])
    perfil = perfilar_clusters(df_clusters)
    nombres_por_cluster = nombrar_arquetipos(perfil)

    return {
        fila["ciudad"]: nombres_por_cluster[fila["cluster"]]
        for _, fila in df_clusters.iterrows()
    }


if __name__ == "__main__":
    print("Cargando dataset de mercado 100% real (scraper + SHF)...\n")

    df_real = construir_dataset_mercado()
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