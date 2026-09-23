"""Línea de órdenes: python -m promotores.cli <orden>."""

from __future__ import annotations

from datetime import date, timedelta

import typer

from . import borme, grafo, proyectos, recoger

app = typer.Typer(add_completion=False, help="Grafo de promotores y detector de fraccionamiento (BOE + BORME).")


def _fecha(s: str | None, defecto: date) -> date:
    return date.fromisoformat(s) if s else defecto


@app.command()
def boe(desde: str = typer.Option(None, help="AAAA-MM-DD (por defecto, hace 7 días)"),
        hasta: str = typer.Option(None, help="AAAA-MM-DD (por defecto, hoy)")):
    """Recoge del BOE los anuncios y resoluciones de proyectos energéticos."""
    hoy = date.today()
    vistos, nuevos = recoger.boe_rango(_fecha(desde, hoy - timedelta(days=7)), _fecha(hasta, hoy))
    typer.echo(f"BOE: {vistos} actos vistos, {nuevos} nuevos")


@app.command("borme")
def borme_cmd(desde: str = typer.Option(None, help="AAAA-MM-DD (por defecto, hace 7 días)"),
              hasta: str = typer.Option(None, help="AAAA-MM-DD (por defecto, hoy)"),
              directo: bool = typer.Option(False, help="De lo antiguo a lo reciente (por defecto, al revés)")):
    """Lee el BORME-A y guarda, seudonimizadas, las inscripciones de sociedades del sector."""
    hoy = date.today()
    dias, n = recoger.borme_rango(_fecha(desde, hoy - timedelta(days=7)), _fecha(hasta, hoy), inverso=not directo)
    typer.echo(f"BORME: {dias} días leídos, {n} inscripciones del sector")


@app.command()
def reprocesar():
    """Vuelve a extraer los proyectos desde los textos en caché."""
    typer.echo(f"{recoger.reprocesar()} actos reprocesados")


@app.command("grafo")
def grafo_cmd():
    """Construye data/grafo.json."""
    g = grafo.construir(proyectos.cargar(), borme.cargar())
    grafo.guardar(g)
    typer.echo(g["resumen"])


@app.command()
def web():
    """Genera docs/ a partir de data/grafo.json."""
    from . import site
    site.generar()
    typer.echo("docs/ generado")


@app.command()
def diario():
    """Lo que hace el workflow cada día: BOE y BORME de la última semana, grafo y web."""
    boe(None, None)
    borme_cmd(None, None, False)
    grafo_cmd()
    web()


if __name__ == "__main__":
    app()
