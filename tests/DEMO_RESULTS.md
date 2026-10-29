# Prova del generador de demostració OTD

Data local: 2026-10-29. Odoo 18 Community, mòdul `18.0.1.2.0`.
Llavor fixa: **180120**.

El generador s'ha executat en una còpia restaurada en un PostgreSQL temporal
independent, dins d'una xarxa Docker interna i amb filestore separat.
No s'ha actualitzat el mòdul ni s'ha executat el generador contra l'original.

## Resultats ORM

Primera execució correcta: 10 proveïdors, 100 comandes, 200 línies, 150
recepcions, 300 moviments, 300 revisions i 100 confirmacions. Totes les
línies acaben completades; 50 comandes tenen una primera recepció parcial i
50 tenen un acord renegociat abans de la recepció final.

| Proveïdor fictici | Avaluades | Puntuals | Tardanes | OTD |
|---|---:|---:|---:|---:|
| Supplier 01 | 20 | 2 | 18 | 10 % |
| Supplier 02 | 20 | 4 | 16 | 20 % |
| Supplier 03 | 20 | 6 | 14 | 30 % |
| Supplier 04 | 20 | 8 | 12 | 40 % |
| Supplier 05 | 20 | 10 | 10 | 50 % |
| Supplier 06 | 20 | 12 | 8 | 60 % |
| Supplier 07 | 20 | 14 | 6 | 70 % |
| Supplier 08 | 20 | 16 | 4 | 80 % |
| Supplier 09 | 20 | 18 | 2 | 90 % |
| Supplier 10 | 20 | 20 | 0 | 100 % |
| Total | 200 | 110 | 90 | 55 % |

Els noms porten el prefix `[OTD DEMO v1]`. El validador comprova cadascuna
de les captures, les dates, els acords aplicats i els percentatges calculats
pel model de proveïdor, sense escriure manualment els resultats OTD.

## Idempotència, proteccions i preservació

- La segona execució, en un procés de shell nou, retorna
  `reused_existing_dataset: true`: mateixos resultats, sense duplicats.
- S'han comparat tots els IDs i hashes de fila de **28 taules** abans/després
  de la segona execució: són idèntics. Les files que ja existien a la còpia
  abans de la primera execució també es mantenen intactes.
- Hi ha **3.376 identificadors externs**. Tota fila nova a les 27 taules de
  dades monitorades té identificador de demostració; la taula de metadades
  `ir.model.data` queda fora d'aquesta comprovació autoreferencial.
- Una validació addicional amb la versió final del generador ha reutilitzat
  el mateix conjunt sense canvis. Una llavor diferent s'ha rebutjat de forma
  controlada, sense modificar el conjunt existent.
- **41 proves locals superades**, incloses vuit noves del pla, cronologia,
  tolerància, llavor, separació de namespaces i bloqueig de la base original.
- No s'ha repetit la suite d'integració del mòdul: no hi ha canvis al codi
  d'Odoo ni al seu esquema. La prova actual executa el generador amb ORM real.

El SHA-256 del contingut lògic complet de `supplier_evaluation` coincideix
amb el d'abans de la prova. El filestore original també és idèntic.
El PostgreSQL temporal ha quedat aturat i conserva el conjunt per a inspecció.

Les evidències completes i còpies queden a `backups/`, exclòs de Git.
Les limitacions i les instruccions d'execució són a `scripts/README.md`.
