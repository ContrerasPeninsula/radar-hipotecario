"""
Scraper de oferta inmobiliaria — Lamudi México.

Selectores HTML confirmados contra la estructura real del sitio (no asumidos):
tarjetas <div class="snippet">, con subcampos por clase y atributos data-test.
El contenido carga vía scroll progresivo (lazy-load) — un GET simple sin scroll
no es suficiente, por eso una primera versión con espera estática devolvía 0 resultados.

Alcance actual: CDMX, Estado de México, Guadalajara (ver CIUDADES_ACTIVAS).
Se puede ampliar a Puerto Vallarta / Mazatlán / Acapulco más adelante.

Responsabilidad al scrapear:
  - User-Agent identificable, delay entre requests, límite de páginas por ciudad.
  - Revisar https://www.lamudi.com.mx/robots.txt antes de escalar el volumen.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import CIUDADES, DIR_DATA

BASE_URL = "https://www.lamudi.com.mx"
RATE_LIMIT_SEGUNDOS = 2.0
MAX_PAGINAS_DEFAULT = 2
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Alcance actual acordado — subconjunto de CIUDADES en config/settings.py.
CIUDADES_ACTIVAS = ["cdmx", "estado_mexico", "guadalajara"]

# Filtro de sanidad sobre m²: descarta parsing erróneo (campos de estacionamiento,
# terreno, etc. capturados por error). No es específico de ningún negocio.
M2_MIN, M2_MAX = 15, 1000


def _num(texto: str | None) -> float | None:
    """'$ 2,024,337 MXN' -> 2024337.0 | '140 m²' -> 140.0 | None si no hay dígitos."""
    if not texto:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", texto.replace(",", ""))
    return float(m.group()) if m else None


def construir_url_busqueda(slug_portal: str, tipo: str = "casa", pagina: int = 1) -> str:
    base = f"{BASE_URL}/{slug_portal}/{tipo}/for-sale/"
    return base if pagina == 1 else f"{base}?page={pagina}"


def iniciar_driver(headless: bool = True):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opciones = Options()
    if headless:
        opciones.add_argument("--headless=new")
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")
    opciones.add_argument("--window-size=1400,1000")
    opciones.add_argument(f"user-agent={USER_AGENT}")
    return webdriver.Chrome(options=opciones)


def extraer_resumen_mercado(soup: BeautifulSoup) -> dict:
    """Lamudi calcula su propia mediana y precio/m² agregados sobre TODOS los resultados
    de la búsqueda (no solo la página visible) — más confiable que promediar tarjetas."""
    bloque = soup.find(class_="prices")
    if not bloque:
        return {"mediana_portal": None, "precio_m2_portal": None}
    mediana = bloque.find(class_="prices__median")
    precio_m2 = bloque.find(class_="prices__per-area")
    return {
        "mediana_portal": _num(mediana.get_text() if mediana else None),
        "precio_m2_portal": _num(precio_m2.get_text() if precio_m2 else None),
    }


def extraer_tarjetas(soup: BeautifulSoup, ciudad: str) -> list[dict]:
    registros = []
    for t in soup.find_all("div", class_="snippet"):
        titulo_el = t.find(class_="snippet__content__title")
        ubic_el = t.find(class_="snippet__content__location")
        precio_el = t.find(class_="snippet__content__price")
        m2_el = t.find(attrs={"data-test": "area-value"})
        rec_el = t.find(attrs={"data-test": "bedrooms-value"})
        ban_el = t.find(attrs={"data-test": "full-bathrooms-value"})
        link_el = t.find("a", href=True)

        precio = _num(precio_el.get_text() if precio_el else None)
        m2 = _num(m2_el.get_text() if m2_el else None)

        registros.append({
            "ciudad": ciudad,
            "titulo": titulo_el.get_text(strip=True) if titulo_el else None,
            "ubicacion": ubic_el.get_text(strip=True) if ubic_el else None,
            "precio": precio,
            "m2": m2,
            "precio_m2": round(precio / m2, 1) if precio and m2 else None,
            "recamaras": _num(rec_el.get_text() if rec_el else None),
            "banos": _num(ban_el.get_text() if ban_el else None),
            "url": (BASE_URL + link_el["href"]) if link_el and link_el["href"].startswith("/") else (link_el["href"] if link_el else None),
            "fecha_scrape": pd.Timestamp.now().normalize(),
        })
    return registros


def scrapear_ciudad(nombre_ciudad: str, tipo: str = "casa", max_paginas: int = MAX_PAGINAS_DEFAULT,
                     headless: bool = True) -> tuple[pd.DataFrame, dict]:
    """Devuelve (df_tarjetas, resumen_portal) para una ciudad."""
    slug = CIUDADES[nombre_ciudad]["slug_portal"]
    driver = iniciar_driver(headless=headless)
    todas_tarjetas = []
    resumen_final = {"mediana_portal": None, "precio_m2_portal": None}

    try:
        for pagina in range(1, max_paginas + 1):
            url = construir_url_busqueda(slug, tipo=tipo, pagina=pagina)
            driver.get(url)
            time.sleep(RATE_LIMIT_SEGUNDOS)

            # Contenido lazy-load: hay que forzar scroll para que el DOM lo renderice.
            for _ in range(4):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)

            soup = BeautifulSoup(driver.page_source, "html.parser")

            # ── DEBUG temporal ──────────────────────────────────────────
            print(f"  [{nombre_ciudad}] título de la página: {driver.title!r}")
            print(f"  [{nombre_ciudad}] longitud del HTML: {len(driver.page_source)} caracteres")
            texto_pagina = soup.get_text().lower()
            for palabra_sospechosa in ["captcha", "verifica", "cloudflare", "just a moment", "acceso denegado", "blocked"]:
                if palabra_sospechosa in texto_pagina:
                    print(f"  [{nombre_ciudad}] ⚠️ posible bloqueo — encontrado: '{palabra_sospechosa}'")
            ruta_screenshot = DIR_DATA / f"debug_{nombre_ciudad}_pagina{pagina}.png"
            driver.save_screenshot(str(ruta_screenshot))
            print(f"  [{nombre_ciudad}] screenshot guardado: {ruta_screenshot}")
            # ── fin DEBUG ────────────────────────────────────────────────

            if pagina == 1:
                resumen_final = extraer_resumen_mercado(soup)

            tarjetas = extraer_tarjetas(soup, nombre_ciudad)
            print(f"  [{nombre_ciudad}] página {pagina}: {len(tarjetas)} tarjetas")

            if not tarjetas:
                break
            todas_tarjetas.extend(tarjetas)

    finally:
        driver.quit()

    df = pd.DataFrame(todas_tarjetas)

    if not df.empty and "m2" in df.columns:
        n_antes = len(df)
        df = df[df["m2"].isna() | df["m2"].between(M2_MIN, M2_MAX)].copy()
        if len(df) != n_antes:
            print(f"  ⚠️  {nombre_ciudad}: descartadas {n_antes - len(df)} tarjeta(s) con m² fuera de [{M2_MIN}, {M2_MAX}]")

    resumen_final["ciudad"] = nombre_ciudad
    return df, resumen_final


def scrapear_ciudades_activas(tipo: str = "casa", max_paginas: int = MAX_PAGINAS_DEFAULT,
                                headless: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scrapea CIUDADES_ACTIVAS y devuelve (df_tarjetas, df_resumen_por_ciudad)."""
    partes_tarjetas, resumenes = [], []

    for ciudad in CIUDADES_ACTIVAS:
        print(f"Scrapeando {ciudad}...")
        df_ciudad, resumen = scrapear_ciudad(ciudad, tipo=tipo, max_paginas=max_paginas, headless=headless)
        partes_tarjetas.append(df_ciudad)
        resumenes.append(resumen)
        time.sleep(RATE_LIMIT_SEGUNDOS)

    df_tarjetas = pd.concat(partes_tarjetas, ignore_index=True) if partes_tarjetas else pd.DataFrame()
    df_resumen = pd.DataFrame(resumenes)
    return df_tarjetas, df_resumen


if __name__ == "__main__":
    print(f"Ciudades activas: {CIUDADES_ACTIVAS}\n")

    df_tarjetas, df_resumen = scrapear_ciudades_activas(max_paginas=1, headless=True)

    if df_tarjetas.empty:
        print("\n⚠️  No se extrajo ningún anuncio. Revisar screenshot/estructura del sitio.")
    else:
        print(f"\nTotal anuncios extraídos: {len(df_tarjetas)}")
        print("\nResumen del portal por ciudad:")
        print(df_resumen[["ciudad", "mediana_portal", "precio_m2_portal"]].to_string(index=False))

        print("\nMediana calculada de las tarjetas extraídas (referencia, sesgada por página):")
        print(df_tarjetas.groupby("ciudad")["precio_m2"].median())

        ruta_out = DIR_DATA / "oferta_lamudi.parquet"
        df_tarjetas.to_parquet(ruta_out, index=False)
        print(f"\n✔ Guardado: {ruta_out}")