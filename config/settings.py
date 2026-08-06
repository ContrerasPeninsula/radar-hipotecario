"""
Configuración central de Radar Hipotecario.
Todo por variables de entorno — sin credenciales en código.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Rutas ────────────────────────────────────────────────────────────────
RAIZ = Path(__file__).resolve().parent.parent
DIR_CONFIG = RAIZ / "config"
DIR_DATA = RAIZ / "data"
DIR_SNAPSHOTS = DIR_DATA / "snapshots"
DIR_MODELOS = RAIZ / "src" / "modelos" / "artefactos"

# ── Banxico SIE ──────────────────────────────────────────────────────────
BANXICO_TOKEN = os.getenv("BANXICO_TOKEN", "")
BANXICO_BASE = "https://www.banxico.org.mx/SieAPIRest/service/v1"

# IDs de series — VALIDAR contra metadatos del SIE antes de la primera corrida
# (scripts/validar_series_banxico.py)
SERIES_BANXICO = {
    "tiie_28": "SF43783",
    "tasa_objetivo": "SF61745",
    "fix_usd": "SF43718",
    "inpc_general": "SP1",
    # Tasas de crédito a la vivienda: extraer IDs del cuadro CF815
    # "tasa_hipotecaria_promedio": "PENDIENTE_CF815",
}

# ── INEGI ────────────────────────────────────────────────────────────────
INEGI_TOKEN = os.getenv("INEGI_TOKEN", "")
INEGI_BASE = "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR"

# ── Alcance geográfico ───────────────────────────────────────────────────
# Cobertura nacional completa (32 entidades) — 100% sourced de config/shf_nacional.json,
# sin depender del scraper (ver src/modelos/segmentacion_ciudades.py y precio_referencia.py).
# clave interna -> nombre de entidad tal como aparece en shf_nacional.json.
CIUDADES = {
    "aguascalientes": "Aguascalientes",
    "baja_california": "Baja California",
    "baja_california_sur": "Baja California Sur",
    "campeche": "Campeche",
    "chiapas": "Chiapas",
    "chihuahua": "Chihuahua",
    "cdmx": "Ciudad de México",
    "coahuila": "Coahuila",
    "colima": "Colima",
    "durango": "Durango",
    "guanajuato": "Guanajuato",
    "guerrero": "Guerrero",
    "hidalgo": "Hidalgo",
    "jalisco": "Jalisco",
    "michoacan": "Michoacán",
    "morelos": "Morelos",
    "estado_mexico": "México",
    "nayarit": "Nayarit",
    "nuevo_leon": "Nuevo León",
    "oaxaca": "Oaxaca",
    "puebla": "Puebla",
    "queretaro": "Querétaro",
    "quintana_roo": "Quintana Roo",
    "san_luis_potosi": "San Luis Potosí",
    "sinaloa": "Sinaloa",
    "sonora": "Sonora",
    "tabasco": "Tabasco",
    "tamaulipas": "Tamaulipas",
    "tlaxcala": "Tlaxcala",
    "veracruz": "Veracruz",
    "yucatan": "Yucatán",
    "zacatecas": "Zacatecas",
}

# ── Sanity checks ────────────────────────────────────────────────────────
RANGO_TASA_HIPOTECARIA = (0.03, 0.30)  # tasas anuales fuera de este rango → flag