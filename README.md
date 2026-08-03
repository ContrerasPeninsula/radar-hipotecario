# Radar Hipotecario 🏠📡

**¿Es buen momento para comprar casa en México, y por cuál vía de crédito te conviene?**

Proyecto final — Diplomado en Ciencia de Datos G33 (UNAM FES Acatlán).
Producto de la compañía ficticia **Valora AI**.

## ¿Qué hace?

El usuario ingresa su ingreso mensual, tipo de empleo, enganche y ciudad. La app devuelve:

1. **Tres escenarios de financiamiento** — Infonavit, crédito bancario y Cofinavit — con monto máximo, mensualidad, y su posición frente al mercado real de esa ciudad (percentiles oficiales SHF).
2. **Semáforo de decisión** (COMPRA_AHORA / ESPERA / NEGOCIA) basado en proyecciones a 12 meses de tasas (Prophet).
3. **Resumen ejecutivo estructurado** (JSON validado por schema, generado por Claude).
4. **Asistente conversacional** que explica resultados, responde dudas generales, y recalcula escenarios hipotéticos en tiempo real (function calling).

Ver **[docs/arquitectura.md](docs/arquitectura.md)** para el detalle técnico y fuentes de datos, y **[docs/limitaciones.md](docs/limitaciones.md)** para limitaciones conocidas y trabajo futuro.

## Setup rápido

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # agregar BANXICO_TOKEN, INEGI_TOKEN, ANTHROPIC_API_KEY
```

**Regenerar datos y correr la app** (orden de dependencias):

```bash
python3 scripts/ingesta_completa.py              # 1. Snapshot Banxico
python3 src/ingesta/scraper_inmuebles24.py       # 2. Oferta inmobiliaria
python3 src/motor_reglas/infonavit.py            # 3. Validar motor de reglas
python3 src/modelos/forecast_tasas.py            # 4. Validar Prophet
python3 src/modelos/segmentacion_ciudades.py     # 5. Validar K-Means
streamlit run app/app.py                          # 6. Correr la app
```

## Estructura del repo

```
config/           Reglas de negocio y constantes (Infonavit, UMA, percentiles SHF)
data/snapshots/   Series de Banxico versionadas (GitHub Actions)
data/             oferta_inmuebles24.parquet (actualización manual)
src/ingesta/      Clientes de API y scraper — ver docs/arquitectura.md
src/motor_reglas/ Infonavit, banco, Cofinavit — lógica determinista
src/modelos/      Prophet, K-Means, posicionamiento de mercado
src/asistente/    Chat con Claude API (tool use + structured outputs)
app/              Aplicación Streamlit
notebooks/        EDA + ingeniería de características + modelado (Colab-ready)
docs/             Documentación técnica detallada
.github/workflows/ Ingesta programada de Banxico
```

## Licencia y alcance

Proyecto académico. Los cálculos son estimaciones informativas basadas en reglas públicas y datos oficiales; no constituyen asesoría financiera ni una precalificación oficial.
