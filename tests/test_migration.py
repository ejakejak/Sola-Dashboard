#!/usr/bin/env python3
"""Phase-1 migration tests — validate the key normalization guarantees.

Runs the real importer against the REAL source workbook (read-only) into a
temporary DB + report, then asserts the canonical normalization rules from
docs/AUDIT_REPORT.md and docs/DATA_DICTIONARY.md.

    python tests/test_migration.py            # or: python -m unittest
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from scripts.import_excel import run_migration  # noqa: E402

SOURCE = os.path.join(BASE, "data", "master.xlsx")
SCHEMA = os.path.join(BASE, "db", "schema.sql")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class TestMigration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="sola_mig_")
        self._db = os.path.join(self._tmp, "sola.db")
        self._report = os.path.join(self._tmp, "migration_report.json")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self):
        return run_migration(SOURCE, self._db, SCHEMA, self._report)

    def _conn(self):
        c = sqlite3.connect(self._db)
        c.row_factory = sqlite3.Row
        return c

    def test_no_errors_and_exit_semantics(self):
        payload = self._run()
        self.assertEqual(payload["errors"], [])

    def test_phone_leading_zero_restored(self):
        self._run()
        with self._conn() as db:
            rows = {r["name"]: r["phone"] for r in db.execute(
                "SELECT name, phone FROM agents")}
        self.assertEqual(rows["ZAKARIA"], "0895391621335")
        self.assertEqual(rows["ARGA"], "085156455465")

    def test_dash_phone_is_null(self):
        self._run()
        with self._conn() as db:
            nulls = [r["vendor_name"] for r in db.execute(
                "SELECT vendor_name FROM vendors WHERE phone IS NULL")]
        self.assertIn("Duwi", nulls)
        self.assertIn("Mas Pupung", nulls)
        self.assertEqual(len(nulls), 2)

    def test_context_variant_prices_not_merged(self):
        """American Drill must keep BOTH the Korsa (40500) and Vest (49200) prices."""
        self._run()
        with self._conn() as db:
            prices = [r["unit_price"] for r in db.execute(
                "SELECT mp.unit_price FROM material_prices mp "
                "JOIN materials m ON m.material_id = mp.material_id "
                "WHERE m.material_name = 'American Drill'")]
        self.assertIn(40500.0, prices)
        self.assertIn(49200.0, prices)

    def test_one_material_master_per_canonical_name(self):
        """Decision D2: no duplicate material master names; context prices live
        in material_prices (Korsa+Vest+Topi+Totebag for American Drill)."""
        self._run()
        with self._conn() as db:
            dupes = [r["material_name"] for r in db.execute(
                "SELECT material_name, COUNT(*) AS c FROM materials "
                "GROUP BY material_name HAVING COUNT(*) > 1")]
            self.assertEqual(dupes, [], f"duplicated material master names: {dupes}")

            # exactly ONE master row each, with its context prices on the master
            master_counts = {
                r["material_name"]: r["c"] for r in db.execute(
                    "SELECT material_name, COUNT(*) AS c FROM materials "
                    "GROUP BY material_name")}
            self.assertEqual(master_counts.get("American Drill"), 1)
            self.assertEqual(master_counts.get("Nagata Drill"), 1)

            def prices(name):
                return sorted(r["unit_price"] for r in db.execute(
                    "SELECT mp.unit_price FROM material_prices mp "
                    "JOIN materials m ON m.material_id = mp.material_id "
                    "WHERE m.material_name = ?", (name,)))

            self.assertEqual(prices("American Drill"),
                             [4000.0, 8000.0, 40500.0, 49200.0])
            self.assertEqual(prices("Nagata Drill"), [5000.0, 52000.0, 60000.0])

            # context categories of those prices are exactly as expected
            cats = sorted(r["category_name"] for r in db.execute(
                "SELECT pc.category_name FROM material_prices mp "
                "JOIN materials m ON m.material_id = mp.material_id "
                "LEFT JOIN product_categories pc ON pc.category_id = mp.category_id "
                "WHERE m.material_name = 'American Drill'"))
            self.assertEqual(cats, ["Korsa", "Topi", "Totebag", "Vest"])

    def test_kaos_alias_mapped_to_jersey(self):
        """'Kaos' in the HPP Jersey group maps to the canonical 'Jersey' material."""
        self._run()
        with self._conn() as db:
            jersey = db.execute(
                "SELECT mp.unit_price FROM material_prices mp "
                "JOIN materials m ON m.material_id = mp.material_id "
                "WHERE m.material_name = 'Jersey'").fetchall()
        self.assertTrue(jersey, "expected a 'Jersey' material with at least one price")
        prices = [r["unit_price"] for r in jersey]
        self.assertIn(15500.0, prices)

    def test_kanvas_trailing_space_trimmed(self):
        self._run()
        with self._conn() as db:
            names = [r["material_name"] for r in db.execute(
                "SELECT material_name FROM materials WHERE material_name LIKE 'Kanvas%'")]
        self.assertIn("Kanvas", names)
        self.assertNotIn("Kanvas ", names)

    def test_fee_mapped_to_commission_template_not_cost(self):
        self._run()
        with self._conn() as db:
            cats = {r["category_name"]: r for r in db.execute(
                "SELECT pc.category_name, ct.commission_mode, ct.commission_cap "
                "FROM commission_templates ct "
                "JOIN product_categories pc ON pc.category_id = ct.product_category_id "
                "WHERE pc.category_name IN ('T-Shirt','Goodiebag')")}
        self.assertEqual(cats["T-Shirt"]["commission_mode"], "flat_cap")
        self.assertEqual(cats["T-Shirt"]["commission_cap"], 5000.0)
        self.assertEqual(cats["Goodiebag"]["commission_mode"], "percent_of_profit")

    def test_stray_m1_flagged_not_imported(self):
        payload = self._run()
        joined = " ".join(payload["warnings"])
        self.assertIn("31500", joined)
        self.assertNotIn("\"m1\"", str(payload).lower())

    def test_category_and_vendor_counts(self):
        payload = self._run()
        self.assertEqual(payload["rows_imported"]["product_categories_count"], 14)
        self.assertEqual(payload["rows_imported"]["vendors_count"], 17)
        self.assertEqual(payload["rows_imported"]["agents_count"], 2)

    def test_foreign_key_integrity(self):
        self._run()
        with self._conn() as db:
            violations = db.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(violations, [])

    def test_idempotent_rerun(self):
        p1 = self._run()
        p2 = self._run()
        counts = lambda p: {k: v for k, v in p["rows_imported"].items()
                            if k.endswith("_count") or k in ("agents", "vendors")}
        self.assertEqual(counts(p1), counts(p2))

    def test_source_workbook_never_modified(self):
        before = sha256(SOURCE)
        self._run()
        self._run()
        after = sha256(SOURCE)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)