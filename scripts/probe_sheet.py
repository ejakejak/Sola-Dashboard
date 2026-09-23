#!/usr/bin/env python3
"""Read-only probe: can the SOLA service account access the live master sheet?"""
import sys
SHEET_ID = "1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA"
KEY = r"D:/Sola/instance/sola-509413-service-account.json"

try:
    import gspread
    gc = gspread.service_account(filename=KEY)
    sh = gc.open_by_key(SHEET_ID)
    print("OPEN_OK sheet:", sh.title, "| url:", sh.url)
    print("tabs:", sh.worksheets())
    ws = sh.sheet1
    print("sheet1 name:", ws.title, "| rows:", ws.row_count, "| cols:", ws.col_count)
    # print first tab's headers
    from pprint import pprint
    pprint(ws.get_all_values(max_rows=3))
except Exception as e:
    print("PROBE_FAIL:", type(e).__name__, str(e))
    sys.exit(1)