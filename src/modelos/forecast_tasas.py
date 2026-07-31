"""
Capa predictiva (ML): proyección a 12 meses de la tasa hipotecaria de referencia
usando Prophet sobre la serie TIIE de Banxico + spread de mercado.

Separación metodológica explícita para el documento del diplomado:
  - Este módulo = MODELO PREDICTIVO (serie de tiempo, Prophet)
  - src/motor_reglas/*.py = MOTOR DE REGLAS (determinista, Infonavit/banco)
  - semaforo() de este archivo = REGLAS aplicadas SOBRE la salida del modelo
    (no es el modelo en sí; se documenta como capa de decisión, no de ML)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DIR_SNAPSHOTS

# Spread provisional banco vs. TIIE, hasta integrar CF815/CNBV real.
# Ver nota en app/app.py::tasa_bancaria_referencia — mismo criterio, un solo lugar de verdad.
SPREAD_BANCARIO_PROVISIONAL = 0.035

UMBRAL_COMPRA_AHORA = -0.005   # proyección baja ≥0.5 pp → comprar ahora (tasa mejorará luego)
UMBRAL_ESPERA = 0.005          # proyección sube ≥0.5 pp → esperar no ayuda, más bien negociar ya


def cargar_serie(nombre_serie: str, ruta_snapshot: Path | None = None) -> pd.DataFrame:
    """
    Carga una serie del snapshot más reciente en formato Prophet: columnas ds, y.
    """
    ruta = ruta_snapshot or (DIR_SNAPSHOTS / "latest" / "series_banxico.parquet")
    if not ruta.exists():
        raise FileNotFoundError(f"No existe snapshot en {ruta}. Corre scripts/ingesta_completa.py primero.")

    df = pd.read_parquet(ruta)
    serie = df.loc[df["serie"] == nombre_serie, ["fecha", "valor"]].copy()
    if serie.empty:
        raise ValueError(f"La serie '{nombre_serie}' no está en el snapshot. Series disponibles: {df['serie'].unique()}")

    serie = serie.rename(columns={"fecha": "ds", "valor": "y"}).sort_values("ds").reset_index(drop=True)
    return serie


def entrenar_prophet(df: pd.DataFrame, periods_dias: int = 365):
    """
    Entrena Prophet sobre una serie diaria y devuelve (modelo, forecast completo).
    Import de Prophet dentro de la función: evita el costo de import si solo se usa cargar_serie/backtest.
    """
    from prophet import Prophet

    modelo = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_prior_scale=0.15,  # conservador: series de tasas no deben sobreajustar quiebres
    )
    modelo.fit(df)

    futuro = modelo.make_future_dataframe(periods=periods_dias, freq="D")
    forecast = modelo.predict(futuro)
    return modelo, forecast


def backtest(df: pd.DataFrame, dias_holdout: int = 365) -> dict:
    """
    Backtesting simple: entrena con todo menos los últimos `dias_holdout` días,
    predice ese tramo, y compara contra los valores reales.
    Reportar MAE/RMSE en el documento académico como evidencia de desempeño del modelo.
    """
    corte = df["ds"].max() - pd.Timedelta(days=dias_holdout)
    train = df[df["ds"] <= corte]
    test = df[df["ds"] > corte]

    if len(test) == 0:
        raise ValueError("No hay suficientes datos para el holdout solicitado")

    _, forecast = entrenar_prophet(train, periods_dias=dias_holdout + 30)

    comparacion = test.merge(forecast[["ds", "yhat"]], on="ds", how="left").dropna()
    mae = (comparacion["y"] - comparacion["yhat"]).abs().mean()
    rmse = ((comparacion["y"] - comparacion["yhat"]) ** 2).mean() ** 0.5

    return {
        "dias_holdout": dias_holdout,
        "n_obs_comparadas": len(comparacion),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "y_promedio_periodo": round(comparacion["y"].mean(), 4),
    }


def proyectar_tasa_hipotecaria(horizonte_dias: int = 365) -> dict:
    """
    Proyecta la tasa hipotecaria de referencia = TIIE proyectada (Prophet) + spread.
    Devuelve el valor actual, el proyectado al horizonte, y la serie completa de forecast.
    """
    tiie = cargar_serie("tiie_28")
    _, forecast = entrenar_prophet(tiie, periods_dias=horizonte_dias)

    tiie_actual = tiie["y"].iloc[-1] / 100  # Banxico reporta en % (ej. 8.25), normalizamos a decimal
    tiie_proyectada = forecast["yhat"].iloc[-1] / 100

    return {
        "fecha_actual": tiie["ds"].iloc[-1],
        "fecha_proyeccion": forecast["ds"].iloc[-1],
        "tasa_hipotecaria_actual": round(tiie_actual + SPREAD_BANCARIO_PROVISIONAL, 4),
        "tasa_hipotecaria_proyectada": round(tiie_proyectada + SPREAD_BANCARIO_PROVISIONAL, 4),
        "delta": round(tiie_proyectada - tiie_actual, 4),
        "forecast_completo": forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]],
    }


def semaforo(proyeccion: dict) -> dict:
    """
    Motor de REGLAS sobre la salida del modelo predictivo — no es ML, es decisión.
    Documentar así en el paper: "el modelo proyecta, las reglas deciden".
    """
    delta = proyeccion["delta"]

    if delta >= abs(UMBRAL_ESPERA):
        senal, razon = "COMPRA_AHORA", "Las tasas proyectan un alza — conviene formalizar el crédito antes de que el costo financiero suba más."
    elif delta <= -abs(UMBRAL_COMPRA_AHORA):
        senal, razon = "ESPERA", "Las tasas proyectan una baja significativa — esperar puede traducirse en una mensualidad más baja para el mismo crédito."
    else:
        senal, razon = "NEGOCIA", "Las tasas se proyectan estables — sin presión financiera por tasa, es buen momento para negociar precio directamente con el vendedor."

    return {
        "senal": senal,
        "razon": razon,
        "tasa_actual": proyeccion["tasa_hipotecaria_actual"],
        "tasa_proyectada": proyeccion["tasa_hipotecaria_proyectada"],
        "delta_pp": round(delta * 100, 2),
    }


if __name__ == "__main__":
    print("Cargando serie TIIE y corriendo backtest de 365 días...")
    tiie = cargar_serie("tiie_28")
    metricas = backtest(tiie, dias_holdout=365)
    print("Backtest:", metricas)

    print("\nProyectando tasa hipotecaria a 12 meses...")
    proyeccion = proyectar_tasa_hipotecaria(horizonte_dias=365)
    print(f"Tasa actual: {proyeccion['tasa_hipotecaria_actual']:.2%}")
    print(f"Tasa proyectada (12m): {proyeccion['tasa_hipotecaria_proyectada']:.2%}")

    print("\nSemáforo:")
    print(semaforo(proyeccion))