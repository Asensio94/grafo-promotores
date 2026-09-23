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

from . import sociedades as so
from .config import GRAFO_PATH, MARGEN_BAJO_UMBRAL, UMBRAL_COMPETENCIA_MW

# Un apoderado o un domicilio compartido por más sociedades que esto suele ser un despacho o un centro de
# negocios: se publica, pero no se usa para unir grupos.
HUB_PERSONA = 40
HUB_DOMICILIO = 25
_MUNICIPIOS_RUIDO = {"Polígono", "Parcela", "Paraje"}


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
            if a["tipo"] == "Socio único":
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
                                                 "fecha": ins["fecha"], "url": url})
            if a["tipo"].startswith(("Fusión", "Escisión", "Segregación", "Cesión global")):
                for o in a.get("sociedades", []):
                    ko = sid(o["clave"], es_clave=True)
                    if ko and ko != k:
                        soc(ko, o["nombre"])
                        evidencias.append({"tipo": "fusion", "a": k, "b": ko, "detalle": a["tipo"],
                                           "fecha": ins["fecha"], "url": url})

    grupo = UF()
    for k in socs:
        grupo.find(k)

    # personas o sociedades que administran / apoderan / son socio único de varias sociedades
    hubs = []
    for sj, vs in vinculos_persona.items():
        ks = sorted({v["soc"] for v in vs})
        if sj.startswith("PJ:"):
            # una persona jurídica que administra o es socio único de otra: control directo
            for k in ks:
                evidencias.append({"tipo": "control", "a": sj[3:], "b": k,
                                   "detalle": ", ".join(sorted({v["cargo"] for v in vs if v["soc"] == k})),
                                   "fecha": max(v["fecha"] for v in vs if v["soc"] == k),
                                   "url": next(v["url"] for v in vs if v["soc"] == k)})
                grupo.union(sj[3:], k)
            continue
        if len(ks) < 2:
            continue
        if len(ks) > HUB_PERSONA:
            hubs.append({"tipo": "persona", "id": sj, "sociedades": len(ks)})
            continue
        for a, b in zip(ks, ks[1:]):
            grupo.union(a, b)
        for k in ks:
            v = next(v for v in vs if v["soc"] == k)
            evidencias.append({"tipo": "persona", "a": sj, "b": k,
                               "detalle": ", ".join(sorted({x["cargo"] for x in vs if x["soc"] == k})),
                               "fecha": v["fecha"], "url": v["url"]})

    for e in evidencias:
        if e["tipo"] == "fusion":
            grupo.union(e["a"], e["b"])

    # domicilio compartido (por código postal para no comparar todo con todo)
    por_cp = defaultdict(list)
    for k, d in socs.items():
        for dom in d["domicilios"]:
            partes = so.partes_domicilio(dom)
            if partes["cp"]:
                por_cp[partes["cp"]].append((k, partes, dom))
    for cp, lista in por_cp.items():
        pares = [(a, b) for a, b in combinations(lista, 2) if a[0] != b[0] and so.mismo_domicilio(a[1], b[1])]
        implicadas = {x for a, b in pares for x in (a[0], b[0])}
        if len(implicadas) > HUB_DOMICILIO:
            hubs.append({"tipo": "domicilio", "id": lista[0][2], "sociedades": len(implicadas)})
            continue
        for a, b in pares:
            grupo.union(a[0], b[0])
            evidencias.append({"tipo": "domicilio", "a": a[0], "b": b[0], "detalle": a[2], "fecha": "", "url": ""})

    # ---- instalaciones
    inst: dict[str, dict] = {}
    por_acto: dict[str, list[str]] = {}
    nombres_sub: dict[str, str] = {}
    for p in sorted(proyectos, key=lambda p: p["fecha"]):
        tits = [sid(t) for t in p["titulares"] if so.clave(t)]
        exps = [clave_expediente(e) for e in p.get("expedientes", [])]
        colectoras = [s["clave"] for s in p.get("subestaciones", []) if not s.get("red_transporte")]
        for s in p.get("subestaciones", []):
            nombres_sub.setdefault(s["clave"], f"{s['nombre']} ({s['kv']} kV)" if s.get("kv") else s["nombre"])
        munis = [m for m in p.get("municipios", []) if m not in _MUNICIPIOS_RUIDO]
        ids = []
        for i in p["instalaciones"]:
            ki = clave_instalacion(i["nombre"])
            if not ki:
                continue
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
    for etiqueta, indice in (("misma subestación colectora", por_col), ("mismo municipio", por_muni)):
        for _, ks in indice.items():
            for a, b in combinations(sorted(set(ks)), 2):
                if mismo_grupo(inst[a], inst[b]):
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
