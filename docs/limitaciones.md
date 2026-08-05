# Limitaciones conocidas y trabajo futuro

## Limitaciones

- La tasa bancaria de referencia usa un spread provisional sobre la TIIE (0.035) mientras se integra el cuadro CF815 de Banxico o datos de CNBV por institución.
- Prophet proyecta razonablemente la tendencia de la TIIE, pero su MAE de backtest (≈0.87pp) refleja la naturaleza discreta de la serie (decisiones de política monetaria, no tendencia continua) — limitación de origen de datos, no de ajuste del modelo. Se probó sensibilidad de `changepoint_prior_scale` (0.05 → 0.15) con ganancia marginal decreciente, confirmando el diagnóstico.
- El K-Means opera sobre solo 32 puntos (las entidades federativas), que es poco para un clustering serio a gran escala. Los arquetipos resultantes son ilustrativos del enfoque metodológico, no una segmentación estadísticamente robusta.
- Los percentiles de precio de SHF son por entidad federativa, no por ciudad ni colonia — es un límite de la fuente oficial, no de cómo se diseñó el sistema. Alguien en Guadalajara y alguien en un municipio rural de Jalisco ven la misma referencia de mercado.

## Resuelto desde una versión anterior de este documento

Una versión previa de este documento limitaba la cobertura a 3 ciudades activas (CDMX, Estado de México, Guadalajara) por el alcance real del scraper de Inmuebles24, y señalaba una muestra pequeña de anuncios en Estado de México (n=3) como riesgo. Esa limitación se resolvió por completo al migrar el K-Means y el posicionamiento de mercado a `config/shf_nacional.json`, que cubre las 32 entidades federativas con datos 100% oficiales — el scraper dejó de ser una dependencia de cobertura. Ver `docs/arquitectura.md` para el detalle de esa migración.

## Trabajo futuro

- Integrar tasas bancarias reales por institución (CF815 de Banxico o CNBV) en vez del spread provisional.
- Explorar un modelo de cambio de régimen (*regime-switching*) para la TIIE, más adecuado a su naturaleza de saltos discretos que Prophet.
- Conseguir una fuente de precios de vivienda con más granularidad geográfica (municipio o zona metropolitana) en cuanto exista de forma oficial.