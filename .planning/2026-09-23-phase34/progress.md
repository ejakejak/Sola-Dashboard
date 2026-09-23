# Progress — Phase 3 + 4: Live Google Sheets backend (SheetsStorage via gspread)

Brief: Doffy "just rewrite the google sheet" (2026-09-23), clearance through Phase 4.

## Log
- [2026-09-23] Rewrote SheetsStorage from skeleton -> real gspread backend:
  lazy open_by_key (Sheets-only scope), tabs()/header_row()/read_tab()/append_rows()/
  update_cell()/clear_tab()/find_tab_by_header(); connect() raises RuntimeError when
  unconfigured. SQL-shaped methods raise NotImplementedError with a clear reason
  (a sheet cannot run SQL). import is lazy so the sqlite path needs no gspread.
- [2026-09-23] tests/test_phase34_sheets.py (12 tests) using a fake gspread (no network).
- [2026-09-23] REAL read-only live probe against the production master sheet succeeded
  (service account present; tabs + headers read by open_by_key).

## Results
- test_phase34* -> Ran 12 tests: OK
- gspread lazy-import verified: sqlite storage + factory never import gspread.
- Live read-only probe (production sheet): tabs = HPP, MASTER HPP, Sheet3, DATABASE AGEN,
  DATABASE PENJAHIT/MAKLOON; AGEN headers = NAMA, ALAMAT, NOHP, FAKULTAS, KAMPUS/SEKOLAH.
- Full suite: Ran 121 tests: OK (87 + 15 + 7 + 12) — zero regression.
- Boot smokes: default (:5095) + STORAGE=sheets (:5096) both clean; ports clear.

## Files created/modified
- app/storage.py (mod): real SheetsStorage backend
- tests/test_phase34_sheets.py (new): 12 tests

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| `gspread_worksheet_missing` invalid except clause in find_tab_by_header | 1 | Broad `except Exception: continue` with comment |
| test_09 read_tab header=False indexing (header row at idx 0) | 1 | Assert data row at index 1 |
| _FakeServiceAccount self-reference in default arg (NameError) | 1 | Module-level _SENTINEL |