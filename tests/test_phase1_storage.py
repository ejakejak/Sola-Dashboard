#!/usr/bin/env python3
"""Phase 1 tests — pluggable storage abstraction (STORAGE = sqlite|sheets).

Behavior contracts from PHASE1_BRIEF.md (not change-detectors):

  (a) factory returns SqliteStorage when STORAGE unset or "sqlite"
  (b) factory returns SheetsStorage when STORAGE=sheets; it constructs (even
      with no creds) but every data method raises NotImplementedError
  (c) SheetsStorage validates config (SPREADSHEET_ID + service-account file)
      and reports readiness without failing construction
  (d) SqliteStorage wraps existing get_db(); a representative query/write works
      against an isolated temp DB inside an app context
  (e) the app boots with STORAGE unset (default sqlite) and with STORAGE=sheets
      and no creds; only a SheetsStorage data call raises

Run:  python tests/test_phase1_storage.py
"""
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app import create_app  # noqa: E402
from app.storage import (  # noqa: E402
    SheetsStorage,
    SqliteStorage,
    Storage,
    get_storage,
)
from db.init_schema import create_schema  # noqa: E402


class TestStorageFactory(unittest.TestCase):
    """(a) + (b) factory selection, dict and object config forms."""

    def test_01_factory_defaults_to_sqlite_when_storage_unset(self):
        storage = get_storage({})  # STORAGE absent
        self.assertIsInstance(storage, SqliteStorage)
        self.assertIsInstance(storage, Storage)
        self.assertEqual(storage.name, "sqlite")

    def test_02_factory_returns_sqlite_for_explicit_sqlite(self):
        storage = get_storage({"STORAGE": "sqlite"})
        self.assertIsInstance(storage, SqliteStorage)

    def test_03_factory_returns_sheets_for_storage_sheets(self):
        storage = get_storage({"STORAGE": "sheets"})
        self.assertIsInstance(storage, SheetsStorage)
        self.assertEqual(storage.name, "sheets")

    def test_04_factory_accepts_object_style_config(self):
        cfg = types.SimpleNamespace(STORAGE="sqlite", SPREADSHEET_ID=None,
                                    GOOGLE_APPLICATION_CREDENTIALS=None)
        self.assertIsInstance(get_storage(cfg), SqliteStorage)

    def test_05_factory_rejects_unknown_backend(self):
        with self.assertRaises(ValueError):
            get_storage({"STORAGE": "postgres"})


class TestSheetsStorageSkeleton(unittest.TestCase):
    """(b) + (c) SheetsStorage: constructs with no creds, stub raises."""

    DATA_METHODS = ("query", "execute", "fetchone", "fetchall",
                    "insert", "update", "delete", "audit")

    def test_06_constructs_without_creds_and_reports_missing(self):
        s = SheetsStorage()  # no sheet id, no creds
        self.assertFalse(s.already_configured)
        self.assertIn("SPREADSHEET_ID", s.missing)
        self.assertIn("GOOGLE_APPLICATION_CREDENTIALS", s.missing)

    def test_07_constructs_even_when_creds_path_missing(self):
        s = SheetsStorage(spreadsheet_id="abc123",
                          credentials_path="/does/not/exist.json")
        self.assertFalse(s.already_configured)
        self.assertIn("GOOGLE_APPLICATION_CREDENTIALS", s.missing)
        self.assertNotIn("SPREADSHEET_ID", s.missing)

    def test_08_marks_configured_when_id_and_creds_file_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            cred = Path(tmp) / "sa.json"
            cred.write_text('{"type": "service_account"}', encoding="utf-8")
            s = SheetsStorage(spreadsheet_id="sheet-1",
                              credentials_path=str(cred))
            self.assertTrue(s.already_configured)
            self.assertEqual(s.missing, [])

    def test_09_all_data_methods_raise_not_implemented(self):
        s = SheetsStorage()
        for method in self.DATA_METHODS:
            with self.assertRaises(NotImplementedError, msg=f"{method}()"):
                if method == "audit":
                    getattr(s, method)(1, "login", "auth")
                else:
                    getattr(s, method)("SELECT 1")


