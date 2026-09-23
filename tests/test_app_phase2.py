#!/usr/bin/env python3
"""Phase-2 smoke tests — Flask backbone + auth + master-data CRUD + audit.

Runs against an ISOLATED temporary database (same schema.sql) so the real
instance/sola.db is never touched by tests.

    python tests/test_app_phase2.py            # or: python -m unittest tests.test_app_phase2
"""
import json
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

STATUS_OK = 200
STATUS_FORBIDDEN = 403
STATUS_REDIRECT = 302


def _make_app(db_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": db_path,
            "SECRET_KEY": "test-secret",
        }
    )
    create_schema(db_path)
    ensure_seeded(db_path)
    _seed_sample_master(db_path)
    return app


def _seed_sample_master(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO materials (material_code, material_name, category, status)"
        " VALUES ('CC-TEST', 'Test Cotton Combed', 'kaos', 'active')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO product_categories (category_name) VALUES ('T-Shirt')"
    )
    cat = cur.execute(
        "SELECT category_id FROM product_categories WHERE category_name='T-Shirt'"
    ).fetchone()[0]
    cur.execute(
        "INSERT OR IGNORE INTO products (product_code, product_name, category_id, status)"
        " VALUES ('PRD-TEST', 'Test Shirt', ?, 'active')",
        (cat,),
    )
    conn.commit()
    conn.close()


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def _login(client, username, password=DEFAULT_PASSWORD):
    return client.post(
        "/login", data={"username": username, "password": password}
    )


_CUSTOMER_PAYLOAD = {
    "customer_code": "CUST-P2-001",
    "name": "Winda Test Customer",
    "company_name": "PT Uji Sola",
    "pic_name": "Winda",
    "phone": "081234567890",
    "email": "winda@sola.test",
    "address": "Jl. Uji No.1",
    "customer_type": "retail",
    "source": "walk-in",
    "notes": "phase-2 smoke",
    "status": "active",
}


class TestPhase2(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "sola_phase2_test.db")
        self.app = _make_app(self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def test_login_required_redirects_anonymous(self):
        r = self.client.get("/master-data/")
        self.assertEqual(r.status_code, STATUS_REDIRECT)
        self.assertIn("/login", r.headers.get("Location", ""))

    def test_admin_can_create_customer(self):
        r = _login(self.client, "admin")
        self.assertEqual(r.status_code, STATUS_REDIRECT, "admin login should redirect to /")
        r = self.client.post(
            "/master-data/customers/new", data=_CUSTOMER_PAYLOAD
        )
        self.assertEqual(r.status_code, STATUS_REDIRECT)
        self.assertIn("/master-data/customers", r.headers.get("Location", ""))

        rows = _query(
            self.db_path,
            "SELECT customer_id, name FROM customers WHERE customer_code=?",
            ("CUST-P2-001",),
        )
        self.assertEqual(len(rows), 1, "customer should have been created")
        self.assertEqual(rows[0]["name"], "Winda Test Customer")

    def test_warehouse_cannot_create_customer_returns_403(self):
        r = _login(self.client, "warehouse")
        self.assertEqual(r.status_code, STATUS_REDIRECT, "warehouse login should succeed")
        r = self.client.post(
            "/master-data/customers/new", data=_CUSTOMER_PAYLOAD
        )
        self.assertEqual(
            r.status_code, STATUS_FORBIDDEN,
            "WAREHOUSE must NOT be able to create a customer (backend-enforced)",
        )
        rows = _query(
            self.db_path,
            "SELECT COUNT(*) AS n FROM customers WHERE customer_code='CUST-P2-001'",
        )
        self.assertEqual(rows[0]["n"], 0, "no customer row should be written for WAREHOUSE")

    def test_warehouse_can_view_materials_list(self):
        r = _login(self.client, "warehouse")
        self.assertEqual(r.status_code, STATUS_REDIRECT)
        r = self.client.get("/master-data/materials")
        self.assertEqual(r.status_code, STATUS_OK)
        body = r.get_data(as_text=True)
        self.assertIn("CC-TEST", body)
        self.assertIn("Test Cotton Combed", body)

    def test_master_data_list_loads_with_data(self):
        _login(self.client, "admin")
        r = self.client.get("/master-data/materials")
        self.assertEqual(r.status_code, STATUS_OK)
        self.assertIn("CC-TEST", r.get_data(as_text=True))
        r = self.client.get("/master-data/products")
        self.assertEqual(r.status_code, STATUS_OK)
        self.assertIn("PRD-TEST", r.get_data(as_text=True))

    def test_audit_log_written_on_create(self):
        _login(self.client, "admin")
        self.client.post("/master-data/customers/new", data=_CUSTOMER_PAYLOAD)
        rows = _query(
            self.db_path,
            "SELECT action, entity, entity_id, new_value FROM audit_logs"
            " WHERE action='CREATE' AND entity='customer'",
        )
        self.assertEqual(len(rows), 1, "exactly one CREATE/customer audit row expected")
        self.assertEqual(rows[0]["action"], "CREATE")
        self.assertEqual(rows[0]["entity"], "customer")
        self.assertTrue(rows[0]["entity_id"], "entity_id should be the new row id")
        payload = json.loads(rows[0]["new_value"])
        self.assertEqual(payload["customer_code"], "CUST-P2-001")

    def test_admin_can_update_material_and_audit_written(self):
        _login(self.client, "admin")
        material_id = _query(
            self.db_path, "SELECT material_id FROM materials WHERE material_code='CC-TEST'"
        )[0]["material_id"]
        r = self.client.post(
            "/master-data/materials/{}/edit".format(material_id),
            data={
                "material_code": "CC-TEST",
                "material_name": "Test Cotton Combed 24s",
                "category": "kaos",
                "specification": "updated",
                "status": "active",
            },
        )
        self.assertEqual(r.status_code, STATUS_REDIRECT)
        new_name = _query(
            self.db_path,
            "SELECT material_name FROM materials WHERE material_id=?",
            (material_id,),
        )[0]["material_name"]
        self.assertEqual(new_name, "Test Cotton Combed 24s")
        audits = _query(
            self.db_path,
            "SELECT action, old_value, new_value FROM audit_logs"
            " WHERE action='UPDATE' AND entity='material' AND entity_id=?",
            (str(material_id),),
        )
        self.assertEqual(len(audits), 1)
        self.assertIn("Combed", audits[0]["new_value"])


if __name__ == "__main__":
    unittest.main(verbosity=2)