"""Web estática (docs/index.html) a partir de data/grafo.json. Los datos van embebidos y se pintan en el navegador."""

from __future__ import annotations

import json
from datetime import date

from . import grafo
from .config import DOCS_DIR

_BOE = "https://www.boe.es/diario_boe/txt.php?id={}"


# primero lo que forma el grupo (propiedad), luego lo que solo cuelga sociedades de él, y al final lo histórico
ORDEN_EV = {"control": 0, "participa": 1, "fusion": 2, "administra": 3, "gestion": 4, "persona": 5, "domicilio": 6,
            "historico": 8}


def _datos(g: dict) -> dict:
    inst, socs = g["instalaciones"], g["sociedades"]

    def nombre_soc(k: str) -> str:
        d = socs.get(k)
        return d["nombres"][0] if d and d["nombres"] else k.title()

    indicios = []
    for i in g["indicios"]:
        indicios.append({
            "id": i["id"], "peso": i["peso"], "suma": i["suma_mw"], "provincias": i["provincias"],
            "desde": i["desde"], "hasta": i["hasta"], "relacion": i["relacion"], "senales": i["senales"],
            "titulares": [{"id": t, "nombre": nombre_soc(t), "grupo": socs.get(t, {}).get("grupo", t)} for t in i["titulares"]],
            "instalaciones": [{
                "nombre": inst[k]["nombres"][0], "mw": inst[k]["mw"], "expedientes": inst[k]["expedientes"][:4],
                "municipios": inst[k]["municipios"][:6],
                "actos": [{"id": a["id"], "fecha": a["fecha"], "acto": a["acto"]} for a in inst[k]["actos"][-4:]],
            } for k in i["instalaciones"]],
        })
    ev_por_soc: dict[str, list] = {}
    for e in g["evidencias"]:
        for lado in ("a", "b"):
            if e[lado] in socs:
                ev_por_soc.setdefault(e[lado], []).append(e)
    grupos = []
    for gr in g["grupos"]:
        ks = gr["sociedades"]
        evs, vistos, personas = [], set(), {}
        for k in ks:
            for e in ev_por_soc.get(k, []):
                clave = (e["tipo"], e["a"], e["b"], e.get("detalle", ""))
                if clave in vistos:
                    continue
                vistos.add(clave)
                if e["tipo"] == "persona":
                    # una fila por persona: «PF-… · apoderado en 5 sociedades»
                    p = personas.setdefault(e["a"], {"tipo": "persona", "a": e["a"], "b": [], "detalle": set(),
                                                     "fecha": "", "url": e.get("url", "")})
                    if nombre_soc(e["b"]) not in p["b"]:
                        p["b"].append(nombre_soc(e["b"]))
                    p["detalle"] |= {x.strip() for x in e.get("detalle", "").split(",") if x.strip()}
                    if e.get("fecha", "") > p["fecha"]:
                        p["fecha"], p["url"] = e["fecha"], e.get("url", "")
                    continue
                evs.append({"tipo": e["tipo"], "a": e["a"] if e["a"].startswith("PF-") else nombre_soc(e["a"]),
                            "b": [nombre_soc(e["b"])], "detalle": e.get("detalle", ""), "fecha": e.get("fecha", ""),
                            "url": e.get("url", "")})
        for p in personas.values():
            p["detalle"] = ", ".join(sorted(p["detalle"]))
            evs.append(p)
        grupos.append({"id": gr["id"], "sociedades": [{"nombre": nombre_soc(k), "en_boe": socs[k]["en_boe"],
                                                         "actos": len(socs[k]["actos_boe"]), "borme": len(socs[k]["borme"])}
                                                        for k in ks],
                       "evidencias": sorted(evs, key=lambda e: (ORDEN_EV.get(e["tipo"], 9), -len(e["b"]), e["a"]))[:60]})
    return {"generado": g["generado"], "umbral": g["umbral_mw"], "resumen": g["resumen"], "indicios": indicios,
            "grupos": grupos, "servicio": g["nodos_servicio"]}