class TestSqliteStorage(unittest.TestCase):
    """(d) SqliteStorage wraps get_db(); representative query + writes work."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "sola_phase1.db")
        create_schema(self.db_path)
        self.app = create_app({
            "TESTING": True,
            "DATABASE_PATH": self.db_path,
            "SECRET_KEY": "phase1-secret",
        })
        self.storage = self.app.extensions["storage"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_10_storage_is_sqlite_backend_on_app(self):
        self.assertIsInstance(self.storage, SqliteStorage)

    def test_11_query_and_fetch_work_against_temp_db(self):
        with self.app.app_context():
            self.storage.execute(
                "INSERT INTO customers (customer_code, name, status) VALUES (?,?,?)",
                ("CUST-P1", "Phase One Customer", "active"))
            self.storage.commit()
            rows = self.storage.query(
                "SELECT customer_code, name FROM customers WHERE customer_code=?",
                ("CUST-P1",))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "Phase One Customer")
            one = self.storage.fetchone(
                "SELECT name FROM customers WHERE customer_code=?",
                ("CUST-P1",))
            self.assertEqual(one["name"], "Phase One Customer")

    def test_12_update_and_delete_commit(self):
        with self.app.app_context():
            self.storage.insert(
                "INSERT INTO customers (customer_code, name, status) VALUES (?,?,?)",
                ("CUST-P1B", "Before Update", "active"))
            self.storage.update(
                "UPDATE customers SET name=? WHERE customer_code=?",
                ("After Update", "CUST-P1B"))
            self.storage.commit()
            row = self.storage.fetchone(
                "SELECT name FROM customers WHERE customer_code=?",
                ("CUST-P1B",))
            self.assertEqual(row["name"], "After Update")
            self.storage.delete(
                "DELETE FROM customers WHERE customer_code=?",
                ("CUST-P1B",))
            self.storage.commit()
            gone = self.storage.fetchall(
                "SELECT customer_code FROM customers WHERE customer_code=?",
                ("CUST-P1B",))
            self.assertEqual(gone, [])

    def test_13_audit_primitive_writes_audit_log(self):
        with self.app.app_context():
            # audit_logs.user_id is FK -> need a real user row first
            self.storage.insert(
                "INSERT INTO users (username, full_name, status) VALUES (?,?,?)",
                ("p1_user", "Phase One", "active"))
            uid = self.storage.fetchone(
                "SELECT user_id FROM users WHERE username=?", ("p1_user",))
            self.storage.audit(uid["user_id"], "login", "auth", entity_id=None,
                               old_value=None, new_value=None)
            rows = self.storage.query(
                "SELECT action, entity FROM audit_logs WHERE action=?",
                ("login",))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["entity"], "auth")


class TestAppBootStorage(unittest.TestCase):
    """(e) The app boots with STORAGE unset (sqlite default) and with
    STORAGE=sheets + no creds. Only a SheetsStorage data call raises."""

    def _mkapp(self, storage=None):
        tmp = Path(tempfile.mkdtemp())
        dbp = str(tmp / "sola_boot.db")
        create_schema(dbp)
        cfg = {"TESTING": True, "DATABASE_PATH": dbp,
               "SECRET_KEY": "phase1-secret"}
        if storage is not None:
            cfg["STORAGE"] = storage
        return tmp, create_app(cfg)

    def test_14_app_boots_with_storage_unset_default_sqlite(self):
        tmp, app = self._mkapp()
        try:
            self.assertIsInstance(app.extensions["storage"], SqliteStorage)
            # a request still works -> no regression
            r = app.test_client().get("/", follow_redirects=False)
            self.assertIn(r.status_code, (200, 302))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_15_app_boots_with_storage_sheets_no_creds(self):
        tmp, app = self._mkapp("sheets")
        try:
            storage = app.extensions["storage"]
            self.assertIsInstance(storage, SheetsStorage)
            self.assertFalse(storage.already_configured, "no creds configured")
            r = app.test_client().get("/", follow_redirects=False)
            self.assertIn(r.status_code, (200, 302), "app boots with sheets")
            with self.assertRaises(NotImplementedError):
                with app.app_context():
                    storage.query("SELECT 1")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)