#!/usr/bin/env python3
"""Phase 6 tests — Inventory & Stock Movements (spec §18 / §24 / §27).

Isolated temp DB (same schema.sql) — the real instance/sola.db is never touched.

Covers:
  inventory list with derived 0/0/0 rows and available = on_hand - reserved
  ADJUSTMENT adds on_hand (signed delta) + records movement + audits; guard: cannot
    push available below 0 (on_hand below reserved)
  RESERVE moves qty -> reserved; over-reserve rejected + attempt audited
  RELEASE deducts on_hand AND clears reserved; exceeding reserved rejected
  ISSUE (OUT) deducts on_hand; over-issue rejected + attempt audited
  MATERIAL USAGE against a production -> OUT movement + on_hand deduction + material_usage row
  low-stock badge shown when available <= LOW_STOCK_THRESHOLD
  additive permission matrix (ADMIN all; WAREHOUSE view+manage; PRODUCTION/QC/FINANCE/
    MANAGEMENT view-only; SALES none) + idempotent re-seed + ADMIN-all invariant
  backend-enforced, not UI-hiding: view-only roles get 403 on writes

    python tests/test_app_phase6.py
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
from db.init_schema import create_schema  # noqa: E402
from seed.seed_auth import DEFAULT_PASSWORD, ensure_seeded  # noqa: E402
from seed.seed_production import seed_workflow_templates  # noqa: E402
from seed.seed_catalog import seed_catalog  # noqa: E402

OK, FORBIDDEN, REDIRECT = 200, 403, 302


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def _login(client, username="admin"):
    return client.post("/login", data={"username": username, "password": DEFAULT_PASSWORD})


def _seed_units(db_path):
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO units (unit_id, unit_code, unit_name) VALUES (?,?,?)",
        [(1, "pcs", "Pcs"), (2, "meter", "Meter")],
    )
    conn.commit()
    conn.close()


# seed_production templates reference canonical migrated category ids (Mug=22, Topi=21)
CATEGORIES = [(21, "Topi"), (22, "Mug")]


def _seed_categories(db_path):
    conn = sqlite3.connect(db_path)
    for cid, name in CATEGORIES:
        conn.execute("INSERT OR IGNORE INTO product_categories (category_id, category_name)"
                     " VALUES (?,?)", (cid, name))
    conn.commit()
    conn.close()


def _mkapp(db_path):
    cfg = {"TESTING": True, "DATABASE_PATH": db_path, "SECRET_KEY": "test-secret"}
    app = create_app(cfg)
    create_schema(db_path)
    _seed_units(db_path)
    _seed_categories(db_path)
    ensure_seeded(db_path)
    # a real-master-shaped material (+ unit) for stock math
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO materials (material_code, material_name, unit_id, status)"
        " VALUES ('CC-24S-T', 'Cotton Combed 24s Test', 2, 'active')"
    )
    conn.commit()
    conn.close()
    seed_workflow_templates(db_path)
    seed_catalog(db_path)
    return app


def _mat(db_path):
    return _query(db_path, "SELECT material_id FROM materials WHERE material_code='CC-24S-T'")[0]["material_id"]


def _make_production(db_path):
    """Insert customer -> order -> production (fixes NOT NULL order_id/customer_id) and return pid."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO customers (customer_code, name, status)"
                " VALUES ('CUST-P6', 'P6 Customer', 'active')")
    cid = cur.execute("SELECT customer_id FROM customers WHERE customer_code='CUST-P6'").fetchone()[0]
    cur.execute("INSERT OR IGNORE INTO orders (order_number, customer_id, status)"
                " VALUES ('ORD-P6-0001', ?, 'confirmed')", (cid,))
    oid = cur.execute("SELECT order_id FROM orders WHERE order_number='ORD-P6-0001'").fetchone()[0]
    cur.execute("INSERT OR IGNORE INTO production_orders (production_code, order_id, quantity,"
                " current_stage, status, overall_progress)"
                " VALUES ('PRD-P6-0001', ?, 10, 'CUTTING', 'in_progress', 10)", (oid,))
    conn.commit()
    pid = cur.execute("SELECT production_id FROM production_orders"
                      " WHERE production_code='PRD-P6-0001'").fetchone()[0]
    conn.close()
    return pid


