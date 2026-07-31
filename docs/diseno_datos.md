# Radar Hipotecario — Diseño de Datos v0.1
**Proyecto final Diplomado Ciencia de Datos G33 · Producto B2C de la compañía ficticia Valora AI**
Fecha de diseño: 2026-07-31 · Autor: Luis Contreras

---

## 1. Arquitectura de fuentes

| # | Fuente | Tipo | Actualización | Uso en el modelo |
|---|--------|------|---------------|------------------|
| 1 | Banxico SIE API | API REST (token gratuito) | Diaria/mensual | Series macro + tasas hipotecarias (features y Prophet) |
| 2 | INEGI API | API REST (token gratuito) | Mensual | INPC, indicadores complementarios |
| 3 | UMA (DOF/INEGI) | Constante versionada | Anual (1 feb) | Motor de reglas Infonavit |
| 4 | Reglas Infonavit | Motor de reglas (JSON versionado) | Al cambiar el instituto | Escenario Infonavit y Cofinavit |
| 5 | CNBV Portafolio de Información | Datos abiertos (CSV/API) | Mensual | Tasas/cartera hipotecaria por banco |
| 6 | Condusef comparativos CAT | Descarga/scraping | Trimestral | Rango de CAT por institución |
| 7 | Índice SHF de precios de vivienda | Descarga (XLSX/CSV) | Trimestral | Tendencia de precios por ciudad/estado |
| 8 | Lamudi (scraper Selenium existente) | Scraping propio | Semanal (scheduler) | Oferta real y precio/m² por ciudad |

**Regla de la rúbrica cumplida:** múltiples fuentes vía API + web scraping, sin Kaggle.

---

## 2. Banxico SIE API

- **Endpoint:** `https://www.banxico.org.mx/SieAPIRest/service/v1/series/{ids}/datos/{fechaIni}/{fechaFin}?token={TOKEN}`
- **Registro de token:** https://www.banxico.org.mx/SieAPIRest/service/v1/token (gratuito, límite ~200 requests/5min — irrelevante para batch diario)

### Series candidatas (VALIDAR IDs contra el catálogo antes de codificar)

| Concepto | Serie / Cuadro | Nota |
|----------|----------------|------|
| TIIE 28 días | `SF43783` | Ancla de costo de fondeo |
| Tasa objetivo Banxico | `SF61745` | Feature para Prophet de tasas |
| Tipo de cambio FIX | `SF43718` | Contexto macro |
| INPC / inflación anual | Cuadro CP151 / serie de variación anual | Alternativa: INEGI API |
| Tasas crédito a la vivienda (promedio ponderado) | **Cuadro CF815** | Extraer los IDs de serie del cuadro vía el endpoint de metadatos |

**Paso obligatorio de setup:** consultar `.../series/{ids}` (metadatos) para confirmar título, unidad y periodicidad de cada serie antes de persistir. Los IDs de cuadros agregados (CF815) contienen varias series internas — mapear cada una a un nombre de negocio en `constantes`.

### Patrón de ingesta
```
ingesta_banxico.py
  → GET series → normaliza a DataFrame (fecha, serie_id, valor)
  → upsert a MongoDB: RadarHipotecario.series_macro
  → índice compuesto (serie_id, fecha) único
```
Reutiliza `core/config_mongodb.py` (agregar entradas al dict `COLLECTIONS`) y el scheduler existente.

---

## 3. INEGI API

- **Endpoint:** `https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR/{indicador}/es/0700/false/BISE/2.0/{TOKEN}?type=json`
- **Uso mínimo:** INPC como respaldo/validación cruzada de Banxico. No sobre-ingerir: 1–2 indicadores bastan para el documento.

---

## 4. UMA — constante versionada

```json
{
  "uma": [
    {"vigencia_inicio": "2025-02-01", "vigencia_fin": "2026-01-31", "diario": 113.14, "mensual": 3439.46},
    {"vigencia_inicio": "2026-02-01", "vigencia_fin": "2027-01-31", "diario": 117.31, "mensual": 3566.22}
  ]
}
```

**Regla crítica:** la UMA se resuelve por fecha de cálculo, no como constante global. Enero 2026 usa UMA 2025. Función `uma_vigente(fecha) -> dict`.

Fuente canónica: comunicado INEGI + publicación DOF (9 ene 2026, incremento 3.69%).

---

## 5. Motor de reglas Infonavit (`reglas_infonavit_v2026.json`)

### ⚠️ Decisión pendiente #1 — Tabla de tasas
Fuentes públicas contradictorias detectadas (jul 2026):
- Portal oficial (producto compra estándar): **tasa única 10.45% para todos los niveles salariales**
- Esquemas con **tasa diferenciada por nivel salarial** (rango reportado ~3.76%–10.45%); existe PDF oficial "Tabla de Tasas de interés diferenciada" en el portal

