"""
Scraper de oferta inmobiliaria — Inmuebles24 México.

Diseño: en vez de depender de un nombre de clase CSS exacto para la tarjeta
(no confirmado con certeza contra el HTML real), identificamos anuncios
genuinos por su URL — el patrón de listing contiene un ID numérico largo
(ej. ".../casa-en-venta-...-146670169.html?n_src=..."), que es mucho más
estable que cualquier clase de contenedor. Dentro de cada tarjeta así
identificada, se extrae precio/m² por patrón de texto (mismo enfoque
robusto usado en scraper_oferta.py para Lamudi).

Confirmado por prueba en vivo (screenshot): el sitio NO bloquea Selenium
headless con User-Agent estándar — a diferencia de Lamudi, que sí bloquea
con un WAF de borde (ver decisión documentada en docs/diseno_datos.md).

Alcance actual: CDMX, Estado de México, Guadalajara.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DIR_DATA

BASE_URL = "https://www.inmuebles24.com"
RATE_LIMIT_SEGUNDOS = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Slugs propios de Inmuebles24 — distintos a los de Lamudi (config.CIUDADES),
# por eso viven aquí y no en config/settings.py.
SLUGS_INMUEBLES24 = {
    "cdmx": "ciudad-de-mexico",
    "estado_mexico": "estado-de-mexico",
    "guadalajara": "guadalajara",
}

# Un anuncio real de Inmuebles24 contiene "-<ID numérico de 6+ dígitos>.html"
# en algún punto de la URL (puede traer parámetros de tracking después, por
# eso NO se ancla el patrón al final del string con $).
PATRON_URL_ANUNCIO = re.compile(r"-\d{6,}\.html")

PATRON_PRECIO = re.compile(r"\$\s?([\d,]{5,})")
PATRON_M2 = re.compile(r"([\d,]+(?:\.\d+)?)\s?m[²2]")

M2_MIN, M2_MAX = 15, 1000


def _num(texto: str | None) -> float | None:
    if not texto:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", texto.replace(",", ""))
    return float(m.group()) if m else None


def construir_url_busqueda(slug: str) -> str:
    return f"{BASE_URL}/casas-en-venta-en-{slug}.html"


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


def aceptar_cookies(driver) -> None:
    """Intenta cerrar el banner de cookies si aparece. No falla si no lo encuentra."""
    from selenium.webdriver.common.by import By
    textos_boton = ["Acepto", "Aceptar", "Accept"]
    for texto in textos_boton:
        try:
            boton = driver.find_element(By.XPATH, f"//button[contains(., '{texto}')]")
            boton.click()
            time.sleep(1)
            return
        except Exception:
            continue


def extraer_tarjetas(soup: BeautifulSoup, ciudad: str) -> list[dict]:
    registros = []
    vistos = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not PATRON_URL_ANUNCIO.search(href):
            continue
        url_completa = href if href.startswith("http") else BASE_URL + href
        if url_completa in vistos:
            continue
        vistos.add(url_completa)

        # Buscar el bloque de texto más informativo: el propio link, o si no
        # trae precio/m², subir un nivel al contenedor padre.
        texto = link.get_text(" ", strip=True)
        precio, m2 = _extraer_precio_m2(texto)

        contenedor = link
        intentos = 0
        while (precio is None or m2 is None) and intentos < 3 and contenedor.parent is not None:
            contenedor = contenedor.parent
            texto = contenedor.get_text(" ", strip=True)
            precio, m2 = _extraer_precio_m2(texto)
            intentos += 1

        if precio is None or m2 is None:
            continue  # no se pudo extraer info completa, se descarta

        registros.append({
            "ciudad": ciudad,
            "precio": precio,
            "m2": m2,
            "precio_m2": round(precio / m2, 1),
            "url": url_completa,
            "fecha_scrape": pd.Timestamp.now().normalize(),
        })

    return registros


def _extraer_precio_m2(texto: str) -> tuple[float | None, float | None]:
    m_precio = PATRON_PRECIO.search(texto)
    m_m2 = PATRON_M2.search(texto)
    precio = float(m_precio.group(1).replace(",", "")) if m_precio else None
    m2 = float(m_m2.group(1).replace(",", "")) if m_m2 else None
    return precio, m2


def scrapear_ciudad(nombre_ciudad: str, headless: bool = True) -> pd.DataFrame:
    slug = SLUGS_INMUEBLES24[nombre_ciudad]
    url = construir_url_busqueda(slug)

    driver = iniciar_driver(headless=headless)
    try:
        driver.get(url)
        time.sleep(RATE_LIMIT_SEGUNDOS)
        aceptar_cookies(driver)

        # Scroll progresivo — contenido lazy-load
        for _ in range(6):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        registros = extraer_tarjetas(soup, nombre_ciudad)
        print(f"  [{nombre_ciudad}] {len(registros)} anuncios con precio+m² extraídos")

    finally:
        driver.quit()

    df = pd.DataFrame(registros)
    if not df.empty:
        n_antes = len(df)
        df = df[df["m2"].between(M2_MIN, M2_MAX)].copy()
        if len(df) != n_antes:
            print(f"  ⚠️  {nombre_ciudad}: descartadas {n_antes - len(df)} tarjeta(s) con m² fuera de [{M2_MIN}, {M2_MAX}]")
    return df


def scrapear_ciudades_activas(headless: bool = True) -> pd.DataFrame:
    partes = []
    for ciudad in SLUGS_INMUEBLES24:
        print(f"Scrapeando {ciudad}...")
        df_ciudad = scrapear_ciudad(ciudad, headless=headless)
        partes.append(df_ciudad)
        time.sleep(RATE_LIMIT_SEGUNDOS)
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


if __name__ == "__main__":
    print(f"Ciudades activas: {list(SLUGS_INMUEBLES24.keys())}\n")

    df = scrapear_ciudades_activas(headless=True)

    if df.empty:
        print("\n⚠️  No se extrajo ningún anuncio. Revisar estructura del sitio.")
    else:
        print(f"\nTotal anuncios extraídos: {len(df)}")
        print("\nResumen por ciudad (mediana precio/m²):")
        print(df.groupby("ciudad")["precio_m2"].agg(["median", "count"]))

        ruta_out = DIR_DATA / "oferta_inmuebles24.parquet"
        df.to_parquet(ruta_out, index=False)
        print(f"\n✔ Guardado: {ruta_out}")