def generar() -> None:
    g = grafo.cargar()
    datos = json.dumps(_datos(g), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = _PLANTILLA.replace("__DATOS__", datos).replace("__FECHA__", date.fromisoformat(g["generado"]).strftime("%d/%m/%Y"))
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")


_PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Grafo de promotores</title>
<meta name="description" content="Quién está detrás de cada proyecto energético publicado en el BOE y qué conjuntos de instalaciones muestran indicios de fraccionamiento.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600;700&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap">
<style>
:root{
  --suelo:#f6f7f4; --hoja:#ffffff; --tinta:#1b2430; --tenue:#5c6570; --filete:#d8dcd5; --filete-suave:#e8ebe5;
  --sello:#5b3f8f; --sello-suave:#ece6f5; --alto:#b3261e; --alto-suave:#fbe9e7; --medio:#9a5b00; --medio-suave:#fdf1dc;
  --barra:#8f7bb5; --umbral:#b3261e;
  --sans:"IBM Plex Sans",system-ui,"Segoe UI",Roboto,sans-serif;
  --cond:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --suelo:#13161b; --hoja:#1b1f26; --tinta:#e5e7ea; --tenue:#9aa3ad; --filete:#2e343d; --filete-suave:#242931;
    --sello:#b9a4e0; --sello-suave:#2b2438; --alto:#f28b82; --alto-suave:#3a1f1d; --medio:#f0b75e; --medio-suave:#33291a;
    --barra:#8c78b8; --umbral:#f28b82; color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --suelo:#13161b; --hoja:#1b1f26; --tinta:#e5e7ea; --tenue:#9aa3ad; --filete:#2e343d; --filete-suave:#242931;
  --sello:#b9a4e0; --sello-suave:#2b2438; --alto:#f28b82; --alto-suave:#3a1f1d; --medio:#f0b75e; --medio-suave:#33291a;
  --barra:#8c78b8; --umbral:#f28b82; color-scheme:dark;
}
*{box-sizing:border-box}
html,body{background:var(--suelo);color:var(--tinta)}
body{margin:0;font:15px/1.55 var(--sans)}
a{color:var(--sello);text-underline-offset:2px}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--sello);outline-offset:2px}
.marco{max-width:1120px;margin:0 auto;padding:0 16px}
header{border-bottom:1px solid var(--filete);background:var(--hoja)}
header .marco{padding-top:28px;padding-bottom:20px;display:grid;gap:10px}
.sello{font:600 11px/1 var(--cond);letter-spacing:.14em;text-transform:uppercase;color:var(--sello);
  border:1.5px solid var(--sello);border-radius:3px;padding:5px 8px;justify-self:start;transform:rotate(-1.2deg)}
h1{font:700 clamp(28px,4.4vw,40px)/1.08 var(--cond);margin:0;text-wrap:balance;letter-spacing:-.01em}
.entradilla{margin:0;max-width:68ch;color:var(--tenue)}
nav{display:flex;gap:18px;flex-wrap:wrap;font-size:14px}
.cifras{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--filete);
  border:1px solid var(--filete);border-radius:6px;overflow:hidden;margin:22px 0 8px}
.cifra{background:var(--hoja);padding:12px 14px}
.cifra b{display:block;font:600 26px/1.1 var(--cond);font-variant-numeric:tabular-nums}
.cifra span{font-size:13px;color:var(--tenue)}
.aviso{border-left:3px solid var(--sello);background:var(--sello-suave);padding:10px 14px;margin:18px 0;font-size:14px;max-width:80ch}
h2{font:600 22px/1.2 var(--cond);margin:36px 0 6px}
.nota{color:var(--tenue);font-size:14px;margin:0 0 14px;max-width:75ch}
.filtros{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:10px 0 16px}
.filtros input,.filtros select{font:inherit;font-size:14px;color:var(--tinta);background:var(--hoja);border:1px solid var(--filete);
  border-radius:5px;padding:7px 10px}
