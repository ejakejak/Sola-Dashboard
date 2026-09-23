# findings.md — SOLA Live Sheet Sync

## Live sheet access (probe_sheet.py, RUN 2026-09-23)
- OPEN_OK: sheet "MASTER DATA SOLA 1.0"
- Tabs: HPP, MASTER HPP, Sheet3, DATABASE AGEN, DATABASE PENJAHIT/MAKLOON
- NOTE: gspread 6.2.1 get_all_values() does NOT accept max_rows kwarg (TypeError). Use get_all_values() plain or range.

## Live DB counts (sola.db, 2026-09-23)
materials=32, processes=15, product_categories=16, material_prices=52,
commission_templates=11, agents=2, vendors=17, vendor_capabilities=48,
cost_components=118, process_prices=7.
NOTE: product_categories live=16 BUT migration_report baseline=14 (seed_catalog adds extras).

## Env
- .env has FLASK_SECRET_KEY + DATABASE_URL only; NO SPREADSHEET_ID/GOOGLE creds.
- .env.example has SPREADSHEET_ID + GOOGLE_APPLICATION_CREDENTIALS.
- Service account: D:/Sola/instance/sola-509413-service-account.json (gitignored).
- config.py does NOT expose SPREADSHEET_ID/GOOGLE_APPLICATION_CREDENTIALS attrs -> read in sync_sheet from env with defaults.
- Admin seed: admin/sola123.
- App currently RUNNING on 127.0.0.1:5000 (GET / -> 302).