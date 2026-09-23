# Grafo de promotores

Quién está detrás de cada proyecto energético publicado en el BOE, y qué conjuntos de instalaciones
muestran **indicios de fraccionamiento** alrededor del umbral de 50 MW.

Web: <https://asensio94.github.io/grafo-promotores/> · se rehace cada día con GitHub Actions.

## Qué hace

1. **BOE** (secciones III y V-B). Extrae de cada anuncio o resolución de un proyecto de generación, almacenamiento
   o evacuación: sociedad titular, potencia de cada instalación, subestaciones (distinguiendo colectoras de nudos de
   la red de transporte), expedientes, municipios, domicilio del promotor, cambios de denominación y frases en las que
   la Administración reconoce una tramitación conjunta o una acumulación.
2. **BORME** (sección A). Lee cada día todas las inscripciones y guarda las de sociedades del sector o ya presentes
   en el grafo: constitución, socio único, nombramientos, ceses y revocaciones de administradores y apoderados,
   fusiones y cambios de denominación o de domicilio.
3. **Grafo**. Une sociedades en *grupos empresariales* cuando comparten socio único, administrador o apoderado,
   domicilio, o se han fusionado. Une instalaciones en *conjuntos* cuando aparecen en el mismo anuncio, evacuan por
   la misma subestación colectora o están en el mismo municipio con titulares del mismo grupo.
4. **Indicios**. En cada conjunto mide:

| Señal | Peso | Qué mide |
|---|---|---|
| Suma por encima del umbral | 2 | Ninguna instalación supera 50 MW, pero la suma sí |
| Justo por debajo de 50 MW | 1–2 | Potencias entre 46 y 50 MW (el 92 % del umbral) |
| Potencias idénticas | 1 | Dos o más instalaciones con exactamente la misma potencia |
| Expedientes seguidos | 1 | Numeración consecutiva en la misma serie (`PEOL-FV-311`, `-312`…) |
| Tramitación conjunta | 1 | Acumulación (`… AC`) o frases de tramitación conjunta en el propio acto |
| Sociedades vinculadas | 2 | Titulares distintas con vínculos documentados entre sí |
| Evacuación compartida | 1 | La misma subestación colectora; los nudos de REE no cuentan |

Son **indicios a revisar, no conclusiones**. Trocear un proyecto puede tener razones técnicas, de acceso a la red o de
calendario. Cada indicio enlaza a los actos del BOE y a las inscripciones del BORME de las que sale.

## Umbrales

- **50 MW**. Por encima, la autorización corresponde a la Administración General del Estado
  (art. 3.13.a de la Ley 24/2013, del Sector Eléctrico); hasta 50 MW, a la comunidad autónoma.
- La evaluación de los efectos acumulativos y sinérgicos es exigible en la evaluación ambiental (Ley 21/2013, anexo VI).
  Un conjunto con indicios es un buen punto de partida para pedirla en una alegación.

## Privacidad

- **Personas físicas**: nunca se guardan ni se publican con su nombre. Se sustituyen por un seudónimo estable
  `PF-xxxxxxxxxx` (HMAC-SHA256 con una clave secreta que no está en el repositorio: `GRAFO_SAL` en Actions,
  `data/.sal` en local). Así se ve que la misma persona actúa en varias sociedades sin publicar quién es.
  Los nombres que aparecen en texto libre del BORME («Otros conceptos») también se seudonimizan.
- No se recogen NIF de personas físicas ni domicilios particulares; solo NIF y domicilios sociales de personas
  jurídicas publicados en el BOE.
- Los apoderados que comparten más de 40 sociedades y los domicilios que comparten más de 25 se tratan como
  despachos o centros de negocios: se listan, pero no unen grupos.
- Si apareces en el grafo y crees que hay un error, abre una incidencia.

## Uso

```bash
pip install -r requirements.txt
python -m promotores.cli boe --desde 2026-09-01      # anuncios del BOE
python -m promotores.cli borme --desde 2026-09-01    # inscripciones del BORME (≈11 s por día)
python -m promotores.cli grafo                       # data/grafo.json
python -m promotores.cli web                         # docs/index.html
python -m promotores.cli diario                      # todo lo anterior para la última semana
```

`data/objetivo.txt` admite sociedades a seguir en el BORME aunque no aparezcan en el BOE (por ejemplo, promotores
de parques autonómicos).

## Datos

- `data/proyectos/AAAA.jsonl`: un acto del BOE por línea.
- `data/borme/AAAA-MM.jsonl`: inscripciones del sector, ya seudonimizadas. `data/borme/dias.txt`: días leídos.
- `data/grafo.json`: sociedades, instalaciones, grupos, evidencias e indicios.

Fuentes: Agencia Estatal BOE, [datos abiertos](https://www.boe.es/datosabiertos/). Código con licencia MIT.

## Límites

La extracción es automática y puede fallar con redacciones atípicas. El BORME no tiene búsqueda por denominación, así
que solo se ven los vínculos inscritos en el periodo leído. Los proyectos autonómicos (hasta 50 MW) solo aparecen si
se publican en el BOE; los boletines autonómicos están en el
[observatorio de alegaciones](https://github.com/Asensio94/observatorio-alegaciones).