def _inv_of(db_path):
    rows = _query(db_path, "SELECT * FROM inventory")
    return rows[0] if rows else None


class TestInventoryMath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p6.db")
        self.app = _mkapp(self.db)
        self.c = self.app.test_client()
        _login(self.c, "admin")
        self.mat = _mat(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_01_list_shows_000_default(self):
        r = self.c.get("/inventory")
        self.assertEqual(r.status_code, OK)
        body = r.get_data(as_text=True)
        # test material row exists and renders 0/0/0 by default (no inventory row)
        self.assertIn("Cotton Combed 24s Test", body)
        self.assertIn("Low stock", body)  # available 0 <= threshold 0

    def test_02_adjust_adds_on_hand(self):
        r = self.c.post("/inventory/adjust", data={
            "material_id": str(self.mat), "delta": "100", "reason": "stock-in",
        })
        self.assertEqual(r.status_code, REDIRECT)
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 100.0)
        self.assertEqual(inv["reserved"], 0.0)
        self.assertEqual(inv["available"], 100.0)
        mv = _query(self.db, "SELECT * FROM stock_movements")[0]
        self.assertEqual(mv["movement_type"], "ADJUSTMENT")
        self.assertEqual(mv["quantity"], 100.0)
        self.assertEqual(mv["reference_type"], "adjustment")
        self.assertEqual(mv["material_id"], self.mat)
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE action='ADJUST'")), 1)

    def test_03_adjust_negative_delta(self):
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "50"})
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "-20"})
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 30.0)
        self.assertEqual(inv["available"], 30.0)

    def test_04_adjust_below_reserved_rejected(self):
        # on_hand 100, then reserve 70 (available 30)
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "100"})
        self.c.post("/inventory/reserve", data={"material_id": str(self.mat), "quantity": "70"})
        # try to adjust on_hand down by 50 -> new on_hand 50 < reserved 70 -> reject
        r = self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "-50"})
        self.assertEqual(r.status_code, REDIRECT)
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 100.0, "adjustment that would go below reserved must be rejected")
        # attempt audited
        denied = _query(self.db, "SELECT * FROM audit_logs WHERE action='ADJUST_DENIED'")
        self.assertEqual(len(denied), 1)

    def test_05_reserve_moves_to_reserved(self):
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "100"})
        self.c.post("/inventory/reserve", data={
            "material_id": str(self.mat), "quantity": "30",
            "reference_type": "order", "notes": "for confirmed order",
        })
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 100.0)
        self.assertEqual(inv["reserved"], 30.0)
        self.assertEqual(inv["available"], 70.0)
        mv = _query(self.db, "SELECT * FROM stock_movements WHERE movement_type='RESERVED'")
        self.assertEqual(len(mv), 1)
        self.assertEqual(mv[0]["quantity"], 30.0)
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE action='RESERVE'")), 1)

    def test_06_over_reserve_rejected_and_audited(self):
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "100"})
        self.c.post("/inventory/reserve", data={"material_id": str(self.mat), "quantity": "90"})  # available 10
        r = self.c.post("/inventory/reserve", data={"material_id": str(self.mat), "quantity": "20"})
        self.assertEqual(r.status_code, REDIRECT)
        inv = _inv_of(self.db)
        self.assertEqual(inv["reserved"], 90.0, "over-reserve must not change reserved")
        self.assertEqual(inv["available"], 10.0)
        denied = _query(self.db, "SELECT * FROM audit_logs WHERE action='RESERVE_DENIED'")
        self.assertEqual(len(denied), 1)
        self.assertIn("over-reserve", str(denied[0].get("new_value")))
        # no RESERVED movement recorded for the rejected one
        self.assertEqual(len(_query(self.db, "SELECT * FROM stock_movements WHERE movement_type='RESERVED'")), 1)

    def test_07_release_deducts_and_clears_reserved(self):
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "100"})
        self.c.post("/inventory/reserve", data={"material_id": str(self.mat), "quantity": "40"})
        self.c.post("/inventory/release", data={"material_id": str(self.mat), "quantity": "15"})
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 85.0, "release should deduct on_hand (fulfillment)")
        self.assertEqual(inv["reserved"], 25.0)
        self.assertEqual(inv["available"], 60.0)
        mv = _query(self.db, "SELECT * FROM stock_movements WHERE movement_type='RELEASED'")
        self.assertEqual(len(mv), 1)
        self.assertEqual(mv[0]["quantity"], 15.0)
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE action='RELEASE'")), 1)

    def test_08_release_exceeding_reserved_rejected(self):
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "100"})
        self.c.post("/inventory/reserve", data={"material_id": str(self.mat), "quantity": "10"})
        r = self.c.post("/inventory/release", data={"material_id": str(self.mat), "quantity": "50"})
        self.assertEqual(r.status_code, REDIRECT)
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 100.0)
        self.assertEqual(inv["reserved"], 10.0)
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE action='RELEASE_DENIED'")), 1)

    def test_09_issue_out_guarded(self):
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "100"})
        r = self.c.post("/inventory/issue", data={
            "material_id": str(self.mat), "quantity": "60", "reference_type": "order_item",
        })
        self.assertEqual(r.status_code, REDIRECT)
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 40.0)
        self.assertEqual(inv["available"], 40.0)
        mv = _query(self.db, "SELECT * FROM stock_movements WHERE movement_type='OUT' AND reference_type='order_item'")
        self.assertEqual(len(mv), 1)
        self.assertEqual(mv[0]["quantity"], 60.0)
        # over-issue: try to issue 100 when only 40 remain
        r2 = self.c.post("/inventory/issue", data={"material_id": str(self.mat), "quantity": "100"})
        self.assertEqual(r2.status_code, REDIRECT)
        inv2 = _inv_of(self.db)
        self.assertEqual(inv2["on_hand"], 40.0, "over-issue must not deduct")
        denied = _query(self.db, "SELECT * FROM audit_logs WHERE action='ISSUE_DENIED'")
        self.assertEqual(len(denied), 1)


