# PHASE 9 DEV BRIEF — SOLA Hardening, QA, Documentation & Deployment Package [for @REX]

You are Developer (REX) under EVA. This is the FINAL phase of the SOLA konveksi dashboard in D:/Sola. All phases done+verified (0-8, 81 tests green). Your job: security hardening, full QA + acceptance evidence, documentation deliverables, and a production deployment package. Reuse existing code; no new big features. Read `docs/DEV_BRIEF.md` and the product spec §27 (audit), §29 (testing list), §31 (deliverables), §32 (acceptance criteria) at `C:/Users/muham/AppData/Local/hermes/cache/documents/doc_dfd0d1a07b14_PROMPT_AI_AGENT_DASHBOARD_KONVEKSI.txt`.

Subagent on DeepSeek (`deepseek/deepseek-v4-flash-0731`) — cheap, intended, do NOT switch providers. Interpreter: `C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe`. App boot: `cd /d/Sola && PYTHONPATH=. <venv-python> run.py` (port 5000/5001). Planning-with-files SOP.

## Scope — do and verify, then produce deliverables
1. **Security hardening**
   - Default admin `admin/sola123` must NOT ship as-is. Add a `scripts/rotate_admin_password.py` (run interactively: read new password from env `SOLA_ADMIN_PASSWORD` or prompt; update `users.password_hash` for the admin + audit). Also change `seed/seed_auth.py` so it does NOT re-reset the admin password on re-seed when a real one already exists (idempotent seed must not clobber a rotated password). Document the one-time rotate step in README.
   - Ensure `FLASK_SECRET_KEY` comes from env (`.env`), not a hard-coded default in committed code; `.env`/`instance/` stay gitignored.
   - Confiria `audit_logs` exist for writes; no secrets in `app/` source (grep for obvious private_key/password literals) — flag/fix any.
2. **QA + acceptance evidence (spec §32)**
   - Run the FULL suite (all phases) and confirm green.
   - Produce `docs/ACCEPTANCE.md` — a checklist of all 17 acceptance criteria (A–Q) with a status (Implemented / Verified / How) mapped to where each is realized/tested (e.g. B→quotations module, I→production_media INTERNAL gating, L→/track timeline, M→/track no-leak tests, N→inventory, O→QC, P→audit_logs, Q→migration_report). Base status on the actual state; do not mark an item Verified unless you can point to a test or a live check you actually ran. Mark genuinely-absent items honestly (e.g. if a criterion is only partially met, say so).
   - DB integrity: `PRAGMA foreign_key_check` empty; note row counts.
   - A quick customer-surface leak sweep isn't needed again (Phase 7 tests cover it); but confirm no route serves INTERNAL media to anonymous (already covered).
3. **Deployment package + documentation (spec §31)**
   - Extend `README.md`: accurate quickstart (venv,pip install -r requirements.txt, init_schema, import_excel, seed (admin + rotate), run.py), env vars table, troubleshooting, upgrade-password instructions.
   - `docs/USER_ROLES.md` — the 8 roles and what each can do (from seed matrix).
   - `docs/API.md` — concise route/endpoint catalog (method, path, permission, purpose) gathered from the blueprints (auth, masterdata, quotations, orders, invoices, production, inventory, track).
   - `docs/TESTING.md` — how to run the full suite + what each test file covers.
   - `docs/DEPLOYMENT.md` — local single-PC deployment steps (Windows): prepare venv, env vars (.env.example→.env), init DB, migrate, seed, rotate admin password, run.py; note it's a local-first single-process app (SQLite), so a multi-worker/Redis deployment is out of scope.
   - These docs must match the real code (paths, commands). No placeholderables.
4. **Package** — create a `dist/SOLA-<v>-deployment.zip` containing the runnable project (excluding `.venv`, `__pycache__`, `.planning`, `_shots`, `instance/*.db` (include an empty `instance/.gitkeep`), `.env` secrets) + a one-page `RUN_ME.txt` with the step-by-step commands. `.gitignore` must still protect secrets.

## Rules
- No new features/routes unless required to close security/doc gaps. Keep scope to hardening + docs + packaging.
- Do NOT invent facts in docs — verify each command against the real project before writing it.
- Audit log rotation/milestone actions appropriately.
- Report: files changed/added, full-suite result, ADMIN password-rotation behavior verified (re-seed does NOT clobber), ACCEPTANCE.md status summary (count of A–Q implemented vs partial/absent), deployment file paths (README, USER_ROLES, API, TESTING, DEPLOYMENT, ACCEPTANCE, RUN_ME.txt, ZIP path), any secrets found/removed, blockers (exact error). Distinguish implemented vs boundary-prepared. Never fabricate.