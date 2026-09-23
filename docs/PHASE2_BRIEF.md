# Phase 2 — Route the App Behind the Storage Abstraction (Brief for REX)

## Status: DRAFT for approval — 2026-09-23
Change the `Status` line to `APPROVED` once Doffy signs off, then implement.

## Objective
Phase 1 built the storage abstraction (`app/storage.py`: `Storage`, `SqliteStorage`,
`SheetsStorage`, factory `get_storage`) and wired it into `app.extensions['storage']`, but
blueprints still import `get_db()` directly. Phase 2 makes the abstraction the **single
data-access path** for the running app: every blueprint obtains its connection/cursor through
`app.extensions['storage']`, while `SqliteStorage` preserves byte-for-byte the current
behavior. The `SheetsStorage` skeleton stays a skeleton — this phase does NOT implement live
sheet I/O (that is Phase 3).

This is the "glue" phase: it proves the abstraction is a real seam (so Phase 3 can swap the
backend without touching blueprints) with ZERO behavioral regression.

## Ground truth (surveyed by REX, 2026-09-23 — do not re-derive)
- DB-touch sites across blueprints: **68** (`commercial.py` 18, `production.py` 14,
  `inventory.py` 11, `masterdata.py` 6, `auth.py` 4, `dashboard.py` 3, `track.py` 3).
- All blueprints import `get_db` (and `audit`) via `from .db import get_db, audit`; they call
  `db = get_db()` then use the raw connection.
- Connection-API methods actually used (from grep across `app/*.py`, excluding storage/db):
  `execute`(×149), `fetchone`(×58), `fetchall`(×47), `commit`(×27), `rollback`(×5 — all in
  `inventory.py`), `close`(×1 — in `app/db.py` teardown only, not blueprints).
- `track.py` also passes the connection into a helper: `_lookup_customer_view(get_db(), code)`.
- No `executemany`, no in-request `row_factory` assignment, no `executescript` in blueprints.
- The app's write pattern is multi-statement: several `execute()` calls followed by ONE
  `db.commit()` (and `rollback()` on error in inventory). This matters — see Design Decision D1.

## Scope — deliverable for Phase 2
1. **Extend the `Storage` interface** (`app/storage.py`) so it can express how the app
   actually drives the DB today:
   - `execute(sql, params=())` — run a statement, return a cursor, **NO implicit commit**
     (lets callers batch then commit exactly as today).
   - `commit()` and `rollback()` — explicit transaction boundaries (rollback is REQUIRED by
     inventory's 5 error paths; it is currently missing from the interface).
   - `lastrowid()`-equivalent — a way to read the last inserted row id from the most recent
     `execute` (commercial/production read `cur.lastrowid` implicitly). Concretely: add
     `insert(sql, params=())` that performs the insert **without** committing and returns the
     cursor, so `cur.lastrowid` is available, matching Phase-1's existing `insert` signature
     but aligned to the no-implicit-commit rule.
   - Keep existing `query` / `fetchone` / `fetchall` / `audit` (already read-committed;
     no change).
   - **Design Decision D1 — commit semantics:** Phase 1's `SqliteStorage.execute/insert/
     update/delete` auto-commit after every write. The app instead batches writes then commits
     once. To migrate without changing behavior, Phase 2 redefines these to **not** auto-commit
     (rollback on error as today), and blueprints call `storage.commit()` where they currently
     call `db.commit()`. Update the Phase-1 unit tests accordingly (they assert auto-commit;
     they must be revised to assert the new batch semantics — this is a contract change, done
     deliberately and covered by tests).
2. **New `Storage.connection()` accessor** — returns a request-scoped connection suitable for
   passing to helpers that currently take `get_db()` (only `track._lookup_customer_view`
   today). `SqliteStorage.connection()` returns `get_db()` (the exact same per-request conn).
   Keeps the abstraction a drop-in for any remaining raw-connection needs without a DSL.
3. **Migrate all 7 blueprints** to source their connection from the storage layer:
   - Replace `from .db import get_db` with `from flask import current_app` (already imported in
     most) and `db = current_app.extensions['storage'].connection()`.
   - `track.py`: replace `_lookup_customer_view(get_db(), code)` with
     `_lookup_customer_view(current_app.extensions['storage'].connection(), code)`.
   - `db.commit()` → `current_app.extensions['storage'].commit()` (or a module-local
     `_storage()`/`_db()` helper per blueprint to keep glue thin).
   - `db.rollback()` → `current_app.extensions['storage'].rollback()`.
   - Keep `from .db import audit` (audit is a storage concern; see D2) — or route audit through
     `storage.audit(...)` where it already exists. Do the minimum churn that achieves the seam.
   - **Do NOT rewrite query SQL** or change any logic — pure plumbing/accessor swap.
4. **`app/db.py`** — unchanged. `get_db()` remains the connection source that
   `SqliteStorage.connection()` delegates to. (It is the sqlite adapter's private impl detail.)

## Design decisions (to confirm in review)
- **D1 — commit/rollback semantics:** Storage write primitives stop auto-committing; explicit
  `commit()`/`rollback()` added. Phase-1 tests updated to the new contract. Rationale: matches
  app's real transactional pattern; makes the seam honest.
- **D2 — audit:** `audit()` stays importable from `.db` and also reachable via
  `storage.audit(...)`. Blueprints may keep `from .db import audit` (lowest churn); the storage
  seam is the *connection + commit* path. (If you'd prefer audit fully routed through the
  storage layer too, say so — it is 3 import sites, cheap either way.)
- **D3 — migrate all sites vs. only the hot path:** recommend ALL 68 sites so Phase 3 swaps one
  backend, not a mix.

## Hard constraints
- **ZERO behavioral regression.** Full existing suite (87 baseline + 15 Phase-1) must pass
  unchanged in COUNT; where Phase-1 tests assert old auto-commit semantics, update THEM to the
  D1 contract (that is a sanctioned contract change, not a behavior change to the app).
- Blueprint SQL and business logic unchanged — only connection acquisition + commit/rollback
  plumbing.
- `db/schema.sql`, `scripts/sync_sheet.py` untouched.
- `SheetsStorage` remains config-validating skeleton; no live Google API calls.
- No new dependencies.

## Tests to add (behavior contracts)
- `SqliteStorage.connection()` returns the same request-scoped connection as `get_db()` inside
  an app context (identity check).
- Write primitives no longer auto-commit: `execute`+`insert`+`update`/`delete` then
  `commit()` persists; without `commit()`, `rollback()` discards. Both asserted against a temp
  DB with context managers (single-connection visibility: use the SAME storage connection).
- `rollback()` discards a batch; a subsequent `commit()` on a fresh batch persists.
- `lastrowid` available via `insert(...)` cursor before commit.
- Blueprint regression is already covered by the existing suite passing unchanged (87+15) —
  that is the seam proof.

## Verification (run and REPORT real output)
```
cd /d/Sola && export PYTHONPATH=.
C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m unittest discover -s tests -p 'test_phase1*' -v
C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m unittest discover -s tests -v       # must be 87+15+n
```
Plus boot smoke on default config and `STORAGE=sheets` (same as Phase 1), report status/errors.

## Report back (evidence, not optimism)
- Exact files created/modified.
- New/updated test names + counts; full-suite result (must be 102+ post-migration).
- The final mapping of each blueprint's `get_db`/`commit`/`rollback` call sites to the storage
  seam (or a clear statement that all 68 are covered).
- Boot smokes for both configs.
- Plan dir for this phase.
- Anything you could NOT do and why. Never report a stub as working.