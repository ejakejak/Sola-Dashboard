# DEV BRIEF — SOLA Konveksi & Production Dashboard (for @REX, Developer)

Role: **Developer** (REX). EVA (product owner/coordinator) owns scope; you own implementation, verification, and tests. Design output must route through @Neo (Designer) — do not ship raw UI you designed.

## Project root
`D:/Sola` (greenfield; existing state below). Stack decision: **local-first, SQLite + Flask** (relational, FK-enforced; spec §26,§33 — data integrity > cosmetic UI). Keep it a maintainable modular monolith; add infra only when a requirement demands it. Full spec: `C:/Users/muham/AppData/Local/hermes/cache/documents/doc_dfd0d1a07b14_PROMPT_AI_AGENT_DASHBOARD_KONVEKSI.txt`.

## Existing state (already done — build on it, don't redo)
- `data/master.xlsx`        — real source (pulled from Google Sheet `1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA`; link-shared, no auth).
- `db/schema.sql`            — relational SQLite schema (FK, per spec §26 entities + audit-grounded additions). **Audit-grounded**: material_prices keyed by product-category context (Korsa/Vest same material, different price»); commission_templates for `Fee` strings ('Max N' cap, '% Keuntungan' percent-of-profit); phone TEXT w/ leading-0; '-' -> NULL.
- `scripts/import_excel.py`   — **DRAFT migration script — HAS SYNTAX BUGS.** OWNS: rewrite cleanly, make it produce `migrations/migration_report.json` (rows_read/imported/duplicates/invalid/skipped/normalized/warnings/errors), idempotent, never touch source Excel, exit 0/1 semantics.

- `docs/AUDIT_REPORT.md`     — canonical audit findings + open decisions (READ FIRST).
- `docs/DATA_DICTIONARY.md`   — Excel→DB mapping + normalization rules (READ FIRST、.

## Phase order (spec §30 — do NOT build everything at once); stop + test after each)
- **Phase 1 (THIS delegation)**: fix/author `scripts/import_excel.py` cleanly; add `db/init_schema.py`; migrate `master.xlsx` → `instance/sola.db`; run andreport shows: materials(≈18), processes(≈25,m, agents(2), vendors(≈17), product_categories(≈14, commission_templates, material_prices(context-aware). Verify phoned leading-0, '-'→NULL, Fee→commission mode/cap, KR/VS context prices preserved, 'Kaos'/'Jersey' alias mapped. Tests:`tests/test_migration.py` (unit + one live run against master.xlsx、.
- **Phase 2**: Master-data CRUD UI/backend products/processes/decorations/materials/vendors/customers/agents — backend authorization first (spec §24)。
- **Phases 3-9**: Customer→Quotation→Order→Invoice(+PDF via reportlab)→Payment; Production mgmt + configurable workflow templates; Inventory (on-hand/reserved/available, spec §18); public `/track` (spec §19-20: no DB ID exposure, rate-limited, media visibility INTERNAL/CUSTOMER, never leak HPP/margin/internal notes); dashboard KPI cards + kanban (spec §21-23); audit_log every consequential action (spec §27); full test list spec §29 (20 tests).

## Non-negotiable rules
- **NEVER invent/fabricate business data** (prices, vendors, materials, customers). Use only `master.xlsx` content. You may only add config-derived scaffolding (workflow template defaults per product category) — label it as such.
- Excel = migration source only; runtime is SQLite relational. Never modify the source file.
- All critical writes go to `audit_logs`. Authorization enforced at the backend layer, not just hidden buttons (spec §24).
- Preserve `db/schema.sql` as the integrity contract; additive migrations only when justified (document why).
- After every phase: run tests, check DB integrity (FK), check routes with live data, update `README.md` phase plan. Do NOT claim done until you exercised the real code path and have tool evidence.

## Verification handover (to EVA)
Report: commit/paths, test count/result, live migration report path + key counts, verified endpoints (list of model/tested), any blocked dependency, and remaining phases. Distinguish: implemented vs boundary-prepared vs not-yet. Cross-check DB integrity (FOREIGN_KEY_CHECK) yourself before claiming success.

**Gate:** EVA independently re-runs the migration + tests + checks before presenting the result to Ejak. UI/canvas/visual any design output → @Neo, not shipped raw.