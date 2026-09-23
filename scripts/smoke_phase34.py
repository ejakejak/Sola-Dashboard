#!/usr/bin/env python3
"""Phase 3-4 LIVE smoke — runs the full commercial loop against the REAL instance/sola.db
via the Flask test client (real routes, real auth, real data). Also writes docs/SAMPLE_INVOICE.pdf.

Records are created with an obvious 'LIVE P34 SMOKE' marker (customers/notes) and can be
removed by scripts/smoke_phase34_cleanup.py. Run after Phase 2 seed (admin/sola123).
"""
import io
import os
import sqlite3
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app  # noqa: E402
from pypdf import PdfReader  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "instance", "sola.db")
SAMPLE_PDF = os.path.join(BASE, "docs", "SAMPLE_INVOICE.pdf")

app = create_app({"TESTING": True, "DATABASE_PATH": DB})
client = app.test_client()


def q(sql, params=()):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def login():
    r = client.post("/login", data={"username": "admin", "password": "sola123"})
    assert r.status_code in (200, 302), f"login failed {r.status_code}"


def pick_customer():
    # Prefer the real "Live Smoke Customer" if it exists, else create one.
    rows = q("SELECT customer_id, name FROM customers WHERE customer_code='CUST-LIVE-01'")
    if rows:
        return rows[0]["customer_id"]
    client.post("/master-data/customers/new", data={
        "customer_code": "CUST-P34LIVE", "name": "Live P34 Smoke Customer",
        "company_name": "PT Smoke P34", "pic_name": "Eva", "phone": "0812",
        "email": "smoke_p34@sola.id", "address": "Jl. Live No.34",
        "customer_type": "retail", "source": "walk-in", "notes": "LIVE P34 SMOKE",
        "status": "active",
    })
    return q("SELECT customer_id FROM customers WHERE customer_code='CUST-P34LIVE'")[0]["customer_id"]


def pick_material():
    # CC-30S Cotton Combed 30s (material_id 33) catalog selling 55.000
    rows = q("SELECT material_id, material_name FROM materials WHERE material_code='CC-30S'")
    if rows:
        return rows[0]
    raise RuntimeError("CC-30S not present in instance/sola.db")


