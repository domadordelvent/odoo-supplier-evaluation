> La interfície utilitza ara textos originals en anglès i traduccions estàndard
> en català (`i18n/ca.po`). Les rutes catalanes d’aquest document es conserven
> com a referència; vegeu [idiomes i validació](../../docs/I18N.md).

# Documentació tècnica del mòdul

Project overview and installation in English: [main README](../../README.md).
This document retains the detailed Catalan implementation notes.

# Supplier Evaluation

Mòdul per a Odoo 18 Community, versió de codi `18.0.1.3.0`.
Dependències: `base`, `purchase`, `stock`, `purchase_stock`.

**Estat: nova interfície OTD implementada i validada en una còpia temporal:
133 proves d'integració superades i comprovació amb Chromium sobre els deu
proveïdors ficticis.**
Les bases permanents es mantenen a `18.0.1.2.0`; la interfície `18.0.1.3.0`
encara no s'hi ha activat. No s'ha fet cap commit d'aquesta fase.
Els resultats i les limitacions es documenten a `tests/UI_RESULTS.md`.

## Objectiu i separació de mètriques

Avaluar cada recepció individual, incloses les recepcions parcials, amb una
tolerància de 24 hores. La puntualitat i la fiabilitat són independents:

- Puntualitat: captura de les dates de cada moviment rebut i classificació
  immutable de la recepció. Si algun moviment rebut arriba tard, preval
  `late`; només s'assigna `on_time` si tots tenen dades suficients i són puntuals.
- Fiabilitat: conservació del compromís original conegut i historial de les
  transicions posteriors de data, sense puntuacions globals.

## Interfície OTD (versió 18.0.1.3.0)

La nova ruta és **Purchase → Avaluació de proveïdors**. És una acció pròpia:
no canvia les accions, el Kanban ni les llistes estàndard de Contactes.
La llista conté nom, OTD, línies avaluades, puntuals i tardanes. El percentatge
és una etiqueta nativa amb colors: menys de 50 % vermell, de 50 a menys de
80 % ambre i de 80 a 100 % verd. Sense resultats es mostra **Sense dades**,
sense classificar el proveïdor com a 0 %.

La columna OTD ordena numèricament en ascendent/descendent, amb els casos
sense dades al final i abans d'aplicar la paginació. El filtre **OTD inferior
al 50 %** exclou els casos sense dades. També hi ha filtres **Amb dades** i
**Sense dades**.

Clicant el proveïdor s'obre el formulari derivat d'avaluació. La pestanya **Avaluació OTD**
mostra el percentatge gran, un `progressbar` natiu i tres comptadors compactes.
**Veure línies avaluades** obre una llista i formulari de consulta de les
captures que justifiquen el resultat. No hi ha gràfics ni JavaScript personalitzats. Una única regla SCSS,
limitada a la pista de progrés OTD, amplia la barra nativa; no afegeix
dependències externes.

Els camps calculats existents i la seva elegibilitat s'han reutilitzat en un
únic domini compartit. Per ordenar camps no emmagatzemats es fa una consulta
agregada derivada de la selecció ORM de línies autoritzades. No es crea una
taula d'estadístiques ni es guarden percentatges dependents d'empresa.
L'ordenació només afegeix capacitat als nostres camps OTD; l'ordre per defecte
de Contactes es conserva. Aquesta capacitat no depèn del context de l'acció,
perquè Odoo 18 no el garanteix en les metadades de `get_views`.

Els permisos i regles de compres, la selecció d'empreses i el proveïdor
capturat continuen limitant comptadors, filtres, ordenació i línies de detall.
El detall és de només lectura. Les captures congelades no s'han modificat.

