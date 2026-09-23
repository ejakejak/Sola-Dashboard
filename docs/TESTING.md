# SOLA — Testing Guide

The suite is **stdlib `unittest` only** (no pytest dependency). Every test file
creates its own **isolated temporary SQLite database** from `db/schema.sql` and
seeds it in-memory/fixture — the real `instance/sola.db` is **never touched** by
tests.

## Run the full suite

```bash
cd D:\Sola
python -m unittest discover -s tests -p 'test_*.py'
```

Expected result (verified on 2026-09-22/23, Python 3.11 + Flask 3.1.1):

```text
Ran 87 tests
OK
```

`87 = 13 migration + 7 phase2 + 9 phase34 + 15 phase5 + 19 phase6 + 7 phase7 +
11 phase8 + 6 phase9`.

## Run one file

```bash
python tests/test_app_phase9.py          # single file
python -m unittest tests.test_app_phase9 # as a module
```

## Per-file coverage

| File | Tests | Covers |
|---|---|---|
| `tests/test_migration.py` | 13 | `scripts/import_excel.py` Excel→SQLite migration: no data loss, canonical material master, context variant prices kept separate, Kaos→Jersey alias, Kanvas trim, fee→commission-template mapping, phone leading-zero restore, stray-M1 flagged, FK integrity, idempotent re-run, source workbook untouched. |
| `tests/test_app_phase2.py` | 7 | Backbone + auth + master-data CRUD: anonymous redirect, admin create customer, warehouse 403 on customer create, master lists load, audit written on create + material update, backend permission enforcement. |
| `tests/test_app_phase34.py` | 9 | Commercial loop: quotation create/audit/numbering, approved-only & once-only conversion, invoice-from-order, payment→outstanding, PDF renders (no HPP/network), order + finance role behaviour, management read-only. |
| `tests/test_app_phase5.py` | 15 | Production + configurable workflow: seeded templates idempotent, template CRUD + `workflow.manage`, from-order auto `production_code` + stages + progress, stage advance recompute, completion status, update audited, media upload + INTERNAL/CUSTOMER visibility gate, internal-media gating for view-only roles, media requires `manage`, QC pass/rework/return-to-stage, QC permission, full permission matrix, idempotent auth seed. |
| `tests/test_app_phase6.py` | 19 | Inventory: 000 default, adjust/reserve/release/issue, guard rails (below-reserved rejected, over-reserve rejected, issue guarded), usage→OUT+usage row, permission matrix, view-roles read-not-write, backend-enforced Sales 403, warehouse-write, production-usage, **idempotent re-seed keeps ADMIN invariant**, low-stock badge, movements/usage views. |
| `tests/test_app_phase7.py` | 7 | Public `/track`: no login, valid code renders customer data **only**, CUSTOMER media served but INTERNAL not, HTML free of prohibited internals, generic not-found (no existence oracle), valid code clears fail-chain, rapid wrong guesses blocked (rate limit/cooldown). |
| `tests/test_app_phase8.py` | 11 | Dashboard: authed renders 6 KPI cards, anonymous redirect, KPI numbers match live DB, low-stock / unpaid-invoice / recent-updates alerts, production Kanban board (9 columns, cards bucket by stage, unsigned/overdue handled, compact-table toggle, management toggle hidden). |
| `tests/test_app_phase9.py` | 6 | **Security hardening (Phase 9):** admin rotation changes hash + writes audit (no plaintext), rotated password logs in / old default does not, **re-seed does NOT clobber rotated password** (×2 seeds), short password rejected, seeded default `sola123` rejected, FK integrity after rotation. |

## Database integrity

```bash
python -c "import sqlite3; from app.config import Config; \
c=sqlite3.connect(Config().DATABASE_PATH); print(c.execute('PRAGMA foreign_key_check').fetchall())"
```
An empty list means no foreign-key violations. Verified empty on `instance/sola.db`
(Phase 9), and both `tests/test_migration.py::test_foreign_key_integrity` and
`tests/test_app_phase9.py::test_06_fk_integrity_after_rotation` assert it within the
suite.

## Notes

- Tests set `PRAGMA foreign_keys=ON` (same as the app).
- A few Phase-7/8 tests emit `ResourceWarning` about an open upload file — harmless
  and non-failing.
- To smoke-test the live app instead: `python run.py` then open `http://127.0.0.1:5000`
  (login `admin`, restricted pages require their role).