def main():
    login()
    cust_id = pick_customer()
    mat = pick_material()
    print(f"[smoke] customer={cust_id} material={mat['material_id']} {mat['material_name']}")

    # ---- 1) create quotation (draft) ----
    r = client.post("/quotations/new", data={
        "customer_id": str(cust_id), "valid_until": "2026-11-30", "discount": "0", "tax": "0",
        "item_product[]": "", "item_material[]": str(mat["material_id"]), "item_decoration[]": "",
        "item_qty[]": "12", "item_unit[]": "", "item_price[]": "55000", "notes": "LIVE P34 SMOKE quote",
    })
    assert r.status_code == 302, f"quote create {r.status_code}"
    quote = q("SELECT * FROM quotations ORDER BY quotation_id DESC LIMIT 1")[0]
    assert quote["status"] == "draft" and quote["total"] == 12 * 55000.0
    print("[smoke] quotation", quote["quotation_number"], "total", quote["total"], "status", quote["status"])

    # ---- 2) approved -> convert one-shot ----
    r = client.post(f"/quotations/{quote['quotation_id']}/status", data={"status": "approved"})
    assert r.status_code == 302
    r = client.post(f"/quotations/{quote['quotation_id']}/convert",
                    data={"priority": "high", "deadline": "2026-12-01"})
    assert r.status_code == 302
    order = q("SELECT * FROM orders ORDER BY order_id DESC LIMIT 1")[0]
    assert order["quotation_id"] == quote["quotation_id"]
    print("[smoke] order", order["order_number"], "grand", order["grand_total"], "prio", order["priority"])
    # locking: second convert must not duplicate
    client.post(f"/quotations/{quote['quotation_id']}/convert", data={"priority": "normal"})
    assert len(q("SELECT * FROM orders WHERE quotation_id=?", (quote["quotation_id"],))) == 1
    assert q("SELECT status FROM quotations WHERE quotation_id=?", (quote["quotation_id"],))[0]["status"] == "converted"
    print("[smoke] quotation locked -> converted, order not duplicated")

    # ---- 3) invoice from order ----
    r = client.post(f"/invoices/from-order/{order['order_id']}")
    assert r.status_code == 302, f"invoice create {r.status_code}"
    inv = q("SELECT * FROM invoices ORDER BY invoice_id DESC LIMIT 1")[0]
    assert inv["status"] == "draft" and inv["outstanding"] == inv["grand_total"]
    print("[smoke] invoice", inv["invoice_number"], "grand", inv["grand_total"], "outstanding", inv["outstanding"])
    # no dupe
    client.post(f"/invoices/from-order/{order['order_id']}")
    assert len(q("SELECT * FROM invoices WHERE order_id=?", (order["order_id"],))) == 1
    print("[smoke] one invoice per order (no manual dupe)")

    # ---- 4) issue + partial payment ----
    r = client.post(f"/invoices/{inv['invoice_id']}/status", data={"status": "issued"})
    assert r.status_code == 302
    half = round(inv["grand_total"] / 2, 2)
    client.post(f"/invoices/{inv['invoice_id']}/payment", data={
        "amount": str(half), "method": "transfer", "reference": "P34-SMOKE-TRX1"})
    inv1 = q("SELECT * FROM invoices WHERE invoice_id=?", (inv["invoice_id"],))[0]
    assert abs(inv1["amount_paid"] - half) < 0.01
    assert abs(inv1["outstanding"] - (inv["grand_total"] - half)) < 0.01
    assert inv1["status"] == "partially_paid"
    print(f"[smoke] partial pay {half} -> outstanding {inv1['outstanding']} status {inv1['status']}")

    # ---- 5) pay rest -> paid ----
    rest = round(inv1["outstanding"], 2)
    client.post(f"/invoices/{inv['invoice_id']}/payment", data={
        "amount": str(rest), "method": "qris", "reference": "P34-SMOKE-QR2"})
    inv2 = q("SELECT * FROM invoices WHERE invoice_id=?", (inv["invoice_id"],))[0]
    assert inv2["status"] == "paid" and inv2["outstanding"] == 0.0
    print("[smoke] fully paid -> status", inv2["status"], "outstanding", inv2["outstanding"])

    # ---- 6) PDF render (via route) + write SAMPLE ----
    r = client.get(f"/invoices/{inv['invoice_id']}/pdf")
    assert r.status_code == 200 and r.data[:4] == b"%PDF"
    payload = r.data
    with open(SAMPLE_PDF, "wb") as fh:
        fh.write(payload)
    reader = PdfReader(io.BytesIO(payload))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    assert len(reader.pages) == 1
    for needle in ("Sola Konveksi Yogyakarta", "BCA 4452337111", "INVOICE", "Grand Total", "Outstanding"):
        assert needle in text, f"{needle} not in PDF text"
    for banned in ("HPP", "margin", "cost_components", "Komisi"):
        assert banned not in text, f"{banned} leaked into customer PDF"
    print(f"[smoke] PDF rendered OK -> {SAMPLE_PDF} ({len(payload)} bytes, 1 page)")
    print("[smoke] byte-render verified: PDF magic, 1 page, company block + payment note + no HPP leak")

    print("\n=== LIVE PHASE 34 SMOKE PASSED ===")
    print(f"quotation={quote['quotation_number']} order={order['order_number']} invoice={inv['invoice_number']}")
    print(f"SAMPLE_INVOICE.pdf -> {SAMPLE_PDF}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("SMOKE FAILED:", repr(e))
        traceback.print_exc()
        raise SystemExit(1)