class TestMaterialUsage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p6u.db")
        self.app = _mkapp(self.db)
        self.c = self.app.test_client()
        _login(self.c, "admin")
        self.mat = _mat(self.db)
        self.pid = _make_production(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_10_usage_triggers_out_and_usage_row(self):
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "100"})
        r = self.c.post("/inventory/usage", data={
            "material_id": str(self.mat), "production_id": str(self.pid), "quantity": "12",
            "notes": "cutting consumption",
        })
        self.assertEqual(r.status_code, REDIRECT)
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 88.0)
        # OUT movement referencing the production
        mv = _query(self.db, "SELECT * FROM stock_movements WHERE movement_type='OUT'")
        self.assertEqual(len(mv), 1)
        self.assertEqual(mv[0]["reference_type"], "production")
        self.assertEqual(mv[0]["reference_id"], self.pid)
        self.assertEqual(mv[0]["quantity"], 12.0)
        # material_usage row tied to production
        usage = _query(self.db, "SELECT * FROM material_usage")
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["production_id"], self.pid)
        self.assertEqual(usage[0]["material_id"], self.mat)
        self.assertEqual(usage[0]["quantity"], 12.0)
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE action='MATERIAL_USAGE'")), 1)

    def test_11_usage_guard_and_missing_production(self):
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "10"})
        # over-consume
        r = self.c.post("/inventory/usage", data={
            "material_id": str(self.mat), "production_id": str(self.pid), "quantity": "50",
        })
        self.assertEqual(r.status_code, REDIRECT)
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 10.0)
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE action='USAGE_DENIED'")), 1)
        # must reference existing production
        r2 = self.c.post("/inventory/usage", data={
            "material_id": str(self.mat), "production_id": "99999", "quantity": "1",
        })
        self.assertEqual(r2.status_code, REDIRECT)
        self.assertEqual(len(_query(self.db, "SELECT * FROM material_usage")), 0)


