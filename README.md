# Radar Hipotecario 🏠📡

**¿Es buen momento para comprar casa en México, y por cuál vía de crédito te conviene?**

Proyecto final — Diplomado en Ciencia de Datos G33 (UNAM FES Acatlán).
Producto de la compañía ficticia **Valora AI**.

## ¿Qué hace?

El usuario ingresa su ingreso mensual, tipo de empleo, enganche y ciudad. La app devuelve:

1. **Tres escenarios de financiamiento lado a lado:** Infonavit, crédito bancario y cofinanciamiento (Cofinavit) — monto máximo, mensualidad, costo total y % del inventario real de su ciudad que puede comprar con cada uno.
2. **Semáforo de decisión** (COMPRA_AHORA / ESPERA / NEGOCIA) basado en proyecciones a 12 meses de tasas y precios (Prophet).

## Arquitectura

```
Fuentes públicas (Banxico SIE, INEGI, SHF, CNBV, scraping de portales)
        │  (GitHub Actions, ingesta programada)
        ▼
data/snapshots/AAAA-MM-DD/   ← Parquet/CSV versionados en el repo
        │
        ├──► notebooks/       ← análisis reproducible (Colab-ready, sin credenciales)
        └──► app/             ← Streamlit (lee snapshots + motor de reglas)
```

- **Capa predictiva (ML):** Prophet para tasas y precios; K-Means para arquetipos de mercado por ciudad.
- **Motor de reglas (determinista):** reglas públicas de Infonavit y originación bancaria estándar, versionadas en `config/`.

## Reproducibilidad

- El notebook corre en **cualquier Colab sin credenciales**: lee los snapshots vía `raw.githubusercontent.com`.
- La celda de ingesta viva contra la API de Banxico es **opcional** y está documentada (token gratuito).
- Los snapshots congelan los datos con los que se escribió el documento final.

## Setup local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # agregar BANXICO_TOKEN
python scripts/ingesta_completa.py
streamlit run app/app.py
```

## Fuentes de datos

| Fuente | Tipo | Uso |
|--------|------|-----|
| [Banxico SIE API](https://www.banxico.org.mx/SieAPIRest/) | API REST | TIIE, tasa objetivo, tasas hipotecarias, FIX |
| [INEGI API](https://www.inegi.org.mx/servicios/api_indicadores.html) | API REST | INPC |
| UMA (INEGI/DOF) | Constante versionada | Motor de reglas Infonavit |
| Índice SHF | Descarga trimestral | Precios de vivienda por entidad |
| CNBV / Condusef | Datos abiertos | Tasas y CAT por institución |
| Scraping de portales inmobiliarios | Selenium | Oferta y precio/m² por ciudad |

## Licencia y alcance

Proyecto académico. Los cálculos son estimaciones informativas basadas en reglas públicas;
no constituyen asesoría financiera ni una precalificación oficial.
