#!/usr/bin/env python3
"""Phase 5 tests — SheetRelatable engine (sheet-backed tables, no SQL).

Behavior contracts:
  (a) insert() appends a row and assigns the next numeric PK when empty
  (b) read_all() / get() round-trip stored records
  (c) find()/find_one() filter by named columns; count()/sum_column() aggregate
  (d) update() changes cells by PK; delete() removes a row (whole-table rewrite)
  (e) insert auto-increments on numeric PKs
Runs against a FAKE gspread (no network), per the gspread skill stub rule.

Run:  python tests/test_phase5_sheetdb.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app.sheetdb import SheetRelational  # noqa: E402

# Reuse the fake gspread harness from test_phase34_sheets.py
_T34 = Path(__file__).with_name("test_phase34_sheets.py")
import runpy  # noqa: E402


def _install_fake():
    ns = runpy.run_path(str(_T34))
    return ns["_install_fake_gspread"](), ns["FAKE_SHEET_ID"]


class TestSheetRelational(unittest.TestCase):
    def setUp(self):
        self._fake, self.sheet_id = _install_fake()
        self.tmp = Path(tempfile.mkdtemp())
        cred = self.tmp / "sa.json"
        cred.write_text("{}", encoding="utf-8")
        from app.storage import SheetsStorage
        sheets = SheetsStorage(spreadsheet_id=self.sheet_id,
                               credentials_path=str(cred))
        rel = SheetRelational(sheets)
        # define a customers table over a fake tab; then (re)seed header row
        rel.define("DATABASE AGEN", ["customer_id", "name", "balance"])
        rel.sheets.clear_tab("DATABASE AGEN")
        rel.sheets.append_rows("DATABASE AGEN", [["customer_id", "name", "balance"]])
        self.rel = rel.table("DATABASE AGEN")

    def tearDown(self):
        sys.modules.pop("gspread", None)

    def test_01_insert_assigns_numeric_pk_and_round_trips(self):
        self.rel.insert({"name": "Alice", "balance": 100.5})
        rows = self.rel.read_all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer_id"], 1)
        self.assertEqual(rows[0]["name"], "Alice")
        self.assertEqual(float(rows[0]["balance"]), 100.5)

    def test_02_insert_auto_increments(self):
        self.rel.insert({"name": "A", "balance": 1})
        self.rel.insert({"name": "B", "balance": 2})
        self.rel.insert({"name": "C", "balance": 3})
        got = [r["customer_id"] for r in self.rel.read_all()]
        self.assertEqual(got, [1, 2, 3])

    def test_03_get_by_pk(self):
        self.rel.insert({"name": "A", "balance": 1})
        self.rel.insert({"name": "B", "balance": 2})
        rec = self.rel.get(2)
        self.assertEqual(rec["name"], "B")
        self.assertIsNone(self.rel.get(99))

    def test_04_find_and_aggregate(self):
        self.rel.insert({"name": "A", "balance": 10})
        self.rel.insert({"name": "B", "balance": 20})
        self.rel.insert({"name": "C", "balance": 30})
        self.assertEqual(self.rel.count(), 3)
        self.assertEqual(self.rel.count(balance="20"), 1)
        self.assertEqual(self.rel.find_one(name="A")["customer_id"], 1)
        self.assertAlmostEqual(self.rel.sum_column("balance"), 60.0)
        self.assertAlmostEqual(self.rel.sum_column("balance", name="B"), 20.0)

    def test_05_update_by_pk(self):
        self.rel.insert({"name": "A", "balance": 1})
        self.rel.insert({"name": "B", "balance": 2})
        upd = self.rel.update(2, {"balance": 99, "name": "Bee"})
        self.assertEqual(upd["balance"], 99)
        rec = self.rel.get(2)
        self.assertEqual(rec["name"], "Bee")
        self.assertEqual(float(rec["balance"]), 99)
        # record 1 untouched
        self.assertEqual(self.rel.get(1)["balance"], 1)

    def test_06_delete_by_pk(self):
        self.rel.insert({"name": "A", "balance": 1})
        self.rel.insert({"name": "B", "balance": 2})
        self.rel.insert({"name": "C", "balance": 3})
        self.assertTrue(self.rel.delete(2))
        got = [r["name"] for r in self.rel.read_all()]
        self.assertEqual(got, ["A", "C"])
        self.assertFalse(self.rel.delete(99))

    def test_07_multi_insert(self):
        self.rel.multi_insert([
            {"name": "A", "balance": 1},
            {"name": "B", "balance": 2},
        ])
        self.assertEqual(len(self.rel.read_all()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)