# Odoo Supplier Evaluation — demostració permanent

Base **neta**, creada des de zero amb Odoo 18 i Supplier Evaluation
`18.0.1.2.0`, sense restaurar dades de l'original ni carregar dades de mostra
dels mòduls estàndard. El conjunt OTD s'ha generat amb la llavor **180120**.

## Entrada

- URL local: <http://127.0.0.1:8074/web/login?db=supplier_evaluation_demo>
- Base: `supplier_evaluation_demo`.
- Usuari: `demo_admin`.
- Contrasenya: fitxer local `credentials/demo-access.txt`, només llegible pel
  propietari i exclòs de Git. No és la contrasenya de l'Odoo original.
- Indicadors: **Purchase → Orders → Vendors → obre un proveïdor → Avaluació OTD**.

Accés web autenticat verificat amb HTTP 200, formulari de proveïdor compilat
i consultes reals dels indicadors mitjançant la sessió de demostració.

## Dades verificades

Hi ha exactament **10 proveïdors**, **100 comandes**, **200 línies**,
**150 recepcions** i **100 confirmacions de renegociació**.
Els proveïdors `[OTD DEMO v1] Supplier 01` … `Supplier 10` tenen cadascun
20 línies avaluades i OTD respectivament de **10 %, 20 %, …, 100 %**.
La segona execució del generador ha reutilitzat el conjunt sense duplicats.
No hi ha comandes o proveïdors copiats de la base original. Els registres
base d'Odoo (usuaris del sistema, moneda, països, etc.) són els d'una
instal·lació nova; l'empresa i l'administrador tenen noms ficticis.

## Docker i persistència

Configuració separada: `compose.demo.yml`, projecte
`odoo-supplier-evaluation-demo`. El fitxer original `docker-compose.yml`
no s'ha modificat.

```sh
docker compose --env-file .env.demo -f compose.demo.yml ps
docker compose --env-file .env.demo -f compose.demo.yml up -d --wait
```

Per aturar només la demostració, conservant les dades:

```sh
docker compose --env-file .env.demo -f compose.demo.yml stop
```

Volums persistents independents:

- `odoo-supplier-evaluation-demo_demo-postgres`
- `odoo-supplier-evaluation-demo_demo-odoo`

Els serveis tenen `restart: unless-stopped`. El servei web s'ha recreat
conservant els volums i s'han tornat a comprovar els 100/200 registres.
No utilitzis `down -v` si vols conservar la demostració.

PostgreSQL només pertany a una xarxa interna sense ports publicats.
Odoo té una xarxa web separada i publica **només `127.0.0.1:8074`**;
no s'ha configurat cap escolta pública ni cap publicació a Internet.
El filtre de bases només admet `supplier_evaluation_demo` i el gestor de
bases no es publica a la interfície.

Totes les tasques programades tenen `active=False`; el servidor també
utilitza `max_cron_threads=0`. Els servidors de correu sortint estan
inactius. No s'instal·la el mòdul ni es regenera el conjunt automàticament
en reiniciar Odoo.

## Fitxers privats

- `.env.demo`: contrasenyes de PostgreSQL, mestra i web independents.
- `secrets/odoo-demo.conf`: configuració privada d'Odoo.
- `credentials/demo-access.txt`: dades d'accés per a l'usuari.

Tots estan exclosos de Git. Els directoris de secrets i credencials estan
restringits al propietari. La configuració del contenidor és de només lectura.
Les còpies de seguretat i les evidències són a `backups/permanent-demo-*`.
El dump de la demostració s'ha verificat amb lectura completa de `pg_restore`.

## Generador i proteccions

La base original `supplier_evaluation` continua bloquejada, encara que
s'activi l'opció permanent. Només el nom exacte `supplier_evaluation_demo`
s'admet amb `OTD_DEMO_ALLOW_PERMANENT=1` i un `OTD_DEMO_TARGET_DB` coincident.
Aquesta base ja està generada; l'ordre següent només la torna a validar:

```sh
docker compose --env-file .env.demo -f compose.demo.yml exec -T \
  -e OTD_DEMO_ALLOW_PERMANENT=1 \
  -e OTD_DEMO_TARGET_DB=supplier_evaluation_demo \
  odoo-demo /entrypoint.sh odoo shell \
  -d supplier_evaluation_demo --no-http --max-cron-threads=0 --workers=0 \
  < scripts/generate_otd_demo.py
```

El manifest detecta alteracions al conjunt: no repara ni elimina registres.
Les limitacions del generador són a `scripts/README.md`.

## Conservació de l'original i les còpies temporals

El SHA-256 del contingut lògic complet de `supplier_evaluation` coincideix
abans i després del desplegament. No s'ha actualitzat ni reiniciat l'Odoo
original. Les tres instàncies PostgreSQL temporals anteriors conserven els
mateixos contenidors, estats i volums; no s'han eliminat.
No s'ha publicat res a GitHub.
