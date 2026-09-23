# PHASE 6 DEV BRIEF — SOLA Inventory & Stock Movements [for @REX]

You are Developer (REX) under EVA. Build Phase 6 (Inventory) of the SOLA dashboard in D:/Sola, ON the verified app (Phases 0-5 done: migrations, master data, auth/audit, commercial loop, production workflows). Reuse existing generic `require_permission()`/`audit()`/`get_db()` and the existing schema tables below. Additive only — do NOT redo prior work.

## Read first
- `docs/DEV_BRIEF.md` (non-negotiables), `docs/DESIGN_SPEC.md` (UI: screen 6 Inventory — table on-hand/reserved/available, low-stock badge, movement drawer; Gold brand).
- `db/schema.sql` — integrity contract. Tables ALREADY exist (reuse, no DDL unless documented-additive): `inventory`, `stock_movements`, `material_usage`, plus `materials`, `orders`, `production_orders`.
- `docs/AUDIT_REPORT.md`, `docs/DATA_DICTIONARY.md`, `docs/CATALOG_SOLA_2026.md`.
- Full product spec sections 18 (inventory), 24 (roles), 25 (UI), 27 (audit): `C:/Users/muham/AppData/Local/hermes/cache/documents/doc_dfd0d1a07b14_PROMPT_AI_AGENT_DASHBOARD_KONVEKSI.txt`.

## Authorization working note
- You run as a subagent pinned to `deepseek/deepseek-v4-flash-0731` (cheap, intended — do NOT switch provider).
- Interpreter to run/verify: `C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe`. App boot: `cd /d/Sola && PYTHONPATH=. <venv-python> run.py` → http://127.0.0.1:5000 (if busy use port 5001 briefly). Follow planning-with-files SOP.

## Scope — implement/test phase-by-phase
1. **Inventory records (`inventory`)**: list materials with `on_hand`, `reserved`, `available` (available = on_hand - reserved). If no row exists for a material, treat as 0/0/0. Provide a page to set/adjust on_hand (ADJUSTMENT) with a reason.
2. **Stock movements (`stock_movements`)**: record `IN | OUT | ADJUSTMENT | RESERVED | RELEASED` with quantity, unit, reference (order/order_item/adjustment), moved_by, notes. Every movement audited.
3. **Reserve/release (spec §18)**: when a confirmed order (or `RESERVE`) is recorded, move quantity to `reserved`; on fulfillment/`RELEASED` move to OUT (deduct on_hand) and clear `reserved`. Enforce not-over-reserving (cannot reserve more than available; reject with a clear message + audit attempt). Enforce not-over-issuing (cannot OUT more than on_hand). Provide the RESERVE / RELEASE / ADJUST actions on the inventory UI (warehouse role).
4. **Material usage (`material_usage`)**: record material consumed against a production/order (e.g. when a production stage completes or QC), which triggers an OUT movement + on_hand deduction, references production_id.
5. **Low-stock alert**: a threshold per material (default, e.g. 0 or a configurable `low_stock_threshold` — store on `inventory` or a sensible existing column; if you add a column document it, else use a module-level default and a Dashboard/Inventory low-stock badge showing materials where `available <= threshold`). Simple is fine now (a warning badge/list + a small count on the inventory page); deep Dashboard alerts come Phase 8.
6. **Permissions (additive, idempotent, spec §24)**: add codes e.g. `inventory.view`, `inventory.manage` (create movement/adjust/reserve/release). Extend `seed/seed_auth.py` PERMISSIONS + ROLE_PERMISSION_MATRIX: ADMIN=all (keep the invariant that ADMIN is granted every permission), WAREHOUSE=view+manage, others view-only (PRODUCTION/QC/FINANCE/MANAGEMENT=view). Re-seed idempotently.
7. **Pages/UI per DESIGN_SPEC**: Inventory table/cards with columns material | on_hand | reserved | available (+ low-stock badge), and actions to: Adjust / Reserve / Release / Issue(OUT); plus a movements view (list of stock_movements with filters/cards) and a usage log. Backend-enforced auth (warehouse+ for writes; view for warehouse+production+...). Cards not giant ungrouped tables.

## Rules
- **Never invent business data**; materials come from the migrated master; units already exist (`pcs`, `meter`…). Use a real migrated material for smoke (e.g. "Cotton Combed 24s").
- Audit every write via `audit()` (movements, adjust, reserve/release, usage).
- Concurrency-safe-wise: do the on_hand/reserved math in a transaction (BEGIN IMMEDIATE) so parts don't double-decrement; keep it simple but correct.
- Additive schema allowed ONLY if clearly documented (prefer reusing existing columns; the schema already has on_hand/reserved/available/location on `inventory` and movement_type on `stock_movements`).

## Report (English): per sub-step files+routes+tests; verified behaviors (ADJUST adds on_hand; reserve moves to reserved and rejects over-reserve; release/work deducts on_hand; available=on_hand-reserved; usage OUT ties to production; movement audit rows; low-stock badge shows), permission matrix, any schema change + why, blockers (exact error). Distinguish implemented vs boundary-prepared. NEVER fabricate — run the real code; on a hard blocker stop and report exactly.