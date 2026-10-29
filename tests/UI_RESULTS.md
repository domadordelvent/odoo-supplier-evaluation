# Ajustos finals de presentació — 2026-10-30

Validats sobre una còpia independent de `supplier_evaluation_demo`, sense
actualitzar ni reiniciar cap servei permanent. Es manté la versió 18.0.1.3.0.

- Formulari primari derivat `view_supplier_otd_form`, vinculat exclusivament
  a l'acció d'avaluació: oculta el botó estàndard On-time Rate. El formulari
  estàndard el conserva, comprovat tant amb ORM com amb Chromium.
- Barra nativa ampliada amb una sola regla SCSS, limitada a
  `.o_supplier_otd_progress .o_progress`: `flex: 1`. El component natiu
  fixa la pista a 100 px; la prova de navegador mesura 398,5 px amb una
  finestra de 1440 px. No hi ha JavaScript personalitzat.
- Detall existent verificat: comanda, producte, termini congelat, data de
  finalització i resultat. Supplier 05: 20 línies, 10 puntuals, 10 tardanes,
  50 %. Les cinc columnes contenen dades a totes les files.
- **135 proves d'integració superades** (133 anteriors + 2 noves),
  **43 proves locals** i Chromium sobre els deu proveïdors, sense errors
  JavaScript. Es mantenen les proves de permisos i multicompany.
- Les dues bases permanents són lògicament idèntiques abans/després:
  cap canvi de taula, seqüència ni esquema als dumps comparats. Les vuit
  taules de negoci, incloses les captures congelades, coincideixen també
  exactament amb la còpia temporal després de totes les proves.
- S'han repetit els passos inicials de preparació perquè PostgreSQL i el
  servidor web temporals encara no estaven preparats en el primer intent.
  La restauració, actualització i validació final han acabat correctament.
- Entorn temporal aturat, conservant base, volum i evidències a
  `backups/otd-ui-20261029T231528Z/`: `final-verification.json`, hashes,
  logs i captures `supplier-05-form.png`, `supplier-05-lines.png` i
  `supplier-05-standard-form.png`. Tot queda exclòs de Git.

No s'ha modificat la lògica de negoci ni executat el generador. Cap commit
ni publicació. Els ajustos estan pendents d'activació autoritzada.

---

# Auditoria i validació de la interfície OTD

Data: 2026-10-29. Codi `18.0.1.3.0`, Odoo 18 Community `18.0-20260305`.

## Auditoria i decisió

La fitxa existent només mostrava camps i text; no hi havia una acció pròpia
de llista ni navegació a les línies del percentatge. Els totals de
`res.partner` són calculats no emmagatzemats i depenen d'usuari i empreses;
Odoo no els ordenava ni filtrava nativament.

S'ha creat una acció pròpia amb llista, cerca i formulari estàndard de
proveïdor, i vistes de detall de les captures de compra. Les vistes primàries
noves tenen prioritat 99 i es vinculen explícitament a les accions noves;
no substitueixen els contactes ni els menús estàndard.

El domini `_supplier_otd_source()` és compartit per còmput, cerca, ordenació
i detall. La consulta d'ordenació utilitza una subconsulta construïda per
l'ORM amb les regles d'accés del comprador, sense sudo i limitada a les
empreses seleccionades autoritzades. Els percentatges es comparen a dos
decimals, igual que el camp original. L'ordenació és SQL, abans del límit i
l'offset, sense carregar tots els proveïdors per ordenar-los en Python.

Odoo 18 obté les metadades dels camps sense garantir el context de l'acció.
Per això els nostres camps admeten ordenació també en aquesta consulta de
metadades, sense alterar l'ordre per defecte ni les vistes de Contactes.
La validació amb navegador ha comprovat que la capçalera OTD és clicable.

## Proves automatitzades

- **133 proves d'integració superades**, en 17,726 segons: 118 preexistents
  i **15 noves UI**. Zero errors i zero fallades al resultat final.
- Els 15 casos UI s'han reexecutat sobre la maquetació final: **15/15**, en
  2,854 segons. No es compten com a casos nous addicionals.
- **43 proves locals superades**, sense accés a bases de dades.
- Actualització i compilació dels XML correctes només a la base temporal.

Els casos nous cobreixen ascendent/descendent, ordre estable, paginació,
metadades d'ordenació, `web_search_read`, filtres, 0 % contra absència de dades,
llindar exacte del 50 %, permisos i sudo, regles de registre de línies i
proveïdors, multicompany, dominis del botó, contextos de cerca, vistes de
només lectura i preservació de captures històriques.

