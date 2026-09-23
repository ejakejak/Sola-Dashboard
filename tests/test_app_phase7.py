#!/usr/bin/env python3
"""Phase 7 tests — public customer tracking /track (spec §19 / §20).

Isolated temp DB (same schema.sql) — the real instance/sola.db is never touched.

Covers:
  (a) anonymous GET /track -> 200 (NO login required)
  (b) valid production_code renders product/qty/deadline/stage/timeline +
      CUSTOMER-visibility media, and ZERO INTERNAL items in the HTML
  (c) wrong/garbage code -> generic not-found (no existence oracle)
  (d) rapid wrong guesses -> rate limit engages (5 fails -> cooldown; 6th blocked)
  (e) customer HTML contains none of HPP / margin / vendor_price / internal
  plus: no DB primary keys leaked in the HTML, CUSTOMER media servable through
  /track/media/<code>/<file> while INTERNAL media is not servable (404).

  python tests/test_app_phase7.py
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

OK, BLOCKED = 200, 429

CODE = "PRD-P7-0001"
PRODUCT_NAME = "Cotton Polo"
VARIANT_NAME = "Combed 24s"
CUST_MEDIA = "prod_9_cutting_preview.png"
INT_MEDIA = "prod_9_internal_only.png"   # lowercase 'internal' on purpose: a leak
                                        # would trip BOTH test (b) and test (e).

UPLOADS = Path(_APP_DIR) / "app" / "static" / "uploads"


def _seed(db_path):
    """Minimal customer-visible production graph: customer -> order -> production
    with 3 stages, a CUSTOMER media row and an INTERNAL media row."""
    os.makedirs(UPLOADS, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()
    cur.execute("INSERT INTO customers (customer_code, name, status) VALUES (?,?,?)",
                ("CUST-P7", "Ana Garner", "active"))
    cid = cur.execute("SELECT customer_id FROM customers WHERE customer_code='CUST-P7'").fetchone()[0]
    cur.execute("INSERT INTO orders (order_number, customer_id, order_date, deadline, status)"
                " VALUES (?,?,?,?, 'confirmed')",
                ("ORD-P7-0001", cid, "2026-09-22", "2026-11-15"))
    oid = cur.execute("SELECT order_id FROM orders WHERE order_number='ORD-P7-0001'").fetchone()[0]
    cur.execute("INSERT INTO products (product_code, product_name, status) VALUES (?,?, 'active')",
                ("PRD-7-001", PRODUCT_NAME))
    pid_prod = cur.execute("SELECT product_id FROM products WHERE product_code='PRD-7-001'").fetchone()[0]
    cur.execute("INSERT INTO product_variants (product_id, variant_name) VALUES (?,?)",
                (pid_prod, VARIANT_NAME))
    vid = cur.execute("SELECT variant_id FROM product_variants WHERE variant_name=?",
                      (VARIANT_NAME,)).fetchone()[0]
    cur.execute(
        "INSERT INTO production_orders (production_code, order_id, product_id, variant_id,"
        " quantity, deadline, current_stage, overall_progress, status, notes)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (CODE, oid, pid_prod, vid, 12, "2026-11-15", "CUTTING", 22.0, "in_progress",
         "Please call before despatching."))
    pid = cur.execute("SELECT production_id FROM production_orders WHERE production_code=?", (CODE,)).fetchone()[0]
    for seq, name, status in [(1, "ORDER", "completed"),
                              (2, "CUTTING", "in_progress"),
                              (3, "SEWING", "pending")]:
        cur.execute(
            "INSERT INTO production_stages (production_id, stage_name, sequence, status)"
            " VALUES (?,?,?,?)", (pid, name, seq, status))
    cur.execute(
        "INSERT INTO production_updates (production_id, progress, quantity_completed, notes)"
        " VALUES (?,?,?,?)", (pid, 20, 2, "Cutting started; 2 of 12 pieces done."))
    cur.execute(
        "INSERT INTO production_media (production_id, file_url, file_type, visibility)"
        " VALUES (?,?,?, 'CUSTOMER')", (pid, CUST_MEDIA, "image"))
    cur.execute(
        "INSERT INTO production_media (production_id, file_url, file_type, visibility)"
        " VALUES (?,?,?, 'INTERNAL')", (pid, INT_MEDIA, "image"))
    conn.commit()
    conn.close()
    # write real tiny files so the CUSTOMER media serve route returns a real 200
    for fn in (CUST_MEDIA, INT_MEDIA):
        fpath = UPLOADS / fn
        # sanitised — our seeded filenames have no separators
        if not fpath.exists():
            fpath.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return pid


def _mkapp(db_path):
    cfg = {"TESTING": True, "DATABASE_PATH": db_path, "SECRET_KEY": "test-secret"}
    app = create_app(cfg)
    create_schema(db_path)
    return app


def _clean_uploads():
    for fn in (CUST_MEDIA, INT_MEDIA):
        try:
            os.remove(UPLOADS / fn)
        except FileNotFoundError:
            pass


class TrackBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p7.db")
        self.app = _mkapp(self.db)
        self.c = self.app.test_client()
        _seed(self.db)

    def tearDown(self):
        _clean_uploads()
        self._tmp.cleanup()


class TestAnonymousAccess(TrackBase):
    def test_01_track_requires_no_login(self):
        r = self.c.get("/track")
        self.assertEqual(r.status_code, OK)
        body = r.get_data(as_text=True)
        self.assertIn("Track your order", body)
        self.assertIn('name="code"', body)


class TestCustomerVisibleLookup(TrackBase):
    def test_02_valid_code_renders_customer_data_only(self):
        r = self.c.post("/track", data={"code": CODE})
        self.assertEqual(r.status_code, OK)
        body = r.get_data(as_text=True)
        # customer-visible fields rendered
        self.assertIn(CODE, body)
        self.assertIn(PRODUCT_NAME, body)
        self.assertIn(VARIANT_NAME, body)
        self.assertIn("12 pcs", body)
        self.assertIn("2026-11-15", body)          # deadline / estimated completion
        self.assertIn("CUTTING", body)             # current stage
        self.assertIn("Photos", body)
        self.assertIn(CUST_MEDIA, body)            # CUSTOMER media rendered
        self.assertIn("Cutting started", body)     # latest customer-visible update
        self.assertIn("Call before despatching".lower(), body.lower())  # important notes
        # timeline stages present
        for st in ("ORDER", "SEWING"):
            self.assertIn(st, body)
        # ZERO INTERNAL items: the INTERNAL-only media filename must not appear
        self.assertNotIn(INT_MEDIA, body, "INTERNAL media must never render on /track")
        # no DB primary keys leaked
        self.assertNotIn("production_id", body)
        self.assertNotIn("media_id", body)
        self.assertNotIn("update_id", body)

    def test_03_customer_media_served_but_internal_not(self):
        ok = self.c.get(f"/track/media/{CODE}/{CUST_MEDIA}")
        self.assertEqual(ok.status_code, OK, "CUSTOMER media should be servable")
        blocked = self.c.get(f"/track/media/{CODE}/{INT_MEDIA}")
        self.assertEqual(blocked.status_code, 404,
                         "INTERNAL media must not be servable on any public surface")

    def test_04_html_free_of_prohibited_internals(self):
        body = self.c.post("/track", data={"code": CODE}).get_data(as_text=True)
        low = body.lower()
        for stick in ("hpp", "margin", "vendor_price", "internal"):
            self.assertNotIn(stick, low, f"customer HTML must not contain '{stick}'")


class TestAntiEnumeration(TrackBase):
    def test_05_wrong_code_generic_no_oracle(self):
        for garbage in ("PRD-000000-999", "NOPE-123", "ABC"):
            r = self.c.post("/track", data={"code": garbage})
            self.assertEqual(r.status_code, OK)
            body = r.get_data(as_text=True)
            self.assertIn("Production not found", body)
            # the generic page must NOT reveal any real production data
            self.assertNotIn(PRODUCT_NAME, body)
            self.assertNotIn(CODE, body)

    def test_06_valid_code_clears_fail_chain_rate_limit(self):
        # 4 wrong guesses then a valid one: no block (5+ fails never accumulate)
        for i in range(4):
            self.c.post("/track", data={"code": f"NOPE-{i}"})
        ok = self.c.post("/track", data={"code": CODE})
        self.assertEqual(ok.status_code, OK)
        self.assertIn(PRODUCT_NAME, ok.get_data(as_text=True))


class TestRateLimit(TrackBase):
    def test_07_rapid_wrong_guesses_eventually_blocked(self):
        statuses = []
        blocked_msg = False
        for i in range(8):
            r = self.c.post("/track", data={"code": f"FAKE-{i}"})
            statuses.append(r.status_code)
            if "Too many attempts" in r.get_data(as_text=True):
                blocked_msg = True
        # first five miss as generic not-found; the cooldown engages at the 5th
        # failure so the 6th+ submission must be rejected (429 or generic block).
        self.assertEqual(statuses[:5], [OK] * 5, "first five wrong codes are generic misses")
        blocked = [s for s in statuses[5:] if s == BLOCKED or blocked_msg]
        self.assertTrue(blocked, f"rate limit must engage; got statuses={statuses}")
        self.assertTrue(any(s == BLOCKED for s in statuses) or blocked_msg,
                        f"expected an explicit block; statuses={statuses}")


if __name__ == "__main__":
    unittest.main(verbosity=2)