"""
Segmentación no supervisada de ciudades — arquetipos de mercado inmobiliario.

Capa de modelación NO SUPERVISADA (K-Means), complementaria a:
  - src/modelos/forecast_tasas.py     → supervisado / series de tiempo (Prophet)
  - src/motor_reglas/*.py             → determinista (reglas Infonavit/banco)

⚠️ ESTADO DE DATOS: PENDIENTE_DATOS_REALES
Al momento de escribir este módulo, solo 2 de las 5 ciudades del proyecto tienen
cifras públicas confirmadas de SHF (Guadalajara, CDMX). Puerto Vallarta, Mazatlán
y Acapulco no aparecen en los boletines de zona metropolitana de SHF — requieren
el scraper de oferta inmobiliaria (aún no construido) o una fuente estatal alterna.

Este archivo NUNCA debe usarse para reportar arquetipos reales hasta que
cargar_datos_mercado() reciba un DataFrame con las 5 ciudades completas.
El bloque __main__ usa datos SINTÉTICOS marcados explícitamente, solo para
validar que el pipeline (escalado → K → perfilamiento) funciona correctamente.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import CIUDADES

FEATURES_DEFAULT = ["precio_m2", "variacion_anual_pct", "absorcion_proxy"]


def cargar_datos_mercado(df: pd.DataFrame, features: list[str] | None = None) -> pd.DataFrame:
    """
    Valida y prepara un DataFrame de mercado para clustering.

    Espera columnas: ciudad + las features indicadas (default FEATURES_DEFAULT).
    Lanza error si falta alguna ciudad de config.CIUDADES o si hay NaN en features
    — un cluster con datos incompletos es peor que no tener el cluster.
    """
    features = features or FEATURES_DEFAULT
    faltantes_ciudad = set(CIUDADES.keys()) - set(df["ciudad"])
    if faltantes_ciudad:
        raise ValueError(
            f"Faltan datos de mercado para: {faltantes_ciudad}. "
            "El K-Means no corre con cobertura parcial de ciudades — "
            "completar vía scraper o fuente estatal antes de continuar."
        )
    if df[features].isna().any().any():
        raise ValueError(f"Hay valores nulos en las features {features} — imputar o excluir antes de clusterizar.")
    return df[["ciudad"] + features].copy()


def elegir_k(df: pd.DataFrame, features: list[str] | None = None, k_max: int | None = None) -> dict:
    """
    Sugiere un valor de k usando el criterio ya definido en el proyecto:
    k está topado por n_ciudades // 3 (evita clusters de un solo elemento
    en un dataset pequeño — mismo criterio usado en el M3 de Valora AI).
    """
    features = features or FEATURES_DEFAULT
    n = len(df)
    k_tope = max(2, n // 3) if k_max is None else k_max

    inercias = {}
    for k in range(2, min(k_tope, n - 1) + 1):
        X = StandardScaler().fit_transform(df[features])
        modelo = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        inercias[k] = modelo.inertia_

    return {"k_sugerido": k_tope, "inercias_por_k": inercias, "n_ciudades": n}


def entrenar_kmeans(df: pd.DataFrame, k: int, features: list[str] | None = None) -> pd.DataFrame:
    """
    Entrena K-Means sobre las features de mercado (estandarizadas) y devuelve
    el DataFrame original con la columna 'cluster' agregada.
    """
    features = features or FEATURES_DEFAULT
    scaler = StandardScaler()
    X = scaler.fit_transform(df[features])

    modelo = KMeans(n_clusters=k, random_state=42, n_init=10)
    df = df.copy()
    df["cluster"] = modelo.fit_predict(X)
    return df


def perfilar_clusters(df: pd.DataFrame, features: list[str] | None = None) -> pd.DataFrame:
    """
    Perfil descriptivo de cada cluster: media de cada feature + ciudades que lo componen.
    Esto es lo que se documenta como 'arquetipo de mercado' en el paper.
    """
    features = features or FEATURES_DEFAULT
    perfil = df.groupby("cluster")[features].mean()
    perfil["ciudades"] = df.groupby("cluster")["ciudad"].apply(list)
    perfil["n_ciudades"] = df.groupby("cluster")["ciudad"].count()
    return perfil.reset_index()


def nombrar_arquetipos(perfil: pd.DataFrame) -> dict[int, str]:
    """
    Asigna un nombre legible a cada cluster según su posición relativa en
    precio y variación anual — heurística simple, ajustar con criterio de negocio
    una vez haya datos reales completos.
    """
    nombres = {}
    precio_mediana = perfil["precio_m2"].median()
    variacion_mediana = perfil["variacion_anual_pct"].median()

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


if __name__ == "__main__":
    print("⚠️  DATOS SINTÉTICOS — solo para validar el pipeline, NO representan mercado real.\n")

    # Datos reales confirmados (SHF, boletín Q1 2026) para 2 ciudades:
    #   Guadalajara: +12.5% YoY | CDMX: +5.1% YoY
    # Las demás son marcadores sintéticos SOLO para poder correr el algoritmo con 5 filas
    # (mínimo razonable para k=2 con el criterio n//3). Sustituir en cuanto haya datos reales.
    df_demo = pd.DataFrame([
        {"ciudad": "guadalajara",      "precio_m2": 28500, "variacion_anual_pct": 12.5, "absorcion_proxy": 0.62},  # SHF real
        {"ciudad": "cdmx",             "precio_m2": 41200, "variacion_anual_pct": 5.1,  "absorcion_proxy": 0.58},  # SHF real
        {"ciudad": "puerto_vallarta",  "precio_m2": 35000, "variacion_anual_pct": 8.0,  "absorcion_proxy": 0.45},  # SINTÉTICO
        {"ciudad": "mazatlan",         "precio_m2": 22000, "variacion_anual_pct": 6.5,  "absorcion_proxy": 0.40},  # SINTÉTICO
        {"ciudad": "acapulco",         "precio_m2": 18500, "variacion_anual_pct": 2.0,  "absorcion_proxy": 0.20},  # SINTÉTICO
    ])

    df_prep = cargar_datos_mercado(df_demo)
    sugerencia = elegir_k(df_prep)
    print(f"K sugerido (n_ciudades // 3, mínimo 2): {sugerencia['k_sugerido']}")
    print(f"Inercias por k: {sugerencia['inercias_por_k']}\n")

    k = sugerencia["k_sugerido"]
    df_clusters = entrenar_kmeans(df_prep, k=k)
    perfil = perfilar_clusters(df_clusters)
    nombres = nombrar_arquetipos(perfil)

    print("Perfil de clusters:")
    print(perfil.to_string(index=False))
    print("\nArquetipos:")
    for cluster_id, nombre in nombres.items():
        ciudades = perfil.loc[perfil["cluster"] == cluster_id, "ciudades"].iloc[0]
        print(f"  Cluster {cluster_id} — {nombre}: {ciudades}")