.filtros input{flex:1 1 240px}
.cuenta{font-size:13px;color:var(--tenue)}
.lista{display:grid;gap:14px}
.caso{background:var(--hoja);border:1px solid var(--filete);border-radius:6px;padding:14px 16px;display:grid;gap:10px}
.caso-cab{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.peso{font:600 12px/1 var(--mono);padding:4px 7px;border-radius:3px;white-space:nowrap}
.peso.alto{background:var(--alto-suave);color:var(--alto)} .peso.medio{background:var(--medio-suave);color:var(--medio)}
.peso.bajo{background:var(--filete-suave);color:var(--tenue)}
.caso h3{font:600 17px/1.3 var(--cond);margin:0;flex:1 1 300px}
.meta{font-size:13px;color:var(--tenue)}
.senales{display:flex;gap:6px;flex-wrap:wrap;margin:0;padding:0;list-style:none}
.senales li{font-size:13px;border:1px solid var(--filete);border-radius:3px;padding:3px 8px;background:var(--suelo)}
.senales li.fuerte{border-color:var(--sello);color:var(--sello)}
.tabla{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:6px 8px;border-top:1px solid var(--filete-suave);vertical-align:top}
th{font:600 11px/1.2 var(--cond);letter-spacing:.08em;text-transform:uppercase;color:var(--tenue);border-top:0}
.mw{font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}
.pot{position:relative;width:120px;height:8px;background:var(--filete-suave);border-radius:2px;margin-top:5px}
.pot i{position:absolute;left:0;top:0;bottom:0;background:var(--barra);border-radius:2px}
.pot u{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--umbral)}
.exp{font-family:var(--mono);font-size:12px}
.titulares{display:flex;gap:6px;flex-wrap:wrap}
.soc{font-size:13px;background:var(--sello-suave);color:var(--tinta);border-radius:3px;padding:2px 7px}
.grupo{background:var(--hoja);border:1px solid var(--filete);border-radius:6px}
.grupo summary{cursor:pointer;padding:12px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:baseline}
.grupo summary b{font:600 16px/1.3 var(--cond)}
.grupo .dentro{padding:0 16px 14px;display:grid;gap:10px}
.pf{font-family:var(--mono);font-size:12px;background:var(--filete-suave);padding:1px 5px;border-radius:3px}
.vacio{color:var(--tenue);font-style:italic}
footer{margin:48px 0 36px;padding-top:18px;border-top:1px solid var(--filete);font-size:13px;color:var(--tenue);display:grid;gap:8px}
footer p{margin:0;max-width:85ch}
.leyenda{display:flex;gap:14px;align-items:center;font-size:13px;color:var(--tenue);flex-wrap:wrap}
@media (prefers-reduced-motion:no-preference){.caso{transition:border-color .15s}.caso:hover{border-color:var(--barra)}}
</style>
</head>
<body>
<header><div class="marco">
  <span class="sello">BOE · BORME · actualizado __FECHA__</span>
  <h1>Grafo de promotores</h1>
  <p class="entradilla">Quién está detrás de cada proyecto energético publicado en el BOE, qué sociedades comparten administradores, apoderados, socio único o domicilio, y qué conjuntos de instalaciones muestran indicios de fraccionamiento alrededor del umbral de 50&nbsp;MW.</p>
  <nav><a href="#indicios">Indicios</a><a href="#grupos">Grupos empresariales</a><a href="#metodo">Método y privacidad</a><a href="https://github.com/Asensio94/grafo-promotores">Código y datos</a></nav>