class TestInventoryPermissions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p6p.db")
        self.app = _mkapp(self.db)
        self.admin = self.app.test_client()
        _login(self.admin, "admin")
        self.mat = _mat(self.db)
        # some on-hand so a view-only role has something to see
        self.admin.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "50"})

    def tearDown(self):
        self._tmp.cleanup()

    def _perms_for(self, role):
        return {r["permission_code"] for r in _query(
            self.db,
            "SELECT p.permission_code FROM role_permissions rp"
            " JOIN permissions p ON p.permission_id=rp.permission_id"
            " JOIN roles r ON r.role_id=rp.role_id WHERE r.role_code=?",
            (role,))}

    def test_12_permission_matrix(self):
        admin = self._perms_for("ADMIN")
        self.assertTrue({"inventory.view", "inventory.manage"} <= admin)
        wh = self._perms_for("WAREHOUSE")
        self.assertTrue({"inventory.view", "inventory.manage"} <= wh)
        for ro in ("PRODUCTION", "QC", "FINANCE", "MANAGEMENT"):
            perms = self._perms_for(ro)
            self.assertIn("inventory.view", perms, f"{ro} view-only inventory")
            self.assertNotIn("inventory.manage", perms, f"{ro} must not manage inventory")
        sales = self._perms_for("SALES")
        self.assertNotIn("inventory.view", sales, "Sales has no Inventory nav per DESIGN_SPEC §2.2")
        self.assertNotIn("inventory.manage", sales)
        cust = self._perms_for("CUSTOMER")
        self.assertNotIn("inventory.view", cust)

    def test_13_view_roles_can_read_not_write(self):
        for username in ("warehouse", "production", "qc", "finance", "management"):
            cli = self.app.test_client()
            _login(cli, username)
            r = cli.get("/inventory")
            self.assertEqual(r.status_code, OK, f"{username} may view inventory")
            # non-warehouse, non-manager roles cannot free-form write
            if username not in ("warehouse", "production"):
                rw = cli.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "10"})
                self.assertEqual(rw.status_code, FORBIDDEN, f"{username} cannot adjust inventory")
                ri = cli.post("/inventory/issue", data={"material_id": str(self.mat), "quantity": "1"})
                self.assertEqual(ri.status_code, FORBIDDEN, f"{username} cannot issue")
                # usage needs inventory.manage OR production.manage — plain view-only roles lack both
                ru = cli.post("/inventory/usage", data={
                    "material_id": str(self.mat), "production_id": "1", "quantity": "1"})
                self.assertEqual(ru.status_code, FORBIDDEN, f"{username} cannot record usage")
            # production holds production.manage -> can view but NOT free-adjust (no inventory.manage)
            if username == "production":
                self.assertEqual(cli.post("/inventory/adjust", data={
                    "material_id": str(self.mat), "delta": "10"}).status_code, FORBIDDEN)

    def test_14_backend_enforced_sales_403(self):
        sales = self.app.test_client()
        _login(sales, "sales")
        self.assertEqual(sales.get("/inventory").status_code, FORBIDDEN,
                         "Sales has no inventory.view -> backend 403, not just hidden nav")
        self.assertEqual(sales.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "5"}).status_code,
                         FORBIDDEN)

    def test_15_warehouse_can_write(self):
        wh = self.app.test_client()
        _login(wh, "warehouse")
        r = wh.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "25"})
        self.assertEqual(r.status_code, REDIRECT)
        inv = _inv_of(self.db)
        self.assertEqual(inv["on_hand"], 75.0, "warehouse (inventory.manage) may adjust")
        # warehouse can record usage (usage route allows inventory.manage)
        r2 = wh.post("/inventory/issue", data={"material_id": str(self.mat), "quantity": "5"})
        self.assertEqual(r2.status_code, REDIRECT)
        self.assertEqual(_inv_of(self.db)["on_hand"], 70.0)

    def test_16_production_role_can_record_usage(self):
        prod = self.app.test_client()
        _login(prod, "production")  # has production.manage -> usage allowed, but NOT adjust
        # cannot free-form adjust (no inventory.manage)
        r = prod.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "10"})
        self.assertEqual(r.status_code, FORBIDDEN)
        # but can record usage because usage route gates on inventory.manage OR production.manage
        pid = _make_production(self.db)
        r2 = prod.post("/inventory/usage", data={
            "material_id": str(self.mat), "production_id": str(pid), "quantity": "5"})
        self.assertEqual(r2.status_code, REDIRECT)
        self.assertEqual(_inv_of(self.db)["on_hand"], 45.0)

    def test_17_idempotent_reseed_admin_invariant(self):
        ensure_seeded(self.db)
        ensure_seeded(self.db)
        n_perms = len(_query(self.db, "SELECT * FROM permissions"))
        admin_role = _query(self.db, "SELECT role_id FROM roles WHERE role_code='ADMIN'")[0]["role_id"]
        n = _query(self.db, "SELECT COUNT(*) n FROM role_permissions WHERE role_id=?", (admin_role,))[0]["n"]
        self.assertEqual(n, n_perms, "ADMIN granted every permission exactly once after re-seed")
        for p in ("inventory.view", "inventory.manage"):
            self.assertEqual(len(_query(self.db, "SELECT * FROM permissions WHERE permission_code=?", (p,))), 1)


