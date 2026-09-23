"""BORME, sección A (actos inscritos): sociedades del sector, sus cargos, socios únicos y domicilios.

Cada día el BORME publica un documento por provincia con decenas o cientos de inscripciones:

    <h5 class="articulo">423011 - NOMBRE SOCIEDAD LIMITADA.</h5>
    <p class="parrafo">Constitución. Comienzo de operaciones: … Objeto social: … Domicilio: … Capital: …
    Declaración de unipersonalidad. Socio único: … Nombramientos. Adm. Unico: …  Datos registrales. …</p>

De todas las inscripciones se guarda solo un índice local de denominaciones (para relecturas dirigidas).
De las del sector (por nombre, por objeto social o por estar ya en el grafo) se guardan los actos
completos. Las personas físicas nunca se guardan con su nombre: se sustituyen por un seudónimo
estable (HMAC con una sal secreta), que permite ver que la misma persona administra varias
sociedades sin publicar quién es.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Iterable, Iterator

from lxml import html as lhtml

from . import red
from . import sociedades as so
from .config import BORME_DIR, BORME_SUMARIO_URL, BORME_TXT_URL, CACHE_DIR, INDICE_DIR, SAL_PATH

_CACHE = CACHE_DIR / "borme"

# ---------------------------------------------------------------- seudónimos

_sal: bytes | None = None


def sal() -> bytes:
    """Sal secreta: variable de entorno GRAFO_SAL (Actions) o data/.sal (local, se crea la primera vez)."""
    global _sal
    if _sal is None:
        import os
        if os.environ.get("GRAFO_SAL"):
            _sal = os.environ["GRAFO_SAL"].encode()
        elif SAL_PATH.exists():
            _sal = SAL_PATH.read_bytes().strip()
        else:
            _sal = secrets.token_hex(32).encode()
            SAL_PATH.write_bytes(_sal)
    return _sal


def _norm_persona(nombre: str) -> str:
    # «CASTRO DIAZ, MIGUEL ANGEL» (socio único) y «CASTRO DIAZ MIGUEL ANGEL» (cargos) son la misma persona
    n = so.sin_acentos(nombre).upper()
    n = re.sub(r"[^A-Z0-9Ñ ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def seudonimo(nombre: str) -> str:
    h = hmac.new(sal(), _norm_persona(nombre).encode(), hashlib.sha256).hexdigest()
    return "PF-" + h[:10]


_PJ_EXTRA = re.compile(
    r"\b(?:SOCIEDAD|SL|SA|SLU|SAU|SLL|SLP|SAS|SARL|SRL|SPA|GMBH|AG|BV|NV|LLC|LLP|LP|INC|LTD|LIMITED|PLC|SE|SCA|SCS|"
    r"FCR|SCR|SICAV|FUND|FONDO|HOLDING|HOLDINGS|GROUP|GRUPO|PARTNERS|CAPITAL|INVEST|INVESTMENT|INVESTMENTS|"
    r"ASSET|MANAGEMENT|TRUST|COOP|COOPERATIVA|AIE|UTE|ENTIDAD|AYUNTAMIENTO|FUNDACION|ASOCIACION|BANCO|BANK|CAJA|"
    r"ENERGIA|ENERGY|RENOVABLES|SOLAR|POWER|AUDITORES|ASESORES|CONSULTING|SERVICES|SERVICIOS|GESTION)\b"
)


def es_juridica(nombre: str) -> bool:
    return bool(_PJ_EXTRA.search(so.sin_acentos(nombre).upper()))


def sujeto(nombre: str) -> dict:
    """Una persona jurídica se guarda con su nombre (es información registral pública de una empresa).
    Una persona física, solo con su seudónimo."""
    nombre = re.sub(r"\s+", " ", nombre).strip(" .;,")
    if es_juridica(nombre):
        return {"tipo": "PJ", "nombre": nombre, "clave": so.clave(nombre)}
    return {"tipo": "PF", "id": seudonimo(nombre)}


# «SUSTAINCO INVEST SL. REPR.143 RRM: ROCA ENRICH RAMON»: persona jurídica con su representante persona física
_REPR_RE = re.compile(r"\.?\s*(?:REPR(?:ES)?\.?\s*(?:143\s*RRM)?|Repres\.?|REPRESENTANTE)\s*:\s*", re.I)


def sujetos_de(nombre: str) -> list[dict]:
    partes = _REPR_RE.split(nombre, maxsplit=1)
    if len(partes) == 2 and partes[1].strip():
        pj, rep = sujeto(partes[0]), sujeto(partes[1])
        rep["representa"] = pj.get("clave", "")
        return [pj, rep]
    return [sujeto(nombre)]


_MAYUS_RE = re.compile(r"\b[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ'\-]+(?:,?\s+[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ'\-]+){1,5}\b")
_NO_NOMBRE = re.compile(r"ARTICUL|ESTATUT|CAPITAL|SOCIAL|SOCIEDAD|JUNTA|CONSEJO|ADMINISTRA|ORGANO|NUEVO|NUEVA|"
                        r"MODIFICACION|REDACCION|INCLUSION|INCLUISION|DOMICILIO|OBJETO|REGISTRO|MERCANTIL|RRM|LEY|"
                        r"UNIPERSONAL|PARTICIPACIONES|ACCIONES|EUROS|TITULO|DISPOSICION|ACUERDO")


def seudonimiza_texto(t: str) -> str:
    """Sustituye en un texto libre del BORME las secuencias en mayúsculas que parecen nombres de persona."""
    def rep(m: re.Match) -> str:
        s = m.group(0)
        if es_juridica(s) or _NO_NOMBRE.search(so.sin_acentos(s)):
            return s
        return seudonimo(s)
    return _MAYUS_RE.sub(rep, t)


# ---------------------------------------------------------------- descarga

def fetch_sumario(day: date) -> dict | None:
    cache = _CACHE / f"sumario_{day:%Y%m%d}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    r = red.get(BORME_SUMARIO_URL.format(yyyymmdd=f"{day:%Y%m%d}"), accept="application/json")
    data = r.json() if r is not None else None
    if data and data.get("status", {}).get("code") not in (None, "200", 200):
        data = None
    if data is not None or day < date.today():
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _as_list(x) -> list:
    return [] if x is None else (x if isinstance(x, list) else [x])


def items_seccion_a(sumario: dict) -> list[tuple[str, str]]:
    """(identificador, provincia) de cada documento provincial de la sección A."""
    out = []
    for diario in _as_list(sumario["data"]["sumario"]["diario"]):
        for sec in _as_list(diario.get("seccion")):
            if sec.get("codigo") != "A":
                continue
            for it in _as_list(sec.get("item")):
                out.append((it["identificador"], it.get("titulo", "")))
    return out


def fetch_entradas(ident: str) -> list[tuple[int, str, str]]:
    """(número, denominación, texto) de cada inscripción de un documento provincial. No se cachea en bruto."""
    r = red.get(BORME_TXT_URL.format(id=ident), timeout=90)
    if r is None:
        return []
    doc = lhtml.fromstring(r.content)
    cont = doc.get_element_by_id("textoxslt", None)
    if cont is None:
        return []
    out, actual = [], None
    for el in cont:
        if el.tag == "h5":
            t = re.sub(r"\s+", " ", el.text_content()).strip()
            m = re.match(r"(\d+)\s*-\s*(.+?)\.?$", t)
            actual = (int(m.group(1)), m.group(2).strip()) if m else None
        elif el.tag == "p" and actual:
            out.append((actual[0], actual[1], re.sub(r"\s+", " ", el.text_content()).strip()))
            actual = None
    return out


# ---------------------------------------------------------------- análisis de una inscripción

_ACTOS = [
    "Constitución", "Nombramientos", "Ceses/Dimisiones", "Revocaciones", "Reelecciones",
    "Cancelaciones de oficio de nombramientos", "Cambio de domicilio social", "Cambio de objeto social",
    "Cambio de denominación social", "Declaración de unipersonalidad", "Pérdida del caracter de unipersonalidad",
    "Pérdida del carácter de unipersonalidad", "Socio único", "Sociedad unipersonal", "Ampliación de capital",
    "Reducción de capital", "Modificaciones estatutarias", "Fusión por absorción", "Fusión por unión",
    "Escisión parcial", "Escisión total", "Escisión", "Segregación", "Cesión global de activo y pasivo",
    "Disolución", "Extinción", "Transformación de sociedad", "Situación concursal", "Reactivación de la sociedad",
    "Cierre provisional hoja registral", "Reapertura hoja registral", "Modificación de poderes",
    "Desembolso de dividendos pasivos", "Emisión de obligaciones", "Primera inscripción", "Otros conceptos",
    "Datos registrales", "Anotación preventiva", "Crédito incobrable", "Apertura de sucursal", "Cierre de sucursal",
    "Empresario individual", "Adaptación", "Acuerdo de ampliación de capital social sin ejecutar",
    "Articulo 378.5 del Reglamento del Registro Mercantil", "Artículo 378.5 del Reglamento del Registro Mercantil",
    "Depósito de libros", "Fe de erratas", "Unipersonalidad", "Rectificación",
]
_ACTOS_RE = re.compile(
    r"(?:(?<=^)|(?<=\.\s)|(?<=\.))\s*(" + "|".join(re.escape(a) for a in sorted(_ACTOS, key=len, reverse=True)) + r")(?=[.:]|\s)",
)
_CON_CARGOS = {"Nombramientos", "Ceses/Dimisiones", "Revocaciones", "Reelecciones", "Cancelaciones de oficio de nombramientos"}
_CARGO_RE = re.compile(r"(?:(?<=^)|(?<=\.\s)|(?<=\.))\s*([A-Z][A-Za-zÁÉÍÓÚáéíóúñ\./ ]{0,24}?\.?)\s*:\s")
_SUBCAMPO_RE = re.compile(r"\b(Comienzo de operaciones|Objeto social|Domicilio|Capital|Duración|Resultante Suscrito|Suscrito|Desembolsado|Resultante Desembolsado)\s*:\s*")


# Etiquetas de cargo tal como las escribe el BORME (con y sin puntos, en mayúsculas o no) → forma canónica y clase.
# La clase decide qué vínculos cuentan en el grafo: administrar o apoderar sí; auditar o custodiar, no.
_CARGOS = {
    "ADMUNICO": ("Adm. único", "admin"), "ADMSOLID": ("Adm. solidario", "admin"), "ADMSOLIDARIO": ("Adm. solidario", "admin"),
    "ADMMANCOM": ("Adm. mancomunado", "admin"), "ADMMANCOMUNADO": ("Adm. mancomunado", "admin"),
    "CONSEJERO": ("Consejero", "admin"), "PRESIDENTE": ("Presidente", "admin"), "VICEPRESID": ("Vicepresidente", "admin"),
    "VICEPRESIDENTE": ("Vicepresidente", "admin"), "SECRETARIO": ("Secretario", "admin"), "VICESECRET": ("Vicesecretario", "admin"),
    "SECNOCONSJ": ("Secretario no consejero", "admin"), "VSECNOCONSJ": ("Vicesecretario no consejero", "admin"),
    "CONSDELEG": ("Consejero delegado", "admin"), "CONDELEG": ("Consejero delegado", "admin"),
    "CONSDELMAN": ("Consejero delegado mancomunado", "admin"), "CONDELMAN": ("Consejero delegado mancomunado", "admin"),
    "CONSDELSOL": ("Consejero delegado solidario", "admin"), "CONDELSOL": ("Consejero delegado solidario", "admin"),
    "MIEMCOMEJ": ("Miembro comité ejecutivo", "admin"), "MIECOMEJEC": ("Miembro comité ejecutivo", "admin"),
    "LIQUIDADOR": ("Liquidador", "admin"), "LIQUISOLI": ("Liquidador solidario", "admin"), "LIQUIDMANC": ("Liquidador mancomunado", "admin"),
    "APODERADO": ("Apoderado", "apoderado"), "APOD": ("Apoderado", "apoderado"), "APOSOL": ("Apoderado solidario", "apoderado"),
    "APODSOL": ("Apoderado solidario", "apoderado"), "APOMAN": ("Apoderado mancomunado", "apoderado"),
    "APODMANC": ("Apoderado mancomunado", "apoderado"), "APOMANC": ("Apoderado mancomunado", "apoderado"),
    "APOSOLID": ("Apoderado solidario", "apoderado"), "AUDITCUENT": ("Auditor de cuentas", "otro"), "APOMANSOL": ("Apoderado mancomunado y solidario", "apoderado"),
    "AUDITOR": ("Auditor", "otro"), "AUDSUPL": ("Auditor suplente", "otro"), "ENTIDDEPOSIT": ("Entidad depositaria", "otro"),
    "SOCPROF": ("Socio profesional", "otro"), "REPRESENTAN": ("Representante", "apoderado"),
}


def cargo(etiqueta: str) -> tuple[str, str]:
    k = re.sub(r"[^A-Z]", "", so.sin_acentos(etiqueta).upper())
    if k in _CARGOS:
        return _CARGOS[k]
    if k.startswith("APO"):
        return etiqueta.strip(" ."), "apoderado"
    if k.startswith(("AUD", "ENTID")):
        return etiqueta.strip(" ."), "otro"
    return etiqueta.strip(" ."), "admin"


def _sujetos(lista: str) -> list[dict]:
    return [s for n in re.split(r";", lista) if n.strip(" .") for s in sujetos_de(n)]


def _subcampos(cuerpo: str) -> dict:
    out, marcas = {}, list(_SUBCAMPO_RE.finditer(cuerpo))
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(cuerpo)
        out[m.group(1)] = cuerpo[m.end():fin].strip(" .")
    return out


def analizar(texto: str) -> list[dict]:
    """Descompone el párrafo de una inscripción en actos, con cargos y sujetos ya seudonimizados."""
    marcas = list(_ACTOS_RE.finditer(texto))
    actos = []
    for i, m in enumerate(marcas):
        tipo = m.group(1)
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        cuerpo = texto[m.end():fin].strip(" .:")
        a: dict = {"tipo": tipo}
        if tipo in _CON_CARGOS:
            cargos = list(_CARGO_RE.finditer(" " + cuerpo if not cuerpo.startswith(" ") else cuerpo))
            base = " " + cuerpo if not cuerpo.startswith(" ") else cuerpo
            a["cargos"] = []
            for j, c in enumerate(cargos):
                cfin = cargos[j + 1].start() if j + 1 < len(cargos) else len(base)
                nombre_cargo, clase = cargo(c.group(1))
                a["cargos"].append({"cargo": nombre_cargo, "clase": clase,
                                    "sujetos": _sujetos(base[c.end():cfin].strip(" ."))})
        elif tipo == "Socio único":
            a["sujetos"] = _sujetos(cuerpo)
        elif tipo == "Constitución":
            sc = _subcampos(cuerpo)
            a.update({k: v for k, v in {
                "objeto": sc.get("Objeto social", "")[:600], "domicilio": sc.get("Domicilio", ""),
                "capital": sc.get("Capital", ""), "comienzo": sc.get("Comienzo de operaciones", ""),
            }.items() if v})
        elif tipo == "Cambio de domicilio social":
            a["domicilio"] = cuerpo
        elif tipo == "Cambio de denominación social":
            a["nueva"] = cuerpo
            a["clave_nueva"] = so.clave(cuerpo)
        elif tipo == "Cambio de objeto social":
            a["objeto"] = cuerpo[:600]
        elif tipo.startswith(("Fusión", "Escisión", "Segregación", "Cesión global")):
            partes = re.split(r":\s*", cuerpo, maxsplit=1)
            lista = partes[1] if len(partes) == 2 else cuerpo
            a["detalle"] = partes[0][:80] if len(partes) == 2 else ""
            a["sociedades"] = [{"nombre": n.strip(" ."), "clave": so.clave(n)} for n in re.split(r"[;,]\s*(?=[A-Z0-9])", lista)
                               if len(n.strip(" .")) > 2][:20]
        elif tipo in ("Ampliación de capital", "Reducción de capital"):
            sc = _subcampos(cuerpo)
            a.update({k: v for k, v in {"capital": sc.get("Capital", ""), "suscrito": sc.get("Resultante Suscrito", "")}.items() if v})
        elif tipo == "Datos registrales":
            a["datos"] = cuerpo[:120]
        elif tipo == "Otros conceptos":
            a["texto"] = seudonimiza_texto(cuerpo[:300])
        # el resto (modificaciones estatutarias, depósitos…) solo interesa como hecho
        actos.append(a)
    return actos


# ---------------------------------------------------------------- selección del sector

_SECTOR_NOMBRE = re.compile(
    r"ENERG|SOLAR|EOLIC|FOTOVOLT|PHOTOVOLT|RENOVABL|RENEWABL|POWER|WIND|VENTO\b|VIENTO|\bPV\b|\bFV\b|\bPFV\b|\bPSF\b|"
    r"\bCSF\b|\bHSF\b|BESS|STORAGE|ALMACENAMIENTO ENERG|HIDROELEC|BIOGAS|BIOMETAN|HIBRID|"
    r"PARQUE EOLICO|PLANTA SOLAR|PLANTA FV|\bHELIO|\bEOLO|AEOLUS|SPV\b|PHOTON"
)
_SECTOR_OBJETO = re.compile(
    r"energ[ií]a\s+el[ée]ctrica|energ[ií]as?\s+renovables?|fotovolt|e[óo]lic|producci[óo]n\s+de\s+(?:energ|electric)|"
    r"generaci[óo]n\s+de\s+(?:energ|electric)|almacenamiento\s+de\s+energ|instalaciones\s+de\s+producci[óo]n\s+de\s+energ",
    re.I,
)


def es_sector(denominacion: str, texto: str, objetivo: set[str]) -> bool:
    if so.clave(denominacion) in objetivo:
        return True
    if _SECTOR_NOMBRE.search(so.sin_acentos(denominacion).upper()):
        return True
    m = re.search(r"Objeto social:\s*(.{0,600})", texto)
    if m and _SECTOR_OBJETO.search(m.group(1)):
        return True
    # socio único o administrador que ya es del sector (p. ej. la matriz de una SPV de nombre neutro)
    for pj in re.findall(r"(?:Socio único|Adm\.\s*Unico|Adm\.\s*Solid\.|Adm\.\s*Mancom\.|Consejero|Presidente)\s*:\s*([^.;]+)", texto):
        k = so.clave(pj)
        if k in objetivo or (es_juridica(pj) and _SECTOR_NOMBRE.search(so.sin_acentos(pj).upper())):
            return True
    return False


# ---------------------------------------------------------------- registro y almacenamiento

@dataclass
class Inscripcion:
    id: str  # documento provincial del BORME
    fecha: str
    provincia: str
    num: int
    sociedad: str
    clave: str
    actos: list[dict] = field(default_factory=list)

    @property
    def url(self) -> str:
        return BORME_TXT_URL.format(id=self.id)


def procesar_dia(day: date, objetivo: set[str]) -> tuple[int, list[Inscripcion]]:
    """Lee todo el BORME-A de un día. Devuelve (inscripciones leídas, inscripciones del sector)."""
    sumario = fetch_sumario(day)
    if not sumario:
        return 0, []
    total, sector, indice = 0, [], []
    for ident, provincia in items_seccion_a(sumario):
        for num, nombre, texto in fetch_entradas(ident):
            total += 1
            k = so.clave(nombre)
            indice.append(f"{day.isoformat()}\t{ident}\t{num}\t{k}\n")
            if es_sector(nombre, texto, objetivo):
                sector.append(Inscripcion(ident, day.isoformat(), provincia, num, nombre, k, analizar(texto)))
    ruta = INDICE_DIR / f"{day:%Y-%m}" / f"{day.isoformat()}.tsv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("".join(indice), encoding="utf-8")
    return total, sector


def cargar(meses: Iterable[str] | None = None) -> list[dict]:
    rutas = [BORME_DIR / f"{m}.jsonl" for m in meses] if meses else sorted(BORME_DIR.glob("*.jsonl"))
    out = []
    for r in rutas:
        if r.exists():
            out += [json.loads(l) for l in r.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def guardar(inscripciones: list[Inscripcion]) -> int:
    por_mes: dict[str, list[dict]] = {}
    for i in inscripciones:
        por_mes.setdefault(i.fecha[:7], []).append(asdict(i))
    nuevas = 0
    for mes, lista in por_mes.items():
        existentes = {(d["id"], d["num"]): d for d in cargar([mes])}
        for d in lista:
            nuevas += (d["id"], d["num"]) not in existentes
            existentes[(d["id"], d["num"])] = d
        filas = sorted(existentes.values(), key=lambda d: (d["fecha"], d["id"], d["num"]))
        (BORME_DIR / f"{mes}.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in filas),
                                               encoding="utf-8")
    return nuevas


_DIAS = BORME_DIR / "dias.txt"


def dias_procesados() -> set[str]:
    """Fechas ya leídas (se versiona en el repo; el índice local no, porque pesa cientos de MB)."""
    if not _DIAS.exists():
        return set()
    return {l.strip() for l in _DIAS.read_text(encoding="utf-8").splitlines() if l.strip()}


def marcar_dias(dias: Iterable[date]) -> None:
    todos = dias_procesados() | {d.isoformat() for d in dias}
    _DIAS.write_text("".join(f"{d}\n" for d in sorted(todos)), encoding="utf-8")


def iter_indice(claves: set[str]) -> Iterator[tuple[str, str, int, str]]:
    """Busca en el índice local todas las inscripciones de unas sociedades (fecha, documento, número, clave)."""
    for r in sorted(INDICE_DIR.glob("*/*.tsv")):
        with open(r, encoding="utf-8") as f:
            for linea in f:
                fecha, ident, num, k = linea.rstrip("\n").split("\t")
                if k in claves:
                    yield fecha, ident, int(num), k
