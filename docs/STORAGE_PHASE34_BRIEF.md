# SOLA — Storage refactor Phases 3+4: Live Google Sheets backend (SheetsStorage via gspread)

NOTE: this is a DIFFERENT phase-series than `docs/PHASE34_BRIEF.md` (the commercial
quotation/invoice loop). This doc covers the storage-abstraction refactor's Phases 3+4.

Status: IMPLEMENTED + VERIFIED — 2026-09-23 (Doffy: "just rewrite the google sheet")

## Objective
Turn the Phase-1 `SheetsStorage` skeleton into a REAL live Google Sheets backend that can
read & write the production "MASTER DATA SOLA 1.0" sheet via gspread, wired so the app runs
unchanged on `STORAGE=sqlite` and offers a full tab CRUD surface on `STORAGE=sheets`.

## What changed
- **`app/storage.py`** — `SheetsStorage` rewritten from skeleton to a real backend:
  - Authenticates via `gspread.service_account` + `open_by_key(spreadsheet_id)` — Sheets-API
    only, NO Drive scope (per the gspread skill's least-privilege rule).
  - Lazy: does not import gspread or touch the network at construction; sqlite path imports
    nothing extra. First data call (or `connect()`) loads gspread.
  - Non-fatal construction: app boots with `STORAGE=sheets` even with no creds; `connect()`
    raises `RuntimeError` when unconfigured.
  - Real tab surface: `tabs()`, `header_row()`, `read_tab()`, `append_rows()`, `update_cell()`,
    `clear_tab()`, `find_tab_by_header()`.
  - SQL-shaped interface methods (`query/execute/fetchone/fetchall/insert/update/delete/
    connection/commit/rollback/audit`) raise `NotImplementedError` with a clear reason: a
    spreadsheet cannot run SQL.

## Design decision (honest boundary)
A Google Sheet is tab-oriented, not relational — it CANNOT execute the app's SQL (149 execute
call sites). So the live Sheets backend exposes a tab-CRUD surface (the same model the
existing `scripts/sync_sheet.py` tooling uses). The SQL abstraction remains fully served by
`SqliteStorage` (the app's default). "Switch the whole app to sheets" is not achievable by
rewriting the sheet connection; the sheet is the master-data source of truth (per SYNC.md),
sync'd via the existing pull/push tooling.

## Tests
- `tests/test_phase34_sheets.py` (12) — unconfigured path, lazy-import guarantee, fake-gspread
  tab CRUD (tabs/header/read/append/update/clear/find_by_header), SQL-shaped raises.

## Verification
- Phase-3/4 suite: 12/12 OK.
- FULL suite: **Ran 121 tests: OK** (87 + 15 + 7 + 12), zero regression.
- REAL read-only live probe against production sheet succeeded: tabs = HPP, MASTER HPP,
  Sheet3, DATABASE AGEN, DATABASE PENJAHIT/MAKLOON; AGEN headers = NAMA, ALAMAT, NOHP,
  FAKULTAS, KAMPUS/SEKOLAH.
- Boot smokes: default (:5095) and STORAGE=sheets (:5096) both clean (root 302->login, login 200).
- Plan dir: `D:/Sola/.planning/2026-09-23-phase34/`.

## Constraints honored
- Zero regression on sqlite (default). Full suite green.
- gspread lazy import — sqlite path needs nothing.
- No secrets in source; creds read from the existing instance/ service-account file + env.