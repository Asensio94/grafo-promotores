"""Grafo de promotores: quién está detrás de cada instalación y qué instalaciones parecen un mismo proyecto troceado.

Dos uniones independientes:

1. Grupos empresariales. Se unen sociedades que comparten socio único, administrador o apoderado (BORME),
   domicilio (BOE), que se han fusionado o que son la misma tras un cambio de denominación.
2. Conjuntos de instalaciones. Se unen instalaciones que aparecen en el mismo anuncio, que evacuan por la
   misma subestación colectora o que están en el mismo municipio, siempre que sus titulares sean del mismo
   grupo (o el anuncio sea el mismo).

Sobre cada conjunto con dos o más instalaciones se miden los indicios de fraccionamiento: cada módulo por
debajo de 50 MW y la suma por encima, potencias idénticas, potencias justo bajo el umbral, expedientes
consecutivos y tramitación conjunta reconocida por la propia Administración. Son indicios a revisar, no
conclusiones: el reparto en módulos puede tener razones técnicas o de acceso a red.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations

from . import borme, sociedades as so
from .config import GRAFO_PATH, MARGEN_BAJO_UMBRAL, UMBRAL_COMPETENCIA_MW

# Una persona, una sociedad administradora o un domicilio compartidos por más sociedades que esto suelen ser
# un despacho, una gestora de servicios societarios o un centro de negocios: se publican, pero no unen grupos.
HUB_PERSONA = 40
HUB_PJ = 40
HUB_DOMICILIO = 8
# Un apoderado en común no basta: los de bancos y grandes grupos percolan todo el grafo. Se exige que dos
# sociedades compartan al menos este número de apoderados (o un administrador, o el socio único).
MIN_APODERADOS_COMUNES = 3
# y solo cuentan los apoderados y consejeros con pocas sociedades: los de un despacho o un banco van en pareja
# a decenas de sociedades de grupos distintos
HUB_DEBIL = 10
_MUNICIPIOS_RUIDO = {"Polígono", "Parcela", "Paraje"}

# Cargos profesionales que no indican control: secretarios no consejeros, liquidadores, gestoras, auditores.
_CARGO_NEUTRO = re.compile(r"SECRE|SECR|VSEC|LIQ|GESTORA|AUDIT|DEPOSIT|SOCPROF", re.I)


def fuerza(rol: str, cargo: str) -> str:
    """socio > admin > apoderado > neutro, según lo que el cargo dice sobre quién controla la sociedad."""
    if rol == "socio":
        return "socio"
    if _CARGO_NEUTRO.search(re.sub(r"[^A-Za-z]", "", so.sin_acentos(cargo))):
        return "neutro"
    if rol != "admin":
        return "apoderado"
    # administrador único, solidario o mancomunado frente a consejero, presidente o consejero delegado: un
    # consejero puede sentarse en consejos de grupos distintos, un administrador rara vez
    return "admin" if so.sin_acentos(cargo).upper().startswith("ADM") else "consejo"


_CONJUNTA = re.compile(r"\b(?:AIE|A I E|UTE|AGRUPACION DE INTERES ECONOMICO|UNION TEMPORAL)\b")
_ALTA = {"Nombramientos", "Reelecciones"}
_BAJA = {"Ceses/Dimisiones", "Revocaciones", "Cancelaciones de oficio de nombramientos"}


def marca_vigencia(vinculos: dict[str, list[dict]], fin_unipersonal: dict[str, list[tuple]]) -> None:
    """Pone v["vigente"]: un cargo sigue en vigor si su último acto es un nombramiento o reelección; un socio
    único, si es el último declarado y la sociedad no ha perdido después la unipersonalidad."""
    eventos = sorted(((v["orden"], 0 if v["acto"] in _BAJA else 1, sj, v) for sj, vs in vinculos.items() for v in vs),
                     key=lambda e: (e[0], e[1]))
    cargo_en_vigor: dict[tuple, bool] = {}
    socio_actual: dict[str, tuple] = {}  # sociedad → (orden, {sujetos})
    for orden, _, sj, v in eventos:
        if v["rol"] == "socio":
            previo = socio_actual.get(v["soc"])
            if previo is None or orden > previo[0]:
                socio_actual[v["soc"]] = (orden, {sj})
            else:
                previo[1].add(sj)
        else:
            cargo_en_vigor[(sj, v["soc"], v["cargo"])] = v["acto"] in _ALTA
    for k, fines in fin_unipersonal.items():
        if k in socio_actual and max(fines) > socio_actual[k][0]:
            socio_actual[k] = (max(fines), set())
    for sj, vs in vinculos.items():
        for v in vs:
            if v["rol"] == "socio":
                suj = socio_actual[v["soc"]][1]
                v["vigente"] = sj in suj
            else:
                v["vigente"] = v["acto"] in _ALTA and cargo_en_vigor[(sj, v["soc"], v["cargo"])]


class UF:
    def __init__(self):
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)

    def grupos(self) -> dict[str, list[str]]:
        out = defaultdict(list)
        for x in list(self.p):
            out[self.find(x)].append(x)
        return out


# ---------------------------------------------------------------- normalizaciones

def clave_expediente(e: str) -> tuple[str, bool]:
    """«SGIISE/PFot-ALM-195 AC» → («PFOT-ALM-195», True). El segundo valor indica acumulación."""
    s = e.upper().strip()
    s = re.sub(r"^(?:SGIISE|SGEE|SGE|DGPEM)/", "", s)
    ac = bool(re.search(r"(?:\s|-)?A?AC$", s)) and not s.endswith("-FASE")
    s = re.sub(r"(?:\s+|-)?A?AC$", "", s)
    s = re.sub(r"-FASE.*$", "", s)
    return s, ac


_TIPO_BESS = re.compile(r"\b(?:BESS|ALM|ALMACENAMIENTO|BATER[IÍ]AS?)\b", re.I)
_TIPO_HIB = re.compile(r"\b(?:HIBRIDACI[OÓ]N|H[IÍ]BRIDO|H[IÍ]BRIDA|HIB)\b", re.I)
_GENERICOS = re.compile(
    r"\b(?:PLANTA|PARQUE|INSTALACI[OÓ]N|SOLAR|FOTOVOLTAICA|FOTOVOLTAICO|AGROVOLTAICA|E[OÓ]LICO|E[OÓ]LICA|"
    r"TERMOSOLAR|DE|DEL|LA|EL|LOS|LAS|PSFV|PFVH|PFV|FV|PS|PE|PEOL|CSF|HSF|ISF|PFOT|BESS|ALM|MODULO|MÓDULO|"
    r"GENERACI[OÓ]N|HIBRIDACI[OÓ]N|H[IÍ]BRIDO|H[IÍ]BRIDA|HIB|AGRUPACI[OÓ]N)\b",
    re.I,
)


def clave_instalacion(nombre: str) -> str:
    """«PSFV Talayuela II» y «Talayuela II» son la misma; «BESS Gaetana» y «Gaetana» no."""
    if re.search(r",|\sy\s", nombre):  # «Carina Solar 8, Carina Solar 9 y Carina Solar 10»: varias a la vez
        return ""
    nombre = re.sub(r"\b([A-Za-z])\.\s?([A-Za-z])\.", r"\1\2", nombre)  # «P.E.» → «PE»
    tipo = "BESS " if _TIPO_BESS.search(nombre) else "HIB " if _TIPO_HIB.search(nombre) else ""
    s = so.sin_acentos(_GENERICOS.sub(" ", nombre)).upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return (tipo + s).strip() if s else ""


def _serie(e: str) -> tuple[str, int] | None:
    m = re.fullmatch(r"(.*?)(\d+)", e)
    return (m.group(1), int(m.group(2))) if m else None


def consecutivos(expedientes: list[str]) -> list[str]:
    """Expedientes de la misma serie con números seguidos («PEOL-FV-311», «-312», «-313»)."""
    por_serie = defaultdict(set)
    for e in expedientes:
        s = _serie(e)
        if s and s[0]:
            por_serie[s[0]].add(s[1])
    out = []
    for pref, nums in por_serie.items():
        nums = sorted(nums)
        racha = [nums[0]]
        for n in nums[1:]:
            if n == racha[-1] + 1:
                racha.append(n)
            else:
                if len(racha) >= 2:
                    out += [f"{pref}{x}" for x in racha]
                racha = [n]
        if len(racha) >= 2:
            out += [f"{pref}{x}" for x in racha]
    return out


# ---------------------------------------------------------------- construcción

def construir(proyectos: list[dict], inscripciones: list[dict]) -> dict:
    alias = UF()  # misma sociedad con distinto nombre
    for p in proyectos:
        for c in p.get("cambios_denominacion", []):
            if c.get("antes") and c.get("despues"):
                alias.union(so.clave(c["antes"]), so.clave(c["despues"]))
    for ins in inscripciones:
        for a in ins["actos"]:
            if a["tipo"] == "Cambio de denominación social" and a.get("clave_nueva"):
                alias.union(ins["clave"], a["clave_nueva"])

    def sid(nombre_o_clave: str, es_clave: bool = False) -> str:
        return alias.find(nombre_o_clave if es_clave else so.clave(nombre_o_clave))

    # ---- sociedades
    socs: dict[str, dict] = {}

    def soc(k: str, nombre: str = "") -> dict:
        d = socs.setdefault(k, {"id": k, "nombres": [], "nifs": [], "domicilios": [], "actos_boe": [],
                                "borme": [], "en_boe": False})
        if nombre and nombre not in d["nombres"]:
            d["nombres"].append(nombre)
        return d

    evidencias: list[dict] = []  # aristas sociedad–sociedad o sociedad–persona, con su fuente

    for p in proyectos:
        tits = [sid(t) for t in p["titulares"] if so.clave(t)]
        for t, k in zip(p["titulares"], tits):
            d = soc(k, t)
            d["en_boe"] = True
            d["actos_boe"].append(p["id"])
            for n in p.get("nifs", []):
                if n not in d["nifs"] and len(p["titulares"]) == 1:
                    d["nifs"].append(n)
            if len(p["titulares"]) == 1:
                for dom in p.get("domicilios", [])[:1]:
                    if dom not in d["domicilios"]:
                        d["domicilios"].append(dom)

    # ---- BORME: personas y sociedades relacionadas
    vinculos_persona: dict[str, list[dict]] = defaultdict(list)  # sujeto → [{soc, rol, cargo, fecha, url}]
    fin_unipersonal: dict[str, list[tuple]] = defaultdict(list)  # sociedad → [(fecha, num)] en que deja de tener socio único
    for ins in inscripciones:
        k = sid(ins["clave"], es_clave=True)
        d = soc(k, ins["sociedad"])
        url = f"https://www.boe.es/diario_borme/txt.php?id={ins['id']}"
        d["borme"].append({"fecha": ins["fecha"], "url": url, "num": ins["num"],
                           "actos": [a["tipo"] for a in ins["actos"]]})
        for a in ins["actos"]:
            if a["tipo"] == "Constitución" and a.get("domicilio") and a["domicilio"] not in d["domicilios"]:
                d["domicilios"].append(a["domicilio"])
            if a["tipo"] == "Cambio de domicilio social" and a.get("domicilio") and a["domicilio"] not in d["domicilios"]:
                d["domicilios"].append(a["domicilio"])
            grupos_suj = []
            if a["tipo"] == "Socio único" or (a["tipo"] in borme._UNIPERSONAL and a.get("sujetos")):
                # el cambio de identidad del socio único se inscribe como «Sociedad unipersonal»: es la venta de la SPV
                grupos_suj.append(("socio", "Socio único", a.get("sujetos", [])))
            for c in a.get("cargos", []):
                if c.get("clase") in ("admin", "apoderado"):
                    grupos_suj.append((c["clase"], c["cargo"], c["sujetos"]))
            for rol, cargo, sujetos in grupos_suj:
                for s in sujetos:
                    sj = s["id"] if s["tipo"] == "PF" else "PJ:" + sid(s["clave"], es_clave=True)
                    if s["tipo"] == "PJ":
                        soc(sid(s["clave"], es_clave=True), s["nombre"])
                    vinculos_persona[sj].append({"soc": k, "rol": rol, "cargo": cargo, "acto": a["tipo"],
                                                 "fecha": ins["fecha"], "orden": (ins["fecha"], ins["num"]),
                                                 "url": url})
            if a["tipo"].startswith("Pérdida del car"):
                fin_unipersonal[k].append((ins["fecha"], ins["num"]))
            if a["tipo"].startswith(("Fusión", "Escisión", "Segregación", "Cesión global")):
                # las inscripciones antiguas guardan a veces varias absorbidas en un solo nombre
                for n in [n for o in a.get("sociedades", []) for n in so.partir_denominaciones(o["nombre"])]:
                    o = {"nombre": n, "clave": so.clave(n)}
                    ko = sid(o["clave"], es_clave=True)
                    if ko and ko != k:
                        soc(ko, o["nombre"])
                        evidencias.append({"tipo": "fusion", "a": k, "b": ko, "detalle": a["tipo"],
                                           "fecha": ins["fecha"], "url": url})

    marca_vigencia(vinculos_persona, fin_unipersonal)

    # La propiedad decide el grupo. Los núcleos se forman por socio único (sociedad o persona), por la sociedad
    # matriz que administra a sus filiales y por fusión. Administradores personales, apoderados y domicilios
    # compartidos son uniones débiles: sirven para colgar de un núcleo las sociedades sin dueño societario
    # conocido, pero nunca funden dos núcleos distintos. Un administrador profesional que se sienta a la vez en
    # SPV de Enel, FRV y Arena, o dos grupos con oficina en la misma torre, no los hacen el mismo grupo.
    nucleo = UF()
    persona_fuerte: dict[str, set[str]] = defaultdict(set)  # sociedad → socios únicos y administradores PF
    debiles: list[tuple[str, str, str]] = []  # (sociedad, sociedad, motivo) para colgar sociedades sin núcleo
    fuentes: list[tuple[str, set[str]]] = []  # (fuente, sociedades que enlaza) para fundir núcleos

    # personas o sociedades que administran / apoderan / son socio único de varias sociedades. Solo unen los
    # vínculos en vigor: las SPV se venden a menudo y, sumando cinco años de historia, cada venta encadena al
    # vendedor con el comprador hasta fundir el sector entero en un solo grupo. Los ceses quedan como evidencia.
    hubs = []
    apoderados_de: dict[str, set[str]] = defaultdict(set)  # sociedad → apoderados no hub (para exigir dos)
    for vs in vinculos_persona.values():
        for v in vs:
            v["fuerza"] = fuerza(v["rol"], v["cargo"])
    # sociedades conjuntas: una AIE o UTE, o una sociedad con dos o más sociedades administradoras o socias en
    # vigor, suele ser la infraestructura común de varios promotores (subestación, línea de evacuación). Es un
    # indicio de nudo compartido, pero no hace del mismo grupo a quienes participan en ella.
    controladoras: dict[str, set[str]] = defaultdict(set)
    for sj, vs in vinculos_persona.items():
        if sj.startswith("PJ:"):
            for v in vs:
                if v["vigente"] and v["fuerza"] in ("socio", "admin", "consejo"):
                    controladoras[v["soc"]].add(sj)
    conjuntas = {k for k in socs if _CONJUNTA.search(k)} | {k for k, c in controladoras.items() if len(c) >= 2}
    for k in sorted(conjuntas):
        hubs.append({"tipo": "conjunta", "id": k, "sociedades": len(controladoras.get(k, ()))})
    for sj, vs in vinculos_persona.items():
        for v in vs:
            if v["fuerza"] != "neutro" and not v["vigente"] and v["acto"] in _ALTA:
                continue  # el nombramiento ya se ha cesado: lo documenta el propio cese
            if v["fuerza"] != "neutro" and not v["vigente"]:
                evidencias.append({"tipo": "historico", "a": sj[3:] if sj.startswith("PJ:") else sj, "b": v["soc"],
                                   "detalle": f'{v["acto"]}: {v["cargo"]}', "fecha": v["fecha"], "url": v["url"]})
        vs = [v for v in vs if v["fuerza"] != "neutro" and v["vigente"]]
        ks = sorted({v["soc"] for v in vs})
        if not ks:
            continue
        por_soc = {k: [v for v in vs if v["soc"] == k] for k in ks}
        # una sociedad que administra otra, como administradora o como consejera, la controla; una persona
        # física solo une por sí sola si es socio único o administradora
        fuertes_pj = ("socio", "admin", "consejo") if sj.startswith("PJ:") else ("socio", "admin")
        fuertes = {k for k in ks if any(v["fuerza"] in fuertes_pj for v in por_soc[k])}
        socio = {k for k in ks if any(v["fuerza"] == "socio" for v in por_soc[k])}
        if sj.startswith("PJ:"):
            # una sociedad que es socio único de otra la controla; si solo la administra, se exige que no sea
            # una gestora que administra decenas de sociedades ajenas
            # una sociedad que administra varias sin ser socia de ninguna es una gestora de servicios societarios
            gestora = len(fuertes - socio) > HUB_PJ or (not socio and len(fuertes) >= 3)
            if gestora:
                hubs.append({"tipo": "sociedad", "id": sj[3:], "sociedades": len(fuertes - socio)})
            # solo la propiedad forma núcleo; administrar sin ser socia es un vínculo débil (lo que hacen las
            # gestoras de fondos, que administran SPV ajenas)
            administradas = sorted(fuertes - socio - conjuntas) if not gestora else []
            debiles += [(sj[3:], k, f"administradora {sj[3:]}") for k in administradas]
            if administradas:
                fuentes.append((f"administradora {sj[3:]}", set(administradas) | {sj[3:]}))
            for k in ks:
                une = k not in conjuntas and k in socio
                tipo = ("control" if une else "participa" if k in conjuntas
                        else "administra" if k in administradas else "gestion")
                evidencias.append({"tipo": tipo, "a": sj[3:], "b": k,
                                   "detalle": ", ".join(sorted({v["cargo"] for v in por_soc[k]})),
                                   "fecha": max(v["fecha"] for v in por_soc[k]), "url": por_soc[k][0]["url"]})
                if une:
                    nucleo.union(sj[3:], k)
            continue
        if len(ks) < 2:
            continue
        if len(ks) > HUB_PERSONA:
            hubs.append({"tipo": "persona", "id": sj, "sociedades": len(ks)})
            continue
        fuertes = sorted(fuertes - conjuntas)
        for k in fuertes:
            persona_fuerte[k].add(sj)
        propias = sorted(socio - conjuntas)  # la misma persona es socio único: el mismo dueño
        for a, b in zip(propias, propias[1:]):
            nucleo.union(a, b)
        debiles += [(a, b, f"administrador {sj}") for a, b in zip(fuertes, fuertes[1:])]
        if len(fuertes) >= 2:
            fuentes.append((f"persona {sj}", set(fuertes)))
        for k in ks:
            if k not in fuertes and k not in conjuntas and len(ks) <= HUB_DEBIL:
                apoderados_de[k].add(sj)
            evidencias.append({"tipo": "persona", "a": sj, "b": k,
                               "detalle": ", ".join(sorted({x["cargo"] for x in por_soc[k]})),
                               "fecha": por_soc[k][0]["fecha"], "url": por_soc[k][0]["url"]})
    # apoderados: dos sociedades se unen si comparten al menos MIN_APODERADOS_COMUNES
    socs_de_apoderado: dict[str, list[str]] = defaultdict(list)
    for k, pfs in apoderados_de.items():
        for pf in pfs:
            socs_de_apoderado[pf].append(k)
    comunes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for pf, ks in socs_de_apoderado.items():
        for a, b in combinations(sorted(ks), 2):
            comunes[(a, b)].add(pf)
    # la fuente es el equipo de apoderados, no la pareja de sociedades: el mismo equipo repetido en diez
    # sociedades es un solo vínculo, no diez independientes; dos equipos que comparten a alguien, tampoco
    equipos = UF()
    for pfs in comunes.values():
        if len(pfs) >= MIN_APODERADOS_COMUNES:
            primero, *resto = sorted(pfs)
            for pf in resto:
                equipos.union(primero, pf)
    for (a, b), pfs in comunes.items():
        if len(pfs) >= MIN_APODERADOS_COMUNES:
            debiles.append((a, b, f"{len(pfs)} apoderados o consejeros comunes"))
            fuentes.append((f"apoderados {equipos.find(min(pfs))}", {a, b}))
    # un administrador que además está en un equipo de apoderados es la misma fuente que ese equipo
    fuentes = [(f"apoderados {equipos.find(f[8:])}" if f.startswith("persona ") and f[8:] in equipos.p else f, ks)
               for f, ks in fuentes]

    for e in evidencias:
        if e["tipo"] == "fusion":
            nucleo.union(e["a"], e["b"])

    # domicilio compartido (por código postal para no comparar todo con todo)
    por_cp = defaultdict(list)
    for k, d in socs.items():
        for dom in d["domicilios"]:
            partes = so.partes_domicilio(dom)
            if partes["cp"]:
                por_cp[partes["cp"]].append((k, partes, dom))
    for cp, lista in por_cp.items():
        # sin número de portal no se sabe si es el mismo edificio; el umbral se aplica a cada dirección, no al
        # código postal entero
        pares = [(a, b) for a, b in combinations(lista, 2) if a[0] != b[0] and a[1]["num"] and b[1]["num"]
                 and so.mismo_domicilio(a[1], b[1])]
        direccion = UF()
        for a, b in pares:
            direccion.union(a[0], b[0])
        tam = Counter(direccion.find(k) for k in {x[0] for a, b in pares for x in (a, b)})
        for raiz, n in tam.items():
            if n > HUB_DOMICILIO:
                dom = next(a[2] for a, b in pares if direccion.find(a[0]) == raiz)
                hubs.append({"tipo": "domicilio", "id": dom, "sociedades": n})
        por_direccion = defaultdict(set)
        for a, b in pares:
            if tam[direccion.find(a[0])] <= HUB_DOMICILIO:
                por_direccion[direccion.find(a[0])] |= {a[0], b[0]}
        fuentes += [(f"domicilio {cp} {r}", ks) for r, ks in por_direccion.items()]
        for a, b in pares:
            if tam[direccion.find(a[0])] <= HUB_DOMICILIO:  # los centros de negocios quedan solo como nodo
                debiles.append((a[0], b[0], "domicilio"))
                evidencias.append({"tipo": "domicilio", "a": a[0], "b": b[0], "detalle": a[2], "fecha": "", "url": ""})

    grupo = UF()
    for k in socs:
        grupo.union(nucleo.find(k), k)
    tam_nucleo = Counter(nucleo.find(k) for k in socs)
    anclado = {k: nucleo.find(k) for k in socs if tam_nucleo[nucleo.find(k)] >= 2}
    # dos núcleos se funden si los enlazan al menos dos fuentes independientes (dos personas, una persona y un
    # domicilio…): así Green Capital Power y sus Green Capital Development, sí; Enel y FRV por un consejero
    # profesional que se sienta en ambas, no
    enlaces: dict[tuple[str, str], set[str]] = defaultdict(set)
    for fuente, ks in fuentes:
        for x, y in combinations(sorted({anclado[k] for k in ks if k in anclado}), 2):
            enlaces[(x, y)].add(fuente)
    for (x, y), fs in enlaces.items():
        if len(fs) >= 2:
            grupo.union(x, y)
    ancla = {grupo.find(k): True for k in anclado}
    for a, b, motivo in debiles:
        ra, rb = grupo.find(a), grupo.find(b)
        if ra == rb or (ancla.get(ra) and ancla.get(rb)):  # ya juntas, o serían dos núcleos distintos
            continue
        grupo.union(a, b)
        ancla[grupo.find(a)] = ancla.get(ra) or ancla.get(rb) or False

    # ---- instalaciones
    inst: dict[str, dict] = {}
    por_acto: dict[str, list[str]] = {}
    nombres_sub: dict[str, str] = {}
    homonimas: dict[str, list[str]] = defaultdict(list)  # clave del nombre → instalaciones distintas con ese nombre
    for p in sorted(proyectos, key=lambda p: p["fecha"]):
        tits = [sid(t) for t in p["titulares"] if so.clave(t)]
        exps = [clave_expediente(e) for e in p.get("expedientes", [])]
        colectoras = [s["clave"] for s in p.get("subestaciones", []) if not s.get("red_transporte")]
        for s in p.get("subestaciones", []):
            nombres_sub.setdefault(s["clave"], f"{s['nombre']} ({s['kv']} kV)" if s.get("kv") else s["nombre"])
        munis = [m for m in p.get("municipios", []) if m not in _MUNICIPIOS_RUIDO]
        ids = []
        provs = p.get("provincias", [])
        for i in p["instalaciones"]:
            base = clave_instalacion(i["nombre"])
            if not base:
                continue
            # el mismo nombre con otro titular y en otra provincia es otra instalación («El Escudo» de Campoo y
            # «Escudo» de Huesca); sin titular ni provincia no hay con qué distinguirlas y se toma la primera
            ki = next((x for x in homonimas[base] if (not tits and not provs)
                       or set(inst[x]["titulares"]) & set(tits) or set(inst[x]["provincias"]) & set(provs)), None)
            if ki is None:
                ki = base if not homonimas[base] else f"{base} ({provs[0] if provs else len(homonimas[base]) + 1})"
                while ki in inst:
                    ki += "*"
                homonimas[base].append(ki)
            d = inst.setdefault(ki, {"id": ki, "nombres": [], "mw": None, "tecnologias": [], "titulares": [],
                                     "expedientes": [], "acumulacion": False, "colectoras": [], "municipios": [],
                                     "provincias": [], "actos": [], "primera": p["fecha"], "ultima": p["fecha"]})
            if i["nombre"] not in d["nombres"]:
                d["nombres"].append(i["nombre"])
            if i.get("mw"):
                d["mw"] = i["mw"]  # la última publicada manda (las modificaciones cambian la potencia)
            d["ultima"] = p["fecha"]
            for lst, vals in ((d["tecnologias"], p.get("tecnologias", [])), (d["titulares"], tits),
                              (d["colectoras"], colectoras), (d["municipios"], munis),
                              (d["provincias"], p.get("provincias", [])), (d["expedientes"], [e for e, _ in exps])):
                for v in vals:
                    if v not in lst:
                        lst.append(v)
            d["acumulacion"] |= any(ac for _, ac in exps) or bool(p.get("agrupacion"))
            d["actos"].append({"id": p["id"], "fecha": p["fecha"], "acto": p["acto"], "url": p["url"]})
            ids.append(ki)
        por_acto[p["id"]] = ids

    for k in list(socs):
        grupo.find(k)
    grupo_de = {k: grupo.find(k) for k in socs}

    def mismo_grupo(a: dict, b: dict) -> bool:
        ga = {grupo_de.get(t, t) for t in a["titulares"]}
        gb = {grupo_de.get(t, t) for t in b["titulares"]}
        return bool(ga & gb)

    def relacion_directa(a: dict, b: dict) -> bool:
        """Mismo titular, mismo núcleo de control o un socio único o administrador en común. El grupo por
        cadenas de terceros es demasiado amplio para juntar dos instalaciones solo por estar en el mismo término."""
        if {nucleo.find(t) for t in a["titulares"]} & {nucleo.find(t) for t in b["titulares"]}:
            return True
        pa = set().union(*(persona_fuerte.get(t, set()) for t in a["titulares"]))
        return bool(pa & set().union(*(persona_fuerte.get(t, set()) for t in b["titulares"])))

    conj = UF()
    motivos: dict[tuple[str, str], set[str]] = defaultdict(set)
    for k in inst:
        conj.find(k)
    for acto, ids in por_acto.items():
        for a, b in combinations(sorted(set(ids)), 2):
            conj.union(a, b)
            motivos[(a, b)].add("mismo anuncio")
    por_col, por_muni = defaultdict(list), defaultdict(list)
    for k, d in inst.items():
        for c in d["colectoras"]:
            por_col[c].append(k)
        for m in d["municipios"]:
            por_muni[m].append(k)
    for etiqueta, indice, relacion in (("misma subestación colectora", por_col, mismo_grupo),
                                       ("mismo municipio", por_muni, relacion_directa)):
        for _, ks in indice.items():
            for a, b in combinations(sorted(set(ks)), 2):
                if relacion(inst[a], inst[b]):
                    conj.union(a, b)
                    motivos[(a, b)].add(etiqueta)

    # ---- indicios por conjunto
    indicios = []
    for raiz, ks in conj.grupos().items():
        if len(ks) < 2:
            continue
        miembros = sorted((inst[k] for k in ks), key=lambda d: d["primera"])
        con_mw = [d for d in miembros if d["mw"]]
        mws = [d["mw"] for d in con_mw]
        suma = round(sum(mws), 3)
        senales = []
        if len(mws) >= 2 and all(m <= UMBRAL_COMPETENCIA_MW for m in mws) and suma > UMBRAL_COMPETENCIA_MW:
            senales.append({"tipo": "suma_supera_umbral", "peso": 2,
                            "texto": f"{len(mws)} instalaciones, ninguna por encima de {UMBRAL_COMPETENCIA_MW:g} MW, "
                                     f"suman {suma:g} MW"})
        bajo = [d for d in con_mw if UMBRAL_COMPETENCIA_MW * (1 - MARGEN_BAJO_UMBRAL) <= d["mw"] <= UMBRAL_COMPETENCIA_MW]
        if bajo:
            senales.append({"tipo": "bajo_umbral", "peso": 2 if len(bajo) >= 2 else 1,
                            "texto": f"{len(bajo)} con potencia justo por debajo de {UMBRAL_COMPETENCIA_MW:g} MW: "
                                     + ", ".join(f"{d['nombres'][0]} ({d['mw']:g} MW)" for d in bajo)})
        rep = Counter(round(m, 2) for m in mws).most_common(1)
        if rep and rep[0][1] >= 2 and rep[0][0] <= UMBRAL_COMPETENCIA_MW:
            senales.append({"tipo": "potencias_identicas", "peso": 1,
                            "texto": f"{rep[0][1]} instalaciones de {rep[0][0]:g} MW exactos"})
        cons = consecutivos(sorted({e for d in miembros for e in d["expedientes"]}))
        if cons:
            senales.append({"tipo": "expedientes_consecutivos", "peso": 1, "texto": "Expedientes seguidos: " + ", ".join(cons)})
        if any(d["acumulacion"] for d in miembros):
            senales.append({"tipo": "tramitacion_conjunta", "peso": 1,
                            "texto": "La Administración acumula o tramita conjuntamente estas instalaciones"})
        titulares = sorted({t for d in miembros for t in d["titulares"]})
        grupos_tit = {grupo_de.get(t, t) for t in titulares}
        if len(titulares) >= 2 and len(grupos_tit) == 1:
            senales.append({"tipo": "sociedades_vinculadas", "peso": 2,
                            "texto": f"{len(titulares)} sociedades titulares distintas con vínculos documentados entre sí"})
        cols = Counter(c for d in miembros for c in d["colectoras"])
        compartidas = [c for c, n in cols.items() if n >= 2]
        if compartidas:
            senales.append({"tipo": "evacuacion_compartida", "peso": 1,
                            "texto": "Comparten subestación: " + ", ".join(nombres_sub.get(c, c) for c in compartidas)})
        peso = sum(s["peso"] for s in senales)
        if not senales or not any(s["tipo"] in ("suma_supera_umbral", "bajo_umbral", "potencias_identicas") for s in senales):
            continue
        rels = sorted({m for (a, b), ms in motivos.items() if a in ks and b in ks for m in ms})
        indicios.append({
            "id": "C-" + re.sub(r"[^A-Z0-9]+", "-", miembros[0]["id"])[:40],
            "peso": peso, "suma_mw": suma, "instalaciones": [d["id"] for d in miembros], "titulares": titulares,
            "provincias": sorted({p for d in miembros for p in d["provincias"]}),
            "desde": miembros[0]["primera"], "hasta": max(d["ultima"] for d in miembros),
            "relacion": rels, "senales": senales,
        })
    indicios.sort(key=lambda x: (-x["peso"], -x["suma_mw"]))

    # ---- grupos empresariales publicables: los que contienen al menos una titular del BOE
    grupos_out = []
    miembros_grupo = defaultdict(list)
    for k, g in grupo_de.items():
        miembros_grupo[g].append(k)
    publicadas = set()
    for g, ks in miembros_grupo.items():
        if not any(socs[k]["en_boe"] for k in ks):
            continue
        publicadas |= set(ks)
        if len(ks) >= 2:
            grupos_out.append({"id": "G-" + g[:40].replace(" ", "-"), "sociedades": sorted(ks),
                               "en_boe": sorted(k for k in ks if socs[k]["en_boe"])})
    grupos_out.sort(key=lambda g: (-len(g["en_boe"]), -len(g["sociedades"])))
    evid_out = [e for e in evidencias if e["b"] in publicadas and (e["a"] in publicadas or e["a"].startswith("PF-"))]
    for k in publicadas:
        socs[k]["grupo"] = grupo_de[k]

    return {
        "generado": date.today().isoformat(),
        "umbral_mw": UMBRAL_COMPETENCIA_MW,
        "resumen": {"actos_boe": len(proyectos), "inscripciones_borme": len(inscripciones),
                    "sociedades": len(publicadas), "instalaciones": len(inst),
                    "grupos": len(grupos_out), "indicios": len(indicios)},
        "indicios": indicios,
        "grupos": grupos_out,
        "sociedades": {k: socs[k] for k in sorted(publicadas)},
        "instalaciones": inst,
        "evidencias": evid_out,
        "nodos_servicio": hubs,
    }


def guardar(g: dict) -> None:
    GRAFO_PATH.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")


def cargar() -> dict:
    return json.loads(GRAFO_PATH.read_text(encoding="utf-8"))
