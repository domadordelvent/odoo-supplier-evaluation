# Contributing

Keep changes scoped and include tests for meaningful behavior changes.
Preserve frozen OTD observations and the distinction between technical date
edits and confirmed supplier agreements. Never weaken company boundaries or
use unrestricted `sudo()` to compute supplier metrics.

Use a separate Odoo 18 test database. Follow [the testing guide](docs/TESTING.md)
and include test results with a proposed change. Do not include database dumps,
real business data, private screenshots or local credentials.

The addon is LGPL-3. Contributions should use that license. No external
services, GitHub account or project Docker setup is required to develop or
install the addon. Technical documentation is currently partly Catalan;
the main README and publication guides are in English. Interface source strings
are English; maintain the standard Catalan catalog and see [I18N](docs/I18N.md).
