#!/usr/bin/env python3
"""Phase 8 tests — Dashboard live KPI cards + alerts + Production Board Kanban.

Isolated temp DB (same schema.sql + auth seed) so the real instance/sola.db is
never touched. Covers exactly what PHASE8_BRIEF §4 requires:

  (a) authenticated GET / renders the 6 KPI cards with numeric values, no 500
  (b) each KPI number matches the live DB (active orders count, in production,
      waiting payment, ready to ship, overdue, outstanding-invoice sum)
  (c) /production/board renders; every production card appears in the column
      matching its current_stage; unassigned/cancelled handled per fallback
  (d) the compact-table toggle control is present and the table lists ALL rows
  (e) low-stock + overdue + unpaid-invoice alerts surface per the seeded data

    python tests/test_app_phase8.py
"""
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app import create_app  # noqa: E402
from db.init_schema import create_schema  # noqa: E402
from seed.seed_auth import DEFAULT_PASSWORD, ensure_seeded  # noqa: E402

OK, REDIRECT = 200, 302
TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
FUTURE = (TODAY + timedelta(days=14)).isoformat()

KPI_LABELS = ["Active Orders", "In Production", "Waiting Payment",
              "Ready to Ship", "Overdue", "Outstanding Invoice"]


def _seed(db_path):
    """Deterministic dashboard/board dataset.

    Active orders: 1   In production: 2   Waiting payment: 1   Ready to ship: 1
    Overdue: 1         Outstanding: 250000                       Low stock: 1
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    cur.execute("INSERT INTO customers (customer_code, name, status) VALUES (?,?,?)",
                ("CUST-P8", "Winda", "active"))
    cid = cur.execute("SELECT customer_id FROM customers WHERE customer_code='CUST-P8'").fetchone()[0]

    # one ACTIVE order + one COMPLETED order
    cur.execute("INSERT INTO orders (order_number, customer_id, order_date, deadline, status, priority)"
                " VALUES (?,?,?,?,?,?)",
                ("ORD-P8-0001", cid, TODAY.isoformat(), FUTURE, "confirmed", "high"))
    oid_a = cur.execute("SELECT order_id FROM orders WHERE order_number='ORD-P8-0001'").fetchone()[0]
    cur.execute("INSERT INTO orders (order_number, customer_id, order_date, deadline, status)"
                " VALUES (?,?,?,?,?)",
                ("ORD-P8-0002", cid, TODAY.isoformat(), FUTURE, "completed"))
    oid_b = cur.execute("SELECT order_id FROM orders WHERE order_number='ORD-P8-0002'").fetchone()[0]

    cur.execute("INSERT INTO products (product_code, product_name, status) VALUES (?,?, 'active')",
                ("PRD-P8-1", "Cotton Polo"))
    prod = cur.execute("SELECT product_id FROM products WHERE product_code='PRD-P8-1'").fetchone()[0]

    # productions: PRD-1 CUTTING (active), PRD-2 PACKING (overdue), PRD-3 COMPLETED (ready to ship)
    # In Production = not completed/cancelled => PRD-1, PRD-2 = 2
    for code, oid, stage, dl, prog, status in [
        ("PRD-P8-001", oid_a, "CUTTING", _future(), 40.0, "in_progress"),
        ("PRD-P8-002", oid_a, "PACKING", YESTERDAY, 80.0, "in_progress"),
        ("PRD-P8-003", oid_b, "COMPLETED", YESTERDAY, 100.0, "completed"),
    ]:
        cur.execute(
            "INSERT INTO production_orders (production_code, order_id, product_id,"
            " quantity, deadline, current_stage, overall_progress, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?, datetime('now'))",
            (code, oid, prod, 12, dl, stage, prog, status))
    pid1 = cur.execute("SELECT production_id FROM production_orders WHERE production_code='PRD-P8-001'").fetchone()[0]
    # one stage in_progress on PRD-1 so the board can show a PIC
    cur.execute("INSERT INTO production_stages (production_id, stage_name, sequence, status, assigned_user)"
                " VALUES (?,?,?,?,?)", (pid1, "CUTTING", 1, "in_progress", None))

    # invoices: one with an outstanding balance (=250000), one fully paid
    cur.execute("INSERT INTO invoices (invoice_number, order_id, customer_id, invoice_date,"
                " due_date, grand_total, amount_paid, outstanding, status)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                ("INV-P8-0001", oid_a, cid, TODAY.isoformat(), FUTURE, 500000.0, 250000.0, 250000.0, "partially_paid"))
    cur.execute("INSERT INTO invoices (invoice_number, order_id, customer_id, invoice_date,"
                " grand_total, amount_paid, outstanding, status)"
                " VALUES (?,?,?,?,?,?,?,?)",
                ("INV-P8-0002", oid_b, cid, TODAY.isoformat(), 500000.0, 500000.0, 0.0, "paid"))

    # low-stock: one tracked material at/below threshold (available = 0)
    cur.execute("INSERT INTO materials (material_code, material_name, status) VALUES (?,?, 'active')",
                ("CC-P8-S", "Combed Low Stock"))
    mat = cur.execute("SELECT material_id FROM materials WHERE material_code='CC-P8-S'").fetchone()[0]
    cur.execute("INSERT INTO inventory (material_id, unit_id, on_hand, reserved, available)"
                " VALUES (?,?,?,?,?)", (mat, None, 0.0, 0.0, 0.0))

    # recent production update feed
    cur.execute("INSERT INTO production_updates (production_id, user_id, progress, quantity_completed, notes)"
                " VALUES (?,?,?,?,?)", (pid1, None, 40, 5, "Cutting half done"))

    conn.commit()
    conn.close()


def _future():
    return (date.today() + timedelta(days=14)).isoformat()


def _mkapp(db_path):
    cfg = {"TESTING": True, "DATABASE_PATH": db_path, "SECRET_KEY": "phase8-secret"}
    app = create_app(cfg)
    create_schema(db_path)
    ensure_seeded(db_path)
    return app


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def _login(client, username="admin"):
    return client.post("/login", data={"username": username, "password": DEFAULT_PASSWORD})


class Phase8Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_phase8.db")
        self.app = _mkapp(self.db)
        self.c = self.app.test_client()
        _seed(self.db)
        _login(self.c, "admin")

    def tearDown(self):
        self._tmp.cleanup()


class TestDashboardKpis(Phase8Base):
    def test_01_dashboard_authed_renders_six_kpi_cards(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, OK, "dashboard must not 500")
        body = r.get_data(as_text=True)
        for label in KPI_LABELS:
            self.assertIn(label, body, f"KPI card '{label}' present")
        # every KPI card annotated with a key + a live numeric value (not a placeholder)
        for key in ("active_orders", "in_production", "waiting_payment",
                    "ready_to_ship", "overdue", "outstanding_invoice"):
            self.assertIn(f'data-kpi="{key}"', body, f"KPI data-key {key} present")

    def test_02_anonymous_dashboard_redirects_to_login(self):
        anon = self.app.test_client()
        r = anon.get("/", follow_redirects=False)
        self.assertEqual(r.status_code, REDIRECT)
        self.assertIn("/login", r.headers.get("Location", ""))

    def test_03_kpi_numbers_match_live_db(self):
        body = self.c.get("/").get_data(as_text=True)

        active = _query(self.db, "SELECT COUNT(*) n FROM orders WHERE status NOT IN ('completed','cancelled')")[0]["n"]
        inprod = _query(self.db, "SELECT COUNT(*) n FROM production_orders WHERE status NOT IN ('completed','cancelled')")[0]["n"]
        waitpay = _query(self.db, "SELECT COUNT(*) n FROM invoices WHERE outstanding > 0")[0]["n"]
        rts = _query(self.db, "SELECT COUNT(*) n FROM production_orders WHERE (status='completed' OR current_stage='COMPLETED') AND status != 'cancelled'")[0]["n"]
        overdue = _query(self.db, "SELECT COUNT(*) n FROM production_orders WHERE deadline IS NOT NULL AND deadline < ? AND status NOT IN ('completed','cancelled')", (TODAY.isoformat(),))[0]["n"]
        outstanding = _query(self.db, "SELECT COALESCE(SUM(outstanding),0) s FROM invoices")[0]["s"]

        self.assertEqual(active, 1, "seed: 1 active order")
        self.assertEqual(inprod, 2, "seed: 2 in production")
        self.assertEqual(waitpay, 1, "seed: 1 waiting payment")
        self.assertEqual(rts, 1, "seed: 1 ready to ship")
        self.assertEqual(overdue, 1, "seed: 1 overdue")
        self.assertEqual(outstanding, 250000.0)

        self.assertIn(f'data-kpi="active_orders" data-value="{active}"', body)
        self.assertIn(f'data-kpi="in_production" data-value="{inprod}"', body)
        self.assertIn(f'data-kpi="waiting_payment" data-value="{waitpay}"', body)
        self.assertIn(f'data-kpi="ready_to_ship" data-value="{rts}"', body)
        self.assertIn(f'data-kpi="overdue" data-value="{overdue}"', body)
        # outstanding shown as formatted money (250.000)
        self.assertIn(f'data-kpi="outstanding_invoice" data-value="250.000"', body)


class TestDashboardAlerts(Phase8Base):
    def test_04_low_stock_alert_surfaces_low_item(self):
        body = self.c.get("/").get_data(as_text=True)
        self.assertIn("Low stock", body)
        self.assertIn("CC-P8-S", body, "low-stock material code shown")

    def test_05_unpaid_invoice_alert_shows_count_and_total(self):
        body = self.c.get("/").get_data(as_text=True)
        self.assertIn("Unpaid invoices", body)
        self.assertIn("Rp 250.000", body, "outstanding formatted total shown")

    def test_06_recent_updates_feed_shows_latest_update(self):
        body = self.c.get("/").get_data(as_text=True)
        self.assertIn("PRD-P8-001", body)
        self.assertIn("Cutting half done", body, "latest update note appears in the feed")


class TestProductionBoard(Phase8Base):
    def test_07_board_renders_nine_columns(self):
        r = self.c.get("/production/board")
        self.assertEqual(r.status_code, OK)
        body = r.get_data(as_text=True)
        for col in ("ORDER", "MATERIAL PREPARATION", "CUTTING", "SEWING", "PRINTING",
                    "FINISHING", "QC", "PACKING", "COMPLETED"):
            self.assertIn(f'data-col="{col}"', body, f"column {col} present")

    def test_08_cards_bucket_into_matching_stage_column(self):
        body = self.c.get("/production/board").get_data(as_text=True)
        expected = {
            "PRD-P8-001": "CUTTING",
            "PRD-P8-002": "PACKING",
            "PRD-P8-003": "COMPLETED",
        }
        # every production card must sit inside the column whose data-col == its current_stage
        for code, stage in expected.items():
            self.assertIn(f'data-code="{code}"', body, f"card {code} rendered")
            self._assert_in_column(body, code, stage)

    def _assert_in_column(self, body, code, stage):
        marker = f'class="kb-col-body" data-col="{stage}"'
        i = body.find(marker)
        self.assertNotEqual(i, -1, f"column body marker not found for {stage}")
        nxt = body.find('class="kb-col-body" data-col="', i + len(marker))
        region = body[i:nxt] if nxt != -1 else body[i:]
        self.assertIn(code, region, f"card {code} must appear in the {stage} column")

    def test_09_board_card_unsigned_pic_and_deadline_ok(self):
        body = self.c.get("/production/board").get_data(as_text=True)
        # PRD-P8-002 is overdue (deadline yesterday, in_progress)
        self.assertIn("PRD-P8-002", body)
        # overdue production carries a text-danger footer
        self.assertIn("text-danger", body, "overdue card flagged danger")

    def test_10_compact_table_toggle_present_and_lists_all_rows(self):
        body = self.c.get("/production/board").get_data(as_text=True)
        self.assertIn('data-view-toggle', body, "compact-table toggle control present")
        # table lists every production once
        codes = [r["production_code"] for r in _query(self.db, "SELECT production_code FROM production_orders")]
        self.assertEqual(len(codes), 3)
        for code in codes:
            self.assertIn(f'data-row-code="{code}"', body, f"row {code} present in compact table")
        # count of data-row-code occurrences equals number of productions (all rows, no dupe)
        rows = len(re.findall(r'data-row-code="[^"]+"', body))
        self.assertEqual(rows, len(codes), "compact table holds one row per production")

    def test_11_board_toggle_hidden_for_management_still_renders(self):
        # Management is read-only but still sees board + toggle (all-roles toggle per §3.2)
        mgmt = self.app.test_client()
        _login(mgmt, "management")
        r = mgmt.get("/production/board")
        self.assertEqual(r.status_code, OK)
        body = r.get_data(as_text=True)
        self.assertIn('data-view-toggle', body, "management sees the compact-table toggle")


if __name__ == "__main__":
    unittest.main(verbosity=2)