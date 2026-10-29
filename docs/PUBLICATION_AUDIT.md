# Publication audit — 2026-10-30

Release: **18.0.1.3.0**, matching `addons/supplier_evaluation/__manifest__.py`.
Baseline: `c0dcff8` (final validated interface and demo). This audit prepares
repository documentation; it does not publish or change deployed databases.

## Packaging and portability

The installable unit is `addons/supplier_evaluation`. Its direct dependencies
are standard Community modules: `base`, `purchase`, `stock`, `purchase_stock`.
References to account, mail, web, product and units of measure are supplied by
their dependency chain. There are no Enterprise modules or external Python
packages required by the addon. Browser tooling is optional and separate.

The addon contains no project database-name restriction, host filesystem path,
Docker API call, project configuration import or bundled credentials. Restrictions
on database names belong to the optional test/demo scripts, not the addon.

A fresh database was initialized using the unmodified official Odoo 18 image,
with only the repository's addon directory mounted read-only. No project Compose
file, private configuration, existing database, filestore or demo generator
was used. PostgreSQL ran in a new independent internal network with no host
port exposed.

Environment: Odoo Community **18.0-20260305**, PostgreSQL 15, Python supplied
by that image. Image digest:

```text
odoo@sha256:371e92a268be52d8c96f0212a2d46b34533f506441a738ef55009c99367a50bc
```

This verifies independence from this project's Docker configuration. A separate
source installation or OS package installation was not executed during the
audit; native installation commands are documented in `INSTALLATION.md`.
The standard image remains a test runtime, not an addon dependency.

## Results

| Check | Result |
| --- | --- |
| Fresh installation and dependency resolution | Passed |
| Standard Odoo integration runner | 135 cases, 0 failures, 0 errors |
| Integration execution time | 16.88 seconds, excluding installation |
| Local Python tests | 44 passed |
| Manifest paths, Python syntax and XML parsing | Passed |
| Demo Compose validation using example variables | Passed |
| Markdown links and release-version consistency | Checked before commit |
| Credentials and private file scan | No findings in candidate files |
| Existing Git historical blob scan | No known local secrets/private keys/token patterns found |
| Screenshot content and PNG metadata | Fictional data only; no text/EXIF chunks |

Odoo's statistics also include fixture/setup entries; the final result line
reports **135 test cases**, not 147 unique tests. Deliberate denial and constraint
checks inside negative tests do not represent failures when the final result
is zero errors.

Prior Chromium validation covered all ten fictional suppliers, native sort and
filter, the enlarged progress track, visibility of standard On-time Rate only
outside the dedicated form, and Supplier 05's 20/10/10 counters and line details.
The release documentation reuses those reviewed screenshots; no new browser
session or generator execution was needed for documentation-only changes.

Raw logs, hashes, container identifiers and audit evidence are kept under the
ignored local `backups/` directory. The new temporary services are stopped;
their databases/volumes are retained. Neither permanent database was accessed,
updated or modified during this publication audit.

## Security, permissions and license

History models grant read access to Purchase and Inventory users, with company
record rules. Purchase managers can create confirmations and use the transient
wizard; guarded model methods protect historical fields, edits and deletion.
The supplier aggregate uses purchase ACLs/record rules and selected authorized
companies. Existing integration tests cover permission denials, elevated ORM
calls, company isolation, cancelled/unknown/incomplete observations and immutable
snapshots. This is not an independent penetration test.

The existing manifest declares `LGPL-3`. The repository now includes the full
LGPL version 3 text in `LICENSE` and the GPL version 3 text it incorporates in
`COPYING`. Odoo is not vendored. No author identity, endorsement or repository
URL has been invented for the manifest. Its optional author/website metadata
can be completed by the repository owner later.

The scan checks known local credential values, private-key/token signatures
and forbidden file categories across candidate files and historical blobs.
It is a targeted review, not a guarantee against every possible secret format.
Fictional `.invalid` addresses and test-only identities are intentional.

## Problems corrected

- Added the missing English root README and separate installation, testing,
  security, contribution and GitHub publication guidance.
- Added the full license texts matching the existing manifest.
- Added three visually reviewed screenshots from the fictional demo, with
  provenance and privacy notes.
- Replaced stale deployment-specific demo instructions with portable setup
  instructions and provided private-file templates with placeholders.
- Corrected technical documentation claiming there was no custom CSS: there
  is one scoped SCSS rule, with no custom JavaScript.
- Marked historical test reports as historical rather than current deployment
  requirements. The current release is consistently 18.0.1.3.0; references to
  18.0.1.2.0 describe earlier validation or compatibility.
- Extended the optional generator's version check to accept the validated
  18.0.1.3.0 release as well as 18.0.1.2.0. One new pure test covers accepted
  versions, unsupported versions and module states. Database guards remain
  unchanged; no generation was executed and no business logic was changed.
- Expanded ignore rules for optional browser environments, reports and HARs.

## Remaining limitations and publication choices

- Existing Git author/committer metadata includes a non-GitHub-noreply email.
  Publishing the existing history exposes that attribution. No history rewrite
  or author identity change was performed; the owner should decide whether
  to retain it before publishing.
- No complete English UI translation, large-volume performance benchmark,
  mobile certification, Enterprise certification or other-major-version support.
- Frozen history has no legacy backfill and is not tamper-proof against direct
  SQL administrators. Supplier parents/children are not consolidated.
- The demo generator was fully ORM-validated on 1.2.0; only its compatibility
  guard was retested for 1.3.0 during this audit. Its protected database names
  and fixed historical dates are intentional.
- Docker examples are local conveniences, not production deployment recipes.
  Image tags are mutable; the exact tested digest is recorded above.
- Repository owner, visibility, optional author/website metadata and private
  vulnerability reporting settings remain publication-time choices.

The repository is technically ready for publication, subject to the owner's
Git-attribution privacy choice and normal final review. No GitHub operation
has been performed.
