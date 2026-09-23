# progress.md — SOLA Live Sheet Sync

## Session 2026-09-23 (complete)
- READ: import_excel, config, db, masterdata, schema, migration_report, seed_auth, auth, __init__, probe_sheet.
- Probed live sheet (read+write). Confirmed gspread 6.2.1 typed reads via `value_render_option="UNFORMATTED_VALUE"`.
- Refactored import_excel.py: added `run_migration_from_workbook` (slash-insensitive tab reconcile) + backward-compatible `run_migration`. All 13 migration tests pass.
- Built scripts/sync_sheet.py (pull/push/compare, --dry-run, --yes, --replace guard, --probe-write).
- VERIFIED LIVE:
  * dry-run pull counts == migration_report.json baseline EXACTLY (32/15/14/52/11/2/17/48/118/7; errors=0).
  * idempotent: 2 dry-run passes, identical counts, exit 0; sola.db sha unchanged by sync.
  * safe reconcile real pull into temp copy of live DB: 0 errors, fk_check PASS, dependent business tables unchanged (products 12, variants 40, inventory 1, etc.).
  * --replace guard refuses on live-style DB.
  * compare shows agents/vendors fully in sync (phone-normalization aware); push --dry-run = 0 writes.
  * push planning proven vs temp DB with a fake agent + changed vendor phone (append + update ops correct).
  * LIVE write probe: marker write/read/revert on DATABASE AGEN A:1000, ok=true, reverted.
  * full unittest suite: 87 pass.
  * running app: GET / -> 302, POST /login admin/sola123 -> 302, credential valid.
- Delivered docs/SYNC.md; requirements.txt now pins gspread==6.2.1 + google-auth (real dep).
- Blocker (transient): Google Sheets 429 read-quota during a repeated pull; retried OK.
- Design find: wipe+replace unsafe on live DB (FK refs from products/variants/inventory/orders) -> real pull uses safe reconcile (upsert, never delete).