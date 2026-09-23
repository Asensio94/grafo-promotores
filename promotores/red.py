"""Acceso HTTP común: una sesión, pausa de cortesía y reintentos ante errores transitorios."""

from __future__ import annotations

import time

import requests

from .config import PAUSA, USER_AGENT

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})
_ultima = 0.0


def get(url: str, *, accept: str | None = None, timeout: int = 60, intentos: int = 4) -> requests.Response | None:
    """GET con pausa mínima entre peticiones. Devuelve None si el recurso no existe (404)."""
    global _ultima
    headers = {"Accept": accept} if accept else {}
    for i in range(intentos):
        espera = PAUSA - (time.monotonic() - _ultima)
        if espera > 0:
            time.sleep(espera)
        _ultima = time.monotonic()
        try:
            r = SESSION.get(url, headers=headers, timeout=timeout)
        except requests.RequestException:
            if i == intentos - 1:
                raise
            time.sleep(5 * (i + 1))
            continue
        if r.status_code == 404:
            return None
        if r.status_code in (429, 500, 502, 503, 504) and i < intentos - 1:
            time.sleep(10 * (i + 1))
            continue
        r.raise_for_status()
        return r
    return None
