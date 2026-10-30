# Testing

Never point test commands at a business or permanent demonstration database.
Use an independent PostgreSQL instance and a separate Odoo data directory.
The repository's integration-shell and browser launchers additionally require
names beginning with `supplier_evaluation_otd_`.

## Local tests (no database or Odoo import)

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Current result: **47 passed**. These tests exercise pure helper logic,
source-level invariants, demo-plan chronology and database/version guards;
they are not a substitute for real ORM tests.

## Real Odoo integration tests

Put the addon on a standard Odoo 18 addons path and use a new isolated database:

```sh
odoo-bin -c /path/to/test-odoo.conf \
  --data-dir=/path/to/disposable-odoo-data \
  -d supplier_evaluation_otd_test -i supplier_evaluation \
  --without-demo=all --test-enable --test-tags=/supplier_evaluation \
  --stop-after-init --no-http --max-cron-threads=0 --workers=0
```

The test configuration must connect only to the test PostgreSQL instance.
Do not use `-i` on an existing business database. To rerun on an isolated
installed copy, use `-u supplier_evaluation` in place of `-i`.

The final Odoo result must report **0 failed, 0 errors out of 138 tests**;
check the result line and exit status. Permission-denial messages and SQL
constraint violations intentionally exercised by negative tests are expected
inside those test cases. The per-module statistics may include setup methods
and differ from the final test-case count.

The optional `tests/odoo_integration.py` is a shell runner for an already
installed isolated copy. It rolls back its test transaction and refuses
permanent database names. It is not needed for the standard test command.

## Optional browser checks

Create a copy containing the validated fictional dataset, not a connection
to a permanent database. Use separate credentials and a local test server.
Install optional tooling in a virtual environment:

```sh
python3 -m venv .venv-browser
.venv-browser/bin/pip install playwright
.venv-browser/bin/python -m playwright install chromium
```

Set `OTD_UI_PASSWORD` privately in your shell. Then:

```sh
.venv-browser/bin/python tests/ui_supplier_otd.py \
  --base-url http://127.0.0.1:8075 \
  --database supplier_evaluation_otd_browser \
  --login demo_admin --output-dir backups/browser-check
```

The script verifies the ten fixed demo suppliers, sorting, the below-50%
filter, enlarged progress bars, isolation from standard forms, Supplier 05's
20/10/10 counters, five drilldown columns and renegotiation wizard.
Use `--language en_US` (default) or `--language ca_ES`; the script changes only
the temporary user’s language preference and creates an incomplete test order
to open the wizard without confirming an agreement. It briefly creates and removes
one no-data supplier **only in the temporary copy**. Its output includes
screenshots and a JSON summary. It never runs the generator.

Browser tooling is optional and is not imported by the installable addon.
Use `--browser-executable` for an existing Chromium executable if required.

## Recorded results

See [publication audit](PUBLICATION_AUDIT.md) for the fresh standard install,
and [historical UI results](../tests/UI_RESULTS.md) for Chromium evidence.
The historic demo generation report is [here](../tests/DEMO_RESULTS.md).
Raw logs, database backups and credentials stay outside version control.