</div></header>
<main class="marco">
  <div class="cifras" id="cifras"></div>
  <div class="aviso"><b>Indicios, no conclusiones.</b> Que varias instalaciones de un mismo grupo queden por debajo de 50&nbsp;MW y sumen más no prueba un fraccionamiento: puede responder a razones técnicas, de acceso a la red o de calendario. Cada caso enlaza a los anuncios del BOE y a las inscripciones del BORME de las que sale, para que se compruebe en la fuente.</div>

  <h2 id="indicios">Conjuntos con indicios de fraccionamiento</h2>
  <p class="nota">Instalaciones unidas por el mismo anuncio, la misma subestación colectora o el mismo municipio, con titulares del mismo grupo. La barra marca la potencia de cada una frente al umbral de <span class="mw">50 MW</span> (línea roja), por encima del cual autoriza la Administración General del Estado (art. 3.13.a de la Ley 24/2013).</p>
  <div class="filtros">
    <input id="q" type="search" placeholder="Buscar sociedad, instalación, expediente o municipio" aria-label="Buscar">
    <select id="prov" aria-label="Provincia"><option value="">Todas las provincias</option></select>
    <select id="senal" aria-label="Señal"><option value="">Cualquier señal</option></select>
    <span class="cuenta" id="cuenta"></span>
  </div>
  <div class="lista" id="lista"></div>

  <h2 id="grupos">Grupos empresariales con vínculos documentados</h2>
  <p class="nota">Sociedades titulares en el BOE unidas por el BORME (socio único, administración, apoderamiento, fusión, cambio de denominación) o por compartir domicilio en los anuncios. Las personas físicas aparecen con un seudónimo estable <span class="pf">PF-…</span>: permite ver que la misma persona actúa en varias sociedades sin publicar quién es.</p>
  <div class="lista" id="grupos-lista"></div>

  <h2 id="metodo">Método y privacidad</h2>
  <div class="nota">
    <p>Cada día se leen los sumarios del BOE (secciones III y V-B) y se extraen los actos de proyectos de generación, almacenamiento y evacuación: titular, potencia de cada instalación, subestaciones, expedientes y municipios. Del BORME (sección A) se guardan las inscripciones de sociedades del sector o ya presentes en el grafo.</p>
    <p>Señales medidas en cada conjunto: suma por encima de 50&nbsp;MW sin que ninguna instalación lo supere; potencias entre 46 y 50&nbsp;MW; potencias idénticas; expedientes con numeración seguida; tramitación conjunta o acumulación reconocida por la Administración; sociedades titulares distintas pero vinculadas; y subestación colectora compartida. Los nudos de la red de transporte no cuentan como vínculo, porque los comparten promotores ajenos entre sí.</p>
    <p>Las personas físicas nunca se publican con su nombre ni se guardan en el repositorio. Su seudónimo es un HMAC-SHA256 con una clave secreta que no se publica. No se recogen NIF de personas físicas.</p>
    <p>Cómo se forma un grupo: manda la propiedad. Un grupo nace de las declaraciones de socio único vigentes (la última inscrita, hasta que se pierde la unipersonalidad) y de las fusiones. Administradores y apoderados en común y domicilios compartidos solo cuelgan de un grupo las sociedades sin dueño conocido; para unir dos grupos con dueño distinto hacen falta al menos dos vínculos independientes. Solo cuentan los cargos vigentes: un cese o una revocación posteriores los anulan. Las agrupaciones de interés económico, las UTE y las sociedades con varios socios de control son infraestructura compartida y no unen a sus socios. Las gestoras que administran decenas de sociedades ajenas, las personas con más de 40 sociedades y los domicilios con más de 8 se tratan como servicio profesional.</p>
    <p>Límites: la extracción es automática y puede fallar con redacciones atípicas; el BORME no tiene búsqueda por nombre, así que un vínculo anterior al periodo leído no aparece. Si detectas un error, abre una incidencia en el repositorio.</p>
  </div>
</main>
<footer class="marco">
  <p>Fuentes: Boletín Oficial del Estado y Boletín Oficial del Registro Mercantil (Agencia Estatal BOE, datos abiertos). Código con licencia MIT.</p>
  <p id="servicio"></p>