class TestLowStockAndViews(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p6l.db")
        self.app = _mkapp(self.db)
        self.c = self.app.test_client()
        _login(self.c, "admin")
        self.mat = _mat(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_18_low_stock_badge_on_list_and_filter(self):
        # material starts 0/0/0 -> available 0 <= threshold 0 -> Low stock
        body = self.c.get("/inventory").get_data(as_text=True)
        self.assertIn("Low stock", body)
        # low filter
        low = self.c.get("/inventory?low=1").get_data(as_text=True)
        self.assertIn("Cotton Combed 24s Test", low)
        # after stocking up, the badge clears and low filter is empty
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "50"})
        low2 = self.c.get("/inventory?low=1").get_data(as_text=True)
        self.assertNotIn("Cotton Combed 24s Test", low2, "stocked material not low anymore")
        allb = self.c.get("/inventory").get_data(as_text=True)
        self.assertIn("OK", allb)

    def test_19_movements_and_usage_views(self):
        self.c.post("/inventory/adjust", data={"material_id": str(self.mat), "delta": "30"})
        self.c.post("/inventory/reserve", data={"material_id": str(self.mat), "quantity": "10"})
        mv = self.c.get("/inventory/movements").get_data(as_text=True)
        self.assertIn("ADJUSTMENT", mv)
        self.assertIn("RESERVED", mv)
        mv_type = self.c.get("/inventory/movements?type=RESERVED").get_data(as_text=True)
        self.assertIn("RESERVED", mv_type)
        self.assertNotIn("Manual adjust", mv_type, "filtered movements must not show the ADJUSTMENT row")
        self.assertIn("Reserve for order", mv_type)
        usage = self.c.get("/inventory/usage-log").get_data(as_text=True)
        self.assertIn("No material usage recorded", usage)


if __name__ == "__main__":
    unittest.main(verbosity=2)