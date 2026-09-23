# Phase 1 — Storage Abstraction Foundation (REX)

Plan dir: `D:/Sola/.planning/2026-09-23-phase1/`
Brief: `D:/Sola/docs/PHASE1_BRIEF.md`
Status date: 2026-09-23
Owner: REX (developer specialist), coordinated by EVA.

## Goal
Introduce a pluggable storage abstraction (`STORAGE=sqlite|sheets`, default `sqlite`) with ZERO behavioral regression. Blueprints keep using `get_db()` in this phase; the abstraction is wired but not yet the primary query path.

## Phases
- [x] P0 — Read brief + recon source (config.py, __init__.py, db.py, run.py, test conventions)
- [x] P1 — Create plan files (.planning/2026-09-23-phase1/)
- [x] P2 — `app/storage.py`: abstract `Storage` + `SqliteStorage` + `SheetsStorage` + factory `get_storage(config)`
- [x] P3 — `app/config.py`: add `STORAGE`, `SPREADSHEET_ID`, `GOOGLE_APPLICATION_CREDENTIALS`
- [x] P4 — `app/__init__.py` `create_app()`: wire `app.extensions["storage"] = get_storage(cfg)`
- [x] P5 — behavior-contract tests (tests/test_phase1_storage.py) → 15/15
- [x] P6 — Full suite (102 OK: 87 baseline + 15 new) + boot smokes (default & STORAGE=sheets) both clean
- [x] P7 — Report evidence

## Hard constraints (from brief)
- Zero regression: full 87-test suite passes unchanged.
- No new deps required at import time for sqlite path (gspread not imported).
- Do NOT modify: db/schema.sql, blueprint data logic, scripts/sync_sheet.py.
- No secrets in source; .env.example placeholders only.
- Boot must work with STORAGE unset, exactly as today.
- SheetsStorage: skeleton; config-validating; data methods raise NotImplementedError; imports clean with no creds.

## Deliverables
1. app/storage.py (Storage, SqliteStorage, SheetsStorage, get_storage)
2. Config: STORAGE, SPREADSHEET_ID, GOOGLE_APPLICATION_CREDENTIALS
3. create_app() → app.extensions["storage"]
4. tests/test_phase1_storage.py
5. Full suite 102/102 (87 baseline + 15 new) + boot smoke evidence