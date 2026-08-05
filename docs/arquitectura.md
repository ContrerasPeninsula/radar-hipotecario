# Arquitectura y fuentes de datos

## Capas del sistema

- **Capa predictiva (supervisada):** Prophet sobre la TIIE de Banxico — backtest de 365 días, MAE ≈0.87pp. Limitación documentada: la TIIE se mueve en escalones discretos (política monetaria), no en tendencia continua.
- **Capa no supervisada:** K-Means de arquetipos de mercado sobre las **32 entidades federativas** (k=5), con dos variables **100% oficiales SHF** — precio mediano de vivienda y variación anual — sin depender del scraper.
- **Motor de reglas (determinista):** tabla oficial de tasas Infonavit (41 escalones por UMA, validada contra PDF del portal), originación bancaria estándar, cofinanciamiento (Cofinavit).
- **Posicionamiento de mercado:** la app ubica la capacidad de crédito del usuario contra percentiles P25/mediana/P75 **oficiales de SHF** de la entidad elegida — mismo criterio y misma fuente que alimenta el K-Means, independiente del scraper.
- **Capa generativa:** asistente con Claude API — grounding en resultados calculados, dos tools de function calling (`recalcular_escenarios_credito` para escenarios hipotéticos directos, `ingreso_necesario_para_precio` para el sentido inverso vía búsqueda binaria sobre el motor de reglas real) y structured outputs para el resumen ejecutivo. El modelo nunca calcula una cifra financiera por su cuenta.

## Diagrama de dependencias

```
Fuentes oficiales (Banxico SIE API, SHF, Infonavit)
        │
        ├──► config/          → reglas Infonavit, UMA, shf_nacional.json (32 entidades)
        ├──► data/snapshots/  → series Banxico versionadas (GitHub Actions semanal)
        ├──► src/motor_reglas/    → Infonavit, banco, Cofinavit (determinista)
        ├──► src/modelos/         → Prophet (tasas), K-Means (32 entidades), precio_referencia
        ├──► src/asistente/       → chat con Claude API (2 tools + structured outputs)
        └──► app/app.py           → Streamlit (4 pestañas)

Inmuebles24 (scraper) ──► exploración documentada, NO alimenta ninguna capa activa
```

## Fuentes de datos

| Fuente | Tipo | Uso |
|--------|------|-----|
| [Banxico SIE API](https://www.banxico.org.mx/SieAPIRest/) | API REST | TIIE, tasa objetivo, FIX, INPC |
| UMA (INEGI/DOF) | Constante versionada | Motor de reglas Infonavit |
| Tabla de tasas Infonavit | PDF oficial validado | Motor de reglas — 41 escalones por UMA |
| Índice SHF de Precios de la Vivienda | Datos abiertos oficiales | Percentiles de precio y variación anual — **32 entidades federativas** — alimenta tanto el K-Means como el posicionamiento de mercado |
| Inmuebles24 (scraper) | Selenium + BeautifulSoup | Exploración inicial — **ya no alimenta ninguna capa en producción** |

**Nota metodológica:** el scraper de Inmuebles24 mostró un sesgo sistemático hacia anuncios "Destacado"/pagados (precios sistemáticamente por encima de la mediana oficial SHF para las mismas entidades — ver evidencia en el notebook de EDA). Por eso se retiró por completo de cualquier cálculo que vea el usuario final: tanto el K-Means como el posicionamiento de mercado usan exclusivamente `config/shf_nacional.json`. El scraper se conserva solo como pieza exploratoria documentada, sin conexión al pipeline activo.

## Reproducibilidad

- El notebook (`notebooks/EDA_ingenieria_caracteristicas.ipynb`) corre en cualquier Colab sin credenciales: lee snapshots públicos vía `raw.githubusercontent.com`, incluye EDA, ingeniería de características, y la sección completa de modelado y evaluación (Prophet con backtest, K-Means con perfil de clusters).
- Los snapshots de Banxico se generan semanalmente vía GitHub Actions y se comitean al repo.
- `config/shf_nacional.json` se actualiza manualmente cada trimestre, cuando SHF publica un nuevo Índice de Precios de la Vivienda — no está automatizado.
- `data/oferta_inmuebles24.parquet` es un artefacto de la exploración inicial del scraper; no se actualiza como parte del flujo normal del proyecto.

## Archivos de exploración (no en uso activo)

- **`src/ingesta/scraper_inmuebles24.py`** — funcional, pero excluido de toda recomendación al usuario final por el sesgo documentado arriba. Se conserva como pieza exploratoria y como evidencia del proceso de diagnóstico.
- **`src/ingesta/inegi.py`** — nunca se conectó al pipeline; el INPC terminó viniendo de Banxico (serie `SP1`), no de INEGI. Se conserva como evidencia de la investigación.
- **`src/ingesta/scraper_oferta.py`** (Lamudi) — bloqueado por un WAF de borde (Cloudflare/Akamai); reemplazado por `scraper_inmuebles24.py`. Se conserva documentado por el proceso de diagnóstico que llevó a la decisión.
- **`src/modelos/inventario.py`** — versión anterior del cálculo de posicionamiento de mercado, basada directamente en el scraper; reemplazada por `precio_referencia.py` al detectar el sesgo hacia anuncios "Destacado".
- **`config/shf_percentiles_ciudades.json`** y **`config/shf_variacion_ciudades.json`** — versión anterior de los datos SHF, cubrían solo 3 ciudades; reemplazados por `config/shf_nacional.json` (32 entidades, fuente única). Se conservan documentados, no se usan en el código activo.