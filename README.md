# SOLA — Konveksi & Production Management System

Greenfield build for SOLA (custom merchandise / konveksi business). A local-first
SQLite + Flask web application for master data, the commercial loop
(quotation → order → invoice → payment), production workflow (stages / updates /
media / QC), inventory, customer tracking `/track`, and a dashboard.

Source of truth: Google Sheet **`MASTER DATA SOLA 1.0`** (id
`1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA`), pulled link-shared to `data/master.xlsx`.
Excel is the **migration source only** — never the runtime store. Project root: `D:/Sola`.

> Local single-machine deployment only. The app is a single Flask process on
> SQLite; multi-worker / Redis / cloud scaling is out of scope by design
> (see `docs/DEPLOYMENT.md`).

## Repository surface

| Path | Purpose |
|---|---|
| `run.py` | Entry point — seeds (if needed) then serves `http://127.0.0.1:5000` |
| `app/` | Flask application (blueprints: auth, masterdata, commercial, production, inventory, track, dashboard) |
| `db/schema.sql` | Relational schema (FK-enabled, audit-grounded); `db/init_schema.py` applies it |
| `scripts/import_excel.py` | Excel → SQLite migration/import + `migrations/migration_report.json` |
| `scripts/rotate_admin_password.py` | **New (Phase 9)** — rotate the ADMIN password, never ships `sola123` |
| `seed/seed_auth.py` | Idempotent seed: 8 roles + 33 permissions + admin/demo users |
| `seed/seed_catalog.py`, `seed/seed_production.py` | Product/catalog + workflow-template seeds |
| `tests/` | Full unittest suite (isolated temp DB — never touches `instance/sola.db`) |
| `docs/` | Design/audit/deployment documentation (`docs/API.md`, `docs/DEPLOYMENT.md`, …) |
| `dist/` | Deployment package `SOLA-1.0.0-deployment.zip` + `RUN_ME.txt` |

## Quickstart (Windows, local single PC)

```bash
cd D:\Sola
# 1. create + activate a virtualenv (first time)
py -3 -m venv .venv
.venv\Scripts\activate
# 2. install dependencies
pip install -r requirements.txt          # Flask==3.1.1
# 3. configure environment (first time) — copy template, then EDIT values
copy .env.example .env
#    → set FLASK_SECRET_KEY to a long random value (see "Environment variables")
# 4. create the schema + migrate master data (first time)
python db/init_schema.py
python scripts/import_excel.py
# 5. seed roles/permissions/users + catalog + workflow templates
python -c "from seed.seed_auth import ensure_seeded; from app.config import Config; ensure_seeded(Config().DATABASE_PATH, verbose=True)"
# 6. ROTATE the ADMIN password — the seeded admin/admin+sola123 must NOT ship (Phase 9)
SOLA_ADMIN_PASSWORD='ChangeMe!2026' python scripts/rotate_admin_password.py
# 7. start the app
python run.py                             # http://127.0.0.1:5000
```

`run.py` itself re-runs the idempotent seeds (auth, production templates, catalog)
on every boot, so steps 5–6 are only strictly needed once. Rotation is **idempotent**:
re-running `run.py` (re-seed) does **not** reset a rotated ADMIN password.

## Environment variables

`.env` is **gitignored**; copy `.env.example` → `.env`. All vars are optional
except `FLASK_SECRET_KEY`, which the app requires at startup (fail-closed — see below).

| Variable | Default | Purpose |
|---|---|---|
| `FLASK_SECRET_KEY` | — **(required)** | Secret key for signed session cookies. Set a long random value; **the app refuses to start without it** (no hard-coded fallback). |
| `DATABASE_URL` | `sqlite:///instance/sola.db` | SQLite path (relative to project root). |
| `SOLA_HOST` / `SOLA_PORT` | `127.0.0.1` / `5000` | Bind address / port for `run.py`. |
| `RATE_LIMIT_WINDOW_SECS` | `3600` | `/track` per-IP rate-limit window. |
| `RATE_LIMIT_MAX_PER_WINDOW` | `20` | Max lookups per IP per window. |
| `RATE_LIMIT_FAILED_THRESHOLD` | `5` | Consecutive failed lookups before cooldown. |
| `RATE_LIMIT_COOLDOWN_SECS` | `90` | Cooldown after failure threshold. |
| `TRACKING_RATE_LIMIT` | `30` | Legacy alias (documented; `RATE_LIMIT_*` are authoritative). |
| `SPREADSHEET_ID` | `1z2cV5C…` | Google Sheet id (migration source). |
| `GOOGLE_APPLICATION_CREDENTIALS` | `D:/Sola/instance/sola-509413-service-account.json` | Service-account key path (gitignored; for sheet read/write). |
| `SOLA_ADMIN_PASSWORD` | — | New ADMIN password for `scripts/rotate_admin_password.py`. |

### Generating a secret key

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Paste the output into `.env` as `FLASK_SECRET_KEY=…`.

## Roles & permissions (spec §24)

8 roles enforced **in the backend** (every protected route re-checks the
permission server-side; hiding a button is only a surface expression):

`ADMIN`, `SALES`, `PRODUCTION`, `WAREHOUSE`, `QC`, `FINANCE`, `MANAGEMENT`, `CUSTOMER`.

CUSTOMER has no dashboard login — it is the `/track` public surface only.
Full per-role matrix: **`docs/USER_ROLES.md`**.

## Changing the ADMIN password (one-time upgrade)

The seeded bootstrap admin is `admin / sola123` (demo only). In production you
must rotate it once so the default never ships:

```bash
# non-interactive (envar):
SOLA_ADMIN_PASSWORD='ChangeMe!2026' python scripts/rotate_admin_password.py
# interactive prompt:
python scripts/rotate_admin_password.py
```

Rules enforced by the script:

- minimum **10 characters**;
- the seeded default `sola123` is **rejected**;
- it writes an `ADMIN_PASSWORD_ROTATED` row to `audit_logs` (the plaintext is
  **never** stored — only a non-secret marker).

Re-seeding (`run.py` / `seed_auth.ensure_seeded`) does **not** overwrite the
rotated hash — verified by `tests/test_app_phase9.py::test_03_reseed_does_NOT_clobber_rotated_password`.

## Testing

The full suite is standalone `unittest` (no pytest) and runs against isolated
temporary databases per test file. **87 tests** across 8 files:

```bash
cd D:\Sola
python -m unittest discover -s tests -p 'test_*.py'
```

See `docs/TESTING.md` for per-file coverage.

## API / routes

Route catalog (method, path, permission): **`docs/API.md`**.

Public surface: `GET /track` and `GET /track/media/<code>/<file>` require **no
login** and are rate-limited; every other route requires authentication.

## Delivery / deployment package

See **`docs/DEPLOYMENT.md`** for the full local single-PC runbook. A ready-to-run
package is produced at `dist/SOLA-1.0.0-deployment.zip`; open `dist/RUN_ME.txt`
for the exact command sequence.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: FLASK_SECRET_KEY is not set` | `.env` missing / key empty | Copy `.env.example` → `.env`, set `FLASK_SECRET_KEY`. |
| `no such table: users` on first login | Schema not created | `python db/init_schema.py`. |
| Password `sola123` no longer works | Admin rotated (Phase 9) | Use the new password; re-running `run.py` won't reset it. |
| `migrations/migration_report.json` missing | Migration not run | `python scripts/import_excel.py`. |

## Acceptance criteria

See **`docs/ACCEPTANCE.md`** — all 17 criteria (A–Q) implemented and verified
against the real test suite and routes.
