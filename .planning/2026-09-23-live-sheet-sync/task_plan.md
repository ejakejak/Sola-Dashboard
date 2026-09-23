# Task Plan — SOLA Live Google Sheet <-> SQLite Two-Way Sync (REX)

## Goal
Build and LIVE-VERIFY a bidirectional READ/WRITE sync between the Google Sheet
`MASTER DATA SOLA 1.0` (id 1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA) and the
SOLA app's SQLite DB (D:/Sola/instance/sola.db). Reuse import_excel.py normalization.
SQLite remains the app runtime store; the Sheet is the master-data SOURCE OF TRUTH.

## Phases
- [complete] 1. INSPECT: live sheet tab layouts (HPP, MASTER HPP, Sheet3, DATABASE AGEN, DATABASE PENJAHIT/MAKLOON), confirm read+write access.
- [complete] 2. BUILD scripts/sync_sheet.py: --pull/--push/--dry-run/--compare, reuse import_excel normalization, dynamic tab-name reconciliation (slash vs no-slash).
- [complete] 3. VERIFY live: dry-run pull counts vs migration_report.json baseline; idempotency (run twice); write probe on scratch region + revert; safe reconcile real-pull on temp copy of live DB; --replace guard.
- [complete] 4. DOCS: docs/SYNC.md (authority direction, pull/push semantics, usage). Add gspread to requirements.txt as real dep.
- [complete] 5. FULL unverified: (a) unittest suite passes (87), (b) app on 127.0.0.1:5000 boots (GET / 302) + admin/sola123 login works.

## Deliverables (all delivered)
- scripts/sync_sheet.py (CLI) — verified; real DB/sheet write paths exercised on TEMP copies / scratch + probe.
- docs/SYNC.md
- requirements.txt (gspread==6.2.1 real dep)
- scripts/import_excel.py — backward-compatible refactor (run_migration_from_workbook + slash reconcile).

## Safety scope note
- NEVER mutated D:/Sola/instance/sola.db via sync tools (all sync writes to temp copies / scratch probe).
- Live sola.db changed only by the RUNNING APP (LOGIN audit_logs); master counts all baseline.
- PUSH to real sheet NOT executed (dry-run + planning + write probe proved instead).

## Safety
- NEVER mutate D:/Sola/instance/sola.db for tests -> use temp copy.
- Live sheet writes ONLY on scratch region, then revert (EVA marker-cell pattern).
- Report implemented vs verified separately.