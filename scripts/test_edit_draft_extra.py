"""Verify hidden Edit Draft on non-draft, GET prefill fields, audit log write."""
import os, sys
os.environ["STORAGE"] = "sheets"
os.environ["SPREADSHEET_ID"] = "1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"D:/Sola/instance/sola-509413-service-account.json"
from app import create_app
app = create_app()

def check(label, cond):
    print(("  PASS  " if cond else "  FAIL  ") + label)

with app.test_client() as c:
    c.post("/login", data={"username": "admin", "password": "sola123"})
    # 1) converted quote (3/1) should NOT show Edit Draft
    b = c.get("/quotations/1").get_data(as_text=True)
    check("Edit Draft HIDDEN on converted QUO-2026-0001", "Edit Draft" not in b)
    # 2) cancelled quote (2) should NOT show
    b = c.get("/quotations/2").get_data(as_text=True)
    check("Edit Draft HIDDEN on cancelled QUO-2026-0002", "Edit Draft" not in b)
    # 3) draft quote edit GET prefill customer/date headings
    b = c.get("/quotations/3/edit").get_data(as_text=True)
    check("edit form prefill customer selected", 'name="customer_id"' in b and 'selected' in b)
    check("edit form shows quotation_date field", 'name="quotation_date"' in b)
    check("edit form shows valid_until field", 'name="valid_until"' in b)
    # 4) audit log entry recorded for the UPDATE on quotation 3
    import gspread
    gc = gspread.service_account(filename=r"D:/Sola/instance/sola-509413-service-account.json")
    sh = gc.open_by_key("1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA")
    ws = sh.worksheet("audit_logs")
    rows = ws.get_all_values()
    # find last UPDATE quotation entries
    updates = [r for r in rows if len(r) > 4 and r[3] == "UPDATE" and r[4] == "quotation" and str(r[5]) == "3"]
    check("audit_logs has UPDATE quotation entity_id=3", len(updates) >= 1)
    if updates:
        print("     last audit rows:", updates[-1][:7])