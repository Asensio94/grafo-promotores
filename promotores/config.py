from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"  # descargas en bruto, fuera del repositorio
DOCS_DIR = ROOT / "docs"  # web estática publicada con GitHub Pages

PROYECTOS_DIR = DATA_DIR / "proyectos"  # un JSONL por año con los anuncios de proyectos energéticos
BORME_DIR = DATA_DIR / "borme"  # inscripciones del sector ya seudonimizadas, un JSONL por mes
INDICE_DIR = CACHE_DIR / "borme_indice"  # denominaciones de TODAS las inscripciones (local, para relecturas dirigidas)
GRAFO_PATH = DATA_DIR / "grafo.json"
SAL_PATH = DATA_DIR / ".sal"
OBJETIVO_PATH = DATA_DIR / "objetivo.txt"  # sociedades a seguir aunque no salgan en el BOE (una por línea)

for d in (CACHE_DIR / "boe", CACHE_DIR / "borme", INDICE_DIR, PROYECTOS_DIR, BORME_DIR, DOCS_DIR):
    d.mkdir(parents=True, exist_ok=True)

USER_AGENT = "grafo-promotores/0.1 (proyecto abierto de conservacion; https://github.com/Asensio94/grafo-promotores)"
PAUSA = 0.35  # segundos entre peticiones al BOE, por cortesía

BOE_SUMARIO_URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{yyyymmdd}"
BOE_XML_URL = "https://www.boe.es/diario_boe/xml.php?id={id}"
BOE_HTML_URL = "https://www.boe.es/diario_boe/txt.php?id={id}"
BORME_SUMARIO_URL = "https://www.boe.es/datosabiertos/api/borme/sumario/{yyyymmdd}"
BORME_TXT_URL = "https://www.boe.es/diario_borme/txt.php?id={id}"

# Umbrales normativos que el detector vigila (ver README, «Umbrales»)
UMBRAL_COMPETENCIA_MW = 50.0  # art. 3.13.a) Ley 24/2013: por encima autoriza la Administración General del Estado
MARGEN_BAJO_UMBRAL = 0.08  # «justo por debajo»: entre el 92 % y el 100 % del umbral
