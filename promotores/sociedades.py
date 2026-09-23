"""Normalización de denominaciones sociales, NIF y domicilios para poder cruzar BOE y BORME."""

from __future__ import annotations

import re
import unicodedata

# Formas jurídicas, en el orden en que conviene probarlas (las largas primero)
_FORMAS = [
    ("SOCIEDAD LIMITADA UNIPERSONAL", "SLU"), ("SOCIEDAD ANONIMA UNIPERSONAL", "SAU"),
    ("SOCIEDAD LIMITADA", "SL"), ("SOCIEDAD ANONIMA", "SA"), ("SOCIEDAD COOPERATIVA", "SCOOP"),
    ("S L U", "SLU"), ("S A U", "SAU"), ("S L L", "SLL"), ("S COOP", "SCOOP"), ("S L", "SL"), ("S A", "SA"),
    ("SLU", "SLU"), ("SAU", "SAU"), ("SLL", "SLL"), ("SCOOP", "SCOOP"), ("SL", "SL"), ("SA", "SA"),
    ("SE", "SE"), ("BV", "BV"), ("GMBH", "GMBH"), ("SPA", "SPA"), ("SRL", "SRL"), ("LTD", "LTD"),
]
_FORMA_RE = re.compile(r"(?:^|\s)(" + "|".join(re.escape(f) for f, _ in _FORMAS) + r")\s*$")
_FORMA_CANON = dict(_FORMAS)

# Una denominación social dentro de un texto: nombre + forma jurídica abreviada o desarrollada
FORMA_TXT = (
    r"(?:S\.?\s?L\.?\s?U\.?|S\.?\s?A\.?\s?U\.?|S\.?\s?L\.?\s?L\.?|S\.?\s?L\.?|S\.?\s?A\.?|SLU|SAU|SL|SA"
    r"|Sociedad\s+Limitada(?:\s+Unipersonal)?|Sociedad\s+An[óo]nima(?:\s+Unipersonal)?)(?![\w])"
)


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def clave(nombre: str) -> str:
    """Clave de cruce: mayúsculas sin acentos ni puntuación, sin la forma jurídica.

    «Energías Renovables de Circe, S.L.» y «ENERGIAS RENOVABLES DE CIRCE SL» dan la misma clave.
    Se pierde la forma jurídica a propósito: el BOE escribe «SL» donde el BORME pone «SOCIEDAD LIMITADA».
    """
    s = sin_acentos(nombre).upper().replace("&", " Y ")
    # el BORME añade el registro cuando la sociedad viene de otra provincia: «X SL (R.M. A CORUÑA)»
    s = re.sub(r"\(\s*R\.?\s*M\.?[^)]*\)", " ", s)
    s = re.sub(r"[.,;:'’\"«»()]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*\(?EN LIQUIDACION\)?$", "", s)
    for _ in range(2):  # «..., S.L. UNIPERSONAL» deja dos colas
        m = _FORMA_RE.search(s)
        if not m or m.start(1) == 0:
            break
        s = s[: m.start(1)].strip()
    s = re.sub(r"\bUNIPERSONAL$", "", s).strip()
    return s


def forma(nombre: str) -> str:
    s = re.sub(r"[.,]", " ", sin_acentos(nombre).upper())
    s = re.sub(r"\s+", " ", s).strip()
    m = _FORMA_RE.search(s)
    return _FORMA_CANON.get(m.group(1), "") if m else ""


def es_persona_juridica(nombre: str) -> bool:
    """Heurística: lleva forma jurídica o palabras de sociedad. Lo que no, se trata como persona física."""
    if forma(nombre):
        return True
    return bool(re.search(r"\b(?:ENERG|RENOVABL|SOLAR|EOLIC|POWER|GROUP|GRUPO|HOLDING|CAPITAL|FUND|INVEST|"
                          r"DESARROLL|PROYECT|INVERSION|GESTION|AYUNTAMIENTO|DIPUTACION|CONSORCIO|FUNDACION|"
                          r"ASOCIACION|COMUNIDAD|COOPERATIVA|UTE|AIE|FONDO|PARTNERS|IBERIA|ESPANA)",
                          sin_acentos(nombre).upper()))


_NIF_RE = re.compile(r"\b(?:C\.?I\.?F\.?|N\.?I\.?F\.?)\s*(?:n\.?º|nº|núm\.?|:)?\s*([A-HJ-NP-SUVW])[\s\-\.]?(\d{2})\.?(\d{3})\.?(\d{2})[\s\-]?([0-9A-J])\b", re.I)


def nifs(texto: str) -> list[str]:
    """NIF de personas jurídicas (letra inicial de sociedad). Los de personas físicas no se capturan."""
    vistos = []
    for m in _NIF_RE.finditer(texto):
        n = (m.group(1) + m.group(2) + m.group(3) + m.group(4) + m.group(5)).upper()
        if n not in vistos:
            vistos.append(n)
    return vistos


_CP_RE = re.compile(r"(?<![\d.,])(?:C\.?\s?P\.?\s*)?(\d{2})\.?(\d{3})(?![\d.,]\d)")
_VIA = r"(?:calle|c/|avenida|avda\.?|av\.|plaza|pza\.?|paseo|pº|p\.º|carretera|ctra\.?|camino|ronda|glorieta|pol[ií]gono|parque empresarial|traves[ií]a|rambla|v[ií]a|urbanizaci[oó]n|lugar|barrio|parcela)"


def partes_domicilio(domicilio: str) -> dict:
    """Descompone un domicilio en código postal, número de portal y palabras de la vía.

    El BOE escribe el mismo domicilio de maneras distintas («calle Berna, n.º1, 45003, de Toledo» y
    «45003, Toledo, calle Berna nº1»), así que se compara por partes y no por cadena.
    """
    d = sin_acentos(domicilio).lower().replace("º", " ").replace("ª", " ")
    cp = ""
    m = _CP_RE.search(d)
    if m:
        cp = m.group(1) + m.group(2)
        d = d[: m.start()] + " " + d[m.end():]
    d = re.sub(r"[^a-z0-9]+", " ", d)
    vacias = {"calle", "c", "avenida", "avda", "av", "plaza", "pza", "paseo", "p", "carretera", "ctra", "camino",
              "ronda", "glorieta", "numero", "num", "n", "no", "nro", "de", "del", "la", "las", "el", "los", "y", "en",
              "a", "efectos", "notificaciones", "domicilio", "social", "sito", "sita", "cp", "codigo", "postal",
              "planta", "piso", "puerta", "local", "oficina", "bajo", "izq", "izda", "dcha", "esc", "s", "sn"}
    toks = d.split()
    num = next((t for t in toks if t.isdigit()), "")
    palabras = sorted({t for t in toks if not t.isdigit() and t not in vacias and len(t) > 2})
    return {"cp": cp, "num": num, "palabras": palabras}


def mismo_domicilio(a: dict, b: dict) -> bool:
    """Mismo código postal, mismo número y al menos una palabra de la vía en común."""
    if not a or not b or not a.get("cp") or a.get("cp") != b.get("cp"):
        return False
    if a.get("num") and b.get("num") and a["num"] != b["num"]:
        return False
    return bool(set(a.get("palabras", [])) & set(b.get("palabras", [])) - {"madrid", "barcelona", "sevilla",
                                                                         "valencia", "zaragoza", "bilbao"})