La primera execució va detectar una preparació incorrecta d'una prova:
canviar el proveïdor recomputa `date_planned` a Odoo. S'ha establert la
promesa en esborrany després del canvi, i corregit l'assert que distingia
0 % de 100 %. No s'ha modificat cap càlcul OTD per superar aquesta prova.

## Navegador amb els deu proveïdors

Prova executable opcional: `tests/ui_supplier_otd.py`. Playwright és una
eina de prova fora del mòdul, no una dependència ni un asset d'Odoo.

S'han comprovat amb Chromium:

- Deu files amb els OTD 10 %, 20 %, …, 100 %, ordre descendent inicial i
  canvi real a ascendent/descendent clicant la capçalera.
- Les deu fitxes: percentatge, vint línies avaluades i barra nativa visible.
- Filtre «OTD inferior al 50 %»: exactament quatre files (40, 30, 20 i 10 %).
- Botó de justificació: vint línies; per al proveïdor del 40 %, vuit puntuals
  i dotze tardanes, igual que els comptadors de la fitxa.
- Una fitxa temporal sense avaluació: «Sense dades», al final de la llista.
  La fitxa creada per provar-ho s'ha eliminat amb ORM a la mateixa còpia.
- Zero errors JavaScript de la pàgina.

La prova espera la resposta `web_read` i el renderitzat d'Owl, en lloc
*d'esperar networkidle*, incompatible amb el long polling d'Odoo. El menú
natiu de filtres es tanca abans de navegar a la fitxa.

Captures locals (només dades fictícies):

- `supplier-otd-list.png`: llista, percentatges i comptadors.
- `supplier-otd-form.png`: fitxa, percentatge gran i tres indicadors.
- `supplier-otd-filter.png`: filtre inferior al 50 %.
- `supplier-otd-lines.png`: línies que justifiquen el percentatge.

Els fitxers i registres són a `backups/otd-ui-*`, exclosos de Git.

## Repetir la prova

Primer restaura una còpia de demostració a un PostgreSQL separat, amb un
filestore propi, i un nom `supplier_evaluation_otd_*`. Actualitza **només la
còpia** a `18.0.1.3.0`, amb cron desactivat. No tornis a generar dades: la
còpia ja conté el conjunt validat.

Des d'un shell Odoo connectat a la còpia, passa `tests/odoo_integration.py`
per stdin. El llançador rebutja les dues bases permanents i reverteix els
registres de les proves.

Per al navegador, prepara un entorn Python separat amb Playwright i Chromium.
Amb `OTD_UI_PASSWORD` definit de manera privada i el servidor temporal al
port local 8075:

```sh
python tests/ui_supplier_otd.py \
  --base-url http://127.0.0.1:8075 \
  --database supplier_evaluation_otd_copia \
  --login demo_admin \
  --output-dir backups/otd-ui-captures
```

Pots indicar `--browser-executable` si ja disposes d'un Chromium compatible.
El script rebutja noms de bases permanents i comprova la base autenticada
abans de crear la fitxa temporal de prova.

## Conservació i limitacions

No s'ha actualitzat ni reiniciat cap de les dues bases permanents per
aquesta tasca. Continuen a `18.0.1.2.0` i els esquemes SQL són idèntics.

Els dumps complets no són idèntics als inicials perquè hi ha hagut activitat
web concurrent. A l'original només canvien `bus_bus`, `bus_presence` i
`res_device_log`; a la demo hi ha canvis de presència/notificacions,
`ir_config_parameter`, `ir_default` i `res_config_settings`. Els registres
HTTP de la demo mostren el desament d'ajustos amb
`res.config.settings.execute`. També avancen les seqüències tècniques
corresponents. No s'ha revertit aquesta activitat.

La comparació de totes les taules dels dumps confirma que les taules de
negoci no han canviat. A més, proveïdors, 100 comandes, 200 línies, 150
recepcions, 300 moviments i detalls, 300 revisions i 100 confirmacions de la
demo coincideixen exactament amb la còpia utilitzada per les proves UI.
No es reivindica una igualtat del dump complet de cap base permanent.

No s'han fet commits ni publicat res a GitHub. No hi ha proves de càrrega a
gran escala ni una prova de navegador mòbil. Els canvis són codi i vistes
pendents d'activació autoritzada a qualsevol base permanent.
