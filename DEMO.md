# Optional local demonstration

The installable addon does not require Docker, this database name, or the demo
generator. See [standard installation](docs/INSTALLATION.md) first.

## Existing validated dataset

The fictional dataset was originally generated with module 18.0.1.2.0 and seed
**180120**, then preserved while upgrading the interface to **18.0.1.3.0**:

- 10 fictional suppliers, 100 purchase orders and 200 completed lines.
- 150 receipts, including partial deliveries, and 100 confirmed renegotiations.
- Supplier 01 through Supplier 10: respectively 10%, 20%, …, 100% OTD,
  with 20 evaluated lines per supplier.
- Supplier 05: 10 on time and 10 late (50%).

Screenshots in [docs/screenshots](docs/screenshots/README.md) contain only this
fictional data. No database dump or preloaded volume is distributed.

## Separate Docker environment

`compose.demo.yml` defines independent PostgreSQL and Odoo volumes, an internal
database network and a web binding at **127.0.0.1:8074**. It never points at the
other Compose project's database. Scheduled workers are disabled.

Prepare private files before starting an environment:

```sh
cp .env.demo.example .env.demo
mkdir -p secrets credentials
cp config/odoo-demo.conf.example secrets/odoo-demo.conf
```

Replace every placeholder with independent random values. The master password
must be copied explicitly into the Odoo configuration: the INI file does not
expand `.env.demo` variables. Web credentials are operator inputs for account
setup; Compose does not automatically create that user. The PostgreSQL password
is passed by the Odoo image entrypoint. Keep the credential directory private,
and make the mounted Odoo configuration readable by the container's Odoo user
without making the containing host directory public.

For a **new, empty demo environment**, start only PostgreSQL, then install:

```sh
docker compose --env-file .env.demo -f compose.demo.yml up -d db-demo
docker compose --env-file .env.demo -f compose.demo.yml run --rm --no-deps \
  odoo-demo odoo -d supplier_evaluation_demo -i supplier_evaluation \
  --without-demo=all --stop-after-init --no-http --max-cron-threads=0
```

Do not use this initialization command on an existing database. Before starting
the web service, use an Odoo shell against this isolated database to set a
unique administrator password, grant Purchase manager and Inventory user access,
use a fictional company identity, and deactivate scheduled jobs and outbound
mail servers. Never expose the initially created administrator credentials.

The optional [generator guide](scripts/README.md) describes the explicit target
and opt-in needed to populate this exact demo database. It is not run during
installation or startup. Generation must be a deliberate separate operation.
The original business database name is always rejected by the generator.
Its full ORM generation was validated on 1.2.0; its 1.3.0 version guard is tested,
but generation was not repeated during publication preparation.

Start and inspect only this environment:

```sh
docker compose --env-file .env.demo -f compose.demo.yml up -d --wait
docker compose --env-file .env.demo -f compose.demo.yml ps
```

## Access

Open <http://127.0.0.1:8074/web/login?db=supplier_evaluation_demo> using the
credentials you configured. Navigate to **Purchase → Supplier evaluation**,
open a supplier and select **OTD evaluation**.

The service is local, not a hosted public demo. The database manager is hidden
and the database filter selects only `supplier_evaluation_demo`.

## Persistence and operations

Volumes are `odoo-supplier-evaluation-demo_demo-postgres` and
`odoo-supplier-evaluation-demo_demo-odoo`. Stop without deleting them:

```sh
docker compose --env-file .env.demo -f compose.demo.yml stop
```

Do not use `down -v` if you want to preserve data. Back up PostgreSQL and the
Odoo filestore together. Private `.env.demo`, `secrets/`, `credentials/`, dumps
and raw test evidence are intentionally excluded from the repository.
The shared addon source is mounted read-only; upgrading installed modules
still requires a deliberate database upgrade and service restart.
