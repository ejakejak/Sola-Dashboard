# SOLA Phase 1 — Storage Abstraction Foundation (Brief for REX)

## Objective
Introduce a storage abstraction layer into the SOLA Konveksi Flask+SQLite app so the data source becomes pluggable (`STORAGE=sqlite|sheets`), defaulting to `sqlite` with ZERO behavioral regression. This is the foundation for later phases that switch live reads/writes to Google Sheets.

## Project facts (verified by EVA — do not re-derive)
- Root: `D:/Sola`. Flask app, stdlib `sqlite3` only (no ORM).
- Current data access: `app/db.py` exposes `get_db()` returning a per-request `sqlite3.Connection` with `row_factory = sqlite3.Row`. All blueprints (`masterdata.py`, `commercial.py`, `production.py`, `inventory.py`, `dashboard.py`, `track.py`, `auth.py`) import `get_db` from `.db`.
- Config: `app/config.py` `Config` class. `DATABASE_PATH` derived from `DATABASE_URL` env (default `sqlite:///instance/sola.db`). App factory: `app/__init__.py` `create_app()` sets `app.config["DATABASE_PATH"]` and registers blueprints.
- Schema: `db/schema.sql` (~35 tables; `db/init_schema.py` runs it). Master+tables references in `docs/SYNC.md`.
- Baseline tests: `python -m unittest discover -s tests` → **87/87 pass** (measured by EVA, ~88s). Entrypoint: `PYTHONPATH=. <hermes venv python> run.py` on :5000.

## Scope — deliverable for Phase 1
1. New `app/storage.py` with an abstract `Storage` interface and two implementations:
   - `SqliteStorage` — wraps the existing `get_db()` behavior (delegate to existing `app/db.py`; do NOT rewrite all queries in this phase).
   - `SheetsStorage` — **skeleton only**: a concrete class that validates config (SPREADSHEET_ID + service account present) and exposes the same interface methods as `NotImplementedError` stubs. NO live Google API calls in this phase. It must import cleanly even when no credentials/sheet config exist.
   - The interface should cover what Phase 3 needs: `query` / `execute` / `insert` / `update` / `delete` / `fetchone` / `fetchall` / `audit` primitives — align names with what the app actually uses so the glue is thin. Keep it minimal; do not invent speculative surface.
2. Config: add `STORAGE` to `Config` (env-driven, default `sqlite`), plus optional `SPREADSHEET_ID` / `GOOGLE_APPLICATION_CREDENTIALS` passthrough (do not fail the app when absent — only `SheetsStorage` construction fails, and only if someone selects `sheets`).
3. Wire `create_app()` to instantiate the selected storage backend and expose it as `app.extensions["storage"]` (or `g.storage`), defaulting to `SqliteStorage`. Existing blueprints keep using `get_db()` unchanged in Phase 1 — the abstraction exists but is not yet the primary query path. The app must still boot with `STORAGE` unset, exactly as today.
4. Selection logic lives in `app/storage.py` (factory `get_storage(config)`), so Phase 3 swaps cleanly.

## Hard constraints
- **Zero regression**: with default config, the app must behave identically and the full 87-test suite must pass unchanged.
- Min dependency footprint: only reuse what's already installed. `gspread` is already in `requirements.txt` (used by `scripts/sync_sheet.py`) but this phase must not require it at import time for the sqlite path.
- Do NOT modify `db/schema.sql`, blueprints' data logic, or `scripts/sync_sheet.py`.
- No secrets in source; `.env.example` placeholders only.
- Follow planning-with-files: create `D:/Sola/.planning/2026-09-23-phase1/` with `task_plan.md` / `findings.md` / `progress.md` and check off phases as you go.

## Tests to add (behavior contracts, not change-detectors)
- Storage factory returns `SqliteStorage` when `STORAGE` unset or `sqlite`.
- `get_storage` returns `SheetsStorage` when `STORAGE=sheets`, and it constructs but its data methods raise `NotImplementedError`.
- `SqliteStorage` wraps `get_db()` and a representative query works against a temp DB.
- App boots with `STORAGE` unset (no env) and with `STORAGE=sheets` with no creds (app boots; only a SheetsStorage data call would raise).
- Re-run the full existing suite → still 87/87.

## Verification commands (run and REPORT real output)
```
cd /d/Sola
export PYTHONPATH=.
C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m unittest discover -s tests -v    # full suite
C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m unittest discover -s tests -p 'test_phase1*' -v
```
Also smoke: boot the app with default env and with `STORAGE=sheets`, report status/errors.

## Report back (evidence, not optimism)
- Exact files created/modified.
- New test names + pass counts.
- Full-suite result (must be 87/87).
- Boot smokes for both configs.
- Plan dir path.
List anything you could NOT do and why. Never report a stub as working.