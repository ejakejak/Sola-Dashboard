# SOLA — Acceptance Criteria Status (spec §32, A–Q)

Each of the 17 criteria is marked **Implemented / Verified / How**, mapped to the
specific test(s) and route(s) that realise and prove it. "Verified" here means the
referenced test actually passed in the Phase-9 full run
(`Ran 87 tests … OK`, 2026-09-23) **and/or** a live route check was exercised.

**Summary: 17 / 17 implemented & verified. 0 partial, 0 absent.**

| Criteria | Status | Evidence (test → route) |
|---|---|---|
| A–E master+commercial | ✔ 5/5 | `test_app_phase2`, `test_app_phase34` |
| F–J production+media | ✔ 5/5 | `test_app_phase5` |
| K–M customer `/track` | ✔ 3/3 | `test_app_phase7` |
| N inventory | ✔ 1/1 | `test_app_phase6` |
| O QC | ✔ 1/1 | `test_app_phase5` |
| P audit log | ✔ 1/1 | multiple (see P) |
| Q migration | ✔ 1/1 | `test_migration` |

---

## A. Admin creates master product / material / process / decoration — **Implemented · Verified**
- **How:** Generic master-data CRUD dispatcher `app/masterdata.py`
  (`_get_resource` maps a `key` to a table + `perm_prefix`). Admin holds every
  `masterdata.*`, `material.*`, `product.*`, `process.*`, `decoration.*` permission.
- **Tests:** `test_app_phase2.py::test_admin_can_create_customer`,
  `test_master_data_list_loads_with_data`, `test_admin_can_update_material_and_audit_written`.
- **Routes:** `POST/GET /master-data/<key>/new`, `/master-data/<key>/<id>/edit`.
- **Boundary note:** customer + material are directly asserted; product/process/
  decoration exercise the same creation path and are seeded with real data
  (12 products, 15 processes in the live DB) but have no separate dedicated unit test.

## B. Sales creates customer, quotation and order — **Implemented · Verified**
- **Tests:** `test_app_phase34.py::test_02_create_quotation_audit_numbering`,
  `test_08_direct_order_and_finance_role`, `test_01_navigation_permissions`;
  permission matrix in `test_app_phase5.py::test_14_matrix` (SALES has
  `customer.create`, `quotation.create/convert`, `order.create`).
- **Routes:** `POST /quotations/new`, `POST /orders/new`, `POST /master-data/customers/new`.

## C. Order generates an invoice — **Implemented · Verified**
- **Tests:** `test_app_phase34.py::test_05_invoice_from_order`.
- **Routes:** `POST /invoices/from-order/<oid>` (`invoice.create`).

## D. Invoice downloadable as PDF — **Implemented · Verified**
- **Tests:** `test_app_phase34.py::test_07_pdf_renders_no_network_hpp` (asserts the
  PDF renders with no HPP / network data).
- **Routes:** `GET /invoices/<iid>/pdf` (`invoice.view`); client-side `window.print()`.

## E. Payment recorded & outstanding auto-computed — **Implemented · Verified**
- **Tests:** `test_app_phase34.py::test_06_payment_outstanding_and_paid`.
- **Routes:** `POST /invoices/<iid>/payment` (`invoice.payment`); outstanding shown
  on invoice list/detail; dashboard `unpaid-invoice` alert
  (`test_app_phase8.py::test_05_unpaid_invoice_alert_shows_count_and_total`).

## F. Order generates a Production Code — **Implemented · Verified**
- **Tests:** `test_app_phase5.py::test_04_from_order_auto_code_stages_progress`
  (asserts `production_code` auto-generated, stage rows + progress created).
- **Routes:** `POST /production/from-order/<oid>` (`production.manage`).

## G. Production has staged workflow — **Implemented · Verified**
- **Tests:** `test_app_phase5.py::test_01_seeded_templates_idempotent`,
  `test_02_admin_edit_template`, `test_03_workflow_manage_required`,
  `test_06_advance_stage_recomputes_progress`.
- **Routes:** `GET /production/templates…`, `POST /production/<pid>/stage/<sid>/advance`.
- Live: 3 workflow templates / 22 template steps seeded.

## H. PIC updates progress — **Implemented · Verified**
- **Tests:** `test_app_phase5.py::test_08_production_update_audited`
  (update recorded + audit row written).
- **Routes:** `POST /production/<pid>/updates` (`production.manage`).

## I. PIC uploads photo/video — **Implemented · Verified**
- **Tests:** `test_app_phase5.py::test_09_media_upload_and_visibility_gate`,
  `test_11_media_upload_requires_manage`.
- **Routes:** `POST /production/<pid>/media` (`production.manage`); served by
  `GET /production/media/<id>/file`.

