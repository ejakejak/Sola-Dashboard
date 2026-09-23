#!/usr/bin/env python3
"""Phase 3-4 smoke tests — Quotation → Order → Invoice → Payment → Invoice PDF.

Runs against an ISOLATED temporary database (same schema.sql) so the real
instance/sola.db is never touched. Covers the entire commercial loop:

  quotation create (draft) -> approved -> one-shot convert (order)
  -> generate invoice from order (no dupe) -> issue -> payment
  -> outstanding math -> paid at <= 0 -> PDF byte-render (magic + pages)
  -> no HPP/margin leakage -> audits on every write.

    python tests/test_app_phase34.py     # or: python -m unittest tests.test_app_phase34
"""
import io
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
from app.commercial import CATALOG_PRICE_BY_MATERIAL  # noqa: E402
from app.invoice_pdf import render_invoice_pdf  # noqa: E402
from db.init_schema import create_schema  # noqa: E402
from seed.seed_auth import DEFAULT_PASSWORD, ensure_seeded  # noqa: E402

OK, FORBIDDEN, REDIRECT = 200, 403, 302


def _mkapp(db_path, extra=None):
    cfg = {"TESTING": True, "DATABASE_PATH": db_path, "SECRET_KEY": "test-secret"}
    if extra:
        cfg.update(extra)
    app = create_app(cfg)
    create_schema(db_path)
    ensure_seeded(db_path)
    _seed_master(db_path)
    return app


def _seed_master(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO customers (customer_code, name, company_name, address, customer_type, status)"
                " VALUES ('CUST-P34', 'Winda User', 'PT Uji Sola', 'Jl. Test No.9', 'retail', 'active')")
    cur.execute("INSERT OR IGNORE INTO materials (material_code, material_name, status)"
                " VALUES ('CC-34S', 'Cotton Combed 34s Test', 'active')")
    conn.commit()
    conn.close()


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def _login(client, username="admin"):
    return client.post("/login", data={"username": username, "password": DEFAULT_PASSWORD})


