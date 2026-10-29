# Generador de demostració OTD

`generate_otd_demo.py` crea dades fictícies mitjançant l'ORM d'Odoo 18 i els
fluxos de `button_confirm()`, `button_validate()` i confirmació de
renegociacions del mòdul `supplier_evaluation` **18.0.1.2.0**.
No instal·la ni actualitza el mòdul.

## Conjunt fix

Llavor per defecte: **180120**. Dates de negoci fixes entre gener i abril de
2026, en UTC. Per empresa seleccionada es creen:

- 10 proveïdors `[OTD DEMO v1] Supplier 01` … `Supplier 10`.
- 100 comandes, 10 per proveïdor, amb exactament dues línies cadascuna.
- 200 línies completades: 110 puntuals i 90 tardanes.
- 150 recepcions: 50 comandes es reben en dues parts i 50 en una sola.
- 50 comandes renegociades, amb 100 confirmacions, una per línia.
- 300 moviments d'estoc i 300 revisions de termini.
- Dos productes consumibles, una ubicació de demostració, un tipus de
  recepció i una seqüència exclusius. No es creen ni es canvien magatzems.

S'intercalen quatre escenaris: recepció completa, parcial completada,
renegociació i parcial seguida de renegociació abans de completar.
Totes les parcials es completen al final: no queden backorders pendents.
Els OTD esperats per proveïdor són 10 %, 20 %, …, 100 % sobre 20 línies
avaluades cadascun. Els preus i quantitats varien, però no ponderen l'OTD.

## Execució només a una còpia temporal

1. Restaura una còpia en un **PostgreSQL independent**, en una xarxa Docker
   interna sense accés al servidor original. Utilitza un filestore i un
   directori de dades separats. No exposis serveis de correu de la còpia.
2. La base ha de tenir el nom `supplier_evaluation_otd_*` i la versió
   `18.0.1.2.0` del mòdul ja instal·lada. El generador rebutja explícitament
   `supplier_evaluation` i qualsevol altre prefix, excepte la base permanent
   exacta amb activació explícita descrita a `DEMO.md`.
3. Utilitza un contenidor Odoo configurat exclusivament per al PostgreSQL
   temporal. Necessita un administrador amb permisos de responsable de
   compres i usuari de magatzem. La seva empresa seleccionada ha de disposar
   d'un magatzem existent. No cal canviar els permisos ni la configuració.
4. Des de l'arrel del repositori, amb els noms de **la còpia temporal**:

```sh
DEMO_DB=supplier_evaluation_otd_demo
DEMO_CONTAINER=odoo-otd-demo

docker exec -i \
  -e OTD_DEMO_TARGET_DB="$DEMO_DB" \
  "$DEMO_CONTAINER" /entrypoint.sh odoo shell \
  -d "$DEMO_DB" --db-filter="^${DEMO_DB}$" \
  --no-http --max-cron-threads=0 --workers=0 \
  < scripts/generate_otd_demo.py
```

`DEMO_CONTAINER` és un exemple: cal indicar un contenidor temporal ja
configurat, mai el servei original. El nom declarat a `OTD_DEMO_TARGET_DB`
ha de coincidir exactament amb la base oberta. No es documenten ordres
contra la base original: continua bloquejada. La demostració permanent
independent `supplier_evaluation_demo` admet la mateixa llavor amb
`OTD_DEMO_ALLOW_PERMANENT=1` i un nom objectiu coincident, després de
l'autorització específica de l'usuari. Desplegament i accés: `DEMO.md`.

La primera execució valida el resultat complet i fa **un únic commit de la
transacció de dades**. Si falla, fa rollback; no modifica registres existents
per intentar corregir-los. Una execució repetida valida el conjunt existent,
retorna `reused_existing_dataset: true` i acaba amb rollback, sense recrear-lo.
Aquest commit és de PostgreSQL, no un commit Git.

La sortida `OTD_DEMO_RESULT=...` conté els comptadors i percentatges verificats.
Per veure'ls a la còpia: **Purchase → Orders → Vendors → cerca `[OTD DEMO v1]`
→ obre el proveïdor → Avaluació OTD**.

## Identificació i idempotència

- Proveïdors, productes i ubicació porten el prefix `[OTD DEMO v1]`.
- Referències de proveïdor, comandes i recepcions utilitzen
  `OTD-DEMO-v1-C<empresa>…`. Els correus són del domini reservat `.invalid`.
- Tots els registres de negoci creats, inclosos línies, captures, moviments,
  detalls de recepció, grups d'aprovisionament, tarifes de proveïdor i
  registres de missatgeria automàtica, tenen identificadors externs
  `supplier_otd_demo.c<empresa>_*`, amb `noupdate=True`.
- Un manifest nou a `ir.config_parameter`, clau
  `supplier_otd_demo.v1.company_<empresa>`, conserva llavor, hash del pla i
  correspondència d'identificadors.
- Si el manifest, la llavor o els registres no concorden, el generador
  s'atura i no repara ni elimina dades. No adopta registres reals amb noms
  semblants ni recrea silenciosament registres de demo que faltin.
- Un bloqueig consultiu transaccional rebutja execucions simultànies per
  empresa. No s'ha fet una prova de càrrega concurrent.

## Dates, validació i limitacions

Les dates es simulen temporalment amb `patch('odoo.fields.Datetime.now', ...)`
dins del procés de shell, al crear/aprovar, confirmar i rebre. No es fa SQL
per escriure registres ni s'escriuen directament camps OTD protegits. És el
mòdul qui crea les captures mitjançant el flux normal. Les captures de la
primera parcial es comproven després de la recepció final.

La validació comprova línies i quantitats, terminis originals i confirmats,
seqüència de dates, recepcions, captures congelades, percentatges del resum
i identificadors externs. També es proven el límit inclusiu de 24 hores i
un segon de retard més enllà de la tolerància.

La reproducció és **de dades de negoci i resultats**, no binària: IDs,
seqüències tècniques, `create_date`/`write_date` i l'usuari actor depenen de
la còpia i de l'instant real d'execució. La llavor no canvia els percentatges
objectiu; canvia la distribució, quantitats i preus.

No es generen factures, impostos, pagaments, devolucions ni valoració
financera d'estoc. Els productes són consumibles no emmagatzemables: hi ha
recepcions reals, però no augmenten quants ni existències de productes reals.
No es modifiquen ajustos d'empresa si la configuració impedeix aprovar una
comanda; el generador falla i reverteix el conjunt.

La prova s'ha fet en una empresa, amb recepció directa, sense navegador real.
No hi ha una ordre de neteja: les captures són immutables. Per tornar a
començar amb una altra llavor, utilitza una còpia temporal nova; no intentis
esborrar historials o manifestos manualment.

Proves locals sense Odoo:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Resultats de la prova ORM i de la segona execució: `tests/DEMO_RESULTS.md`.
