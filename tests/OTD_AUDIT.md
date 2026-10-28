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