class TestPhase34(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "sola_phase34.db")
        self.app = _mkapp(self.db_path)
        self.client = self.app.test_client()
        _login(self.client, "admin")
        self.cust_id = _query(self.db_path, "SELECT customer_id FROM customers WHERE customer_code='CUST-P34'")[0]["customer_id"]
        self.mat_id = _query(self.db_path, "SELECT material_id FROM materials WHERE material_code='CC-34S'")[0]["material_id"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_01_navigation_permissions(self):
        # anonymous (fresh, unlogged client) is redirected to login
        anon = self.app.test_client()
        r = anon.get("/quotations/", follow_redirects=False)
        self.assertEqual(r.status_code, REDIRECT, "anonymous must be redirected")

    def test_02_create_quotation_audit_numbering(self):
        price = CATALOG_PRICE_BY_MATERIAL.get(self.mat_id, 55000)
        r = self.client.post("/quotations/new", data={
            "customer_id": str(self.cust_id),
            "discount": "0", "tax": "0",
            "item_product[]": "",
            "item_material[]": str(self.mat_id),
            "item_qty[]": "10",
            "item_unit[]": "",
            "item_price[]": str(price),
        })
        self.assertEqual(r.status_code, REDIRECT, "quotation create should redirect")
        rows = _query(self.db_path, "SELECT * FROM quotations")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["quotation_number"].startswith("QUO-2026-"))
        self.assertEqual(rows[0]["status"], "draft")
        self.assertAlmostEqual(rows[0]["total"], 10 * price, places=2, msg="quotation total = qty * price")
        qt = _query(self.db_path, "SELECT * FROM quotation_items")
        self.assertEqual(len(qt), 1)
        self.assertAlmostEqual(float(qt[0]["subtotal"]), 10 * price, places=2)
        audits = _query(self.db_path, "SELECT * FROM audit_logs WHERE action='CREATE' AND entity='quotation'")
        self.assertEqual(len(audits), 1, "quotation CREATE must be audited")
        self.assertEqual(audits[0]["entity_id"], str(rows[0]["quotation_id"]))
        return rows[0]["quotation_id"]

    def test_03_bad_conversion_requires_approved(self):
        qid = self.test_02_create_quotation_audit_numbering()
        # draft -> convert must be rejected
        r = self.client.post(f"/quotations/{qid}/convert", data={"priority": "normal"})
        self.assertEqual(r.status_code, REDIRECT)
        order_count = _query(self.db_path, "SELECT COUNT(*) n FROM orders")[0]["n"]
        self.assertEqual(order_count, 0, "only APPROVED quotation may convert")
        # set approved
        self.client.post(f"/quotations/{qid}/status", data={"status": "approved"})
        st = _query(self.db_path, "SELECT status FROM quotations WHERE quotation_id=?", (qid,))[0]["status"]
        self.assertEqual(st, "approved")

    def test_04_convert_once_locks_quotation(self):
        qid = self.test_02_create_quotation_audit_numbering()
        self.client.post(f"/quotations/{qid}/status", data={"status": "approved"})
        r = self.client.post(f"/quotations/{qid}/convert", data={"priority": "high", "deadline": "2026-12-01"})
        self.assertEqual(r.status_code, REDIRECT)
        orders = _query(self.db_path, "SELECT * FROM orders")
        self.assertEqual(len(orders), 1)
        o = orders[0]
        self.assertTrue(o["order_number"].startswith("ORD-2026-"))
        self.assertEqual(o["status"], "confirmed")
        self.assertEqual(o["priority"], "high")
        self.assertEqual(o["quotation_id"], qid)
        self.assertAlmostEqual(float(o["grand_total"]), float(_query(
            self.db_path, "SELECT total FROM quotations WHERE quotation_id=?", (qid,))[0]["total"]))
        # one-shot: a second convert attempt must be blocked
        self.client.post(f"/quotations/{qid}/convert", data={"priority": "normal"})
        self.assertEqual(len(_query(self.db_path, "SELECT * FROM orders")), 1, "order must NOT duplicate")
        q_st = _query(self.db_path, "SELECT status FROM quotations WHERE quotation_id=?", (qid,))[0]["status"]
        self.assertEqual(q_st, "converted", "quotation must be locked as converted")
        # order audit
        audits = _query(self.db_path, "SELECT * FROM audit_logs WHERE entity='order' AND action='CREATE'")
        self.assertEqual(len(audits), 1)
        return o["order_id"], qid

    def test_05_invoice_from_order(self):
        oid, qid = self.test_04_convert_once_locks_quotation()
        r = self.client.post(f"/invoices/from-order/{oid}")
        self.assertEqual(r.status_code, REDIRECT)
        invs = _query(self.db_path, "SELECT * FROM invoices")
        self.assertEqual(len(invs), 1)
        i = invs[0]
        self.assertTrue(i["invoice_number"].startswith("INV-2026-"))
        self.assertEqual(i["order_id"], oid)
        self.assertAlmostEqual(float(i["grand_total"]), float(
            _query(self.db_path, "SELECT grand_total FROM orders WHERE order_id=?", (oid,))[0]["grand_total"]))
        self.assertAlmostEqual(float(i["amount_paid"]), 0.0)
        self.assertAlmostEqual(float(i["outstanding"]), float(i["grand_total"]), msg="outstanding=grand_total before payment")
        self.assertEqual(i["status"], "draft")
        # no manual dupe: a second generate from the same order must be blocked
        self.client.post(f"/invoices/from-order/{oid}")
        self.assertEqual(len(_query(self.db_path, "SELECT * FROM invoices")), 1, "one invoice per order")
        inv_items = _query(self.db_path, "SELECT * FROM invoice_items WHERE invoice_id=?", (i["invoice_id"],))
        self.assertEqual(len(inv_items), 1, "invoice items copied from order items")
        self.assertTrue(inv_items[0]["description"], "line-item description present")
        audits = _query(self.db_path, "SELECT * FROM audit_logs WHERE entity='invoice' AND action='CREATE'")
        self.assertEqual(len(audits), 1)
        return i["invoice_id"], i["grand_total"]

    def test_06_payment_outstanding_and_paid(self):
        iid, grand = self.test_05_invoice_from_order()
        # must issue before payment
        self.client.post(f"/invoices/{iid}/status", data={"status": "issued"})
        # partial payment
        self.client.post(f"/invoices/{iid}/payment", data={
            "amount": str(grand / 2), "method": "transfer", "reference": "TRX-001",
        })
        i1 = _query(self.db_path, "SELECT * FROM invoices WHERE invoice_id=?", (iid,))[0]
        self.assertAlmostEqual(float(i1["amount_paid"]), grand / 2, places=2)
        self.assertAlmostEqual(float(i1["outstanding"]), grand / 2, places=2, msg="outstanding = grand - paid")
        self.assertEqual(i1["status"], "partially_paid")
        # pay rest -> fully paid
        self.client.post(f"/invoices/{iid}/payment", data={
            "amount": str(grand / 2), "method": "qris", "reference": "QR-002",
        })
        i2 = _query(self.db_path, "SELECT * FROM invoices WHERE invoice_id=?", (iid,))[0]
        self.assertAlmostEqual(float(i2["amount_paid"]), grand, places=2)
        self.assertAlmostEqual(float(i2["outstanding"]), 0.0, places=2)
        self.assertEqual(i2["status"], "paid", "status paid when outstanding <= 0")
        # payments audited
        pays = _query(self.db_path, "SELECT * FROM audit_logs WHERE entity='payment' AND action='CREATE'")
        self.assertEqual(len(pays), 2, "every payment audited")
        # DB payment rows
        db_pays = _query(self.db_path, "SELECT * FROM payments WHERE invoice_id=?", (iid,))
        self.assertEqual(len(db_pays), 2)
        return iid

    def test_07_pdf_renders_no_network_hpp(self):
        import io as _io
        from pypdf import PdfReader

        iid, grand = self.test_05_invoice_from_order()
        self.client.post(f"/invoices/{iid}/status", data={"status": "issued"})
        # byte-render via the PDF route (like the app)
        r = self.client.get(f"/invoices/{iid}/pdf")
        self.assertEqual(r.status_code, OK)
        payload = r.data
        self.assertTrue(payload[:4] == b"%PDF", "PDF magic bytes present: " + repr(payload[:8]))
        reader = PdfReader(_io.BytesIO(payload))
        self.assertEqual(len(reader.pages), 1, "invoice should render on one A4 page")
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        self.assertIn("Sola Konveksi Yogyakarta", text, "company block name present")
        self.assertIn("BCA 4452337111", text, "payment BSAC note present")
        self.assertIn("INVOICE", text)
        self.assertIn("Grand Total", text)
        self.assertIn("Outstanding", text)
        # NO internal/cost leakage: HPP / margin / unit cost never appear
        for banned in ("HPP", "margin", "cost_components", "Komisi"):
            self.assertNotIn(banned, text, f"'{banned}' must not appear on customer PDF")
        return iid

    def test_08_direct_order_and_finance_role(self):
        # finance role can view invoices but NOT convert quotations
        fin = self.app.test_client()
        _login(fin, "finance")
        r = fin.get("/invoices/")
        self.assertEqual(r.status_code, OK, "FINANCE can view invoices")
        r = fin.get("/quotations/")
        self.assertEqual(r.status_code, OK, "FINANCE can view quotations (read)")
        r = fin.post("/quotations/99/convert", data={"priority": "normal"})
        self.assertEqual(r.status_code, FORBIDDEN, "FINANCE cannot convert quotations (backend-enforced)")

    def test_09_management_read_only(self):
        mgmt = self.app.test_client()
        _login(mgmt, "management")
        # management has no quotation.create permission
        r = mgmt.post("/quotations/new", data={
            "customer_id": str(self.cust_id), "item_material[]": str(self.mat_id),
            "item_qty[]": "1", "item_price[]": "55000",
        })
        self.assertEqual(r.status_code, FORBIDDEN, "MANAGEMENT cannot create quotations")


if __name__ == "__main__":
    unittest.main(verbosity=2)