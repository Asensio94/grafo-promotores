"""Recogida por rangos de fechas: BOE (proyectos) y BORME (sociedades)."""

from __future__ import annotations

from datetime import date, timedelta

from rich.progress import Progress

from . import boe, borme, proyectos
from . import sociedades as so
from .config import OBJETIVO_PATH


def boe_rango(desde: date, hasta: date, *, progreso: bool = True) -> tuple[int, int]:
    """Recorre el BOE entre dos fechas y guarda los proyectos energéticos. Devuelve (vistos, nuevos)."""
    vistos = nuevos = 0
    pendientes: list[proyectos.Proyecto] = []
    dias = boe.dias(desde, hasta)
    with Progress(disable=not progreso) as bar:
        t = bar.add_task("BOE", total=len(dias))
        for d in dias:
            bar.update(t, advance=1, description=f"BOE {d:%Y-%m-%d} · {vistos} proyectos")
            sumario = boe.fetch_sumario(d)
            for it in boe.iter_items(sumario, d) if sumario else ():
                if not proyectos.es_proyecto(it.titulo):
                    continue
                texto = boe.fetch_texto(it.identificador)
                pendientes.append(proyectos.extraer(
                    it.identificador, it.fecha, it.seccion, it.departamento, it.titulo, it.url_html, texto))
                vistos += 1
            # se guarda cada fin de mes para no perder trabajo si se corta un histórico largo
            if pendientes and (d == dias[-1] or (d + timedelta(days=1)).month != d.month):
                nuevos += proyectos.guardar(pendientes)
                pendientes = []
    return vistos, nuevos


def objetivo() -> set[str]:
    """Sociedades que interesan aunque su nombre no sea del sector: titulares del BOE y la lista manual."""
    claves = {so.clave(n) for p in proyectos.cargar() for n in p["titulares"] + p["otras_sociedades"]}
    if OBJETIVO_PATH.exists():
        claves |= {so.clave(l) for l in OBJETIVO_PATH.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.startswith("#")}
    return {k for k in claves if k}


def borme_rango(desde: date, hasta: date, *, inverso: bool = True, progreso: bool = True) -> tuple[int, int]:
    """Lee el BORME-A de un rango (por defecto de lo reciente a lo antiguo). Devuelve (días leídos, inscripciones)."""
    hechos = borme.dias_procesados()
    dias = [d for d in boe.dias(desde, hasta) if d.weekday() < 5 and d.isoformat() not in hechos]
    if inverso:
        dias.reverse()
    obj = objetivo()
    leidos, total, pendientes, marcados = 0, 0, [], []
    with Progress(disable=not progreso) as bar:
        t = bar.add_task("BORME", total=len(dias))
        for i, d in enumerate(dias):
            bar.update(t, advance=1, description=f"BORME {d:%Y-%m-%d} · {total} inscripciones del sector")
            _, sector = borme.procesar_dia(d, obj)
            pendientes += sector
            marcados.append(d)
            leidos += 1
            total += len(sector)
            if i % 5 == 4 or i == len(dias) - 1:
                borme.guardar(pendientes)
                borme.marcar_dias(marcados)
                pendientes, marcados = [], []
    return leidos, total


def reprocesar() -> int:
    """Vuelve a extraer todos los proyectos guardados desde los textos en caché (tras cambiar reglas)."""
    rehechos = []
    for d in proyectos.cargar():
        texto = boe.fetch_texto(d["id"])
        rehechos.append(proyectos.extraer(d["id"], d["fecha"], d["seccion"], d["departamento"], d["titulo"], d["url"],
                                          texto, fuente=d.get("fuente", "BOE")))
    proyectos.guardar(rehechos)
    return len(rehechos)
