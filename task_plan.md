# Task Plan — SOLA Phase 2 (REX): Flask app + auth + Master Data CRUD

## Goal
Build the Flask application backbone + backend-enforced role auth + Master Data CRUD for 7 resources, wired to the verified `instance/sola.db`. Modular monolith, stdlib sqlite3, Flask==3.1.1.

## Phases
1. **Skeleton** — `app/__init__.py` (factory), `app/config.py` (env/.env + company block), `app/db.py`, blueprints, `run.py`, `.env`. Status: complete
2. **Auth + Authorization** — 8 roles + 15 permissions + permission matrix + ADMIN bootstrap (+ demo users); login/session; `current_user`, `require_role`, `require_permission`; 403/404 pages; backend-enforced. Status: complete
3. **Master Data CRUD** — materials, products, processes, decorations, vendors, agents, customers (list/create/update), cards+forms. Status: complete
4. **Audit** — all writes -> audit_logs. Status: complete
5. **Tests** — `tests/test_app_phase2.py` (7 tests) pass. Status: complete
6. **Smoke test live app** — live server on 127.0.0.1:5000, routes hit with real data, 403 verified, stopped; smoke test data cleaned. Status: complete

## Deliverables
All delivered. Schema changes: NONE (reused existing roles/permissions/role_permissions/users/audit_logs + master tables).

## Owner decisions applied (2026-09-22)
- NPWP NOT used: not rendered/required in customer form or display; column left unused in DB.
- Company/invoice block (name/logo/phone/address/payment) seeded editable via `instance/company_settings.json` + `app/config.py` defaults.