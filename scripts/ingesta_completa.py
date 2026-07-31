"""
Pipeline de ingesta → snapshot versionado.
Corre local (python scripts/ingesta_completa.py) o vía GitHub Actions programado.

Salida: data/snapshots/AAAA-MM-DD/*.parquet + latest/ (symlink lógico: copia)
El notebook y la app leen SIEMPRE de snapshots — nunca de APIs en vivo.
"""
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import DIR_SNAPSHOTS
from src.ingesta.banxico import descargar_series

HISTORIA_ANIOS = 10


def main() -> None:
    hoy = date.today()
    destino = DIR_SNAPSHOTS / hoy.isoformat()
    destino.mkdir(parents=True, exist_ok=True)

    # ── Banxico ─────────────────────────────────────────────────────────
    ini = (hoy - timedelta(days=365 * HISTORIA_ANIOS)).isoformat()
    df = descargar_series(fecha_ini=ini, fecha_fin=hoy.isoformat())
    df.to_parquet(destino / "series_banxico.parquet", index=False)
    print(f"✔ Banxico: {len(df):,} filas, {df['serie'].nunique()} series → {destino}")

    # ── TODO: SHF, CNBV, scraping de oferta ─────────────────────────────
    # Cada fuente escribe su propio parquet en `destino` con el mismo patrón.

    # ── latest/ para URLs estables en notebook y app ────────────────────
    latest = DIR_SNAPSHOTS / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(destino, latest)
    print(f"✔ Snapshot copiado a {latest}")


if __name__ == "__main__":
    main()
