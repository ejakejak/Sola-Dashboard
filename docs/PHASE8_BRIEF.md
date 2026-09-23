# PHASE 8 DEV BRIEF — SOLA Dashboard Analytics + Production Kanban Board [for @REX]

You are Developer (REX) under EVA. Build Phase 8 of the SOLA dashboard in D:/Sola — the Dashboard home (KPI cards + alerts) and the ProductionBoard Kanban — ON the verified app (Phases 0-7 done; 70 tests green). Reuse generic `get_db()`, existing `orders`/`invoices`/`payments`/`production_orders`/`production_stages`/`inventory` and the auth gate/`can()`. Additive; do not redo.

## Read first
- `docs/DESIGN_SPEC.md` — screen 1 (Dashboard: 6 KPI cards + board snapshot + alert stack + recent feed) and screen 3 (Production Board: 9-column Kanban, draggable cards, toolbar, compact-table toggle), §1.1 status tokens, Gold brand.
- `db/schema.sql` — integrity contract (reuse existing tables; no DDL unless documented-additive).
- `docs/DEV_BRIEF.md` (included) + `docs/AUDIT_REPORT.md` + `docs/DATA_DICTIONARY.md`.
- Full product spec §21 (Dashboard home) + §22 (Production Board): `C:/Users/muham/AppData/Local/hermes/cache/documents/doc_dfd0d1a07b14_PROMPT_AI_AGENT_DASHBOARD_KONVEKSI.txt`.

## Authorization/run notes
- Subagent on DeepSeek (`deepseek/deepseek-v4-flash-0731`) — cheap, intended; do NOT switch providers.
- Interpreter: `C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe`; app `cd /d/Sola && PYTHONPATH=. <venv-python> run.py` → 5000 (else 5001). Planning-with-files SOP.

## Scope — implement/test phase-by-phase (front-end + a little KPI/query logic)
1. **Dashboard home (`/`)** — replace the current placeholder index page with the real dashboard per DESIGN_SPEC screen 1:
   - **KPI cards** (computed from live DB, not hard-coded): Active Orders (count of orders not in completed/cancelled), In Production (count of `production_orders.status='in_progress'` or active), Waiting Payment (invoices outstanding > 0 / partially paid), Ready to Ship (production completed/COMPLETED stage but not yet shipped), Overdue (orders/productions past deadline not completed), Outstanding Invoice (sum of invoice `outstanding`).
   - **Low-stock alert** (inventory `available <= threshold`), **upcoming deadline** (nearest N production deadlines), **recent production update** feed (latest `production_updates`).
   - Cards, tabs, and light charts/bars — NOT a giant table; keep the status-color semantics (success/warning/danger/info/neutral).
2. **Production Board Kanban (`/production/board` or upgrade `/production`)** per DESIGN_SPEC screen 3:
   - Columns matching the workflow current-stage set: `ORDER → MATERIAL PREPARATION → CUTTING → SEWING → PRINTING → FINISHING → QC → PACKING → COMPLETED`. Bucket each `production_orders.current_stage` into its column (fallback: if a current_stage has no exact column, use the row's `status`; COMPLETED → last column).
   - Card per production: production code, customer, product, qty, deadline, overall progress (bar), stage/status badge, PIC if set, priority. Click card → existing production detail.
   - A **compact-table toggle** (all roles, per the accepted design default #6) switching between kanban and a dense list.
   - Drag-to-move stage is a nice-to-have (only if quick): implement as a POST per card (advance/drop to a column) — otherwise leave a prominent "Advance stage" button per card linking to the detail action; do NOT claim drag if not delivered.
3. **Alerts** (overdue productions, unpaid invoices, low stock) surfaced on the dashboard alert stack with status tokens.
4. **Tests** `tests/test_app_phase8.py`: (a) dashboard `/` (authed) renders the 6 KPI cards with numeric values and no server error; (b) KPI numbers match the live DB (e.g. count of active orders present on the page); (c) `/production/board` renders and every production card appears in the column matching its current_stage; (d) compact-table toggle present and shows all rows; (e) low-stock + overdue entries appear when the seeded data warrants. Run the FULL suite to confirm no regression.
5. **Nav** — Dashboard is `/`; add/keep Production Board nav (hidden by `can`). Keep Master/Quotation/Order/Invoice/Production/Inventory nav as-is.

## Rules
- KPI cards must derive from the DB (never hard-coded numbers); keep the query layer simple (stdlib sqlite). Status colors per DESIGN_SPEC.
- Read-only views for read-only roles; writes (advance stage) via existing production permission gates.
- Audit only real writes. Never invent business data — numbers come from the existing seeded rows.
- Additive schema allowed only if documented (prefer reuse).

## Report (English): files+routes+tests; verified behaviors (dashboard shows correct live KPI numbers matching DB; board buckets cards into the right stage columns; compact toggle works; alerts show), permission note, any schema change + why, blockers (exact error). Distinguish implemented vs boundary-prepared. Never fabricate — run the real code; on a hard blocker stop and report exactly.