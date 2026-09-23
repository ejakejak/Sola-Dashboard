# SOLA Live Sheet ↔ SQLite Sync

This document explains how the SOLA konveksi app keeps master data in sync between the
Google Sheet **MASTER DATA SOLA 1.0** (the SOURCE OF TRUTH for master data) and the
app's local-first SQLite runtime store **`D:/Sola/instance/sola.db`**.

Script: `scripts/sync_sheet.py`. It is a CLI — there is deliberately **no web button**:
adding a route would touch the running app surface, and the sync is a maintained,
auditable operator action, so it stays a command-line tool (see *Why no web button*).

---

## 1. Direction of authority

```
                        PULL (sheet -> DB)  ─────────────────────────────►
                        authoritative; sheet wins
  ┌──────────────────┐                     ┌─────────────────────────────┐
  │  Google Sheet    │                     │  SQLite  sola.db            │
  │  MASTER DATA     │                     │  (app runtime store)        │
  │  SOLA 1.0        │                    │                            │
  └──────────────────┘                     └─────────────────────────────┘
                        ◄── PUSH (DB -> sheet)
                        opt-in, app wins ONLY on the flat agent/vendor tabs
```

* **Sheet is the source of truth** for master data: materials, prices, processes,
  categories, colors, sizes, units, agents, vendors, vendor capabilities, commission
  templates.
* **PULL** brings the sheet's master data into SQLite. This is the primary, safe,
  routine direction. Because the live DB carries *business* rows (products, variants,
  inventory, orders, quotations) that reference master rows, PULL **reconciles by
  natural key (upsert) and never deletes** master rows that those business tables
  depend on. A destructive full wipe+replace is available only via `--replace` and only
  on a DB with **no** dependent business rows (see *Safety*).
* **PUSH** writes app-side changes back to the sheet, but **only** the flat tabs that map
  1:1 to app tables:
  * `DATABASE AGEN` → `agents` (name, address, phone, faculty, campus)
  * `DATABASE PENJAHIT/MAKLOON` → `vendors` (name, address, phone, specialization)
  Pivot tabs (`HPP`, `Sheet3`) and `MASTER HPP` are **pull-only**: their layout is a
  derived normalization of the relational DB (e.g. the context-variant material codes
  `DR-AM-KR`/`DR-AM-VS` collapse into one `materials` row), so reconstructing them from
  the DB would be lossy. No master value flows down on PUSH.

The chat ordering rule: **when in doubt, PULL.** Never PUSH unless an operator has
deliberately edited an agent/vendor in the app and wants it to survive on the sheet.

---

## 2. Pull vs push semantics

| Op | CLI | Writes | What it does |
|----|-----|--------|--------------|
| PULL (dry-run) | `--pull --dry-run` | none | Imports the live sheet into an isolated **temp DB** and prints the resulting counts. Verifies the sheet parses + normalizes identically to the local `data/master.xlsx` baseline (see *Verification*). |
| PULL (real) | `--pull --yes` | sola.db | Builds the sheet snapshot in a temp DB (reusing `scripts/import_excel.py` normalization), then **reconciles** it into the target DB by natural key (upsert) — `materials`, `processes`, `product_categories`, `units`, `sizes`, `colors`, `material_prices`, `process_prices`, `commission_templates`, `agents`, `vendors`, `vendor_capabilities`, `cost_components`. Deletes nothing; business tables are untouched. |
| PULL (replace) | `--pull --replace --yes` | sola.db | Full wipe + replace of the import domain. **Refused** if any business table references master rows. Only for a fresh/migration DB. |
| PUSH (dry-run) | `--push --dry-run` | none | Reports the agent/vendor diffs (DB → sheet) and the exact planned cell writes. |
| PUSH (real) | `--push --yes` | Sheet | Applies the planned agent/vendor writes to the sheet (update existing rows / append new ones). |
| COMPARE | `--compare` | none | Reports `only_sheet` / `only_db` / `changed` rows for agents & vendors, plus DB vs sheet-import counts. |

Safe defaults: **every operation is dry-run unless `--yes` is passed.** `--dry-run` is
the default posture for verification; the real write paths require an explicit `--yes`.

---

## 3. How to run it

```bash
# environment
export GOOGLE_APPLICATION_CREDENTIALS=D:/Sola/instance/sola-509413-service-account.json
export SPREADSHEET_ID=1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA

cd /d/Sola
PY=${HERMES_VENV:-C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe}

# 0. sanity: can the service account talk to the live sheet (read+write probe)?
PYTHONPATH=. $PY scripts/sync_sheet.py --probe-write

# 1. safe preview — live sheet -> temp DB counts (real DB untouched):
PYTHONPATH=. $PY scripts/sync_sheet.py --pull --dry-run

# 2. check the live sheet vs the live DB are in agreement:
PYTHONPATH=. $PY scripts/sync_sheet.py --compare

# 3. bring the live DB in line with the sheet (safe reconcile, no deletes):
PYTHONPATH=. $PY scripts/sync_sheet.py --pull --yes

# 4. preview / apply app-side agent+vendor edits back to the sheet:
PYTHONPATH=. $PY scripts/sync_sheet.py --push --dry-run
PYTHONPATH=. $PY scripts/sync_sheet.py --push --yes      # only if you deliberately edited vendors/agents

# (fresh/migration only) destructive full re-import:
PYTHONPATH=. $PY scripts/sync_sheet.py --pull --replace --yes --db /tmp/fresh.db
```

`--db`, `--schema`, `--report`, `--sheet-id`, `--credentials` override the defaults.

---

## 4. Tab-name note

The live sheet's vendor tab is **`DATABASE PENJAHIT/MAKLOON`** (with a slash); the
locally-downloaded `data/master.xlsx` snapshot uses **`DATABASE PENJAHITMAKLOON`**
(no slash). `scripts/import_excel.py` now resolves required sheets **slash-insensitively**
(`run_migration_from_workbook`), so the *same* import + normalization path handles both
sources. The xlsx-file import path is unchanged / backward compatible (legitimately
has no slash).

---

## 5. Why no web button (deliberate)

Exposing sync as an authenticated Flask route is *possible* but was **not** added: (a) it
would touch the surface of the already-running app (`app/__init__.py` + a route + nav),
raising destabilization risk for zero operational gain; (b) sync is a high-consequence
write (especially PUSH) that should be a deliberate, inspectable operator action, not a
click. Script CLIs are the deliverable. If a button is wanted later, gate it behind an
ADMIN `masterdata.*` permission and call `scripts/sync_sheet.py` as a subprocess in
dry-run-first posture.

---

## 6. Verification guide

Numbers are the expected import counts (identical to `migrations/migration_report.json`
and the local xlsx import):

| Table | Import count |
|-------|--------------|
| materials | 32 |
| processes | 15 |
| product_categories | 14 *(live DB may carry 16 because seed catalog adds extras)* |
| material_prices | 52 |
| commission_templates | 11 |
| agents | 2 |
| vendors | 17 |
| vendor_capabilities | 48 |
| cost_components | 118 |
| process_prices | 7 |

Run `git diff` is unavailable (D:/Sola is not a git repo). To re-verify locally:
```bash
PYTHONPATH=. $PY -m unittest discover -s tests -v     # full suite incl. migration 13 tests
```
The migration tests exercise the refactored `run_migration_from_workbook` via the
xlsx path and assert the same normalization guarantees.