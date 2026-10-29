## Ajustos finals UI — 2026-10-30

135 proves d'integració, 43 proves locals i Chromium superats sobre una
còpia temporal. Supplier 05: 20 línies, 10 puntuals i 10 tardanes.
Indicador estàndard conservat fora de l'acció pròpia, barra ampliada.
Bases permanents i captures congelades intactes. Vegeu `UI_RESULTS.md`.

# Interfície OTD nativa — 18.0.1.3.0, pendent d'activació

Data: 2026-10-29. **133 proves ORM superades** (15 noves d'interfície),
43 proves locals superades i comprovació real amb Chromium sobre els deu
proveïdors ficticis en una còpia temporal independent. Els 15 casos UI
s'han tornat a executar després dels últims ajustos de maquetació.

La llista ordena als dos sentits, el filtre < 50 % retorna quatre proveïdors,
les deu fitxes mostren els valors 10–100 % i el botó de detall retorna les
20 línies corresponents (8 puntuals i 12 tardanes en el cas del 40 %).
També s'ha comprovat l'etiqueta «Sense dades» i l'absència d'errors JavaScript.

No s'ha actualitzat cap base permanent ni fet cap commit. Es conserven les
dades de negoci, les captures OTD, l'esquema i la versió `18.0.1.2.0` de totes
dues bases. Els dumps complets sí que difereixen per activitat concurrent:
presència/notificacions/dispositiu a l'original i ajustos de configuració,
valors per defecte i presència a la demo. Els registres HTTP confirmen aquesta
activitat; no s'ha revertit. Les captures de les 200 línies de la demo
coincideixen exactament amb les de la còpia de prova.

Detalls, scripts de prova i captures: [UI_RESULTS.md](UI_RESULTS.md).

---

# Demostració permanent neta

Base `supplier_evaluation_demo`, mòdul `18.0.1.2.0`, creada des de zero sense
mostres d'Odoo ni restauració de l'original. Llavor `180120`: 10 proveïdors,
100 comandes, 200 línies i OTD del 10 % al 100 %, verificats amb el generador
i amb consultes autenticades a la interfície web local del port 8074.
La segona execució reutilitza el conjunt sense duplicats.

43 proves locals superades. Els nous casos exigeixen una activació explícita
per a la base permanent i confirmen que `supplier_evaluation` continua
bloquejada, fins i tot amb aquesta activació.

El primer accés des de l'host va trobar el port sense publicar en una xarxa
exclusivament interna. S'ha separat la xarxa web de la xarxa interna de
PostgreSQL i vinculat el port exclusivament a `127.0.0.1`. Els controls finals
confirmen HTTP 200, autenticació, vista OTD, persistència després de recrear
el servei, zero tasques programades actives i servidor de correu inactiu.

La base original conserva el mateix SHA-256 lògic. Les tres instàncies
temporals anteriors conserven identificadors, estats i volums. No s'ha
publicat res a GitHub. Instruccions i credencials locals: [DEMO.md](../DEMO.md).

---

# Generador de demostració — validació en base temporal

Data: 2026-10-29. Mòdul `18.0.1.2.0`, sense canvis al seu esquema.

Generades i validades amb ORM 100 comandes i 200 línies de 10 proveïdors.
Segona execució sense duplicats, amb IDs i hashes de 28 taules idèntics.
Les dades que ja existien a la còpia no s'han modificat. 41 proves locals
superades. Detalls, percentatges i limitacions: [DEMO_RESULTS.md](DEMO_RESULTS.md).

No s'ha executat el generador a `supplier_evaluation` ni publicat res a GitHub.

---

# OTD agregat per proveïdor — pendent d'activació a la base original

Data local: 2026-10-29. Execució UTC: 2026-10-28.
Versió de codi i de la base temporal: `18.0.1.2.0`.

- **118 proves d'integració superades** en 15,369 segons: les 97 preexistents
  i **21 noves d'agregació**. Resultat final: **0 errors i 0 fallades**.
- **33 proves locals superades**; no s'ha repetit la suite d'integració
  després d'obtenir el resultat correcte.
- La nova vista del proveïdor s'ha instal·lat i compilat a la base temporal.
  Les proves comproven els quatre indicadors, la visibilitat de «Sense dades»
  i l'absència de la pestanya per als usuaris sense permisos de compres.
- La primera execució es va aturar en esperar set decimals en un camp que
  Odoo arrodoneix a dos. S'ha corregit l'assert de la prova; el resultat
  esperat d'una línia puntual de tres és `33.33`. La segona execució completa
  ha superat tota la suite, inclosa una nova prova de devolució posterior.

La cobertura nova inclou 0/100 %, absència de dades, fraccions, pesos iguals
per línia, parcials i múltiples recepcions, originals desconeguts, recepcions
antigues sense captura, cancel·lacions, canvis posteriors de dates/acords,
quantitats i preus, devolucions, atribució al proveïdor congelat, contactes,
càlcul per lots, preservació de captures, permisos de comprador/responsable,
portal/magatzem, regles de registre, intents amb sudo i selecció d'empreses
separades/conjuntes sense compartir valors erronis de memòria cau.

S'ha restaurat una còpia verificada en un PostgreSQL separat, amb xarxa
Docker interna i filestore independent. Només s'ha actualitzat aquesta
base temporal. Les dades de prova s'han revertit i el contenidor de proves
ha quedat aturat; es conserva per a inspecció.

El SHA-256 del dump lògic complet de `supplier_evaluation` coincideix abans i
després. El filestore original també és idèntic. La base original continua
a `18.0.1.1.0`: no s'ha actualitzat, ni s'han reiniciat els seus serveis.
No s'ha executat el generador de dades fictícies ni publicat res a GitHub.
Les evidències, registres i còpies romanen a `backups/`, exclòs de Git.

Limitacions: no hi ha prova de navegador real ni càrrega amb sessions
concurrents. Els resultats depenen de les empreses seleccionades i de les
regles de lectura de cada usuari. La nova pestanya encara no és a la base
original; requereix una actualització autoritzada posterior.

---

# OTD per línia completada — codi pendent d'activació

Data: 2026-10-28. Versió de codi: `18.0.1.1.0`.

- **33 proves locals superades**: 14 preexistents i 19 noves de l'OTD.
- **97 proves d'integració superades** en 16,517 segons: 19 OTD i 78
  preexistents, amb **0 errors i 0 fallades**, al primer intent.
- Actualització del mòdul i compilació de les vistes correctes només a la base
  temporal independent. Sense avisos ni errors als registres.
- Sintaxi validada dels 22 fitxers Python i dels quatre XML.
- `git diff --check` sense errors.

Les proves locals executen els mètodes de producció amb substituts d'Odoo.
Cobreixen originals i confirmacions, canvis tècnics ignorats, tall temporal,
límit de 24 hores, parcials, quantitats netes incompletes, sobrerecepcions,
dades desconegudes, congelació posterior i proteccions dels camps.
No validen SQL, bloquejos concurrents ni conversions reals d'unitats.

Els casos ORM afegeixen recepcions reals, confirmacions entre parcials,
preservació de captures anteriors, línies antigues, permisos, còpies,
conversions d'unitats, devolucions abans/després i cancel·lació de backorders.
El codi instal·lat de les unitats i devolucions s'ha consultat en mode lectura.

La còpia de seguretat s'ha verificat amb SHA-256, lectura completa del dump,
lectura completa de l'arxiu de filestore i restauració efectiva a la base
`supplier_evaluation_otd_*`. El PostgreSQL temporal
utilitza una xarxa Docker interna independent, sense connexió al servidor
original, i un filestore separat. El contenidor temporal s'ha aturat després
de les comprovacions; la còpia de proves es conserva per a inspecció.

Les connexions utilitzades per llegir la base original tenien
`default_transaction_read_only=on`. El SHA-256 del contingut lògic complet,
incloses les seqüències, coincideix abans i després. El filestore original
també es conserva intacte. Les dades de negoci de la còpia de proves s'han
revertit; els valors de seqüència consumits afecten només la base temporal.

El llançador rebutja bases sense el prefix `supplier_evaluation_otd_`.
No s'ha actualitzat ni modificat `supplier_evaluation`, no s'han reiniciat
els serveis originals i no s'ha executat el generador de dades fictícies.
Les evidències locals i les còpies queden a `backups/`, exclòs de Git.

Limitacions: no hi ha prova de navegador real ni de concurrència amb sessions
simultànies. La funcionalitat encara no s'ha activat a la base original.

---

# Assistent visual de renegociacions

Data local: 2026-10-18. Registres UTC: 2026-10-17.
Entorn: Odoo 18 Community `18.0-20260305`, PostgreSQL 15.

## Resultat final

- **78 proves d'integració superades** en 8,481 segons: 32 d'historial,
  25 de confirmacions i 21 de l'assistent i de les vistes.
- **14 proves unitàries superades** sense accés a base de dades.
- Sintaxi correcta dels **19 fitxers Python** i dels quatre XML del manifest.
- Actualització del mòdul i validació de les vistes d'Odoo correctes.
- Versió i dependències conservades: `18.0.1.0.0`; `base`, `purchase`, `stock`,
  `purchase_stock`.

## Interfície i reutilització

Hi ha accés a l'historial des de les línies de compra, tant en llista com en
formulari, i des del menú Compres → Terminis de proveïdors. El botó de
confirmació apareix només als responsables de compres. Les confirmacions
registrades tenen llista, formulari i cerca propis, i també es mostren a la
revisió corresponent; totes aquestes vistes són de només lectura.

L'assistent mostra la data original conservada, l'última acceptada i la nova
proposta. Exigeix justificació i selecció explícita d'atribució Sí/No.
L'avís indica que no s'elimina el compromís original ni es modifiquen les
avaluacions de recepcions completades.

El model transitori no duplica la lògica de confirmació: la previsualització i
`create()` comparteixen `_prepare_confirmation_values()`, i el botó final
crida `revision.action_confirm_renegotiation()`. La persistència, comprovacions
de permisos, unicitat i immutabilitat continuen al model de confirmacions.

## Cobertura nova

Les 21 proves d'integració noves cobreixen:

- Dates mostrades i obertura sense crear confirmacions ni modificar revisions.
- Desament d'un formulari amb `odoo.tests.Form` i creació per l'acció existent.
- Atribució negativa, selecció obligatòria i justificació obligatòria.
- Últim acord acceptat diferenciat de les dates tècniques intermèdies.
- Permisos al servidor per obrir, crear i confirmar, inclosos intents amb sudo.
- Protecció de les dates mostrades, empresa i revisió seleccionada.
- Revalidació d'un assistent obert quan la revisió ha canviat.
- Dos assistents oberts: una sola confirmació.
- Cancel·lació i rebuig de revisions no confirmables abans d'obrir el modal.
- Neteja de valors per defecte procedents d'altres vistes.
- Visibilitat del botó per grup, avís de conservació i controls obligatoris.
- Historial filtrat per línia i rebuig de línies no desades.
- Vistes compilades de compra amb els dos accessos a l'historial.
- Menús i formularis/llistes de confirmació de només lectura.
- Consulta posterior des de l'historial.
- Conservació de captures completades, originals i backorders.

## Execucions i ajustos

La primera execució es va aturar a la prova del formulari: `Form` retorna les
dates com a cadenes, mentre que el registre ORM retorna `datetime`. Es va
corregir només la prova per normalitzar amb `fields.Datetime.to_datetime()`.
La prova del formulari va passar individualment i després va passar tota
la suite: **78/78**, sense errors ni fallades.

La primera actualització també va mostrar avisos de docutils perquè Odoo
interpretava el README Markdown com a reStructuredText. S'ha afegit una
descripció de text pla al manifest; l'actualització final ja no mostra
els avisos de format. No ha calgut modificar Docker ni les dependències.

Arxius de registre a `backups/pre-renegotiation-wizard-20261017T223413Z/`:

- `upgrade.log`: primera actualització, amb els avisos de descripció.
- `upgrade-description.log`: actualització final sense aquests avisos.
- `integration.log`: execució inicial i comparació de dates incorrecta a la prova.
- `integration-form.log`: prova corregida del formulari, superada.
- `integration-final.log`: execució final de 78 proves, superada.

## Còpia i dades

Abans d'actualitzar s'han copiat PostgreSQL i el filestore a
`backups/pre-renegotiation-wizard-20261017T223413Z/`, amb permisos limitats al
propietari. El dump s'ha llegit completament amb `pg_restore --file=/dev/null`,
s'ha verificat el gzip del filestore (572 fitxers) i s'han registrat SHA-256.

Les dades creades per les proves s'han revertit. Verificació final:

| Registres | Abans | Després |
|---|---:|---:|
| Comandes | 11 | 11 |
| Línies | 23 | 23 |
| Recepcions | 14 | 14 |
| Moviments | 34 | 34 |
| Revisions | 0 | 0 |
| Confirmacions | 0 | 0 |

No queden assistents ni usuaris de prova. Els originals coneguts i captures
històriques continuen a zero: no s'ha omplert retroactivament cap recepció.
L'evidència és `post-validation.json` de la carpeta de còpia.

No s'ha eliminat ni reinicialitzat la base ni modificat la configuració de
Docker. S'ha reiniciat únicament el contenidor Odoo per activar el codi a la
interfície web; PostgreSQL no s'ha reiniciat. Comprovació HTTP del formulari
de connexió: **200**, amb el formulari de login correcte. Vegeu
`service-activation.log`.
Els salts en seqüències PostgreSQL després de proves amb rollback són normals.

## Limitacions i abast

- S'han validat les vistes d'Odoo i el formulari amb `Form`; no s'ha executat
  una prova de navegació en un navegador real ni un tour JavaScript.
- El botó d'una revisió tècnica antiga pot ser visible; el servidor la rebutja
  si ja no és vigent. Els originals desconeguts tampoc no es poden confirmar.
- La confirmació continua sent una declaració del responsable amb justificació;
  no es verifica externament la prova documental.
- No es modifiquen puntuacions, informes, `supplier_postponement_count`,
  selecció de terminis per a futures recepcions ni captures ja completades.
- La confirmació conserva la restricció SQL anti-duplicats. La prova de dos
  assistents és seqüencial; no és una prova de càrrega amb sessions concurrents.
