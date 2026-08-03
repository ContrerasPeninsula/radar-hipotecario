# Arquitectura y fuentes de datos

## Capas del sistema

- **Capa predictiva (supervisada):** Prophet sobre la TIIE de Banxico — backtest de 365 días, MAE ≈0.87pp. Limitación documentada: la TIIE se mueve en escalones discretos (política monetaria), no en tendencia continua.
- **Capa no supervisada:** K-Means de arquetipos de mercado por ciudad, con dos features 100% reales de fuentes independientes: precio/m² (scraper) y variación anual (índice oficial SHF).
- **Motor de reglas (determinista):** tabla oficial de tasas Infonavit (41 escalones por UMA, validada contra PDF del portal), originación bancaria estándar, cofinanciamiento.
- **Posicionamiento de mercado:** en vez de un "% de inventario alcanzable" calculado sobre el scraper (sesgado hacia anuncios "Destacado"/pagados), la app ubica la capacidad del usuario contra percentiles P25/mediana/P75 **oficiales de SHF**, escalados por el índice de cada ciudad — independiente del scraper.
- **Capa generativa:** asistente con Claude API — grounding en resultados calculados, function calling para recalcular escenarios hipotéticos, structured outputs para el resumen ejecutivo.

## Diagrama de dependencias

```
Fuentes oficiales (Banxico SIE API, SHF, Infonavit) + scraper (Inmuebles24)
        │
        ├──► config/          → reglas Infonavit, UMA, percentiles/variación SHF
        ├──► data/snapshots/  → series Banxico versionadas (GitHub Actions semanal)
        ├──► data/            → oferta_inmuebles24.parquet (actualización manual)
        ├──► src/motor_reglas/    → Infonavit, banco, Cofinavit (determinista)
        ├──► src/modelos/         → Prophet (tasas), K-Means (ciudades), precio_referencia
        ├──► src/asistente/       → chat con Claude API
        └──► app/app.py           → Streamlit (4 pestañas)
```

## Fuentes de datos

| Fuente | Tipo | Uso |
|--------|------|-----|
| [Banxico SIE API](https://www.banxico.org.mx/SieAPIRest/) | API REST | TIIE, tasa objetivo, FIX, INPC |
| UMA (INEGI/DOF) | Constante versionada | Motor de reglas Infonavit |
| Tabla de tasas Infonavit | PDF oficial validado | Motor de reglas — 41 escalones por UMA |
| Índice SHF de Precios de la Vivienda | Datos abiertos oficiales | Percentiles de precio (posicionamiento de mercado) y variación anual (K-Means) por ciudad — basado en avalúos hipotecarios reales |
| Inmuebles24 (scraper) | Selenium + BeautifulSoup | Precio/m² real por ciudad — única feature del K-Means que depende del scraper |

**Nota metodológica:** el scraper de Inmuebles24 tiene un sesgo documentado hacia anuncios "Destacado"/pagados. Por eso se limitó su uso a una sola variable del K-Means; la decisión de "¿me alcanza en esta ciudad?" que ve el usuario usa percentiles oficiales de SHF, no el scraper.

## Reproducibilidad

- El notebook (`notebooks/EDA_ingenieria_caracteristicas.ipynb`) corre en cualquier Colab sin credenciales: lee snapshots públicos vía `raw.githubusercontent.com`, incluye EDA, ingeniería de características, y la sección completa de modelado y evaluación (Prophet con backtest, K-Means con perfil de clusters).
- Los snapshots de Banxico se generan semanalmente vía GitHub Actions y se comitean al repo.
- `data/oferta_inmuebles24.parquet` se actualiza manualmente — el scraper no está automatizado en cron para evitar activar repetidamente la detección de bots del portal.

## Archivos de exploración (no en uso activo)

- **`src/ingesta/inegi.py`** — nunca se conectó al pipeline; el INPC terminó viniendo de Banxico (serie `SP1`), no de INEGI. Se conserva como evidencia de la investigación.
- **`src/ingesta/scraper_oferta.py`** (Lamudi) — bloqueado por un WAF de borde (Cloudflare/Akamai); reemplazado por `scraper_inmuebles24.py`. Se conserva documentado por el proceso de diagnóstico que llevó a la decisión.
- **`src/modelos/inventario.py`** — versión anterior del cálculo de "% inventario alcanzable" basada directamente en el scraper; reemplazada por `precio_referencia.py` al detectar el sesgo hacia anuncios "Destacado".
