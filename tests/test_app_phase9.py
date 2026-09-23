#!/usr/bin/env python3
"""Phase 9 tests — security hardening: ADMIN password rotation + re-seed invariant.

Runs against an ISOLATED temporary database (same schema.sql + auth seed) so the
real instance/sola.db is never touched.

Covers the Phase 9 hardening criteria:
  (a) rotate_admin_password replaces the default admin hash and writes an
      'ADMIN_PASSWORD_ROTATED' audit row WITHOUT storing the plaintext.
  (b) After rotation, re-running ensure_seeded() does NOT clobber the new hash —
      the rotated password still logs in and the old default does not (the
      central idempotent-seed no-clobber guarantee).
  (c) Wait: enforced minimum length + the seeded default 'sola123' is rejected.
  (d) FK integrity holds inside the rotation path.

    python tests/test_app_phase9.py
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app import create_app  # noqa: E402
from db.init_schema import create_schema  # noqa: E402
from seed.seed_auth import DEFAULT_PASSWORD, ensure_seeded  # noqa: E402
from scripts.rotate_admin_password import MIN_LENGTH, rotate_admin_password  # noqa: E402


def _login(client, username, password):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


class RotateScript(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p9.db")
        create_schema(self.db)
        ensure_seeded(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _app(self):
        app = create_app({"TESTING": True, "DATABASE_PATH": self.db})
        return app.test_client()

    def _hash_of(self, username="admin"):
        return self.conn.execute(
            "SELECT password_hash FROM users WHERE username=?", (username,)
        ).fetchone()

    def test_01_rotate_changes_hash_and_writes_audit(self):
        before = self._hash_of()["password_hash"]
        rotate_admin_password(self.db, "Str0ngPass-2026!")
        after = self._hash_of()["password_hash"]
        self.assertNotEqual(after, before, "password hash must change after rotation")
        audit = self.conn.execute(
            "SELECT action, entity, new_value FROM audit_logs"
            " WHERE action='ADMIN_PASSWORD_ROTATED'"
        ).fetchall()
        self.assertEqual(len(audit), 1, "exactly one rotation audit row")
        self.assertEqual(audit[0]["entity"], "users")
        # plaintext must never be stored in the audit row
        self.assertNotIn("Str0ngPass-2026!", str(dict(audit[0])))

    def test_02_rotated_password_logs_in_default_does_not(self):
        rotate_admin_password(self.db, "Str0ngPass-2026!")
        c = self._app()
        ok = _login(c, "admin", "Str0ngPass-2026!")
        self.assertEqual(ok.status_code, 200)
        self.assertNotIn("Invalid username or password", ok.get_data(as_text=True))
        # the old default must no longer authenticate
        bad = self._app()
        r = _login(bad, "admin", DEFAULT_PASSWORD)
        self.assertIn("Invalid username or password", r.get_data(as_text=True))

    def test_03_reseed_does_NOT_clobber_rotated_password(self):
        """Central no-clobber invariant: re-seeding after rotation must NOT reset admin."""
        rotate_admin_password(self.db, "Str0ngPass-2026!")
        ensure_seeded(self.db)          # idempotent re-seed
        ensure_seeded(self.db)          # run twice to be sure
        # rotated password still works after re-seed ...
        c = self._app()
        ok = _login(c, "admin", "Str0ngPass-2026!")
        self.assertEqual(ok.status_code, 200)
        self.assertNotIn("Invalid username or password", ok.get_data(as_text=True))
        # ... and the old default no longer authenticates
        bad = self._app()
        r = _login(bad, "admin", DEFAULT_PASSWORD)
        self.assertIn("Invalid username or password", r.get_data(as_text=True))
        # only one ADMIN_PASSWORD_ROTATED audit row (seeding adds no spurious audit)
        n = self.conn.execute(
            "SELECT COUNT(*) n FROM audit_logs WHERE action='ADMIN_PASSWORD_ROTATED'"
        ).fetchone()["n"]
        self.assertEqual(n, 1)

    def test_04_short_password_rejected(self):
        with self.assertRaises(SystemExit):
            rotate_admin_password(self.db, "short")

    def test_05_default_password_rejected(self):
        with self.assertRaises(SystemExit):
            rotate_admin_password(self.db, DEFAULT_PASSWORD)

    def test_06_fk_integrity_after_rotation(self):
        rotate_admin_password(self.db, "Str0ngPass-2026!")
        violations = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(violations, [], "foreign_key_check must be empty after rotation")


if __name__ == "__main__":
    unittest.main()