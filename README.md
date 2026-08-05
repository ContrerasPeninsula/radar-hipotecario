# Radar Hipotecario 🏠📡

**¿Es buen momento para comprar casa en México, y por cuál vía de crédito te conviene?**

Proyecto final — Diplomado en Ciencia de Datos G33 (UNAM FES Acatlán).
Producto de la compañía ficticia **Valora AI**.

## ¿Qué hace?

El usuario ingresa su ingreso mensual, tipo de empleo, enganche y ciudad. La app devuelve:

1. **Tres escenarios de financiamiento** — Infonavit, crédito bancario y Cofinavit — con monto máximo, mensualidad, y su posición frente al mercado real de esa ciudad (percentiles oficiales SHF).
2. **Semáforo de decisión** (COMPRA_AHORA / ESPERA / NEGOCIA) basado en proyecciones a 12 meses de tasas (Prophet).
3. **Resumen ejecutivo estructurado** (JSON validado por schema, generado por Claude).
4. **Asistente conversacional** que explica resultados, responde dudas generales, recalcula escenarios hipotéticos en tiempo real (function calling), y resuelve preguntas inversas ("¿cuál ingreso necesito para alcanzar tal precio?") por búsqueda binaria sobre el motor de reglas real, sin que el modelo adivine cifras.

Ver **[docs/arquitectura.md](docs/arquitectura.md)** para el detalle técnico y fuentes de datos, y **[docs/limitaciones.md](docs/limitaciones.md)** para limitaciones conocidas y trabajo futuro.

## Setup rápido

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # agregar BANXICO_TOKEN, INEGI_TOKEN, ANTHROPIC_API_KEY
```

**Regenerar datos y correr la app** (orden de dependencias):

```bash
python3 scripts/ingesta_completa.py              # 1. Snapshot Banxico (requerido)
python3 src/motor_reglas/infonavit.py            # 2. Validar motor de reglas
python3 src/modelos/forecast_tasas.py            # 3. Validar Prophet
python3 src/modelos/segmentacion_ciudades.py     # 4. Validar K-Means
streamlit run app/app.py                          # 5. Correr la app
```

> El scraper de Inmuebles24 (`src/ingesta/scraper_inmuebles24.py`) **no es parte de esta secuencia** — la app no depende de él. Precios y percentiles vienen 100% de `config/shf_nacional.json` (oficial SHF). El scraper se mantiene solo como pieza exploratoria documentada; ver `docs/limitaciones.md` para el porqué.

## Despliegue

La app corre en **Streamlit Community Cloud**, desplegada directo desde este repo (`main`, `app/app.py`). No requiere secrets para la parte determinista (motor de reglas, percentiles SHF); `ANTHROPIC_API_KEY` es necesaria solo para el asistente conversacional y el resumen ejecutivo.

**App en vivo:** _[agregar URL una vez desplegada]_

Notas de despliegue:
- `runtime.txt` fija `python-3.9` — misma versión que el entorno de desarrollo local, importante porque el build de Prophet/`cmdstanpy` es sensible a la versión de Python.
- `requirements.txt` fija `anthropic==0.120.2` (no `>=`) porque el asistente usa el parámetro `effort` vía `output_config`, disponible solo en versiones recientes del SDK.
- El snapshot de Banxico y los JSON de `config/` deben estar comiteados al repo — la app los lee directo del filesystem, no los regenera en la nube.

## Estructura del repo

```
config/           Reglas de negocio y constantes (Infonavit, UMA, percentiles SHF)
data/snapshots/   Series de Banxico versionadas (GitHub Actions)
data/             oferta_inmuebles24.parquet (exploratorio — no alimenta la app en producción)
scripts/          Orquestación de ingesta (ingesta_completa.py)
src/ingesta/      Clientes de API y scraper — ver docs/arquitectura.md
src/motor_reglas/ Infonavit, banco, Cofinavit — lógica determinista
src/modelos/      Prophet, K-Means, posicionamiento de mercado
src/asistente/    Chat con Claude API (tool use + structured outputs)
app/              Aplicación Streamlit
notebooks/        EDA + ingeniería de características + modelado (Colab-ready)
docs/             Documentación técnica detallada
tests/            Reservado para pruebas automatizadas (aún sin implementar)
.github/workflows/ Ingesta programada de Banxico
```

## Licencia y alcance

Proyecto académico. Los cálculos son estimaciones informativas basadas en reglas públicas y datos oficiales; no constituyen asesoría financiera ni una precalificación oficial.
