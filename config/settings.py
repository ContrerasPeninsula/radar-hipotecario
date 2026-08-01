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
    # Tasas de crédito a la vivienda: extraer IDs del cuadro CF815 vía metadatos
    # "tasa_hipotecaria_promedio": "PENDIENTE_CF815",
}

# ── INEGI ────────────────────────────────────────────────────────────────
INEGI_TOKEN = os.getenv("INEGI_TOKEN", "")
INEGI_BASE = "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml"

# ── Alcance geográfico ───────────────────────────────────────────────────
CIUDADES = {
    "guadalajara": {"estado": "jalisco", "slug_portal": "jalisco/guadalajara"},
    "cdmx": {"estado": "ciudad-de-mexico", "slug_portal": "distrito-federal"},
    "estado_mexico": {"estado": "mexico", "slug_portal": "mexico"},
}

# ── Sanity checks ────────────────────────────────────────────────────────
RANGO_TASA_HIPOTECARIA = (0.08, 0.30)  # tasas anuales fuera de este rango → flag
