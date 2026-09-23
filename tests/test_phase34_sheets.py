#!/usr/bin/env python3
"""Phase 3/4 tests — live Google Sheets backend (SheetsStorage via gspread).

Behavior contracts:
  (a) SheetsStorage constructs with no creds and reports missing; connect()
      raises RuntimeError when unconfigured.
  (b) gspread is a LAZY import — importing the module and building a sqlite-factory
      storage never imports gspread (sqlite path needs nothing).
  (c) With a fake gspread client injected (sys.modules), connect() opens BY KEY
      (never by title), and tabs()/header_row()/read_tab()/append_rows()/
      update_cell()/clear_tab()/find_tab_by_header() work against the fake.
  (d) SQL-shaped methods (query/execute/fetch*/insert/update/delete/connection/
      commit/rollback/audit) still raise NotImplementedError with a clear reason.

Run:  python tests/test_phase34_sheets.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app.storage import SheetsStorage, SqliteStorage, get_storage  # noqa: E402


# ---------------------------------------------------------------------------
# Fake gspread client (open_by_key only; open(title) must fail) + fake sheet
# ---------------------------------------------------------------------------
class FakeWorksheet:
    def __init__(self, title, rows):
        self.title = title
        self._rows = rows  # 2D list incl. header (row 0)

    def row_values(self, row):
        return self._rows[row - 1] if 0 < row <= len(self._rows) else []

    def get_all_values(self, value_render_option="UNFORMATTED_VALUE"):
        return [list(r) for r in self._rows]

    def append_rows(self, rows, value_input_option=None):
        for r in rows:
            self._rows.append(list(r))

    def update_cell(self, row, col, value):
        while len(self._rows) < row:
            self._rows.append([])
        while len(self._rows[row - 1]) < col:
            self._rows[row - 1].append("")
        self._rows[row - 1][col - 1] = value

    def clear(self):
        self._rows = []


class FakeGSpread:
    class Client:
        def __init__(self, spreadsheet):
            self._spreadsheet = spreadsheet

        def open_by_key(self, key):
            if key != FAKE_SHEET_ID:
                raise RuntimeError(f"no sheet with id {key}")
            return self._spreadsheet

        def open(self, title):
            # By-title requires Drive — must never be used by SheetsStorage.
            raise RuntimeError("open(title) must not be called; use open_by_key")


FAKE_SHEET_ID = "FAKE_SHEET_ID_123"
_FAKE_ROWS = {
    "DATABASE AGEN": [["Nama", "Alamat", "No HP"], ["Budi", "Jl. X", "08123"]],
    "DATABASE PENJAHIT/MAKLOON": [["Nama", "Alamat", "No HP"], ["Tukang", "Jl. Y", "082"]],
}


def _make_fake_worksheet(title):
    return FakeWorksheet(title, [list(r) for r in _FAKE_ROWS[title]])


def make_fake_spreadsheet():
    return FakeGSpread.Spreadsheet() if hasattr(FakeGSpread, "Spreadsheet") else None


# A fake Spreadsheet object (worksheets() / worksheet()).
class FakeSpreadsheet:
    def __init__(self):
        self._tabs = {t: FakeWorksheet(t, [list(r) for r in rows])
                      for t, rows in _FAKE_ROWS.items()}

    def worksheets(self):
        return list(self._tabs.values())

    def worksheet(self, title):
        if title not in self._tabs:
            raise RuntimeError(f"WorksheetNotFound: {title}")
        return self._tabs[title]


FakeGSpread.Spreadsheet = FakeSpreadsheet


def _install_fake_gspread():
    """Inject the fake gspread into sys.modules so SheetsStorage.connect() uses it."""
    _SENTINEL = object()

    class _FakeServiceAccount:
        @staticmethod
        def service_account(filename=_SENTINEL):
            return FakeGSpread.Client(FakeSpreadsheet())

    module = _FakeServiceAccount()
    # give the module a `WorksheetNotFound` alias used by gspread normally
    module.WorksheetNotFound = RuntimeError
    sys.modules["gspread"] = module
    return module


class TestSheetsUnconfigured(unittest.TestCase):
    def test_01_constructs_without_creds_and_reports_missing(self):
        s = SheetsStorage()
        self.assertFalse(s.already_configured)
        self.assertIn("SPREADSHEET_ID", s.missing)
        self.assertIn("GOOGLE_APPLICATION_CREDENTIALS", s.missing)

    def test_02_connect_raises_when_unconfigured(self):
        s = SheetsStorage()
        with self.assertRaises(RuntimeError):
            s.connect()

    def test_03_constructs_with_real_but_missing_creds_file(self):
        s = SheetsStorage(spreadsheet_id="abc", credentials_path="/nope/missing.json")
        self.assertFalse(s.already_configured)
        self.assertIn("GOOGLE_APPLICATION_CREDENTIALS", s.missing)
        with self.assertRaises(RuntimeError):
            s.connect()


class TestGspreadLazyImport(unittest.TestCase):
    def test_04_sqlite_storage_and_factory_never_import_gspread(self):
        # Ensure gspread is not already imported, then build the sqlite path.
        had = sys.modules.pop("gspread", None)
        try:
            storage = get_storage({"STORAGE": "sqlite"})
            self.assertIsInstance(storage, SqliteStorage)
            top = get_storage({})
            self.assertIsInstance(top, SqliteStorage)
            self.assertNotIn("gspread", sys.modules,
                             "sqlite path must not import gspread")
        finally:
            if had is not None:
                sys.modules["gspread"] = had


class TestSheetsLiveBackend(unittest.TestCase):
    def setUp(self):
        self._fake = _install_fake_gspread()
        self.tmp = Path(tempfile.mkdtemp())
        cred = self.tmp / "sa.json"
        cred.write_text("{}", encoding="utf-8")
        self.sheet = SheetsStorage(spreadsheet_id=FAKE_SHEET_ID,
                                   credentials_path=str(cred))
        self.assertTrue(self.sheet.already_configured)

    def tearDown(self):
        sys.modules.pop("gspread", None)

    def test_05_tabs_lists_live_tab_titles(self):
        self.assertEqual(set(self.sheet.tabs()),
                         {"DATABASE AGEN", "DATABASE PENJAHIT/MAKLOON"})

    def test_06_header_row_returns_headers(self):
        self.assertEqual(self.sheet.header_row("DATABASE AGEN"), ["Nama", "Alamat", "No HP"])

    def test_07_read_tab_drops_header_by_default(self):
        rows = self.sheet.read_tab("DATABASE AGEN")
        self.assertEqual(rows, [["Budi", "Jl. X", "08123"]])

    def test_08_append_rows_then_read(self):
        self.sheet.append_rows("DATABASE AGEN", [["Siti", "Jl. Z", "085"]])
        rows = self.sheet.read_tab("DATABASE AGEN")
        self.assertIn(["Siti", "Jl. Z", "085"], rows)

    def test_09_update_cell_writes_single_cell(self):
        self.sheet.update_cell("DATABASE AGEN", row=2, col=1, value="BUDI2")
        # header=False keeps the full grid (index 0 = header), data row at idx 1
        rows = self.sheet.read_tab("DATABASE AGEN", header=False)
        self.assertEqual(rows[1][0], "BUDI2")

    def test_10_clear_tab_empties(self):
        self.sheet.clear_tab("DATABASE AGEN")
        self.assertEqual(self.sheet.read_tab("DATABASE AGEN", header=False), [])

    def test_11_find_tab_by_header_resolves(self):
        tab = self.sheet.find_tab_by_header(["Nama", "Alamat", "No HP"])
        self.assertIn(tab, ("DATABASE AGEN", "DATABASE PENJAHIT/MAKLOON"))

    def test_12_sql_shaped_methods_raise_with_clear_reason(self):
        s = self.sheet
        for meth in ("connection", "commit", "rollback"):
            with self.assertRaises(NotImplementedError, msg=f"{meth}()"):
                getattr(s, meth)()
        for meth in ("query", "execute", "fetchone", "fetchall", "insert",
                     "update", "delete"):
            with self.assertRaises(NotImplementedError, msg=f"{meth}()"):
                getattr(s, meth)("SELECT 1")
        with self.assertRaises(NotImplementedError):
            s.audit(1, "login", "auth")


if __name__ == "__main__":
    unittest.main(verbosity=2)