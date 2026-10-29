# Installation

## Standard Odoo 18 Community

This addon is independent of the repository's Docker files. Install and
configure Odoo 18 Community and PostgreSQL using the normal Odoo procedure.
Use an Odoo service account with access to the custom addons directory.

Copy `addons/supplier_evaluation/` into a directory on `addons_path`. For
example, a source checkout could use:

```ini
[options]
addons_path = /opt/odoo/odoo/addons,/opt/odoo/addons,/opt/odoo/custom-addons
```

These paths are examples; retain the standard paths for your installation.
The final directory must contain `supplier_evaluation/__manifest__.py`.
Restart Odoo, update the Apps list in developer mode, remove the Apps filter
and install **Supplier Evaluation**. Or use the configured executable:

```sh
odoo-bin -c /path/to/odoo.conf -d supplier_evaluation_otd_test \
  -i supplier_evaluation --without-demo=all --stop-after-init
```

The only direct addon dependencies are `base`, `purchase`, `stock` and
`purchase_stock`. They are available in Community. Their standard dependency
chain supplies `account`, `mail`, `web`, `product` and `uom` references used
by this addon. There are no pip or binary requirements beyond normal Odoo.

Enable Purchase access for users who need evaluation totals. Purchase
managers can confirm deadline renegotiations. Inventory users have read
access to history, but do not gain access to supplier aggregates just by
having Inventory permissions. See [security](../SECURITY.md).

Open **Purchase → Avaluació de proveïdors**. A newly installed database, or
legacy completed lines without captured observations, can correctly show
`Sense dades`. Installing does not backfill or generate business data.

## Upgrades

Back up both PostgreSQL and the Odoo filestore. Test upgrades on a separate
database and data directory, with outbound mail and scheduled jobs disabled.
Run `-u supplier_evaluation --stop-after-init` against the intended database
using its existing configuration, then restart its service. Compare business
records and captured outcomes before and after. Do not run the demo generator
as part of an upgrade.

## Optional local Docker development

`docker-compose.yml` is a local convenience, not a production deployment:

```sh
cp .env.example .env
# Edit .env and replace the PostgreSQL password before starting.
docker compose up -d
```

Odoo binds to `127.0.0.1:8073`; PostgreSQL has no published host port.
Use the web database manager to create a **disposable** database with your
own credentials, then install the addon. This Compose file persists the
PostgreSQL volume; Odoo's image creates its own data volume. It does not
provide a complete managed filestore lifecycle, TLS, backups or production
hardening. In particular, preserve the existing Odoo volume when recreating
containers containing attachments.

For a separate local demo at `127.0.0.1:8074`, see [DEMO.md](../DEMO.md).
Templates are supplied; private configuration and credentials are intentionally
not included. No Docker command or database name is required by addon code.

## Compatibility references

- [Odoo 18 module manifest reference](https://www.odoo.com/documentation/18.0/developer/reference/backend/module.html)
- [Odoo 18 source installation](https://www.odoo.com/documentation/18.0/administration/on_premise/source.html)
