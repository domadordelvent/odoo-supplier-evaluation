# Supplier Evaluation

Mòdul per a Odoo 18 Community, versió de codi `18.0.1.1.0`.
Dependències: `base`, `purchase`, `stock`, `purchase_stock`.

**Estat: OTD per línia completada implementat i validat en una base temporal
independent: 97 proves d'integració superades (19 OTD i 78 preexistents).**
La base original `supplier_evaluation` continua sense actualitzar.
Els resultats actuals i anteriors es documenten a `tests/RESULTS.md`.

## Objectiu i separació de mètriques

Avaluar cada recepció individual, incloses les recepcions parcials, amb una
tolerància de 24 hores. La puntualitat i la fiabilitat són independents:

- Puntualitat: captura de les dates de cada moviment rebut i classificació
  immutable de la recepció. Si algun moviment rebut arriba tard, preval
  `late`; només s'assigna `on_time` si tots tenen dades suficients i són puntuals.
- Fiabilitat: conservació del compromís original conegut i historial de les
  transicions posteriors de data, sense puntuacions globals.

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
`unknown` significa completada sense evidència suficient. No hi ha percentatge
global de proveïdor en aquesta fase.

Les captures històriques de `stock.move` i `stock.picking` continuen intactes,
amb la seva semàntica anterior. Per això el resultat de recepció pot diferir
de l'OTD de línia. La captura OTD utilitza els mateixos bloquejos de línia que
les confirmacions per serialitzar-les amb la validació de recepcions.

A la comanda, les columnes **OTD línia completada**, **Termini OTD** i
**Línia completada el** es poden activar des del selector de columnes.
El formulari de línia també mostra la confirmació utilitzada.
Aquestes vistes requereixen actualitzar el mòdul; no s'han activat a la base.

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
No s'han afegit puntuacions globals ni informes.

## Proves i estat de validació

Proves locals, sense Odoo ni base de dades:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

S'han superat 33 proves locals (19 de l'OTD i 14 preexistents) que executen
els mètodes de producció amb substituts de les declaracions, cursor i part
del model base d'Odoo.
No validen la integració amb l'ORM ni el SQL contra PostgreSQL.

S'han superat **97 proves reals TransactionCase**: 32 d'historial, 25 de
confirmacions, 21 de l'assistent i les vistes i 19 d'OTD. L'execució completa
va finalitzar en 16,517 segons, amb zero errors i zero fallades.

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

La comparació SHA-256 dels dumps lògics abans i després confirma que la base
original no ha canviat. També s'ha verificat la integritat del filestore.
No s'ha executat el generador de dades fictícies. Les còpies, els registres
i les comprovacions es conserven a `backups/`, exclòs de Git.
Les escriptures SQL externes a l'ORM no queden cobertes pel seguiment de dates.
