"""Proyectos de generación y almacenamiento eléctrico publicados en el BOE.

De cada anuncio o resolución se extrae lo que sirve para reconstruir quién está detrás y cómo se
reparte un proyecto: instalaciones con su potencia, titular (NIF y domicilio si constan), subestaciones
de evacuación, nudo de la red de transporte, expediente y las frases en las que la propia
Administración habla de tramitación conjunta, acumulación o infraestructura compartida.
Todo queda enlazado al anuncio oficial para que cualquiera pueda comprobarlo.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from . import sociedades as so
from .config import PROYECTOS_DIR
from .municipios import extraer_municipios

# ---------------------------------------------------------------- filtro

_TECNOLOGIAS = {
    "eolica": r"e[óo]lic|aerogenerador",
    "fotovoltaica": r"fotovolt|planta\s+solar|parque\s+solar|instalaci[óo]n\s+solar|huerto\s+solar|\bPSF\b|\bFV\b|\bPFV\b|\bCSF\b",
    "almacenamiento": r"almacenamiento\s+(?:energ|el[ée]ctr|por\s+bater|con\s+bater|de\s+energ|mediante)|\bBESS\b|bater[íi]as|stand\s*alone",
    "bombeo": r"bombeo|reversible",
    "hidraulica": r"hidroel[ée]ctric|minicentral|salto\s+de\s+agua",
    "termosolar": r"termosolar|solar\s+t[ée]rmica|termoel[ée]ctrica\s+solar",
    "biomasa": r"biomasa|biog[áa]s|biometan",
    "hidrogeno": r"hidr[óo]geno|electroliz",
    "marina": r"e[óo]lica\s+marina|energ[íi]as\s+marinas|offshore|flotante",
}
_TEC_RE = {k: re.compile(v, re.I) for k, v in _TECNOLOGIAS.items()}

_TRAMITE = re.compile(
    r"autorizaci[óo]n\s+administrativa|impacto\s+ambiental|utilidad\s+p[úu]blica|informaci[óo]n\s+p[úu]blica|"
    r"desistimiento|desestima|actas?\s+previas|caducidad|potencia\s+instalada|\bMW\b|infraestructura\s+de\s+evacuaci",
    re.I,
)
_EXCLUIR = re.compile(
    r"sellos?\s+de\s+correo|convenio|fundaci[óo]n|plan\s+de\s+estudios|m[áa]ster|munici[óo]n|sistema\s+de\s+arma|"
    r"enseres|pertrechos|contenedores|mercanc[íi]a|congelaci|solar\s+sin\s+edificar|ponencia\s+de\s+valores|"
    r"retribuci[óo]n\s+a\s+la\s+operaci|registro\s+de\s+aguas|concesi[óo]n\s+de\s+aguas|aprovechamiento\s+de\s+aguas|"
    r"desinformaci|dep[óo]sitos\s+para\s+almacenamiento\s+de\s+agua|recurso\s+interpuesto|concurso\s+p[úu]blico\s+para\s+la\s+transmisi",
    re.I,
)


def tecnologias(texto: str) -> list[str]:
    return [k for k, r in _TEC_RE.items() if r.search(texto)]


def es_proyecto(titulo: str) -> bool:
    """¿Es un acto sobre una instalación de generación o almacenamiento? Se decide por el título."""
    if _EXCLUIR.search(titulo) or not _TRAMITE.search(titulo):
        return False
    return bool(tecnologias(titulo))


# ---------------------------------------------------------------- tipo de acto

_ACTOS = [
    ("correccion", r"corrig(?:e|en)\s+errores|rectificaci[óo]n\s+de\s+error"),
    ("desistimiento", r"desistimiento"),
    ("desestimacion", r"desestima|deniega|denegaci[óo]n"),
    ("caducidad", r"caducidad"),
    ("expropiacion", r"actas?\s+previas|ocupaci[óo]n\s+de\s+(?:bienes|fincas|determinadas)|expropiaci"),
    ("evaluacion_ambiental", r"formula\s+(?:declaraci[óo]n|informe)\s+de\s+impacto|modificaci[óo]n\s+de\s+condiciones\s+de\s+la\s+declaraci"),
    ("informacion_publica", r"informaci[óo]n\s+p[úu]blica|somete"),
    ("utilidad_publica", r"declara(?:ci[óo]n)?,?\s+en\s+concreto|declara\s+la\s+utilidad|reconocimiento,?\s+en\s+concreto"),
    ("autorizacion", r"otorga|concede|autoriza|publicaci[óo]n\s+de\s+la\s+resoluci"),
]
_ACTOS_RE = [(k, re.compile(v, re.I)) for k, v in _ACTOS]


def tipo_acto(titulo: str) -> str:
    for k, r in _ACTOS_RE:
        if r.search(titulo):
            return k
    return "otro"


# ---------------------------------------------------------------- potencias

_NUM = r"\d{1,4}(?:[.,]\d{1,4})?"
_MW_RE = re.compile(rf"({_NUM})\s*(MWp|MWn|MVA|MW)\b", re.I)


def num(x: str) -> float | None:
    """«43,896» → 43.896; «1.200» → 1200 (punto de millar); «4.5» → 4.5."""
    x = x.strip()
    try:
        if "," in x:
            return float(x.replace(".", "").replace(",", "."))
        if re.fullmatch(r"\d{1,3}\.\d{3}", x):
            return float(x.replace(".", ""))
        return float(x)
    except ValueError:
        return None


_Q = r"[«\"“”'‘’]"  # comillas de apertura o cierre, el BOE usa todas
_NOMBRE_Q = rf"{_Q}\s*(?P<n>[^«»\"“”\n]{{2,90}}?)\s*{_Q}"
_TIPO_INST = (
    r"(?i:parque\s+e[óo]lico|parque\s+solar(?:\s+fotovoltaico)?|planta\s+(?:solar\s+)?(?:fotovoltaica|termosolar)|"
    r"planta\s+de\s+almacenamiento|instalaci[óo]n\s+(?:solar\s+)?fotovoltaica(?:\s+h[íi]brida)?|instalaci[óo]n\s+solar|"
    r"instalaci[óo]n\s+h[íi]brida|m[óo]dulo\s+(?:de\s+generaci[óo]n\s+(?:e[óo]lic[oa]|fotovoltaic[oa])|de\s+almacenamiento(?:\s+(?:energ[ée]tico|por\s+bater[íi]as|con\s+bater[íi]as))?|fotovoltaico|e[óo]lico|por\s+bater[íi]as)|"
    r"central\s+hidroel[ée]ctrica(?:\s+reversible)?|proyecto)"
)
# «Salinas I», de 36 MW  ·  parque eólico Peñaflor, de 49,5 MW  ·  PSF Ronda 5 de 1,41 MVA
_INST_Q_RE = re.compile(rf"{_NOMBRE_Q},?\s+(?:de|con\s+una\s+potencia(?:\s+instalada)?\s+de)\s+(?P<mw>{_NUM})\s*(?:MWp|MWn|MVA|MW)\b", re.I)
_INST_T_RE = re.compile(
    rf"{_TIPO_INST}\s+(?:denominad[oa]\s+)?(?:existente\s+)?(?P<n>(?:[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÑáéíóúñ'’\-\.]*)(?:\s+(?:de|del|la|las|los|el|y|[A-ZÁÉÍÓÚÑ0-9IVX][\wÁÉÍÓÚÑáéíóúñ'’\-\.]*)){{0,6}}?),?\s+"
    rf"(?i:de|con\s+una\s+potencia(?:\s+instalada)?\s+de)\s+(?P<mw>{_NUM})\s*(?:MWp|MWn|MVA|MW)\b",
)
# «San Gil» y «Loma Gorda», de 36 MW y 49,8 MW de potencia instalada, respectivamente
_RESPECT_RE = re.compile(
    rf"{_Q}(?P<a>[^«»\"“”\n]{{2,60}}?){_Q}\s+y\s+{_Q}(?P<b>[^«»\"“”\n]{{2,60}}?){_Q},?\s+de\s+(?P<ma>{_NUM})\s*MW\s+y\s+"
    rf"(?P<mb>{_NUM})\s*MW[^.\n]{{0,40}}?respectivamente",
    re.I,
)
# Helena Solar 15, Helena Solar 16 y Helena Solar 17, de 22,8 MW de potencia instalada cada una
_CADA_RE = re.compile(
    rf"(?P<lista>(?:[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\-\.]*(?:\s+[\wÁÉÍÓÚÑáéíóúñ\-\.]+){{0,4}},\s+)+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\-\.]*(?:\s+[\wÁÉÍÓÚÑáéíóúñ\-\.]+){{0,4}}\s+y\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\-\.]*(?:\s+[\wÁÉÍÓÚÑáéíóúñ\-\.]+){{0,4}}),\s+de\s+(?P<mw>{_NUM})\s*(?:MWp|MWn|MW)\s+(?:de\s+potencia\s+(?:instalada\s+)?)?cada\s+un[oa]",
)
_HIBRIDA_RE = re.compile(rf"(?:instalaci[óo]n|planta|central)\s+h[íi]brida\s+(?:[^.\n]{{0,60}}?)de\s+(?P<mw>{_NUM})\s*MW\b", re.I)
_AEROS_RE = re.compile(r"\b(?P<n>\d{1,3})\s+aerogeneradores(?:\s+(?:del?\s+)?(?:modelo|tipo)?\s*(?P<m>[A-Z][\w\-\.]*(?:\s+[A-Z0-9][\w\-\.]*){0,2}))?", re.I)
_UNITARIA_RE = re.compile(rf"(?P<mw>{_NUM})\s*MW\s+de\s+potencia\s+unitaria", re.I)


def _limpia_nombre(n: str) -> str:
    n = re.sub(r"\s+", " ", n).strip(" ,.;:-")
    n = re.sub(r"^(?:el|la|los|las|denominad[oa])\s+", "", n, flags=re.I)
    return n


def _es_nombre_valido(n: str) -> bool:
    if len(n) < 2 or len(n) > 90:
        return False
    if re.fullmatch(r"(?:potencia|instalad[ao]|total|nominal|pico|la|el|su|de|dicha|dicho)(?:\s.*)?", n, re.I):
        return False
    return not re.search(r"\b(?:potencia\s+instalada|infraestructura\s+de\s+evacuaci|t[ée]rmino|provincia)\b", n, re.I)


def instalaciones(texto: str) -> list[dict]:
    """Instalaciones con nombre y potencia, en orden de aparición y sin repetir."""
    vistas: dict[str, dict] = {}

    def add(nombre: str, mw: str, pos: int):
        nombre = _limpia_nombre(nombre)
        v = num(mw)
        if v is None or v <= 0 or v > 5000 or not _es_nombre_valido(nombre):
            return
        k = so.sin_acentos(nombre).lower()
        if k not in vistas:
            vistas[k] = {"nombre": nombre, "mw": v, "_pos": pos}

    for m in _RESPECT_RE.finditer(texto):
        add(m.group("a"), m.group("ma"), m.start())
        add(m.group("b"), m.group("mb"), m.start() + 1)
    for m in _CADA_RE.finditer(texto):
        for parte in re.split(r",\s+|\s+y\s+", m.group("lista")):
            add(parte, m.group("mw"), m.start())
    for r in (_INST_Q_RE, _INST_T_RE):
        for m in r.finditer(texto):
            add(m.group("n"), m.group("mw"), m.start())
    out = sorted(vistas.values(), key=lambda d: d.pop("_pos") if "_pos" in d else 0)
    for d in out:
        d.pop("_pos", None)
    return out


# ---------------------------------------------------------------- titulares

# Una denominación social: palabras (la primera en mayúscula o cifra) + forma jurídica. El recorte por la
# izquierda de lo que no es nombre se hace después, en _recorta.
_SOC = rf"[«\"“]?(?P<s>[A-ZÁÉÍÓÚÑ0-9][\w&ÁÉÍÓÚÑáéíóúñü'’\.\-]*(?:\s+[\w&ÁÉÍÓÚÑáéíóúñü'’\.\-]+){{0,9}}?),?\s+(?P<f>{so.FORMA_TXT})[»\"”]?"
_SOC_RE = re.compile(_SOC)

# Contexto que convierte una sociedad citada en titular del proyecto
_ANTES_TITULAR = re.compile(
    r"(?:otorga(?:n|do|da)?\s+a|otorg[óo]\s+a|concede(?:r)?\s+a|formulad[oa]\s+por|solicitud\s+(?:formulada\s+por|de)|favor\s+de|"
    r"petici[óo]n\s+de|instancia\s+de|escrito\s+de|promovid[oa]\s+por|presentad[oa]\s+por|"
    r"peticionari[oa]|promotor(?:a)?(?:[\s\-]peticionari[oa])?|solicitante|titular(?:\s+del\s+proyecto)?|entidad\s+peticionaria\s+es|"
    r"(?:la|por)\s+(?:empresa|mercantil|sociedad|entidad)|mercantil|respecto\s+del?\s+que|del?\s+que|de\s+los\s+que|del?\s+cual)"
    r"\s*[:\-]?\s*(?:(?:la|a\s+la)\s+(?:empresa|mercantil|sociedad|entidad)\s+)?[«\"“]?\s*$",
    re.I,
)
_DESPUES_TITULAR = re.compile(
    r"^\s*[»\"”]?\s*(?:\((?:CIF|NIF)[^)]*\)\s*)?,?\s*(?:y\s+[A-ZÁÉÍÓÚÑ][^.]{0,80}?(?:SL|SA|SLU|SAU|S\.L\.U?|S\.A\.U?)\.?,?\s*)?"
    r"(?:con\s+(?:domicilio|CIF|NIF|C\.I\.F|N\.I\.F)|\(?en\s+adelante|es\s+(?:el\s+)?promotor|son\s+(?:los\s+)?promotores|"
    r"promotor(?:a)?\s+del|solicit[óoa]|ha\s+solicitado|present[óa]|como\s+promotor|titular\s+de)",
    re.I,
)
# Sociedades que aparecen en los anuncios sin ser titulares: la red, las distribuidoras, los consultados
_NO_TITULAR = re.compile(
    r"Red\s+El[ée]ctrica|\bREE\b|Distribuci[óo]n|i-DE|\bUFD\b|Redes\s+Digitales|e-distribuci|Enagas|Exolum|\bCLH\b|Telef[óo]nica|"
    r"Adif|Aena|Correos|Emasesa|Canal\s+de\s+Isabel|Aguas\s+de|Autopista|Iberdrola\s+Distribuci|Viesgo\s+Distribuci|Begasa|"
    r"Ministerio|Direcci[óo]n\s+General|Delegaci[óo]n|Subdelegaci[óo]n|Ayuntamiento|Confederaci[óo]n|Consejer[íi]a|Diputaci[óo]n",
    re.I,
)
_CONECTOR = {"de", "del", "la", "las", "el", "los", "y", "e", "i", "&", "en", "d'", "l'"}
_CAMBIO_DENOM_RE = re.compile(
    rf"cambio\s+de\s+(?:su\s+)?denominaci[óo]n(?:\s+social)?\s+de\s+{_SOC},?\s+a\s+(?:la\s+de\s+)?{_SOC.replace('(?P<s>', '(?P<s2>').replace('(?P<f>', '(?P<f2>')}",
    re.I,
)


def _recorta(nombre: str) -> str:
    """Quita por la izquierda lo que no forma parte del nombre («Consta la solicitud de Greenalia Solar» → «Greenalia Solar»)."""
    toks = nombre.split()
    i = len(toks)
    while i > 0:
        t = toks[i - 1]
        if t[:1].isupper() or t[:1].isdigit() or t.lower() in _CONECTOR or t[:1] in "&(":
            i -= 1
            continue
        break
    toks = toks[i:]
    # Un fin de frase («Palencia. IBERENOVA…», «2024. Cerezo Solar…») o una palabra de encabezado
    # («Con fecha…», «Antecedentes», «Promotor-peticionario») marcan dónde empieza de verdad el nombre
    for j in range(len(toks) - 2, -1, -1):
        t = toks[j]
        if (t.endswith(".") and not re.fullmatch(r"(?:[A-Z]\.)+|Cía\.|Hnos\.|Sdad\.", t)) or t.endswith(":") or \
                re.fullmatch(r"(?:\d{4}|Con|En|Por|Mediante|Seg[úu]n|Asimismo|Adem[áa]s|Antecedentes|Promotor(?:a)?(?:-peticionari[oa])?|"
                             r"Peticionari[oa]|Titular|Solicitante|Objeto|Hechos)", t, re.I):
            toks = toks[j + 1:]
            break
    while toks and toks[0].lower() in _CONECTOR:
        toks = toks[1:]
    return " ".join(toks)


def _limpia_soc(m: re.Match, g: str = "s", gf: str = "f") -> str:
    nombre = _recorta(re.sub(r"\s+", " ", m.group(g)).strip(" ,.«»\"“”"))
    f = so.forma("X " + m.group(gf)) or re.sub(r"\s+", "", m.group(gf)).strip(".")
    return f"{nombre}, {f}" if nombre else ""


def titulares(titulo: str, texto: str) -> tuple[list[str], list[str]]:
    """Sociedades en contexto de titular: (titulares, otras citadas).

    Si el título nombra sociedades, esas son las titulares y las del cuerpo quedan como «otras»
    (suelen ser las que comparten evacuación o las de la instalación con la que se hibrida).
    Si el título no nombra ninguna, las del cuerpo pasan a titulares.
    """
    del_titulo, del_cuerpo, vistos = [], [], set()

    def considera(fuente: str, m: re.Match, destino: list, exigir_contexto: bool):
        nombre = _limpia_soc(m)
        if not nombre or _NO_TITULAR.search(nombre):
            return
        k = so.clave(nombre)
        if len(k) < 3 or k in vistos:
            return
        antes = fuente[max(0, m.start() - 70): m.start()]
        despues = fuente[m.end(): m.end() + 120]
        if exigir_contexto and not (_ANTES_TITULAR.search(antes) or _DESPUES_TITULAR.search(despues)):
            return
        vistos.add(k)
        destino.append(nombre)

    for m in _SOC_RE.finditer(titulo):
        considera(titulo, m, del_titulo, exigir_contexto=False)
    cuerpo = texto[:8000]
    for m in _SOC_RE.finditer(cuerpo):
        considera(cuerpo, m, del_cuerpo, exigir_contexto=True)
    if del_titulo:
        return del_titulo[:6], del_cuerpo[:8]
    return del_cuerpo[:3], del_cuerpo[3:10]


def cambios_denominacion(texto: str) -> list[dict]:
    out = []
    for m in _CAMBIO_DENOM_RE.finditer(texto):
        out.append({"antes": _limpia_soc(m), "despues": _limpia_soc(m, "s2", "f2")})
    return out

_DOMICILIO_RE = re.compile(
    r"domicilio(?:\s+social)?(?:\s+a\s+efectos\s+de\s+notificaci[óo]n(?:es)?)?\s*(?:en|:)?\s*(?P<d>[^\n;]{8,160}?)"
    r"(?=\s*(?:(?<![\s.][A-Za-zº])\.\s|\.$|;|\n|,\s*(?:y\s+)?(?:con\s+)?(?:C\.?I\.?F|N\.?I\.?F)|,\s+(?:solicita|ha\s+solicitado|para|por\s+la\s+que|en\s+relaci)))",
    re.I,
)


def domicilios(texto: str) -> list[str]:
    res = []
    for m in _DOMICILIO_RE.finditer(texto[:8000]):
        d = re.sub(r"\s+", " ", m.group("d")).strip(" ,.")
        if re.search(r"\d", d) and d not in res:
            res.append(d)
    return res[:4]


# ---------------------------------------------------------------- evacuación

_KV = r"\d{2,3}(?:\s*/\s*\d{1,3}(?:[.,]\d)?){0,3}"
_PAL = r"[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÑáéíóúñ'’\-\.]*"
_SUB_RE = re.compile(
    rf"\b(?:SET|ST|SE|subestaci[óo]n(?:\s+(?:el[ée]ctrica|colectora|transformadora|elevadora|de\s+transformaci[óo]n|de\s+evacuaci[óo]n|de\s+seccionamiento|existente|renovables?))*|nudo(?:\s+de\s+la\s+red\s+de\s+transporte)?)"
    rf"\s+{_Q}?(?P<n>(?:{_PAL})(?:\s+(?:de|del|la|las|el|los|{_PAL})){{0,5}}?){_Q}?\s*,?\s*(?P<kv>{_KV})\s*kV\b",
)
_PROPIEDAD_REE = re.compile(r"^[^.\n]{0,80}?(?:propiedad\s+de\s+)?Red\s+(?:de\s+)?El[ée]ctrica|^\s*REE\b|^[^.\n]{0,20}\(REE\)", re.I)


def _clave_sub(nombre: str) -> str:
    n = so.sin_acentos(nombre).lower()
    n = re.sub(r"\b(?:set|st|se|subestacion|electrica|colectora|transformadora|elevadora|existente|nudo|de|del|la|el|ree|"
               r"ice|pe|pfv|fv|psf|hfv|cs|ss)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def subestaciones(texto: str) -> list[dict]:
    """Subestaciones citadas, con su tensión y si son de la red de transporte (REE).

    Las colectoras del promotor (132/30 kV, 30/220 kV…) son la señal fuerte de infraestructura compartida;
    un nudo de REE a 400 kV lo comparten decenas de proyectos sin relación entre sí.
    """
    subs: dict[str, dict] = {}
    for m in _SUB_RE.finditer(texto):
        nombre = re.sub(r"\s+", " ", m.group("n")).strip(" ,.«»\"")
        if re.fullmatch(r"(?:de|a|en|la|el|\d+)", nombre, re.I):
            continue
        kv = re.sub(r"\s+", "", m.group("kv"))
        tensiones = [float(x.replace(",", ".")) for x in kv.split("/") if x]
        base = _clave_sub(nombre)
        if not base:
            continue
        # Un nudo de la red de transporte tiene una sola tensión (220 o 400 kV). Una colectora con el mismo
        # topónimo («Colectora Belinchón 400/132/30 kV») es otra instalación, del promotor.
        transporte = len(tensiones) == 1 and tensiones[0] >= 220
        firma = "/".join(f"{t:g}" for t in sorted(set(tensiones), reverse=True))
        k = f"{base}|{'T' if transporte else firma}"
        despues = texto[m.end(): m.end() + 120]
        antes = texto[max(0, m.start() - 60): m.start()]
        ree = transporte and bool(_PROPIEDAD_REE.search(despues) or re.search(r"\bREE\b", m.group(0))
                                  or re.search(r"nudo|red\s+de\s+transporte", antes, re.I))
        d = subs.setdefault(k, {"nombre": nombre, "kv": kv, "clave": k, "red_transporte": False})
        d["red_transporte"] = d["red_transporte"] or ree
    return list(subs.values())


# ---------------------------------------------------------------- expedientes y frases de agrupación

_EXPTE_RE = re.compile(
    r"\b(?P<e>(?:PEol|PFot|PEOL|PFOT|PHib|PAlm|PFot-ALM|PEol-FV|SGEE|IAT|AT|ATLINEA|RE|AAU|AAP|EIA|FV|PE|PSF|ENER|SIE|IE)"
    r"[\-/]?(?:[A-Z]{1,5}[\-/])?\d{1,6}(?:[\-/\.]\d{1,6})*(?:[\-/ ][A-Z]{1,4}\b)?)",
)
_EXPTE_CTX_RE = re.compile(
    r"\b(?:expediente|expte\.?|exp\.|referencia)\s*(?:n[úu]m(?:ero)?\.?|n\.?º|nº)?\s*[:\-]?\s*(?P<e>[A-Z0-9][A-Z0-9/\-\._]{2,40}\d[A-Z0-9/\-\._]*|[A-Z0-9/\-\._]*\d[A-Z0-9/\-\._]{2,40})",
    re.I,
)


def expedientes(titulo: str, texto: str) -> list[str]:
    out = []
    for r in (_EXPTE_CTX_RE, _EXPTE_RE):
        for m in r.finditer(titulo + "\n" + texto[:12000]):
            e = m.group("e").strip(" .,-/")
            if len(e) < 4 or re.fullmatch(r"\d{1,4}", e) or re.fullmatch(r"(?:RE|AT|FV|PE)-?\d{1,2}", e):
                continue
            if re.fullmatch(r"\d{4}", e) or e in out:
                continue
            out.append(e)
    return out[:8]


_AGRUPA_RE = re.compile(
    r"[^.\n]*(?:acumulaci[óo]n|tramitaci[óo]n\s+conjunta|de\s+forma\s+conjunta|compartid[ao]s?\s+(?:con|entre|por)|"
    r"infraestructuras?\s+(?:de\s+evacuaci[óo]n\s+)?compartid|acuerdo\s+de\s+promotores|comparten|"
    r"cada\s+un[oa]\b[^.\n]*MW|fraccionamiento|fragmentaci[óo]n|efectos\s+sin[ée]rgicos|efectos\s+acumulativos)[^.\n]*",
    re.I,
)


def frases_agrupacion(texto: str) -> list[str]:
    res = []
    for m in _AGRUPA_RE.finditer(texto):
        f = re.sub(r"\s+", " ", m.group(0)).strip(" –-•·")
        if len(f) > 450:
            # recorta alrededor de la palabra clave
            k = _AGRUPA_RE.pattern
            i = max(0, re.search(r"acumulaci|conjunta|compartid|acuerdo de promotores|comparten|cada un|fraccion|fragment|sin[ée]rgic|acumulativ", f, re.I).start() - 200)
            f = ("…" if i else "") + f[i: i + 420] + "…"
        if f not in res:
            res.append(f)
    return res[:12]


# ---------------------------------------------------------------- registro

@dataclass
class Proyecto:
    id: str
    fecha: str
    fuente: str
    seccion: str
    departamento: str
    titulo: str
    url: str
    acto: str = ""
    tecnologias: list[str] = field(default_factory=list)
    instalaciones: list[dict] = field(default_factory=list)
    potencia_mw: float | None = None  # la de la instalación principal (la primera nombrada en el título)
    potencia_hibrida_mw: float | None = None
    titulares: list[str] = field(default_factory=list)
    otras_sociedades: list[str] = field(default_factory=list)  # citadas junto al proyecto (evacuación compartida, hibridación…)
    nifs: list[str] = field(default_factory=list)
    domicilios: list[str] = field(default_factory=list)
    subestaciones: list[dict] = field(default_factory=list)
    expedientes: list[str] = field(default_factory=list)
    municipios: list[str] = field(default_factory=list)
    provincias: list[str] = field(default_factory=list)
    aerogeneradores: int | None = None
    modelo_aerogenerador: str = ""
    potencia_unitaria_mw: float | None = None
    agrupacion: list[str] = field(default_factory=list)
    cambios_denominacion: list[dict] = field(default_factory=list)


def extraer(ident: str, fecha: str, seccion: str, departamento: str, titulo: str, url: str, texto: str,
            fuente: str = "BOE") -> Proyecto:
    p = Proyecto(id=ident, fecha=fecha, fuente=fuente, seccion=seccion, departamento=departamento, titulo=titulo, url=url)
    cuerpo = titulo + "\n" + texto
    p.acto = tipo_acto(titulo)
    p.tecnologias = tecnologias(titulo) or tecnologias(texto[:3000])
    if re.search(r"h[íi]brid", titulo, re.I) and "hibrida" not in p.tecnologias:
        p.tecnologias.append("hibrida")
    p.instalaciones = instalaciones(cuerpo)
    en_titulo = instalaciones(titulo)
    if en_titulo:
        p.potencia_mw = en_titulo[0]["mw"]
    elif p.instalaciones:
        p.potencia_mw = p.instalaciones[0]["mw"]
    else:
        m = _MW_RE.search(titulo) or _MW_RE.search(texto[:4000])
        p.potencia_mw = num(m.group(1)) if m else None
    m = _HIBRIDA_RE.search(cuerpo)
    if m:
        p.potencia_hibrida_mw = num(m.group("mw"))
    p.titulares, p.otras_sociedades = titulares(titulo, texto)
    p.nifs = so.nifs(texto[:10000])
    p.domicilios = domicilios(texto)
    p.subestaciones = subestaciones(texto)
    p.expedientes = expedientes(titulo, texto)
    p.municipios, p.provincias = extraer_municipios(titulo, texto)
    m = _AEROS_RE.search(texto)
    if m:
        p.aerogeneradores = int(m.group("n"))
        p.modelo_aerogenerador = (m.group("m") or "").strip(" .,")
    m = _UNITARIA_RE.search(texto)
    if m:
        p.potencia_unitaria_mw = num(m.group("mw"))
    p.agrupacion = frases_agrupacion(texto)
    p.cambios_denominacion = cambios_denominacion(texto)
    return p


# ---------------------------------------------------------------- almacenamiento en JSONL por año

def cargar(anio: int | None = None) -> list[dict]:
    rutas = [PROYECTOS_DIR / f"{anio}.jsonl"] if anio else sorted(PROYECTOS_DIR.glob("*.jsonl"))
    out = []
    for r in rutas:
        if r.exists():
            out += [json.loads(l) for l in r.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def guardar(proyectos: list[Proyecto | dict]) -> int:
    """Añade o reemplaza por identificador, un fichero por año. Devuelve cuántos son nuevos."""
    por_anio: dict[int, list[dict]] = {}
    for p in proyectos:
        d = asdict(p) if isinstance(p, Proyecto) else p
        por_anio.setdefault(int(d["fecha"][:4]), []).append(d)
    nuevos = 0
    for anio, lista in por_anio.items():
        existentes = {d["id"]: d for d in cargar(anio)}
        for d in lista:
            nuevos += d["id"] not in existentes
            existentes[d["id"]] = d
        filas = sorted(existentes.values(), key=lambda d: (d["fecha"], d["id"]))
        (PROYECTOS_DIR / f"{anio}.jsonl").write_text(
            "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in filas), encoding="utf-8")
    return nuevos
