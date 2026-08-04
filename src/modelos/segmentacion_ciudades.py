"""
Segmentación no supervisada de mercado inmobiliario — arquetipos por entidad.

v5 — cobertura completa de las 32 entidades federativas vía config.CIUDADES,
que ahora ES el mapeo clave-interna -> entidad (ya no hace falta un dict aparte).
Ambas features 100% oficiales SHF (config/shf_nacional.json), cero scraper:
  - precio_mediano:       tabla oficial "Distribución de precios... 2026" (pesos reales)
  - variacion_anual_pct:  índice oficial SHF (T1 2025 vs T1 2026)

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
from config.settings import CIUDADES, DIR_CONFIG

FEATURES_DEFAULT = ["precio_mediano", "variacion_anual_pct"]


def cargar_datos_nacionales() -> pd.DataFrame:
    """Carga las 32 entidades del JSON oficial SHF — precio mediano + variación anual."""
    ruta = DIR_CONFIG / "shf_nacional.json"
    with open(ruta, encoding="utf-8") as f:
        data = json.load(f)

    filas = [
        {"entidad": entidad, "precio_mediano": info["mediana"], "variacion_anual_pct": info["variacion_anual_pct"]}
        for entidad, info in data["estados"].items()
    ]
    return pd.DataFrame(filas)


def cargar_datos_mercado(df_nacional: pd.DataFrame, ciudades: dict | None = None) -> pd.DataFrame:
    """
    Traduce entidad -> clave interna (config.CIUDADES) y filtra al alcance activo.
    ciudades=None usa las 32 entidades directamente (nivel nacional completo).
    """
    if ciudades is None:
        df = df_nacional.rename(columns={"entidad": "ciudad"})
        return df[["ciudad"] + FEATURES_DEFAULT].copy()

    filas = []
    for clave, entidad in ciudades.items():
        fila = df_nacional[df_nacional["entidad"] == entidad]
        if fila.empty:
            raise ValueError(f"Entidad '{entidad}' (clave '{clave}') no encontrada en shf_nacional.json")
        filas.append({"ciudad": clave, **fila.iloc[0][FEATURES_DEFAULT].to_dict()})

    return pd.DataFrame(filas)


def cargar_variacion_shf() -> pd.DataFrame:
    """Compatibilidad con app.py: variación anual por ciudad (config.CIUDADES)."""
    df_nacional = cargar_datos_nacionales()
    filas = []
    for clave, entidad in CIUDADES.items():
        fila = df_nacional[df_nacional["entidad"] == entidad]
        if not fila.empty:
            filas.append({"ciudad": clave, "variacion_anual_pct": fila.iloc[0]["variacion_anual_pct"]})
    return pd.DataFrame(filas)


def elegir_k(df: pd.DataFrame, features: list[str] | None = None, k_max: int | None = None) -> dict:
    """k tope = n // 3, mínimo 2 (mismo criterio ya usado en el M3 de Valora AI),
    salvo que se pase k_max explícito (ej. para acotar interpretabilidad a nivel nacional)."""
    features = features or FEATURES_DEFAULT
    n = len(df)
    k_tope = max(2, n // 3) if k_max is None else k_max
    k_tope = min(k_tope, n - 1)

    inercias = {}
    for k in range(2, k_tope + 1):
        X = StandardScaler().fit_transform(df[features])
        modelo = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        inercias[k] = modelo.inertia_

    return {"k_sugerido": k_tope, "inercias_por_k": inercias, "n": n}


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
    perfil["miembros"] = df.groupby("cluster")["ciudad"].apply(list)
    perfil["n_miembros"] = df.groupby("cluster")["ciudad"].count()
    return perfil.reset_index()


def nombrar_arquetipos(perfil: pd.DataFrame) -> dict[int, str]:
    precio_mediana_global = perfil["precio_mediano"].median()
    variacion_mediana_global = perfil["variacion_anual_pct"].median()

    nombres = {}
    for _, fila in perfil.iterrows():
        precio_alto = fila["precio_mediano"] >= precio_mediana_global
        variacion_alta = fila["variacion_anual_pct"] >= variacion_mediana_global
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


def obtener_arquetipos(nacional: bool = True) -> dict[str, str]:
    """
    Pipeline completo listo para usar en la UI: {ciudad: nombre_arquetipo}.
    nacional=True (default) corre las 32 entidades — ya es el alcance completo
    del proyecto, no hace falta acotar a un subconjunto.
    """
    df_nacional = cargar_datos_nacionales()
    df_prep = cargar_datos_mercado(df_nacional, ciudades=None if nacional else CIUDADES)

    # Para 32 entidades, acotamos a un máximo de 5 arquetipos — más interpretable
    # que dejar que n//3 genere 10 clusters (varios de un solo estado).
    k_maximo = 5 if nacional else None
    sugerencia = elegir_k(df_prep, k_max=k_maximo)

    df_clusters = entrenar_kmeans(df_prep, k=sugerencia["k_sugerido"])
    perfil = perfilar_clusters(df_clusters)
    nombres_por_cluster = nombrar_arquetipos(perfil)

    return {
        fila["ciudad"]: nombres_por_cluster[fila["cluster"]]
        for _, fila in df_clusters.iterrows()
    }


if __name__ == "__main__":
    print("Cargando datos oficiales SHF (32 entidades, cero scraper)...\n")
    df_nacional = cargar_datos_nacionales()
    print(df_nacional.to_string(index=False))

    print("\n" + "=" * 60)
    print("K-MEANS — nivel NACIONAL (32 entidades, k acotado a 5)")
    print("=" * 60)
    df_prep_nac = cargar_datos_mercado(df_nacional, ciudades=None)
    sugerencia_nac = elegir_k(df_prep_nac, k_max=5)
    print(f"K sugerido: {sugerencia_nac['k_sugerido']} (n={sugerencia_nac['n']})")
    df_clusters_nac = entrenar_kmeans(df_prep_nac, k=sugerencia_nac["k_sugerido"])
    perfil_nac = perfilar_clusters(df_clusters_nac)
    nombres_nac = nombrar_arquetipos(perfil_nac)
    print(perfil_nac.to_string(index=False))
    for cid, nombre in nombres_nac.items():
        miembros = perfil_nac.loc[perfil_nac["cluster"] == cid, "miembros"].iloc[0]
        print(f"  Cluster {cid} — {nombre}: {miembros}")