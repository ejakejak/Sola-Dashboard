# Findings — Phase 1 Storage Abstraction

Session: 2026-09-23 (REX)

## Recon (source of truth, read directly)
- `app/db.py`: `get_db()` returns per-request `sqlite3.Connection` (row_factory=Row, PRAGMA foreign_keys=ON) using `current_app.config["DATABASE_PATH"]`, stored in `g`. `close_db` teardown. `audit()` helper inserts into `audit_logs` and commits.
- `app/config.py`: `Config` class with `__init__` loading `.env` via `_load_dotenv` then reading env. `DATABASE_PATH` derived from `DATABASE_URL` (default `sqlite:///instance/sola.db`). Raises RuntimeError if `FLASK_SECRET_KEY` unset (fail-closed). Pattern: `self.X = os.environ.get("X", default)`.
- `app/__init__.py`: `create_app(test_config=None)` → builds `cfg = Config()`, sets app.config keys, `app.teardown_appcontext(close_db)`, registers blueprints, sets `app.extensions["rate_limiter"]`. test_config overrides app.config via `app.config.update(test_config)` — but NOT the `cfg` fields (ra limiter uses cfg fields + setdefault).
- `run.py`: creates app, seeds, runs on SOLA_HOST/SOLA_PORT default 127.0.0.1:5000.
- `.env.example` already documents SPREADSHEET_ID + GOOGLE_APPLICATION_CREDENTIALS (placeholders/example values).
- Tests follow pattern: `_mkapp(db_path)` → `create_app({"TESTING":True, "DATABASE_PATH":db_path, "SECRET_KEY":...})`, then `create_schema(db_path)` + `ensure_seeded(db_path)`. Temp DB in `tempfile.TemporaryDirectory()`.

## Decisions
- Storage interface (exact brief §3 list, no speculative surface): `query`, `execute`, `insert`, `update`, `delete`, `fetchone`, `fetchall`, `audit`.
- `get_storage(config)` factory: reads `STORAGE` from a dict-like (app.config) OR object (Config) — supports test override via app.config. Unknown value → ValueError (fail fast). Default `sqlite`.
- `SheetsStorage.__init__` VALIDATES but does NOT raise at construction → app boots with `STORAGE=sheets` even with no creds (required by brief test). Missing config captured in `missing` / `_config_ok`. All data methods raise `NotImplementedError`. (Brief phrase "only SheetsStorage construction fails" is superseded by the explicit test requirement that the app boots with STORAGE=sheets + no creds; construction stays lenient, data calls raise.)
- `SqliteStorage` delegates to existing `app/db.get_db()`; executes within Flask app context; commits on write ops. Constructor does NOT touch the DB (no app context needed to construct) → safe to construct at create_app time.
- create_app wiring: set app.config["STORAGE"/"SPREADSHEET_ID"/"GOOGLE_APPLICATION_CREDENTIALS"] from cfg (so test_config can override STORAGE), then `app.extensions["storage"] = get_storage(app.config)`.

## Environment notes
- D:/Sola is NOT a git repository (git status fails). No VCS operations possible/needed.
- Use Hermes venv python: `C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe`.
- Full suite: `cd /d/Sola && export PYTHONPATH=. && <python> -m unittest discover -s tests -v` → baseline 87/87 (measured by EVA).