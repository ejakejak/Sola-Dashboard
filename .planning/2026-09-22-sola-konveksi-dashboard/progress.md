# Progress Log — SOLA Konveksi & Production Management System

Project root: `D:/Sola`. Full spec: `docs/DEV_BRIEF.md`, `docs/DESIGN_BRIEF.md`.

## Session 2026-09-22

### Phase 0 — Audit (COMPLETE, EVA verified)
- Pulled real source Google Sheet → `data/master.xlsx` (5 sheets: HPP, MASTER HPP, Sheet3, DATABASE AGEN, DATABASE PENJAHITMAKLOON).
- Authored `docs/AUDIT_REPORT.md` (normalization findings: phone leading-0 loss, `-`→NULL, `Fee` strings Max N / `% Keuntungan`, Korsa-Vest context prices, name aliases, trailing-space `Kanvas `, stray M1=31500, separator rows, pivot layout), `docs/DATA_DICTIONARY.md`, `db/schema.sql` (relational FK schema).
- Credential stored: `instance/sola-509413-service-account.json` (`evaaccount@sola-509413.iam.gserviceaccount.com`, gitignored, per 2026-09-22).

### Phase 1 — DB schema + migration (COMPLETE, EVA verified)
- `scripts/import_excel.py` authored by REX (clean, idempotent, report-emitting, never touches source). `db/init_schema.py` created. `instance/sola.db` built.
- **EVA catch:** material master was duplicated (American Drill ×4, Nagata Drill ×3) → REX fixed to one master/canonical name + category-keyed `material_prices`. Verified independently: 0 dup master names; materials 32; processes 15; categories 14; material_prices 52; commission_templates 11; agents 2; vendors 17; cost_components 118; FK check `[]`; **13/13 tests pass** (`tests/test_migration.py`, incl. regression `test_one_material_master_per_canonical_name`). Migration report `migrations/migration_report.json` (exit 0, 0 errors).

### Design spec (COMPLETE, EVA verified + corrected)
- `docs/DESIGN_SPEC.md` (10 screens, 365 lines) authored by Neo.
- **EVA catch:** brand was indigo `#4F46E5` → corrected to **Sola Gold `#CCA300`** + white white `#FFFFFF/#FEFDFD` + derived dark gold `#8A6D00` (est). Verified independently: gold present, 0 indigo.
- Logo assets: `app/static/assets/sola-logo-1.png` / `sola-logo-2.png` (identical; gold field + white SOLA wordmark).
- Invoice PDF block (client-provided 2026-09-22): phone `62 823-7127-5988`, address maps `https://maps.app.goo.gl/xHd1obgDP7uY97y88`, payment `KETERANGAN PEMBAYARAN` → BCA `4452337111` a.n. Irhami Al Adaby. Placeholders for legal name/street/NPWP.

### Phase 2 — Flask app + auth + Master Data (COMPLETE, EVA verified)
- REX built: app/__init__.py, app/config.py, app/db.py, app/auth.py, app/masterdata.py, seed/seed_auth.py, run.py, templates (base/index/login/403/404/master_*). Reused existing schema (no schema changes). NPWP not exposed.
- Routes: `/` , `/login`,`/logout`, `/master-data/`,`/master-data/<key>`(list),`.../<key>/new`, `.../<key>/<rid>/edit`. 7 resources full CRUD (materials, products, processes, decorations, vendors, agents, customers); no delete (intentional).
- Auth (backend-enforced): 8 roles, 15 permissions, 31 role_permissions, 8 users seeded (roles=ADMIN/SALES/PRODUCTION/WAREHOUSE/QC/FINANCE/MANAGEMENT/CUSTOMER). Default admin `admin`/`sola123`. Audit log on every CREATE/UPDATE + LOGIN/LOGOUT.
- **EVA verified:** ran `tests/test_app_phase2.py` → 7/7 pass; seed state confirmed in DB; live server: auth gate 302→/login on protected routes, SOLA-branded pages.
- Catalog ingested: `docs/CATALOG_SOLA_2026.md` (selling prices + included steps; complements master.xlsx HPP). Company block finalized (Sola Konveksi Yogyakarta; Jl. Magelang No.KM7…; BCA 4452337111 a.n. Irhami Al Adaby; NPWP removed).

## Phase plan (spec §30) — next
- **Phase 5 (Production + workflows) — COMPLETE, EVA verified (44/44 tests green).** Configurable workflow templates (garment default 9-stage, Mug short, Topi variant; admin-editable; no hard-coding). Production-from-order auto `PRD-YYMMDD-NNN` (`PRD-260922-001`, 9 materialized stages, derived progress). Stages/updates/media (INTERNAL|CUSTOMER, backend-gated via `production.media.internal.read`)/QC pass-fail-rework-with-return. Catalog catalog seed: 12 products / 40 variants (selling price+included+add-ons in `product_variants.notes`, SELLING side; master.xlsx stays HPP). Permissions 31 (ADMIN=all). Screenshots: `_shots/phase5/`.
- **Phase 6 (NEXT, in flight):** Inventory + stock movements (on_hand/reserved/available, IN/OUT/ADJUST/RESERVE/RELEASE w/ guards, material_usage, low-stock, warehouse perms). REX on DeepSeek.
- **Phase 7**: public `/track` (customer production tracking, INTERNAL never leaked, rate-limited anti-enumeration).
- **Phase 8**: Dashboard KPIs + Production Kanban + alerts (analytics).
- **Phase 9**: Security hardening (change default admin `admin/sola123`), QA, deployment packaging, docs, acceptance run.

## Accepted design defaults (Ejak reviewed recommendations; no override)
1 Global search across Orders/Productions/Customers/Invoices. 2 INTERNAL media: restricted by default (Management read-only dash/reports), grantable perm `production.media.internal.read`. 4 IDR + Indonesian locale dd/mm/yyyy. 5 /track: 20 lookups/IP-hr, 5 fails→90s cooldown. 6 Board compact-table toggle for all roles.