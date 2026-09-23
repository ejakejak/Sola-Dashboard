#!/usr/bin/env python3
"""Phase 2 tests — storage abstraction as the primary DB access seam.

Behavior contracts from PHASE2_BRIEF.md:

  (a) SqliteStorage.connection() returns the SAME request-scoped connection that
      get_db() provides (identity), so blueprints/helpers taking a raw connection
      work unchanged.
  (b) Write primitives do NOT auto-commit (D1): an insert is invisible to a
      SEPARATE connection until storage.commit(); rollback() discards a batch.
  (c) insert() returns a cursor with lastrowid readable before commit.

Run:  python tests/test_phase2_storage.py
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app import create_app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.storage import SqliteStorage, Storage  # noqa: E402
from db.init_schema import create_schema  # noqa: E402


class TestSqliteConnectionSeam(unittest.TestCase):
    """(a) connection() identity + interface presence."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "sola_phase2.db")
        create_schema(self.db_path)
        self.app = create_app({
            "TESTING": True,
            "DATABASE_PATH": self.db_path,
            "SECRET_KEY": "phase2-secret",
        })
        self.storage = self.app.extensions["storage"]
        self.assertIsInstance(self.storage, SqliteStorage)

    def tearDown(self):
        self._tmp.cleanup()

    def test_01_storage_implements_full_contract(self):
        for method in ("connection", "commit", "rollback", "query", "execute",
                       "fetchone", "fetchall", "insert", "update", "delete", "audit"):
            self.assertTrue(callable(getattr(self.storage, method)),
                            f"SqliteStorage.{method} exists")

    def test_02_connection_returns_same_object_as_get_db(self):
        with self.app.app_context():
            self.assertIs(self.storage.connection(), get_db(),
                          "connection() must be the exact per-request get_db() conn")

    def test_03_connection_consistent_within_request(self):
        with self.app.app_context():
            a = self.storage.connection()
            b = self.storage.connection()
            self.assertIs(a, b, "connection() is stable within one request/app context")


class TestSqliteTransactionSemantics(unittest.TestCase):
    """(b)+(c) D1: write primitives do not auto-commit; rollback discards."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "sola_phase2_tx.db")
        create_schema(self.db_path)
        self.app = create_app({
            "TESTING": True,
            "DATABASE_PATH": self.db_path,
            "SECRET_KEY": "phase2-secret",
        })
        self.storage = self.app.extensions["storage"]

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _new_conn(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert_customer(self, code="CUST-P2", name="Tx Customer"):
        with self.app.app_context():
            return self.storage.insert(
                "INSERT INTO customers (customer_code, name, status) VALUES (?,?,?)",
                (code, name, "active"))

    def test_04_insert_not_committed_until_explicit_commit(self):
        with self.app.app_context():
            self.storage.execute(
                "INSERT INTO customers (customer_code, name, status) VALUES (?,?,?)",
                ("CUST-P2A", "Uncommitted", "active"))
            # separate connection must NOT see the uncommitted row
            conn = self._new_conn(self.db_path)
            n = conn.execute("SELECT COUNT(*) FROM customers "
                             "WHERE customer_code='CUST-P2A'").fetchone()[0]
            conn.close()
            self.assertEqual(n, 0, "row invisible from another connection before commit")
            # after commit, visible
            self.storage.commit()
            conn = self._new_conn(self.db_path)
            n = conn.execute("SELECT COUNT(*) FROM customers "
                             "WHERE customer_code='CUST-P2A'").fetchone()[0]
            conn.close()
            self.assertEqual(n, 1, "row visible after commit")

    def test_05_rollback_discards_pending_batch(self):
        with self.app.app_context():
            self.storage.insert(
                "INSERT INTO customers (customer_code, name, status) VALUES (?,?,?)",
                ("CUST-P2B", "To Rollback", "active"))
            self.storage.rollback()
            conn = self._new_conn(self.db_path)
            n = conn.execute("SELECT COUNT(*) FROM customers "
                             "WHERE customer_code='CUST-P2B'").fetchone()[0]
            conn.close()
            self.assertEqual(n, 0, "rollback discards uncommitted write")

    def test_06_multiple_writes_committed_once(self):
        with self.app.app_context():
            for code in ("CUST-P2C1", "CUST-P2C2"):
                self.storage.insert(
                    "INSERT INTO customers (customer_code, name, status) VALUES (?,?,?)",
                    (code, "Batch", "active"))
            self.storage.commit()
            conn = self._new_conn(self.db_path)
            n = conn.execute("SELECT COUNT(*) FROM customers "
                             "WHERE customer_code LIKE 'CUST-P2C%'").fetchone()[0]
            conn.close()
            self.assertEqual(n, 2, "batch commit persists all writes")

    def test_07_insert_cursor_exposes_lastrowid_before_commit(self):
        with self.app.app_context():
            cur = self.storage.insert(
                "INSERT INTO customers (customer_code, name, status) VALUES (?,?,?)",
                ("CUST-P2D", "Lastrowid", "active"))
            lid = cur.lastrowid
            self.assertGreater(lid, 0, "lastrowid available before commit")
            self.storage.commit()
            conn = self._new_conn(self.db_path)
            try:
                got = conn.execute("SELECT name FROM customers WHERE customer_id=?",
                                   (lid,)).fetchone()
            finally:
                conn.close()
            self.assertEqual(got["name"], "Lastrowid")


if __name__ == "__main__":
    unittest.main(verbosity=2)