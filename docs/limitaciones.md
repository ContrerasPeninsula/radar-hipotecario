# Limitaciones conocidas y trabajo futuro

## Limitaciones

- La tasa bancaria de referencia usa un spread provisional sobre la TIIE (0.035) mientras se integra el cuadro CF815 de Banxico o datos de CNBV.
- El scraper de Inmuebles24 refleja el orden por default del portal (sesgo hacia anuncios "Destacado"/pagados) — su uso se limita a una sola feature del K-Means, no a la recomendación principal de la app.
- Alcance de 3 ciudades activas (CDMX, Estado de México, Guadalajara) por cobertura real del scraper; Puerto Vallarta, Mazatlán y Acapulco quedaron fuera del alcance original.
- Prophet proyecta razonablemente la tendencia de la TIIE, pero su MAE de backtest (≈0.87pp) refleja la naturaleza discreta de la serie (decisiones de política monetaria, no tendencia continua) — limitación de origen de datos, no de ajuste del modelo. Se probó sensibilidad de `changepoint_prior_scale` (0.05 → 0.15) con ganancia marginal decreciente, confirmando el diagnóstico.
- El K-Means opera sobre solo 3 ciudades — ilustrativo del enfoque metodológico, no una segmentación estadísticamente robusta a esa escala.
- Estado de México tiene una muestra pequeña de anuncios scrapeados (n=3).

## Trabajo futuro

- Integrar tasas bancarias reales (CF815/CNBV) en vez del spread provisional.
- Ampliar el scraper (o una fuente alterna) a las 5 ciudades del alcance original.
- Explorar un modelo de cambio de régimen para la TIIE, más adecuado a su naturaleza de saltos discretos que Prophet.
- Automatizar la actualización de `oferta_inmuebles24.parquet` de forma segura (sin activar detección de bots).
