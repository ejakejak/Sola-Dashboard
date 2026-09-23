# Phase 5 — Sheet-Only Cutover: drop SQLite, spreadsheet is the live store

Status: DRAFT (in progress) — 2026-09-23
Decision: Doffy chose FULL CUTOVER — SQLite removed from the app entirely (one-way
migration from current data into the sheet; no SQLite backup/test baseline).
Directive: "we're not using SQL, just write on that spreadsheet it's okay to replace everything"

## What this means
- The app's live store becomes the Google Sheet (the SPREADSHEET_ID in env, "MASTER DATA SOLA 1.0").
- No SQLite at runtime; db.py and get_db() are retired from the app data path.
- A sheet cannot run SQL -> every table becomes a TAB; every query becomes
  load-tab -> logic-in-Python -> write-back.
- All 7 blueprints + dashboard + auth get rewritten to use the SheetsStorage tab-CRUD engine.

## Honest magnitude
~35 tables in db/schema.sql, ~149 SQL execute call sites, 27 commits, 5 rollbacks (inventory),
complex joins/aggregations for dashboard KPIs / invoices / orders. This is a large re-platform.
Approach: build a SheetRelation engine on top of SheetsStorage that models each table as a tab
with a primary key and foreign-key columns, and provides read/filter/insert/update/delete in
Python over loaded rows, so blueprints call the seam instead of SQL.

## Steps (check off)
- [ ] Audit db/schema.sql -> full table map (columns, keys, FKs) + seed data
- [ ] Audit every SQL call site across the 7 blueprints + dashboard + auth
- [ ] Define tab layout for every table on the live sheet (business tabs appended to master)
- [ ] Implement SheetRelation engine in app/storage.py (or app/sheetdb.py)
- [ ] One-way migration: export current sola.db rows -> write to the sheet tabs
- [ ] Rewrite blueprints to use the sheet engine (no SQL)
- [ ] Retire db.py / get_db() / sqlite from the app; update config + factory
- [ ] New behavior tests against a fake sheet; rerun boot smokes
- [ ] Report evidence

## Guardrails (my responsibility)
- Back up current sola.db BEFORE any sheet write (a local .bak) so the one-way step is recoverable
  even though the user doesn't want SQLite in the running app.
- Do not clear master-data tabs; append business tables as NEW tabs.
- Rerun the full existing suite until the sheet engine passes it (as the regression gate), then port.