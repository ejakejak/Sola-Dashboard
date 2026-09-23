# SOLA — Local Single-PC Deployment (Windows)

SOLA is a **local-first, single-process** Flask application with a SQLite database.
This guide deploys it on one Windows PC (the business machine). Multi-worker /
Redis / cloud scaling is **out of scope by design** — the app is explicitly not
built for it.

The deployable artifact is `dist/SOLA-1.0.0-deployment.zip`; unpack it anywhere on
the target PC (for example `D:\Sola`). The steps below also work on a fresh clone.

## Prerequisites

- Windows 10/11
- Python **3.11** (3.10–3.12 fine) on `PATH` (`py -3` works)
- Internet once, to `pip install Flask`

## 1. Unpack the deployable

```bash
cd D:\
# unzip dist/SOLA-1.0.0-deployment.zip  ->  creates a `SOLA/` folder
# or:  tar -xzf dist/SOLA-1.0.0-deployment.zip
cd D:\Sola
```

The package intentionally contains **no** secrets and **no** database. It ships an
empty `instance/` (with `.gitkeep`) and `.env.example` (placeholders only).

## 2. Create a virtualenv + install

```bash
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt         # Flask==3.1.1 (+ auto deps)
```

## 3. Configure the environment

```bash
copy .env.example .env
```
Edit `.env`:

| Key | Action |
|---|---|
| `FLASK_SECRET_KEY` | **Required.** Generate: `python -c "import secrets; print(secrets.token_hex(32))"` and paste. The app **refuses to start** without it. |
| `DATABASE_URL` | Leave as `sqlite:///instance/sola.db` unless you relocate the DB. |
| `SOLA_HOST` / `SOLA_PORT` | Leave `127.0.0.1` / `5000` for a local-single-PC install. |
| `SPREADSHEET_ID`, `GOOGLE_APPLICATION_CREDENTIALS` | Only needed to re-pull/refresh the Excel master source. On a fresh machine, copy the service-account JSON into `instance/` and point `GOOGLE_APPLICATION_CREDENTIALS` at it. If unused for re-migration, they can stay as placeholders. |

> `.env` and `instance/` are gitignored and are **excluded** from the deployment
> package; they are created **on the target machine**, so no secret ever ships.

## 4. Initialise the schema

```bash
python db/init_schema.py                 # applies db/schema.sql to instance/sola.db
```

## 5. Migrate master data from Excel (first time, if you have the source sheet)

Pulled `data/master.xlsx` must exist (migration source, link-shared from the
Google Sheet). Then:

```bash
python scripts/import_excel.py           # writes migrations/migration_report.json
```
If you are redeploying onto an existing database, **skip this step** — re-importing
would duplicate data. The migration is safely idempotent only for a fresh DB.

## 6. Seed roles / permissions / users + catalog + workflow templates

```bash
python -c "from seed.seed_auth import ensure_seeded; from app.config import Config; ensure_seeded(Config().DATABASE_PATH, verbose=True)"
python -c "from seed.seed_production import seed_workflow_templates; from app.config import Config; seed_workflow_templates(Config().DATABASE_PATH, verbose=True)"
python -c "from seed.seed_catalog import seed_catalog; from app.config import Config; seed_catalog(Config().DATABASE_PATH, verbose=True)"
```
(`run.py` re-runs all three on every boot, so the above are belt-and-braces.)

## 7. Rotate the ADMIN password — REQUIRED before real use

The seeded admin is `admin / sola123`. **Do not leave it.** Rotate it once:

```bash
# Windows cmd / PowerShell (env var):
set SOLA_ADMIN_PASSWORD=ChangeMe!2026 && python scripts/rotate_admin_password.py
# or interactive:
python scripts/rotate_admin_password.py
```

The script enforces a 10-char minimum, rejects `sola123`, and writes an
`ADMIN_PASSWORD_ROTATED` audit row. Re-seeding later (e.g. every `run.py` boot)
does **not** overwrite the rotated hash.

## 8. Run

```bash
python run.py
# open http://127.0.0.1:5000
```

## 9. Verify

- Log in as `admin` (rotated password) / restricted users with their roles.
- `python -m unittest discover -s tests -p 'test_*.py'` → `Ran 87 tests … OK`.
- FK integrity: `python -c "import sqlite3;from app.config import Config;print(sqlite3.connect(Config().DATABASE_PATH).execute('PRAGMA foreign_key_check').fetchall())"` → `[]`.

## Operational notes

- **Backup**: stop the app, copy `instance/sola.db` (and `data/`, `migrations/` if
  you want the migration trail). SQLite backup = file copy.
- **Upgrade SQLA**: applies to the running DB only — this is a local single-process
  design, so no rolling-restart concerns.
- **Logs**: Flask prints to the console; `/track` rate-limit blocks are logged there
  and to your shell.

## Out of scope (by design)

- Multi-process / multi-worker serving, Redis-backed sessions/rate limits, remote
  multi-user deployment. If SOLA later needs concurrent multi-user access on a LAN,
  that is a separate project (move off SQLite + single Flask process, add a real
  auth proxy / TLS); this package does not attempt it.