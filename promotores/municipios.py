"""Extracción de municipios y provincias de anuncios oficiales.

Copiado de observatorio-alegaciones (observatorio/extract.py, misma autoría y licencia MIT),
donde está contrastado con cientos de anuncios del BOE y del BOC. Si se mejora allí, conviene traerlo.
"""

from __future__ import annotations

import re
import unicodedata


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


PROVINCIAS = [
    "A Coruña", "Álava", "Araba", "Albacete", "Alicante", "Alacant", "Almería", "Asturias", "Ávila", "Badajoz",
    "Illes Balears", "Islas Baleares", "Barcelona", "Bizkaia", "Vizcaya", "Burgos", "Cáceres", "Cádiz", "Cantabria",
    "Castellón", "Castelló", "Ciudad Real", "Córdoba", "Cuenca", "Gipuzkoa", "Guipúzcoa", "Girona", "Granada",
    "Guadalajara", "Huelva", "Huesca", "Jaén", "La Rioja", "Las Palmas", "León", "Lleida", "Lugo", "Madrid", "Málaga",
    "Murcia", "Navarra", "Ourense", "Palencia", "Pontevedra", "Salamanca", "Santa Cruz de Tenerife", "Segovia",
    "Sevilla", "Soria", "Tarragona", "Teruel", "Toledo", "Valencia", "València", "Valladolid", "Zamora", "Zaragoza",
    "Ceuta", "Melilla",
]
_PROV_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in sorted(PROVINCIAS, key=len, reverse=True)) + r")\b", re.I)
_PROV_CANON = {_strip_accents(p.lower()): p for p in PROVINCIAS}

# Caracteres válidos en un nombre de municipio (incluye gallego, catalán, euskera)
_NOM = r"[A-Za-zÁÉÍÓÚÑÀÈÒÇÜÏáéíóúñàèòçüïl'’\-\.\s/,]"

# Fórmulas: "términos municipales de A, B y C", "T.M. de A", "T.M.: A", "T.M. ARNEDO (LA RIOJA)",
# "Término Municipal: EL BURGO DE EBRO", "Término Municipal y Provincia: A, B y C (Lugo); D (Ourense)"
_TM_RE = re.compile(
    r"(?:t[eé]rminos?\s+municipal(?:es)?(?:\s+y\s+provincia)?|\bt\.?\s*m\.?|\btt\.?\s*mm\.?|\bmunicipios?)"
    r"\s*(?::|\s+de\s+|\s+)"
    r"(?P<lista>" + _NOM + r"{3,220}?)"
    r"(?=\s*(?:\(|,?\s*(?:en\s+la\s+|de\s+la\s+)?provincia|\.\s|\.$|;|\n|$|,\s*pertenecientes|\s+pertenecientes|\s+y\s+(?:se|uno|en\s+la)\b|\s+con\s+un|\s+para\b|\s+en\s+la\s+(?:provincia|comarca|comunidad|isla)|\s+aprobado|\s+que\b|\s+conforme|\s+donde|\s+cuyo))",
    re.I,
)
_STOP_WORDS = {"la", "el", "los", "las", "de", "del", "provincia", "en", "y", "e", "i", "provincia y", "municipal"}
_BASURA = re.compile(
    r"^(?:y|e|i|de|del|en)\s+|^[a-záéíóúñ]+\s+de\s+(?=[A-ZÁÉÍÓÚÑ])|\s+(?:y|e|i)$|\s+pertenecientes.*$|\s+(?:en|de)\s+la\s+provincia.*$",
)
_PUERTO_RE = re.compile(r"(?:[Pp]uerto|Autoridad\s+Portuaria)\s+de\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+(?:de|del|la)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+|\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?)")


def _titlecase(s: str) -> str:
    """Convierte 'EL BURGO DE EBRO' → 'El Burgo de Ebro' respetando partículas."""
    if s != s.upper():
        return s
    minus = {"de", "del", "la", "las", "los", "el", "y", "e", "i", "a", "o", "os", "as", "da", "do", "das", "dos", "d'", "l'"}
    out = []
    for i, w in enumerate(s.lower().split()):
        out.append(w if (w in minus and i > 0) else w[:1].upper() + w[1:])
    return " ".join(out)


def _split_lista(lista: str) -> list[str]:
    lista = re.sub(r"\s+", " ", lista).strip(" ,.;:")
    partes = re.split(r"\s*[,;]\s*|\s+(?:y|e|i)\s+(?:de\s+)?(?=[A-ZÁÉÍÓÚÑ])", lista)
    out: list[str] = []
    for p in partes:
        p = _BASURA.sub("", p.strip(" ,.;:"))
        p = _BASURA.sub("", p).strip(" ,.;:")
        if not p or len(p) < 3 or _strip_accents(p.lower()) in _STOP_WORDS:
            continue
        if len(p.split()) > 6 or not p[0].isupper():
            continue
        out.append(_titlecase(p))
    return out


def extraer_municipios(titulo: str, texto: str) -> tuple[list[str], list[str]]:
    """Devuelve (municipios, provincias). Las provincias se toman del título si aparecen ahí
    (evita capturar la dirección del promotor en Madrid); si no, del texto."""
    base = titulo + "\n" + texto
    munis: list[str] = []
    claves: set[str] = set()
    for m in _TM_RE.finditer(base):
        for x in _split_lista(m.group("lista")):
            clave = re.sub(r"[^a-z]", "", _strip_accents(x.lower()))
            if clave and clave != "provincia" and clave not in claves:
                claves.add(clave)
                munis.append(x)

    def _provs(s: str) -> list[str]:
        out: list[str] = []
        for m in _PROV_RE.finditer(s):
            p = _PROV_CANON.get(_strip_accents(m.group(1).lower()), m.group(1))
            if p not in out:
                out.append(p)
        return out

    if not munis:
        # Concesiones portuarias: "Puerto de Santander" → municipio Santander
        for m in _PUERTO_RE.finditer(base):
            x = m.group(1)
            if _strip_accents(x.lower()) in _PROV_CANON or x.lower() in {"baleares", "canarias", "interés", "titularidad", "refugio"}:
                continue  # autoridades portuarias de ámbito provincial/autonómico: no hay municipio
            if x not in munis:
                munis.append(x)
    provs = _provs(titulo)
    if not provs:
        # Zona de "Emplazamiento"/"Término municipal" del texto, no las direcciones postales
        zona = " ".join(m.group(0) for m in re.finditer(r".{0,40}(?:t[eé]rmino|municipi|emplazamiento|provincia de).{0,160}", texto, re.I))
        provs = _provs(zona) or _provs(texto[:3000])
    return munis[:40], provs[:6]
