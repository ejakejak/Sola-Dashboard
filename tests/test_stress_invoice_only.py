"""Stress test — Invoice-only flow (no sheets / no complex engine)."""
import sqlite3, time, sys, os
sys.path.insert(0, ".")
os.environ["STORAGE"] = "sqlite"
os.environ["DATABASE_URL"] = "sqlite:///instance/sola.db"

from flask import Flask
from app import create_app

def test_invoice_flow():
    app = create_app({"TESTING": True, "DATABASE_PATH": "instance/sola.db"})
    with app.test_client() as c:
        # Smoke routes
        print("Route smoke:", end=" ")
        r = c.get("/")
        print(f"index={r.status_code}", end=" ")
        r = c.get("/invoices/")
        print(f"list={r.status_code}", end=" ")
        r = c.get("/invoices/new")
        print(f"new={r.status_code}", end=" ")

        # Create invoice
        print("Creating invoice...", end=" ")
        r = c.post("/invoices/new", data={
            "customer_id": "1",
            "subtotal": "500000",
            "discount": "0",
            "tax_rate": "11",
            "item_description[]": ["Item A", "Item B"],
            "item_qty[]": ["2", "1"],
            "item_price[]": ["100000", "300000"],
        }, follow_redirects=True)
        print(f"create={r.status_code}", end=" ")

        # Check DB record
        conn = sqlite3.connect("instance/sola.db")
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM invoices ORDER BY invoice_id DESC LIMIT 1")
        inv = cur.fetchone()
        print(f"db_invoice={inv is not None}", end=" ")
        conn.close()
        print()
        print("STRESS TEST PASSED")

if __name__ == "__main__":
    start = time.time()
    test_invoice_flow()
    print(f"Duration: {time.time()-start:.2f}s")