## J. System distinguishes INTERNAL vs CUSTOMER media — **Implemented · Verified**
- **Tests:** `test_app_phase5.py::test_09_…visibility_gate`,
  `test_10_internal_media_gated_for_view_only_roles`; `test_app_phase7.py::test_03…`.
- **Routes:** media **list** filters on `visibility='CUSTOMER' OR internal-read-perm`;
  **file** route `GET /production/media/<id>/file` returns **403** for INTERNAL media
  without `production.media.internal.read`. DB default visibility is `INTERNAL`.

## K. Customer opens `/track` and enters a Production Code — **Implemented · Verified**
- **Tests:** `test_app_phase7.py::test_01_track_requires_no_login`,
  `test_02_valid_code_renders_customer_data_only`.
- **Routes:** `GET/POST /track` (public, rate-limited).

## L. Customer sees production progress as a timeline — **Implemented · Verified**
- **Tests:** `test_app_phase7.py::test_02…` (renders ordered stages + latest update).
- **Routes:** `GET /track`; stage list selected in `app/track.py::_lookup_customer_view`
  ordered by `sequence` with per-stage status, plus latest update + CUSTOMER media.

## M. Customer cannot see internal data — **Implemented · Verified**
- **Tests:** `test_app_phase7.py::test_03_customer_media_served_but_internal_not`,
  `test_04_html_free_of_prohibited_internals`, `test_05_wrong_code_generic_no_oracle`.
- **Routes:** `/track` renders customer-visible columns only (no cost/HPP/margin/vendor/
  invoice data, no DB ids); `/track/media/…` re-validates `visibility='CUSTOMER'`
  else 404; INTERNAL media never listed or served to anonymous.

## N. Inventory records stock movements — **Implemented · Verified**
- **Tests:** `test_app_phase6.py::test_02…test_11` (adjust/reserve/release/issue/usage
  all write `stock_movements`), `test_19_movements_and_usage_views`.
- **Routes:** `POST /inventory/adjust|reserve|release|issue|usage`;
  `GET /inventory/movements`, `/inventory/usage-log`.
- Live: 7 `stock_movements` rows in `instance/sola.db`.

## O. QC does pass / fail / rework — **Implemented · Verified**
- **Tests:** `test_app_phase5.py::test_12_qc_pass_rework_return_to_stage`,
  `test_13_qc_requires_permission`.
- **Routes:** `POST /production/<pid>/qc` (`qc.manage`) → `quality_checks`.

## P. All important changes recorded in audit log — **Implemented · Verified**
- **Tests:** `test_app_phase2.py::test_audit_log_written_on_create` +
  `test_admin_can_update_material_and_audit_written`; `test_app_phase5.py::test_08…`;
  `test_app_phase6.py::test_06_over_reserve_rejected_and_audited`;
  `test_app_phase9.py::test_01_…writes_audit`.
- **Routes/impl:** `app/db.py::audit()` is invoked on create/update/status/convert/
  payment/production-update/media/QC/inventory-write/login/logout.
- Live: **54 `audit_logs` rows** in `instance/sola.db`.
- **Boundary note:** "all important changes" is implemented as a write-path audit
  convention rather than a DB **trigger/after** log; a future hardening could add
  DB-level triggers, but every current mutating route already audits.

## Q. Excel migrated to DB without losing important data — **Implemented · Verified**
- **Tests:** `tests/test_migration.py` — 13 tests: no errors/exit semantics, phone
  leading-zero restore, context variant prices kept separate, one canonical material
  master per name, Kaos→Jersey alias, Kanvas trim, fee→commission-template mapping,
  stray-M1 flagged, FK integrity, idempotent re-run, source workbook never modified,
  category/vendor counts.
- **Artifact:** `docs/CATALOG_SOLA_2026.md` + `migrations/migration_report.json`.

---

## Phase-9 verification summary (this run)

- Full suite: **87 / 87 passed** (`python -m unittest discover -s tests -p 'test_*.py'`).
  Prior-phase baseline was 81; +6 added in `tests/test_app_phase9.py`.
- `PRAGMA foreign_key_check` on `instance/sola.db`: **empty** (0 violations).
- Row totals (live DB): users 8, roles 8, permissions 33, role_permissions 82,
  audit_logs 54, materials 32, products 12, processes 15, vendors 17, customers 2,
  quotations/orders/invoices 1 each, production_orders 1, stock_movements 7,
  production_workflow_templates 3 (+22 steps), product_variants 40, cost_components 118.
- ADMIN rotation behaviour verified live: rotate → re-seed ×2 → rotated password
  still authenticates, default `sola123` does not, exactly one `ADMIN_PASSWORD_ROTATED`
  audit row, FK clean.
- No secrets found in `app/` source; `FLASK_SECRET_KEY` now env-only (fail-closed).