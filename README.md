# Radar Hipotecario 🏠📡

**¿Es buen momento para comprar casa en México, y por cuál vía de crédito te conviene?**

Proyecto final — Diplomado en Ciencia de Datos G33 (UNAM FES Acatlán).
Producto de la compañía ficticia **Valora AI**.

## ¿Qué hace?

El usuario ingresa su ingreso mensual, tipo de empleo, enganche y ciudad. La app devuelve:

1. **Tres escenarios de financiamiento** lado a lado — Infonavit, crédito bancario y Cofinavit (cofinanciamiento) — con monto máximo, mensualidad, y su posición frente al mercado real de esa ciudad (percentiles oficiales SHF).
2. **Semáforo de decisión** (COMPRA_AHORA / ESPERA / NEGOCIA) basado en proyecciones a 12 meses de tasas (Prophet).
3. **Resumen ejecutivo estructurado** (JSON validado por schema, generado por Claude).
4. **Asistente conversacional** que explica los resultados, responde dudas generales, y puede *recalcular* escenarios hipotéticos en tiempo real usando el motor de reglas (function calling / tool use).

## Arquitectura

Fuentes oficiales (Banxico SIE API, SHF, Infonavit) + scraper (Inmuebles24)
│
├──► config/ → reglas Infonavit, UMA, percentiles/variación SHF
├──► data/snapshots/ → series Banxico versionadas (GitHub Actions semanal)
├──► src/motor_reglas/ → Infonavit, banco, Cofinavit (determinista)
├──► src/modelos/ → Prophet (tasas), K-Means (ciudades), precio_referencia
├──► src/asistente/ → chat con Claude API (tool use + structured outputs)
└──► app/app.py → Streamlit (4 pestañas)

- **Capa predictiva (supervisada):** Prophet sobre TIIE de Banxico — backtest de 365 días, MAE ≈0.87pp.
- **Capa no supervisada:** K-Means de arquetipos de mercado por ciudad, con **dos features 100% reales**: precio/m² (scraper) y variación anual (índice oficial SHF).
- **Motor de reglas (determinista):** tabla oficial de tasas Infonavit (41 escalones por UMA, validada contra PDF del portal), originación bancaria estándar, cofinanciamiento.
- **Capa generativa:** asistente con Claude API — grounding en resultados calculados, function calling para recalcular escenarios hipotéticos contra el motor de reglas real, structured outputs para el resumen ejecutivo.

## Reproducibilidad

- El notebook (`notebooks/EDA_ingenieria_caracteristicas.ipynb`) corre en **cualquier Colab sin credenciales**: lee snapshots públicos vía `raw.githubusercontent.com`.
- Los snapshots se generan semanalmente vía GitHub Actions y se comitean al repo — congelan los datos con los que se escribió el análisis.
- La ingesta viva (Banxico API) es opcional y solo necesaria para regenerar snapshots, no para reproducir el análisis.

## Fuentes de datos

| Fuente | Tipo | Uso |
|--------|------|-----|
| [Banxico SIE API](https://www.banxico.org.mx/SieAPIRest/) | API REST | TIIE, tasa objetivo, FIX, INPC |
| UMA (INEGI/DOF) | Constante versionada | Motor de reglas Infonavit |
| Tabla de tasas Infonavit | PDF oficial validado | Motor de reglas — 41 escalones por UMA |
| Índice SHF de Precios de la Vivienda | Datos abiertos oficiales | Percentiles de precio y variación anual por ciudad — basado en avalúos hipotecarios reales, no listados de portal |
| Inmuebles24 (scraper) | Selenium + BeautifulSoup | Precio/m² real por ciudad — feature del K-Means únicamente |

**Nota metodológica importante:** el % de "inventario alcanzable" que se mostraba en versiones anteriores usaba directamente el scraper y resultó sesgado hacia anuncios "Destacado"/pagados del portal (segmento premium). Se reemplazó por un posicionamiento contra percentiles oficiales de SHF (datos de avalúos hipotecarios reales), independiente del scraper. El scraper se conserva como fuente de la feature `precio_m2` del K-Means, donde su sesgo es una limitación conocida y documentada, no la base de una recomendación al usuario.

## Setup local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # agregar BANXICO_TOKEN, INEGI_TOKEN, ANTHROPIC_API_KEY
python scripts/ingesta_completa.py
python src/ingesta/scraper_inmuebles24.py   # opcional, regenera oferta_inmuebles24.parquet
streamlit run app/app.py
```

## Estructura del repo

config/ Reglas de negocio y constantes (Infonavit, UMA, percentiles SHF)
data/snapshots/ Series de Banxico versionadas por fecha
src/ingesta/ Clientes de API (Banxico, INEGI) y scraper (Inmuebles24)
src/motor_reglas/ Infonavit, banco, Cofinavit — lógica determinista
src/modelos/ Prophet, K-Means, posicionamiento de mercado
src/asistente/ Chat con Claude API (tool use + structured outputs)
app/ Aplicación Streamlit
notebooks/ EDA e ingeniería de características (Colab-ready)
docs/ Documento de diseño de datos
.github/workflows/ Ingesta programada (GitHub Actions)

## Limitaciones conocidas

- La tasa bancaria de referencia usa un spread provisional sobre la TIIE mientras se integra el cuadro CF815 de Banxico o datos de CNBV.
- El scraper de Inmuebles24 refleja el orden por default del portal (sesgo hacia anuncios pagados) — su uso se limita a una sola feature del K-Means, no a recomendaciones de compra.
- Estado de México tiene una muestra pequeña de anuncios scrapeados.
- El K-Means usa 3 ciudades activas (CDMX, Estado de México, Guadalajara); Puerto Vallarta, Mazatlán y Acapulco quedaron fuera de alcance por falta de cobertura del scraper.

## Licencia y alcance

Proyecto académico. Los cálculos son estimaciones informativas basadas en reglas públicas y datos oficiales; no constituyen asesoría financiera ni una precalificación oficial.