**Acción antes de codificar:** descargar el PDF oficial del portal Infonavit, contrastar 3–4 casos contra el simulador de Mi Cuenta Infonavit, y fijar en el JSON: (a) producto modelado, (b) tabla de tasas con fecha de descarga, (c) URL fuente. El JSON es la única fuente de verdad del motor — nunca prensa.

### Reglas confirmadas a codificar

| Regla | Valor 2026 |
|-------|-----------|
| Puntaje mínimo | 100 puntos (nuevo esquema; sustituye 1,080) |
| Cotización | ≥ 6 meses consecutivos formales (IMSS), sin interrupciones |
| Plazo | 1–30 años; edad + plazo ≤ 70 (H) / 75 (M) |
| Cuota de administración | $0 para créditos posteriores al 1-may-2024 |
| Aporte patronal (5% salario) | Abono directo a capital |
| SSV (subcuenta de vivienda) | Se suma como enganche/complemento; input autoreportado opcional |
| Monto máximo compra | ~2.8–2.9 M MXN (validar contra simulador) |
| Modalidades | Individual · Cofinavit (Infonavit + banco) · Segundo crédito |

### Interfaz del motor
```python
def escenario_infonavit(salario_mensual, edad, sexo, ssv=0, fecha=None) -> dict:
    # returns: elegible, tasa, monto_max, plazo_max, mensualidad_estimada, capacidad_total
```
Determinista, sin ML. Se documenta en el paper como "motor de reglas de negocio", separado explícitamente de la capa predictiva.

---

## 6. Lado bancario

- **CNBV Portafolio de Información:** cartera hipotecaria y tasas por institución (datos abiertos, CSV descargable). Frecuencia mensual.
- **Condusef:** comparativos de CAT por producto hipotecario.
- **Sanity check de rangos (jul 2026):** tasa promedio ~11.6%, CAT promedio ~14.1% (rango ~11.2%–28.2%). Si el pipeline produce tasas fuera de [8%, 30%], flag automático.

```python
def escenario_bancario(ingreso_mensual, enganche, plazo, tasa_ref=None) -> dict:
    # tasa_ref: última tasa promedio Banxico/CNBV si no se especifica banco
    # regla estándar de originación: mensualidad ≤ 30-35% del ingreso
```

---

## 7. Precios de vivienda

- **Índice SHF:** descarga trimestral por entidad/municipio → `RadarHipotecario.shf_precios`
- **Lamudi (existente):** reutilizar scraper; ampliar a las ciudades objetivo del proyecto. Slug confirmado Acapulco: `guerrero/acapulco-de-juarez`.
- Cruce: % del inventario Lamudi alcanzable por cada escenario de crédito en cada ciudad → este es el output más demostrable en la demo.

---

## 8. Capa de modelos (para el documento y notebook)

| Modelo | Tipo | Input | Output |
|--------|------|-------|--------|
| Prophet tasas | Serie de tiempo | Series Banxico (tasa hipotecaria, TIIE, objetivo) | Proyección 12 meses |
| Prophet/regresión precios | Serie de tiempo | SHF + Lamudi por ciudad | Proyección precio/m² |
| Semáforo compra | Clasificación (reglas + score) | Proyecciones + capacidad del usuario | COMPRA_AHORA / ESPERA / NEGOCIA |
| Segmentación ciudades | K-Means | Precio/m², absorción proxy, variación SHF | Arquetipos de mercado |

Separación explícita en el paper: **capa predictiva (ML)** vs **motor de reglas (Infonavit/banco)**.

---

## 9. Colecciones MongoDB nuevas

```
RadarHipotecario.series_macro      (serie_id, fecha, valor, fuente)  [único: serie_id+fecha]
RadarHipotecario.shf_precios       (entidad, municipio, trimestre, indice)
RadarHipotecario.oferta_lamudi     (ciudad, fecha_scrape, precio, m2, url_hash)
RadarHipotecario.reglas_infonavit  (version, vigencia, json_reglas, url_fuente, fecha_descarga)
RadarHipotecario.inferencias       (log de consultas de la UI para el apartado de testing)
```

---

## 10. Pendientes antes de escribir código

1. **[BLOQUEANTE]** Registrar token Banxico SIE + validar IDs de series contra metadatos (especialmente cuadro CF815).
2. **[BLOQUEANTE]** Descargar tabla oficial de tasas Infonavit y validar contra simulador → cerrar Decisión #1.
3. Definir ciudades del alcance (propuesta: las 5 de Valora AI para reutilizar Lamudi, o CDMX+GDL+MTY para historia B2C nacional).
4. Confirmar formato de descarga SHF vigente (cambia entre trimestres).
5. Decidir si el semáforo es reglas puras sobre proyecciones de Prophet o un clasificador entrenado (recomendación: reglas sobre proyecciones — más defendible y honesto metodológicamente).
