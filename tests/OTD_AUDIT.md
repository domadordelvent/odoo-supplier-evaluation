# Auditoria de l'OTD agregat per proveïdor

Data: 2026-10-29.

L'auditoria inicial confirma que `purchase_line_otd.py` ja conserva un únic
resultat de primera finalització, juntament amb proveïdor, termini i instant
capturats. `res_partner.py` només contenia la declaració `_inherit` i encara
no hi havia vista ni percentatge agregat propi.

La implementació reutilitza aquests camps sense modificar el mètode de
captura ni cap resultat històric. `res.partner` afegeix percentatge, tres
comptadors, senyal d'existència de dades i una relació de dependències amb
les línies capturades. Tots els indicadors són no emmagatzemats.

Una consulta ORM agrupada per proveïdor capturat i estat compta files, no
quantitats ni imports. Filtra captura, dates conegudes, estat on_time/late,
comandes aprovades/no cancel·lades i empreses seleccionades autoritzades.
La consulta elimina qualsevol sudo heretat i aplica les regles de compres.
La memòria cau depèn d'usuari i empreses; les captures i l'estat de comanda
invaliden els valors calculats.

La nova pestanya «Avaluació OTD» al formulari de contacte està restringida a
compres i diferencia explícitament «Sense dades» de 0 %. L'indicador natiu
`on_time_rate` d'Odoo no es modifica, perquè té una fórmula diferent.

Validació: 118 proves ORM superades en una còpia temporal independent,
incloses 21 noves de l'agregat; 33 proves locals superades. El SHA-256 de la
base original i el contingut del filestore són idèntics abans i després.
La versió nova és `18.0.1.2.0`; l'original segueix a `18.0.1.1.0`.
Els detalls i limitacions consten a `tests/RESULTS.md`.

---

# Auditoria i implementació de l'OTD per línia completada

Data: 2026-10-28.

## Estat comprovat

- `stock.move` calcula puntualitat a partir de les dates capturades, amb
  tolerància inclusiva de 24 hores.
- `stock.picking._action_done()` conserva les captures dels moviments rebuts
  i classifica la recepció. Una parcial ja pot tenir resultat: això encara
  no és un OTD per línia de compra completada.
- `purchase.order.line` conserva el compromís original i les revisions,
  però no té camps ni càlcul d'OTD per línia completada.
- Les confirmacions de renegociacions són immutables, però actualment no
  seleccionen el termini de les captures: s'utilitza `date_planned` vigent.
- Les línies antigues poden tenir el compromís original desconegut i les
  recepcions antigues poden no tenir captures. No s'han d'inventar dates.

## Semàntica d'Odoo observada al codi instal·lat

S'ha llegit, sense executar l'ORM, el fitxer
`purchase_stock/models/purchase_order_line.py` del contenidor existent.
`_compute_qty_received()` converteix quantitats a la unitat de la línia i
tracta específicament les devolucions i els moviments relacionats amb
dropshipping. No és suficient sumar les quantitats de totes les recepcions.

La implementació ha de concretar el tractament de parcials, devolucions,
sobrerecepcions, canvis de quantitat i cancel·lacions de quantitats pendents.
També cal diferenciar un resultat desconegut d'una línia puntual o tardana.

## Criteri confirmat i implementació

L'usuari ha confirmat l'últim termini renegociat i confirmat abans de completar
la línia, o el compromís original registrat si no existeix aquest acord, amb
24 hores de tolerància. Els canvis tècnics no confirmats no intervenen i les
captures històriques es conserven.

`models/purchase_line_otd.py` afegeix una captura immutable de primera
finalització a la línia. El flux de recepció selecciona les línies encara
incompletes sota els bloquejos existents i les avalua després de validar i
capturar els moviments. No reomple línies antigues ja completades.
El resultat inclou el context de quantitat, unitat, proveïdor i acord.

Es compara amb el darrer acord anterior segons `confirmed_at`, ordenat per
data i identificador. Abans de validar es fixa sota bloqueig el límit dels
identificadors ja existents. Això permet distingir els acords anteriors
dins del mateix segon dels acords creats després de rebre. Sense dades suficients es captura
`unknown`, sense inventar originals ni modificar recepcions antigues.

Les devolucions anteriors intervenen en `qty_received` estàndard; les
posteriors no substitueixen l'observació congelada. Cancel·lar el saldo
pendent no completa una línia. Les sobrerecepcions compten una vegada.
La documentació funcional completa és al README del mòdul.

## Verificació executada

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`

Resultat: **33 proves locals superades**, 19 noves de l'OTD.
També s'han superat **97 proves ORM: 19 OTD i 78 preexistents**, amb zero errors
i zero fallades, en 16,517 segons. L'actualització del mòdul i la compilació
de les vistes s'han validat en una còpia temporal independent.

La còpia de seguretat s'ha restaurat a un PostgreSQL separat, amb xarxa
Docker interna i filestore propis. S'han verificat els SHA-256, el dump i
l'arxiu de filestore. La comparació del contingut lògic abans i després
confirma que la base original i el seu filestore no han canviat.

No s'ha actualitzat `supplier_evaluation`, no s'han executat proves contra
aquesta base ni reiniciat els seus serveis. No s'ha executat cap generador
de dades fictícies. La còpia temporal queda conservada amb el seu contenidor
aturat. Les evidències i els backups estan exclosos de Git.

No s'han executat proves de navegador real ni de sessions concurrents.
