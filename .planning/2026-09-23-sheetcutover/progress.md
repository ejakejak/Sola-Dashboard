# Progress — Phase 5: Sheet-Only Cutover (SQLite dropped, spreadsheet is live)

Status: FUNCTIONALLY COMPLETE + VERIFIED. A few legacy-inert sqlite refs remain (see Remaining).
Decision: Doffy FULL CUTOVER ("we're not using SQL... replace everything").

## Done & VERIFIED (real output)
- [x] Audited schema: 41 tables from instance/sola.db (full column map).
- [x] Backup of live sqlite: instance/sola.db.bak-20260923 (360K = live).
- [x] app/sheetdb.py: SheetRoot/SheetRelation engine (tables-as-tabs, CRUD in Python).
     - tests/test_phase5_sheetdb.py (7) — insert/pk/auto-incr/find/count/sum/update/delete/multi: OK
- [x] app/storage.py SheetsStorage: added add_tab(); tabs() cached (quota-friendly);
     append_rows uses RAW (gspread 6.2.1 mis-serializes USER_ENTERED).
- [x] scripts/migrate_to_sheet.py: one-way dump of all 41 tables -> own tab on live sheet.
     Ran --yes: **DONE: wrote 41 tabs to the live sheet** (46 tabs total w/ 5 master).
     Data integrity read-back confirmed through SheetRelational:
       users=8 (admin/role1/active), materials=32, orders=1
       (ORD-2026-0001 confirmed/high/grand_total=660000/deadline=2026-12-01).
     NOTE: relation must be defined with the EXACT column order from the tab (positional map).

## Remaining (legacy-inert sqlite references — NOT the app's data path)
- [x] all 7 blueprints ported to sheet engine; residual SQL call sites = 0 (verified via grep;
      only invoice_pdf.py keeps a legacy-sql branch behind hasattr(conn,'table') for non-sheet conns)
- [x] Read-caching in SheetsStorage (worksheet-object + 10s TTL value cache, invalidate on write)
      — fixed HTTP 429 quota-exceeded on a single dashboard page
- [x] Config STORAGE default sqlite -> sheets (Phase 5 default; SqliteStorage remains a legacy adapter)
- [x] CLEAN BOOT (no STORAGE env, sheet creds only): login 200->302, dashboard 200 (6 KPI cards),
      /production/board 200 (9 columns) — served from the live sheet
- [x] WRITE path lands on sheet: 2 new LOGIN audit rows (ids 62,63) from smoke logins
- [ ] app/__init__.py still registers teardown(close_db) + DATABASE_PATH (harmless — blueprints no
      longer use get_db). Optional cleanup.
- [ ] run.py still seeds the legacy sola.db file on boot (writes leftover file; app reads sheets).
- [ ] app/db.py (get_db/audit) remains as legacy adapter; imported only by invoice_pdf bc-branch +
      SqliteStorage. Cosmetic cleanup pass.

## Verified KPI sample (from live sheet)
active_orders=1, in_production=1, waiting_payment=0, ready_to_ship=0, overdue=0, outstanding_invoice=0

## Errors this phase
| Error | Attempt | Resolution |
|-------|---------|------------|
| gspread WorksheetNotFound on append to just-created tab | 1 | Dedicated add_tab() creates tab, refresh_tabs() after create |
| gspread 400 Invalid values[0][0] list_value (USER_ENTERED) | 1 | append_rows uses RAW; fixed header double-nesting in migrate (data head) |
| gspread 429 quota exceeded (read reqs/min) | 1 | tabs() cached once; loop fetches existing ONCE; time.sleep(0.6) pacing; now EXIT=0 |
| Phase5 test: find("balance"="20") vs numeric 20 | 1 | _val_eq() lenient numeric coercion |
| Phase5 test: header cleared in setup | 1 | re-seed header row after clear_tab |
| _FakeServiceAccount self-ref default arg | 1 | module-level _SENTINEL |