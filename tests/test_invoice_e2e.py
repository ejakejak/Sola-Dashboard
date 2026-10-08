
import sqlite3, sys, os
os.environ["STORAGE"] = "sqlite"
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app

def test_e2e():
    app = create_app({"TESTING": True, "DATABASE_PATH": "instance/sola.db"})
    with app.test_client() as c:
        # Login with demo user (seeded by seed_auth)
        r = c.post("/login", data={"username": "demo", "password": "demo123"}, follow_redirects=True)
        print("Login:", r.status_code)
        # Create invoice
        r = c.post("/invoices/new", data={
            "customer_id": "1", "subtotal": "500000", "discount": "0",
            "tax_rate": "11",
            "item_description[]": ["Test item"],
            "item_qty[]": ["1"], "item_price[]": ["500000"],
        }, follow_redirects=True)
        print("Create invoice:", r.status_code)
        # Check DB
        conn = sqlite3.connect("instance/sola.db")
        cur = conn.execute("SELECT invoice_number FROM invoices ORDER BY invoice_id DESC LIMIT 1")
        inv = cur.fetchone()
        print("DB invoice:", inv[0] if inv else "NONE")
        conn.close()
        print("E2E PASSED" if inv else "E2E FAILED")

if __name__ == "__main__":
    test_e2e()
