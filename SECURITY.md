# Security

## Supported scope

This release targets Odoo 18 Community. Use Odoo's normal authentication,
Purchase/Inventory groups and company configuration; this addon adds no
public HTTP controller or unauthenticated API.

Purchase users can read supplier aggregates and contributing purchase lines,
subject to their existing ACLs, record rules and selected authorized companies.
Inventory users can read deadline history. Only Purchase managers can create
confirmed renegotiations through the guarded workflow. History and captured
outcomes are immutable through the module's supported ORM interfaces; direct
SQL administrators remain able to alter the database.

Cross-model SQL used for aggregate ordering is derived from an ORM selection
that applies purchase-line record rules. Percentages are not stored as global,
company-independent supplier fields.

## Reporting a vulnerability

Do not post credentials, database dumps, customer records or exploit details
in public issues. Once the repository is published, use GitHub's private
vulnerability reporting if its owner has enabled it. No private reporting
address or response-time commitment is configured in this repository yet.

## Credentials and local environments

Generate independent secrets for every environment. `.env` files, Odoo
configuration, filestores, logs, backups and credentials are ignored. Example
files contain placeholders only. Do not commit a rendered Docker configuration
or `docker inspect` output: either may contain environment credentials.

Compose examples bind Odoo to loopback and do not publish PostgreSQL. They
are local development examples, not an Internet-facing production deployment.
Snapshot, test and generator instructions require isolated databases.
