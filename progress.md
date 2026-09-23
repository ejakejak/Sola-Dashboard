# Progress Log — SOLA Phase 2 (REX)

## Session 2026-09-22 — Phase 2 COMPLETE

### Built
- `run.py`, `app/__init__.py`, `app/config.py`, `app/db.py`, `app/auth.py`, `app/masterdata.py`, `seed/seed_auth.py`, `.env`, `instance/company_settings.json`
- Templates: base/login/index/master_index/master_list/master_form/403/404; `app/static/css/app.css`

### Verified
- `tests/test_app_phase2.py` — **7/7 OK** (isolated temp DB): admin create customer ✓, warehouse 403 on customer create ✓, materials list loads ✓, master list loads with data ✓, audit row on create ✓, material update + audit ✓, anon redirect to login ✓.
- `tests/test_migration.py` — **13/13 OK** (no regression).
- Live smoke (server on 127.0.0.1:5000, real instance/sola.db): admin login 302→/; materials list 200 with 32 cards; customers/processes/vendors/agents/decorations/products lists 200 with real data; admin create customer `CUST-SMOKE-001` → audit CREATE/customer/1; **warehouse POST customer/new → 403** ("403 — Forbidden"); FK check `[]` clean. Smoke customer + its audit row removed afterwards (customers back to 0); 2 benign LOGIN audit rows remain.

### Delivered seed state (instance/sola.db)
roles 8 (ADMIN..CUSTOMER), permissions 15, role_permissions 31, users 8 (admin + 7 demo). Idempotent (re-run reports 0 new users). Default login `admin / sola123`.

## Errors encountered
| Error | Resolution |
|-------|------------|
| NameError `require_permission` in masterdata.py | Added to the `.auth` import line. |
| Jinja `c.items` resolved to dict method (not iterable) | Renamed card key `items`→`fields`. |
| `seed/seed_auth.py` run directly: No module named app | Run as `python -m seed.seed_auth` from project root. |
|| curl `-o /dev/null` "write error" on git-bash | Cosmetic wrapper notice; statuses still returned; used real output files for smoke test. |

---

## Session 2026-09-23 — Phase 9 COMPLETE (Security + QA + Docs + Deployment package)

### Security hardening
- **`scripts/rotate_admin_password.py` (new)** — ADMIN password rotation. Reads `SOLA_ADMIN_PASSWORD` env or interactive `getpass` prompt; enforces ≥10 chars and rejects the seeded default `sola123`; updates `users.password_hash`; writes an `ADMIN_PASSWORD_ROTATED` audit row (no plaintext stored).
- **`seed/seed_auth.py` no-clobber confirmed** — the existing upsert never rewrites `password_hash` on an existing admin, so re-seed does NOT reset a rotated password (locked in by new test).
- **`app/config.py`** — removed the hard-coded SECRET_KEY fallback (`dev-insecure-change-me`); now `FLASK_SECRET_KEY` MUST come from `.env` and the app fails fast at startup if it is missing.
- **Secret sweep of `app/ run.py seed/ scripts/`** — only hits were the comment, the config assignment, and the demo `DEFAULT_PASSWORD="sola123"` (intended demo default, rotation documented). No private keys / API keys in committed source. Service-account JSON lives in gitignored `instance/`.
- **Cleaned junk file** `seed/seed_auth.py\uf00apackage` (corrupted leftover, never imported) — deleted from source.

### QA (spec §32) — verified
- Full suite **87/87 OK** (`python -m unittest discover -s tests -p 'test_*.py'`); prior baseline 81, +6 new in `tests/test_app_phase9.py`.
- `PRAGMA foreign_key_check` on `instance/sola.db`: **empty**.
- **`docs/ACCEPTANCE.md`** — all 17 criteria (A–Q) **implemented & verified**, each mapped to a real test + route; 0 partial / 0 absent. Two honest boundary notes: (A) product/process/decoration create share the generic dispatcher (customer + material directly tested); (P) audit is a write-path convention (every mutating route calls `audit()`; 54 rows live) rather than a DB trigger.

### Documentation (spec §31)
- **`README.md`** (extended: real quickstart, env var table incl. `FLASK_SECRET_KEY`, rotate step, troubleshooting)
- **`docs/USER_ROLES.md`**, **`docs/API.md`**, **`docs/TESTING.md`**, **`docs/DEPLOYMENT.md`** (new)

### Deployment package + runbook
- **`dist/SOLA-1.0.0-deployment.zip`** (434,898 B, 93 entries) — excludes `.venv`, `__pycache__`, `.planning`, `_shots`, `instance/*.db` & `instance/*.json` (ships `instance/.gitkeep`), `.env`, dev upload images, 20 MB catalog PDF. Includes `.env.example`, `data/master.xlsx`, all `app/ db/ seed/ scripts/ tests/ docs/`, `run.py`, `requirements.txt`, `migrations/migration_report.json`.
- **`dist/RUN_ME.txt`** — one-page command runbook.
- **Clean-build validated from the extracted ZIP**: init_schema → seed → rotate → re-seed×2 (rotated pw still works, default fails, FK empty, 1 audit row) → `python run.py` boots, `GET /` 302→`/login?next=/`, `GET /track` 200.

### Notes / invariants
- Real `instance/sola.db` admin password **left untouched** (still the seeded default) by design — rotation is an explicit deploy-time step; the live app on :5000 was not interrupted (the parent's server was left running).