</footer>
<script id="datos" type="application/json">__DATOS__</script>
<script>
(function(){
  var D = JSON.parse(document.getElementById("datos").textContent);
  var U = D.umbral, BOE = "https://www.boe.es/diario_boe/txt.php?id=";
  var NOMBRES = {suma_supera_umbral:"Suma por encima del umbral", bajo_umbral:"Justo por debajo de 50 MW",
    potencias_identicas:"Potencias idénticas", expedientes_consecutivos:"Expedientes seguidos",
    tramitacion_conjunta:"Tramitación conjunta", sociedades_vinculadas:"Sociedades vinculadas",
    evacuacion_compartida:"Evacuación compartida"};
  var ACTOS = {informacion_publica:"información pública", autorizacion:"autorización", utilidad_publica:"utilidad pública",
    evaluacion_ambiental:"evaluación ambiental", desistimiento:"desistimiento", desestimacion:"desestimación",
    correccion:"corrección", caducidad:"caducidad", expropiacion:"expropiación", otro:"otro"};
  var TIPO_EV = {persona:"Persona en común", control:"Socio único", participa:"Participación sin control exclusivo",
    administra:"Administra la sociedad", gestion:"Gestora profesional", domicilio:"Domicilio compartido",
    fusion:"Fusión o escisión", historico:"Vínculo ya extinguido"};
  function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]})}
  function mw(x){return x==null?"—":x.toLocaleString("es-ES",{maximumFractionDigits:3})+" MW"}
  function fecha(s){if(!s)return"";var p=s.split("-");return p[2]+"/"+p[1]+"/"+p[0]}
  function nivel(p){return p>=7?"alto":p>=4?"medio":"bajo"}

  var R = D.resumen;
  document.getElementById("cifras").innerHTML = [
    [R.indicios,"conjuntos con indicios"],[R.grupos,"grupos empresariales"],[R.instalaciones,"instalaciones"],
    [R.sociedades,"sociedades"],[R.actos_boe,"actos del BOE"],[R.inscripciones_borme,"inscripciones del BORME"]
  ].map(function(c){return '<div class="cifra"><b>'+c[0].toLocaleString("es-ES")+'</b><span>'+c[1]+'</span></div>'}).join("");

  var provs = {}, senales = {};
  D.indicios.forEach(function(i){
    i.provincias.forEach(function(p){provs[p]=1});
    i.senales.forEach(function(s){senales[s.tipo]=1});
    i._texto = (i.titulares.map(function(t){return t.nombre}).join(" ")+" "+i.instalaciones.map(function(x){
      return x.nombre+" "+x.expedientes.join(" ")+" "+x.municipios.join(" ")}).join(" ")+" "+i.provincias.join(" ")).toLowerCase();
  });
  var sp = document.getElementById("prov"), ss = document.getElementById("senal");
  Object.keys(provs).sort().forEach(function(p){sp.insertAdjacentHTML("beforeend",'<option>'+esc(p)+'</option>')});
  Object.keys(NOMBRES).filter(function(k){return senales[k]}).forEach(function(k){ss.insertAdjacentHTML("beforeend",'<option value="'+k+'">'+NOMBRES[k]+'</option>')});

  function barra(x){
    if(x==null) return "";
    var tope = Math.max(U*1.6, x), w = Math.min(100, x/tope*100), u = U/tope*100;
    return '<div class="pot" aria-hidden="true"><i style="width:'+w.toFixed(1)+'%"></i><u style="left:'+u.toFixed(1)+'%"></u></div>';
  }
  function caso(i){
    var fuertes = {suma_supera_umbral:1,bajo_umbral:1,sociedades_vinculadas:1,tramitacion_conjunta:1};
    var filas = i.instalaciones.map(function(x){
      var actos = x.actos.map(function(a){return '<a href="'+BOE+esc(a.id)+'">'+fecha(a.fecha)+'</a> <span class="meta">'+(ACTOS[a.acto]||a.acto)+'</span>'}).join("<br>");
      return '<tr><td>'+esc(x.nombre)+'<div class="meta">'+esc(x.municipios.join(", "))+'</div></td><td class="mw">'+mw(x.mw)+barra(x.mw)+
        '</td><td class="exp">'+esc(x.expedientes.join(" · "))+'</td><td>'+actos+'</td></tr>';
    }).join("");
    return '<article class="caso" id="'+esc(i.id)+'"><div class="caso-cab"><span class="peso '+nivel(i.peso)+'" title="Suma de pesos de las señales">peso '+i.peso+'</span>'+
      '<h3>'+esc(i.instalaciones.map(function(x){return x.nombre}).slice(0,4).join(" · "))+(i.instalaciones.length>4?' · …':'')+'</h3>'+
      '<span class="meta">'+esc(i.provincias.join(", "))+' · suma '+mw(i.suma)+' · '+fecha(i.desde)+(i.hasta!==i.desde?' – '+fecha(i.hasta):'')+'</span></div>'+
      '<div class="titulares">'+i.titulares.map(function(t){return '<span class="soc">'+esc(t.nombre)+'</span>'}).join("")+'</div>'+
      '<ul class="senales">'+i.senales.map(function(s){return '<li class="'+(fuertes[s.tipo]?'fuerte':'')+'" title="'+esc(NOMBRES[s.tipo]||s.tipo)+'">'+esc(s.texto)+'</li>'}).join("")+'</ul>'+
      '<div class="meta">Unidas por: '+esc(i.relacion.join(", "))+'</div>'+
      '<div class="tabla"><table><thead><tr><th>Instalación</th><th>Potencia</th><th>Expedientes</th><th>Actos en el BOE</th></tr></thead><tbody>'+filas+'</tbody></table></div></article>';
  }
  var lista = document.getElementById("lista"), cuenta = document.getElementById("cuenta"), q = document.getElementById("q");
  function pinta(){
    var t = q.value.trim().toLowerCase(), p = sp.value, s = ss.value;
    var sel = D.indicios.filter(function(i){
      return (!t || i._texto.indexOf(t)>=0) && (!p || i.provincias.indexOf(p)>=0) && (!s || i.senales.some(function(x){return x.tipo===s}));
    });
    cuenta.textContent = sel.length+" de "+D.indicios.length;
    lista.innerHTML = sel.length ? sel.slice(0,150).map(caso).join("") + (sel.length>150?'<p class="meta">Se muestran los 150 de más peso; afina la búsqueda para ver el resto.</p>':'')
      : '<p class="vacio">Ningún conjunto coincide con el filtro.</p>';
  }
  [q,sp,ss].forEach(function(el){el.addEventListener("input",pinta)});
  pinta();

  document.getElementById("grupos-lista").innerHTML = D.grupos.length ? D.grupos.map(function(g){
    var boe = g.sociedades.filter(function(s){return s.en_boe});
    var ev = g.evidencias.map(function(e){
      var a = /^PF-/.test(e.a) ? '<span class="pf">'+esc(e.a)+'</span>' : esc(e.a);
      var fuente = e.url ? ' · <a href="'+esc(e.url)+'">'+(e.url.indexOf("borme")>=0?"BORME":"fuente")+(e.fecha?' '+fecha(e.fecha):'')+'</a>' : '';
      var socs = e.b.length > 1 ? e.b.length+' sociedades: '+esc(e.b.join(" · ")) : esc(e.b[0]);
      return '<tr><td>'+(TIPO_EV[e.tipo]||e.tipo)+'</td><td>'+a+'</td><td>'+socs+'</td><td>'+esc(e.detalle)+fuente+'</td></tr>';
    }).join("");
    return '<details class="grupo"><summary><b>'+esc(boe.slice(0,3).map(function(s){return s.nombre}).join(" · "))+(boe.length>3?' · …':'')+'</b>'+
      '<span class="meta">'+g.sociedades.length+' sociedades, '+boe.length+' titulares en el BOE</span></summary><div class="dentro">'+
      '<div class="titulares">'+g.sociedades.map(function(s){return '<span class="soc" title="'+s.actos+' actos BOE, '+s.borme+' inscripciones BORME">'+esc(s.nombre)+'</span>'}).join("")+'</div>'+
      (ev ? '<div class="tabla"><table><thead><tr><th>Vínculo</th><th>Quién</th><th>Con</th><th>Detalle y última fuente</th></tr></thead><tbody>'+ev+'</tbody></table></div>' : '')+
      '</div></details>';
  }).join("") : '<p class="vacio">Todavía no hay grupos con más de una sociedad.</p>';

  if (D.servicio && D.servicio.length) document.getElementById("servicio").textContent =
    (function(){var n={};D.servicio.forEach(function(h){n[h.tipo]=(n[h.tipo]||0)+1});
      return "No unen grupos: "+[[n.persona,"personas con cargos en muchas sociedades"],[n.sociedad,"gestoras profesionales"],
        [n.domicilio,"domicilios de despacho"],[n.conjunta,"sociedades conjuntas (AIE, UTE o varios socios de control)"]]
        .filter(function(x){return x[0]}).map(function(x){return x[0].toLocaleString("es-ES")+" "+x[1]}).join(", ")+".";})();
})();
</script>
</body>
</html>
"""
