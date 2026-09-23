"""Live-test Quotation EDIT DRAFT against the authoritative Google Sheet.

END-TO-END against the REAL store (MASTER DATA SOLA 1.0). Tests QUO-2026-0003.
Run:  python <this file>
"""
import os
import sys
os.environ["STORAGE"] = "sheets"
os.environ["SPREADSHEET_ID"] = "1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"D:/Sola/instance/sola-509413-service-account.json"

from app import create_app
from app.sheetdb import SheetRelational
from app.commercial import _TABLES

SHEET_ID = os.environ["SPREADSHEET_ID"]
KEY = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

app = create_app()

def rel():
    r = SheetRelational(app.extensions["storage"])
    for n, cols in _TABLES.items():
        r.define(n, cols, cols[0])
    return r

def qcheck(label, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + (" | " + extra if extra else ""))
    return cond

def main():
    ok = True
    T = []
    with app.test_client() as c:
        # login
        r = c.post("/login", data={"username": "admin", "password": "sola123"})
        print("login POST", r.status_code, r.headers.get("Location"))
        # fetch detail to capture pre-state
        r = c.get("/quotations/3")
        body = r.get_data(as_text=True)
        print("detail GET /quotations/3 ->", r.status_code)
        is_draft = 'st-draft' in body or '>draft<' in body
        T.append(("detail renders draft", is_draft))
        has_edit_btn = 'class="btn btn-primary" href="/quotations/3/edit"' in body.replace("'", '"') or "Edit Draft" in body
        T.append(("Edit Draft button shown", has_edit_btn))

        # GET edit form
        r = c.get("/quotations/3/edit")
        body = r.get_data(as_text=True)
        T.append(("edit GET 200", r.status_code == 200))
        import re
        # first item qty field value 30
        qtys = re.findall(r'name="item_qty\[\]"[^>]*value="(\d+)"', body) or \
               re.findall(r'name="item_qty\[\]"[^>]*>', body)
        prices = re.findall(r'name="item_price\[\]"[^>]*value="([\d.]+)"', body)
        print("  edit GET prefilled qtys:", qtys, "prices:", prices)

        # POST: change first item qty 30 -> 35. Mirror create-form payload.
        data = {
            "customer_id": "4",
            "quotation_date": "2026-09-23",
            "valid_until": "2026-09-30",
            "discount": "0",
            "tax": "0",
            "notes": "",
            # item 1 = product 2 (first row): qty 35, material 65, unit 1, price 85000
            "item_product[]": ["2", ""],
            "item_material[]": ["65", ""],
            "item_decoration[]": ["", "5"],
            "item_qty[]": ["35", "30"],
            "item_unit[]": ["1", "1"],
            "item_price[]": ["85000", "5000"],
        }
        r = c.post("/quotations/3/edit", data=data)
        print("edit POST ->", r.status_code, r.headers.get("Location"))
        T.append(("edit POST redirects to detail", r.status_code == 302 and "/quotations/3" in (r.headers.get("Location") or "")))

        # Verify on detail
        r = c.get("/quotations/3")
        body = r.get_data(as_text=True)
        # number unchanged
        num_ok = "QUO-2026-0003" in body
        T.append(("number unchanged QUO-2026-0003", num_ok))
        still_draft = '>draft<' in body or 'st-draft' in body
        T.append(("status stays draft", still_draft))
        # total: 35*85000=2,975,000 + 30*5000=150,000 = 3,125,000
        total_ok = "Rp 3.125.000" in body
        T.append(("total recomputed 3.125.000 (35x85000 + 30x5000)", total_ok))
        # first item subtotal
        sub_ok = "Rp 2.975.000" in body
        T.append(("first item subtotal 2.975.000 (35*85000)", sub_ok))

    for label, cond in T:
        qcheck(label, cond)
        ok = ok and cond
    print("\nRESULT:", "ALL PASS" if ok else "SOME FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())