La instal·lació estàndard i els requisits independents de Docker es descriuen
a [la guia d'instal·lació](../../docs/INSTALLATION.md). El desplegament de cada
entorn és independent del codi del repositori.

## OTD per línia completada

La nova mètrica és independent de la classificació existent de recepcions.
Cada línia genera una sola captura en passar de quantitat rebuda inferior a
la demanada a quantitat rebuda suficient durant la validació d'una recepció.
S'utilitza `qty_received` d'Odoo, amb les conversions d'unitats i devolucions
que aplica el model estàndard, i la precisió de la unitat de la línia.

- Referència: última renegociació confirmada de la línia i del proveïdor actual
  existent abans de validar i amb `confirmed_at` no posterior a la finalització. Sense confirmació vàlida,
  s'utilitza el compromís original conegut del mateix proveïdor.
- `date_planned` no intervé en l'OTD. Una revisió tècnica no confirmada no
  modifica el termini de referència.
- Finalització: última data immutable capturada dels moviments rebuts de la
  línia. No es llegeixen `move.date` ni `picking.date_done` com a substituts.
- Puntual si la finalització és anterior o igual al termini més 24 hores;
  un segon més tard ja és retard. Les dates es comparen en UTC.
- Abans de validar es fixa, sota bloqueig, quines confirmacions ja existeixen.
  Això admet un acord anterior dins del mateix segon sense admetre acords
  creats després de la recepció; les dates tenen precisió de segons.

La captura conserva resultat, termini, confirmació utilitzada (si existeix),
data de finalització, instant de captura, proveïdor, quantitats demanada i
rebuda i unitat. Tots els camps són de només lectura, `copy=False` i protegits
al servidor contra creació/escriptura pública, inclosos `sudo()` i valors de
context. Les línies capturades no es poden eliminar ordinàriament.

Una parcial no genera resultat. Les sobrerecepcions compten una vegada.
Una devolució anterior a la primera finalització que redueix `qty_received`
impedeix completar fins a rebre la quantitat que falta. Una devolució,
confirmació, canvi de dates o canvi de quantitat posterior no substitueix
l'observació congelada: no és un indicador de saldo net recalculat.

S'exclouen serveis, seccions/notes, quantitats no positives, línies cancel·lades
i recepcions que no passen pel flux d'entrada física de proveïdor. Cancel·lar
un backorder no completa una línia parcial. Reduir la quantitat d'una línia
ja rebuda no genera retroactivament una captura.

Les línies ja completades abans d'activar aquesta versió no es reomplen.
Una línia parcial antiga que es completa ara però té recepcions sense captura,
o un termini original desconegut sense acord vàlid, es marca `unknown`;
no es presenta com a puntual. Buit significa encara no avaluada, mentre que
`unknown` significa completada sense evidència suficient. L'agregat per
proveïdor només inclou resultats coneguts, com es descriu a continuació.

Les captures històriques de `stock.move` i `stock.picking` continuen intactes,
amb la seva semàntica anterior. Per això el resultat de recepció pot diferir
de l'OTD de línia. La captura OTD utilitza els mateixos bloquejos de línia que
les confirmacions per serialitzar-les amb la validació de recepcions.

A la comanda, les columnes **OTD línia completada**, **Termini OTD** i
**Línia completada el** es poden activar des del selector de columnes.
El formulari de línia també mostra la confirmació utilitzada.
Aquestes vistes requereixen actualitzar el mòdul; no s'han activat a la base.

## OTD agregat a la fitxa del proveïdor

Ruta després d'activar la versió `18.0.1.2.0` a la base corresponent:
**Compres → Comandes → Proveïdors → obre el proveïdor → Avaluació OTD**.
En anglès: **Purchase → Orders → Vendors → Avaluació OTD**. També es pot
obrir la mateixa fitxa des de Contactes. Cal ser usuari o responsable de compres.
La pestanya bàsica agregada ja és a les bases permanents `18.0.1.2.0`;
la presentació millorada i la llista dedicada són noves de `18.0.1.3.0`.

La fitxa mostra **Percentatge OTD**, **Línies avaluades**, **Línies puntuals**
i **Línies tardanes**. La fórmula és:

`100 × línies puntuals / (línies puntuals + línies tardanes)`

Cada línia compta una vegada, sense ponderació per quantitat ni preu. El
percentatge es presenta amb dos decimals. Sense línies avaluades es mostra
**Sense dades** i els comptadors són zero; si totes les avaluades són tardanes,
es mostra correctament **0 %**, que és un resultat diferent d'absència de dades.
Els clients API han de consultar `supplier_otd_has_data` abans d'interpretar
el valor numèric de `supplier_otd_percentage`.

Només es compten línies amb captura OTD congelada, data de finalització,
termini i resultat conegut `on_time` o `late`, de comandes en estat `purchase`
o `done`. No es compten seccions/notes, línies sense captura, parcials encara
no completades, desconegudes ni comandes cancel·lades.

L'atribució utilitza `supplier_otd_supplier_id`, el proveïdor capturat, encara
que la comanda canviï després de proveïdor. Cada fitxa és independent: els
contactes d'una empresa no es consoliden silenciosament a la fitxa pare.
No hi ha un filtre temporal implícit. Una devolució o un canvi de quantitat
posterior no elimina l'observació històrica de primera finalització ni en
recalcula el resultat. Una cancel·lació de comanda sí que l'exclou del resum,
sense tocar la captura.

Els camps són calculats no emmagatzemats: no hi ha migració de captures ni
escriptures als resultats històrics. Una consulta agrupada de les línies
resol tots els proveïdors consultats. Les dependències invaliden la memòria
cau en completar línies o canviar l'estat de la comanda.

L'agregat inclou només les empreses seleccionades que pertanyen a l'usuari,
amb memòria cau diferenciada per usuari i context d'empreses. Els permisos i
les regles de registre de compres continuen aplicant-se, fins i tot si el
proveïdor es consulta amb `sudo()`. Usuaris sense grup de compres, inclosos
portal i magatzem, no poden llegir els camps agregats.

El camp estàndard d'Odoo `on_time_rate` es conserva amb la seva fórmula
original, basada en quantitats i dates previstes. L'OTD agregat d'aquesta
pestanya utilitza exclusivament les nostres captures per línia.

## Historial de terminis

S'amplien `purchase.order`, `purchase.order.line`, `stock.move`, `stock.picking`
i `res.partner` amb `_inherit`. El model nou
`supplier.evaluation.deadline.revision` conserva les revisions per línia.

El primer compromís es fixa en aprovar una línia nova. Les línies antigues
sense historial mantenen l'original com a desconegut: una data observada avui
no es presenta com una promesa històrica del proveïdor. Cada línia té el seu
propi historial, encara que comparteixi comanda o recepció amb altres línies.

### Canvis explícits i recàlculs persistits

`date_planned` és un camp calculat emmagatzemat i editable a Odoo 18. El
seguiment intercepta `_write_multi()`, el punt que utilitza `_flush()` per
persistir tant valors editats com valors calculats. Compara les dates SQL
anterior i posterior, dins de la mateixa transacció i amb bloquejos de files.
No força una lectura recursiva del camp mentre s'està persistint.

- Només una transició real de data genera una revisió de canvi.
- Una escriptura explícita força la persistència de la data en acabar; això
  conserva les dates intermèdies de diverses escriptures explícites.
- Els recàlculs intermedis que només existeixen a la memòria cau i no s'arriben
  a persistir no es registren com a transicions SQL independents.
- No es creen revisions de canvi per recomputar el mateix valor ni repetir
  el buidatge de la memòria cau.
- Els registres virtuals `new()`/onchange no inicialitzen ni modifiquen
  l'historial del registre original. Un formulari descartat no és un acord.
- Els canvis en esborrany previs al primer compromís no es presenten com a
  renegociacions. Les inicialitzacions són esdeveniments de base separats.
- Una línia antiga confirmada sense historial rep una base `unknown_initial`
  amb l'antiga data observada i, si canvia, una revisió tècnica posterior.

### Atribució prudent

Ni un recàlcul ni una escriptura directa de `date_planned` demostren una
renegociació del proveïdor. Per tant, els canvis detectats s'enregistren com:

- `revision_type = technical`.
- `change_source = unverified`.
- `change_direction = postponed`, `advanced`, `set` o `removed`, segons dates.

Això permet veure terminis successivament posteriors sense atribuir-los al
proveïdor. `supplier_postponement_count` només compta revisions
`postponement`, reservades per a renegociacions acreditades; aquest mòdul
registra ara les confirmacions en un model separat. En aquesta fase el
comptador existent encara no incorpora les confirmacions, i no augmenta amb
canvis tècnics. Una simple edició de dates no acredita una renegociació.
`changed_by_id` identifica l'usuari del procés que persisteix el valor, no
necessàriament qui ha negociat ni qui ha originat el recàlcul diferit.

## Confirmació de renegociacions: fase 1

El model immutable `supplier.evaluation.deadline.confirmation` referencia una
revisió existent. La confirmació no modifica `revision_type`, `change_source`,
les dates ni les dades d'auditoria de la revisió.

Camps principals:

- `revision_id`, `purchase_line_id`, `order_id`, `company_id`, `supplier_id`.
- `previous_confirmation_id`, per encadenar acords de la mateixa línia.
- `previous_agreed_date`, `new_agreed_date` i `change_direction`.
- `confirmed_by_id`, `confirmed_at`, `justification`, `supplier_attributable`.

Les dates i dades d'auditoria es deriven al servidor. L'entrada admesa és la
revisió, una justificació no buida i una atribució explícita de tipus booleà.
L'atribució `False` també és vàlida: un acord pot respondre a una petició del
comprador. La confirmació és una declaració expressa del responsable de
compres; el sistema no dedueix un acord ni en verifica externament l'evidència.

L'acció pública `revision.action_confirm_renegotiation(justification,
supplier_attributable)` comprova `purchase.group_purchase_manager`. La mateixa
comprovació es repeteix a `create()` i s'aplica també amb `sudo()` d'un usuari
que no pertany al grup. La resposta de l'acció obre el registre confirmat;
el nou assistent utilitza aquesta mateixa acció i les validacions compartides.

Exemple en Odoo shell, amb un responsable de compres:

```python
action = revision.with_user(manager).action_confirm_renegotiation(
    "Nou termini acordat per correu amb el proveïdor", True,
)
confirmation = env[action["res_model"]].browse(action["res_id"])
```

Requisits de confirmació:

- Revisió tècnica vigent, amb dues dates informades i diferents, en una línia
  de compra aprovada i del proveïdor actual.
- Nova data igual a `date_planned` actual: si un recàlcul ha generat una revisió
  posterior, cal confirmar aquesta nova revisió i no l'anterior.
- Data acceptada anterior coneguda: prové de l'última confirmació de la línia
  o del compromís original conegut del mateix proveïdor.
- Nova data diferent de l'última acceptada; s'admeten ajornaments i avançaments.
- No s'admeten inicialitzacions, línies antigues sense acord conegut,
  comandes cancel·lades, revisions obsoletes ni acords heretats d'un altre
  proveïdor. Aquesta fase no inventa ni inicialitza compromisos antics.

Els bloquejos de línia existents serialitzen l'operació amb canvis de dates.
Una restricció SQL `UNIQUE(revision_id)` i una comprovació al servidor
impedeixen duplicats. No s'accepten dates, usuaris ni relacions falsificats
pel client. Tampoc es poden modificar, eliminar ordinàriament o copiar
confirmacions; les comandes duplicades no hereten aquests registres.

Els usuaris de compres i magatzem tenen lectura. Només els responsables de
compres poden crear confirmacions, i no hi ha permisos ordinaris d'escriptura
o eliminació. La regla d'empresa i les comprovacions al servidor limiten
l'accés a les empreses permeses, inclosos els intents amb `sudo()`.

## Interfície visual de renegociacions

Per confirmar un acord cal pertànyer al grup estàndard de responsables de
compres (`purchase.group_purchase_manager`). Els compradors ordinaris poden
consultar l'historial i les confirmacions, però no confirmar acords.

1. Desa la comanda i els canvis de data.
2. Obre **Compres → Terminis de proveïdors → Historial de terminis**. També
   pots utilitzar la icona de calendari **Historial de terminis** de cada línia
   de compra; aquest accés filtra l'historial per la línia seleccionada.
3. A l'última revisió tècnica vigent, prem **Confirmar renegociació**.
4. L'assistent mostra el compromís original conservat, l'última data acceptada
   i la nova data proposada. La data anterior acceptada pot ser diferent de la
   previsió tècnica anterior de la revisió.
5. Escriu una justificació i selecciona explícitament **Sí** o **No** sobre
   l'atribució al proveïdor. No hi ha una resposta marcada per defecte.
6. Confirma. S'obre la confirmació registrada, que és de només lectura.
   **Cancel·lar** no registra cap confirmació.

L'avís de l'assistent explica que confirmar no elimina el compromís original,
l'historial ni les avaluacions de recepcions completades. Els camps de dates
són de consulta i el servidor calcula les dades definitives en confirmar.

Les confirmacions es poden consultar des de la revisió original i des de
**Compres → Terminis de proveïdors → Renegociacions confirmades**, amb cerca
per comanda, línia o proveïdor. Les llistes i formularis d'auditoria no
permeten crear, editar, eliminar ni duplicar aquests registres manualment.

L'assistent és un `TransientModel`
`supplier.evaluation.deadline.renegotiation.wizard`. Els seus permisos i la
regla d'empresa són exclusius de responsables de compres. La restricció també
es comprova al servidor, inclosos intents amb `sudo()` d'un usuari sense grup.
Les dates i relacions del formulari no es poden falsificar per API.

La previsualització i la creació definitiva comparteixen
`_prepare_confirmation_values()`. El servidor revalida el termini en confirmar:
si ha canviat o algú ja ha confirmat la revisió, rebutja l'operació i cal tornar
a consultar l'historial. Les inicialitzacions i els originals desconeguts
continuen sense ser renegociacions confirmables. Una revisió tècnica antiga
pot tenir el botó visible, però el servidor només admet la revisió vigent.

## Captures històriques de recepcions

El codi de validació fixa les dates per moviment rebut i conserva el resultat
per recepció una sola vegada. Les captures són persistents, de només lectura
amb protecció ORM i `copy=False`; els backorders han de capturar el seu propi
termini quan es validin. Les recepcions antigues completades no es reavaluen
ni s'omplen amb dates originals inventades.

El nou seguiment de recàlculs només afegeix revisions a les línies de compra;
no escriu les captures de moviments o la classificació de recepcions tancades.
Les revisions no admeten modificació, eliminació ordinària ni creació pública.

En aquesta primera fase, les confirmacions documenten acords i atribució,
però no canvien la selecció de data de les futures captures: la validació
continua utilitzant el `date_planned` vigent. No s'han modificat les captures
completades, el càlcul de puntualitat ni el recompte de fiabilitat existent.
Aquesta semàntica anterior de recepció es conserva. La nova captura OTD de
línia descrita més amunt sí que utilitza l'últim acord confirmat vàlid.
La nova vista agregada del proveïdor no altera aquests resultats de recepció.

## Proves i estat de validació

Proves locals, sense Odoo ni base de dades:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

S'han superat 33 proves locals (19 de l'OTD i 14 preexistents) que executen
els mètodes de producció amb substituts de les declaracions, cursor i part
del model base d'Odoo.
No validen la integració amb l'ORM ni el SQL contra PostgreSQL.

S'han superat **133 proves reals TransactionCase**: 32 d'historial, 25 de
confirmacions, 21 de l'assistent i les vistes, 19 d'OTD per línia, 21 de
l'agregat i 15 de la nova interfície. L'execució completa va finalitzar en
17,726 segons, amb zero errors i zero fallades. Els 15 casos UI s'han tornat
a comprovar després dels últims ajustos de maquetació.

S'ha restaurat una còpia verificada en un PostgreSQL separat, dins d'una
xarxa Docker interna, amb un filestore independent. Només s'ha actualitzat
el mòdul a aquesta base temporal. Les dades de les proves es reverteixen;
les seqüències PostgreSQL poden avançar encara que hi hagi rollback.

`tests/odoo_integration.py` s'executa des d'un Odoo shell configurat per al
servidor temporal i rebutja bases sense el prefix `supplier_evaluation_otd_`.
Cal preparar el nou esquema a la còpia abans d'executar-lo. No s'ha de dirigir
el llançador ni l'actualització del mòdul a la base original.

Les proves utilitzen les vistes compilades d'Odoo i el simulador `Form` del
client. La instal·lació de les vistes i tota la suite s'han completat sense
avisos ni errors als registres. No s'ha executat una prova de navegador real,
un tour JavaScript ni una prova de càrrega amb sessions concurrents.

La comparació de les taules confirma que les dades de negoci i les captures
no han canviat. Els dumps complets reflecteixen activitat tècnica de sessions
concurrents; vegeu `tests/UI_RESULTS.md` per al detall.
No s'ha executat el generador de dades fictícies. Les còpies, els registres
i les comprovacions es conserven a `backups/`, exclòs de Git.
Les escriptures SQL externes a l'ORM no queden cobertes pel seguiment de dates.

## Generador de demostració

El generador extern `scripts/generate_otd_demo.py` prepara 10 proveïdors,
100 comandes i 200 línies, amb OTD diferents. Utilitza l'ORM i només admet
bases temporals `supplier_evaluation_otd_*` i la demostració independent
`supplier_evaluation_demo` amb activació explícita; `supplier_evaluation`
està bloquejada. No s'ha executat a la base original.

Instruccions i limitacions: [scripts/README.md](../../scripts/README.md).
Resultats: [tests/DEMO_RESULTS.md](../../tests/DEMO_RESULTS.md).

## Demostració permanent independent

La base neta `supplier_evaluation_demo` està disponible només a
`http://127.0.0.1:8074`, amb credencials pròpies, tasques programades
desactivades i volums persistents. Conté exactament 10 proveïdors, 100
comandes i 200 línies fictícies; OTD de 10 % a 100 %.
Configuració, accés i gestió: [DEMO.md](../../DEMO.md).
La base original i les còpies temporals anteriors es conserven intactes.

### Ajustos finals de la vista OTD (18.0.1.3.0)

L'acció **Purchase → Avaluació de proveïdors** utilitza un formulari primari
propi que amaga «On-time Rate». Els formularis estàndard d'Odoo conserven
l'indicador. La barra continua utilitzant el component natiu; una única
regla SCSS limitada a la pista OTD n'amplia l'amplada. El detall mostra
comanda, producte, termini OTD, finalització i resultat congelats.
