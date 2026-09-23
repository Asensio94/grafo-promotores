"""Sumarios y anuncios del BOE (API de datos abiertos).

Adaptado de observatorio-alegaciones (observatorio/boe.py). Aquí interesan dos secciones:
la III (resoluciones de autorización y declaraciones de impacto ambiental, que citan al titular)
y la V-B (anuncios de información pública, con peticionario, domicilio e infraestructura de evacuación).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator

from lxml import etree

from . import red
from .config import BOE_HTML_URL, BOE_SUMARIO_URL, BOE_XML_URL, CACHE_DIR

SECCIONES = ("3", "5B")
_CACHE = CACHE_DIR / "boe"


@dataclass
class Item:
    identificador: str
    fecha: str
    seccion: str
    departamento: str
    titulo: str

    @property
    def url_html(self) -> str:
        return BOE_HTML_URL.format(id=self.identificador)


def _as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def fetch_sumario(day: date) -> dict | None:
    """Sumario JSON de un día, o None si no hubo BOE. Se cachea también la ausencia."""
    cache = _CACHE / f"sumario_{day:%Y%m%d}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    r = red.get(BOE_SUMARIO_URL.format(yyyymmdd=f"{day:%Y%m%d}"), accept="application/json")
    data = r.json() if r is not None else None
    if data and data.get("status", {}).get("code") not in (None, "200", 200):
        data = None
    # Los días futuros no se cachean como vacíos: todavía pueden publicarse
    if data is not None or day < date.today():
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def iter_items(sumario: dict, day: date, secciones: tuple[str, ...] = SECCIONES) -> Iterator[Item]:
    for diario in _as_list(sumario["data"]["sumario"]["diario"]):
        for sec in _as_list(diario.get("seccion")):
            codigo = sec.get("codigo", "")
            if codigo not in secciones:
                continue
            for dep in _as_list(sec.get("departamento")):
                items = _as_list(dep.get("item"))
                for ep in _as_list(dep.get("epigrafe")):
                    items += _as_list(ep.get("item"))
                for it in items:
                    yield Item(
                        identificador=it.get("identificador", ""),
                        fecha=day.isoformat(),
                        seccion=codigo,
                        departamento=dep.get("nombre", ""),
                        titulo=re.sub(r"\s+", " ", it.get("titulo", "")).strip(),
                    )


def fetch_texto(identificador: str) -> str:
    """Texto plano del anuncio a partir de su XML (cacheado)."""
    cache = _CACHE / f"{identificador}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    r = red.get(BOE_XML_URL.format(id=identificador), accept="application/xml", timeout=90)
    texto = ""
    if r is not None:
        texto_el = etree.fromstring(r.content).find(".//texto")
        if texto_el is not None:
            partes = (p.strip() for p in texto_el.itertext())
            texto = re.sub(r"[ \t]+", " ", "\n".join(p for p in partes if p))
    cache.write_text(texto, encoding="utf-8")
    return texto


def dias(desde: date, hasta: date) -> list[date]:
    """Todas las fechas del intervalo; el API responde 404 los días sin diario."""
    return [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
