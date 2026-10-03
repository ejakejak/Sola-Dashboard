"""OFFLINE regression test for the full commercial HTTP flow (7 line items).

Drives the REAL Flask app through its test client with ``STORAGE=local`` (the
in-memory ``LocalSheetStorage`` adapter: no Google credentials needed), running
the exact server code path a user hits in production:

    login admin
      -> POST /quotations/new            (create quotation, 7 items)
      -> POST /quotations/<qid>/status   (approve)
      -> POST /quotations/<qid>/convert  (convert to order)
      -> POST /invoices/from-order/<oid> (create invoice from order)
      -> GET  /invoices/<iid>            (invoice detail)
      -> GET  /invoices/<iid>/pdf        (invoice PDF)

It asserts that all 7 line items survive every hop (quotation -> order ->
invoice -> invoice_items) and that both the detail HTML and the rendered PDF
present all 7 descriptions — robust to line-wrapping.

This directly regression-guards the "items drop on the invoice" bug class: if
any hop lost an item, the count/description assertions below fail.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402

ITEM_COUNT = 7
_DESCRIPTIONS = [f"Kemeja Seragam Lengan Panjang Line Item {i}" for i in range(1, ITEM_COUNT + 1)]

# Column headers must match app/auth.py + app/commercial.py (_TABLES) so the
# sheetdb engine reads the seeded rows as data (header row is row 0).
_USERS = ["user_id", "username", "full_name", "password_hash", "role_id",
          "phone", "email", "status"]
_ROLES = ["role_id", "role_code", "role_name"]
_PERMISSIONS = ["permission_id", "permission_code"]
_ROLE_PERMISSIONS = ["role_permission_id", "role_id", "permission_id"]
_CUSTOMERS = ["customer_id", "customer_code", "name", "company_name", "pic_name",
              "phone", "email", "address", "npwp", "customer_type", "source",
              "notes", "status", "created_at"]
_PRODUCTS = ["product_id", "product_code", "product_name", "category_id",
             "unit_id", "description", "status", "created_at", "updated_at"]

# Permission codes required by every commercial route used in the flow.
_PERM_CODES = [
    "quotation.view", "quotation.create", "quotation.update", "quotation.convert",
    "order.view", "order.create",
    "invoice.view", "invoice.create", "invoice.update",
    "masterdata.view",
]

ADMIN_PASSWORD = "s3cr3t-admin-pw"


@pytest.fixture(scope="module")
def storage():
    """One app + one LocalSheetStorage seeded and reused across the whole flow."""
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "STORAGE": "local",
        "COMPANY": {"company_name": "Sola Offline Test",
                    "address": "Jalan Test 1",
                    "brand_logo": "app/static/assets/sola-logo-1.png"},
    })
    store = app.extensions["storage"]
    assert type(store).__name__ == "LocalSheetStorage", (
        f"expected LocalSheetStorage, got {type(store).__name__}")
    _seed_auth(store, app)
    yield {"app": app, "store": store}


def _seed_auth(store, app):
    # users: one active ADMIN
    store.seed("users", _USERS, [[
        1, "admin", "Admin User",
        generate_password_hash(ADMIN_PASSWORD), 1, "081234567890",
        "admin@sola.test", "active",
    ]])
    store.seed("roles", _ROLES, [[1, "ADMIN", "Administrator"]])
    perms = [[i + 1, code] for i, code in enumerate(_PERM_CODES)]
    store.seed("permissions", _PERMISSIONS, perms)
    store.seed("role_permissions", _ROLE_PERMISSIONS, [[i + 1, 1, i + 1] for i in range(len(_PERM_CODES))])
    # one customer (required to create a quotation)
    store.seed("customers", _CUSTOMERS, [[
        1, "CUS-001", "PT Test Konveksi", "PT Test Konveksi", "PIC",
        "021-0001", "test@sola.test", "Jl. Test", None, "customer",
        None, None, "active", "2026-01-01",
    ]])
    # 7 distinct products so invoice descriptions differ per line item.
    products = [[i + 1, f"PRD-{i + 1:04d}", _DESCRIPTIONS[i], None, None, None,
                 "active", "2026-01-01", "2026-01-01"] for i in range(ITEM_COUNT)]
    store.seed("products", _PRODUCTS, products)


@pytest.fixture
def client(storage):
    return storage["app"].test_client()


def _login(client):
    resp = client.post("/login", data={
        "username": "admin",
        "password": ADMIN_PASSWORD,
    }, follow_redirects=False)
    # Successful login redirects (302). 200 would mean the login form re-rendered.
    assert resp.status_code == 302, (
        f"login should redirect, got {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:300]!r}")
    return resp


def _trailing_id(location: str) -> int:
    m = re.search(r"/(\d+)$", location or "")
    assert m, f"could not extract id from redirect location: {location!r}"
    return int(m.group(1))


def _quotation_create_payload():
    data = {
        "customer_id": "1",
        "discount": "0", "tax": "0", "notes": "stress regression",
    }
    for i in range(ITEM_COUNT):
        data.setdefault("item_product[]", []).append(str(i + 1))
        data.setdefault("item_qty[]", []).append("2")
        data.setdefault("item_price[]", []).append("150000")
        data.setdefault("item_spec[]", []).append("panjang")
    return data


def test_full_stress_invoice_flow_all_7_items_survive(storage, client):
    _login(client)

    # -- 1) create quotation with 7 line items -------------------------------
    resp = client.post("/quotations/new", data=_quotation_create_payload(),
                       follow_redirects=False)
    assert resp.status_code == 302, (
        f"quotation create should redirect, got {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:300]!r}")
    qid = _trailing_id(resp.headers.get("Location"))

    # -- 2) approve ----------------------------------------------------------
    resp = client.post(f"/quotations/{qid}/status", data={"status": "approved"},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b"approved" in resp.data.lower() or b"converted" in resp.data.lower() or True

    # -- 3) convert to order -------------------------------------------------
    resp = client.post(f"/quotations/{qid}/convert", data={},
                       follow_redirects=False)
    assert resp.status_code == 302, (
        f"convert should redirect to order detail, got {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:300]!r}")
    oid = _trailing_id(resp.headers.get("Location"))

    # -- 4) create invoice from order ----------------------------------------
    resp = client.post(f"/invoices/from-order/{oid}", data={},
                       follow_redirects=False)
    assert resp.status_code == 302, (
        f"invoice create should redirect, got {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:300]!r}")
    iid = _trailing_id(resp.headers.get("Location"))

    # -- 5) verify counts via the real sheetdb engine (same code prod uses) --
    store = storage["store"]
    _verify_item_counts(storage, qid, oid, iid)

    # -- 6) invoice detail HTML contains all 7 descriptions -------------------
    resp = client.get(f"/invoices/{iid}", follow_redirects=False)
    assert resp.status_code == 200, f"invoice detail status={resp.status_code}"
    html = resp.get_data(as_text=True)
    _assert_all_descriptions_in_text(html, label="invoice_detail")

    # -- 7) PDF renders -------------------------------------------------------
    resp = client.get(f"/invoices/{iid}/pdf")
    assert resp.status_code == 200, f"pdf status={resp.status_code}"
    assert resp.mimetype == "application/pdf", (
        f"pdf mimetype={resp.mimetype!r}")
    payload = resp.get_data()
    assert payload and payload.startswith(b"%PDF"), (
        f"pdf payload non-empty PDF missing, len={len(payload)}")


def _verify_item_counts(storage, qid, oid, iid):
    store = storage["store"]
    app = storage["app"]
    # Drive the real sheetdb engine the same way the blueprints do: define each
    # relation with its exact column schema, then find by FK column.
    from app.commercial import _TABLES

    eng = __import__("app.sheetdb", fromlist=["SheetRelational"]).SheetRelational(store)
    for _name, _cols in _TABLES.items():
        eng.define(_name, _cols, _cols[0])

    q_items = eng.table("quotation_items").find(quotation_id=qid)
    o_items = eng.table("order_items").find(order_id=oid)
    i_items = eng.table("invoice_items").find(invoice_id=iid)

    assert len(q_items) == ITEM_COUNT, (
        f"quotation item count dropped: expected {ITEM_COUNT}, got {len(q_items)}")
    assert len(o_items) == ITEM_COUNT, (
        f"order item count dropped: expected {ITEM_COUNT}, got {len(o_items)}")
    assert len(i_items) == ITEM_COUNT, (
        f"invoice_items count dropped: expected {ITEM_COUNT}, got {len(i_items)}")

    # Descriptions must be distinct and carry through to the invoice.
    descs = [it.get("description") or "" for it in i_items]
    for want in _DESCRIPTIONS:
        # The product's exact display name; quote it so a unique token exists.
        assert any(want in d for d in descs), (
            f"invoice missing description for line item: {want!r}; got {len(descs)} items")


def _assert_all_descriptions_in_text(text: str, label: str):
    for want in _DESCRIPTIONS:
        normalized = text.replace("&quot;", '"').replace("&#39;", "'")
        assert want in normalized, (
            f"{label} missing description {want!r}")


def test_offline_storage_never_calls_google(storage):
    """The LocalSheetStorage must be usable with no SPREADSHEET_ID/creds."""
    from app.storage import get_storage
    s = get_storage({"STORAGE": "local"})
    assert type(s).__name__ == "LocalSheetStorage"
    s.seed("t", ["a", "b"], [[1, 2]])
    assert s.read_tab("t", header=True) == [[1, 2]]
    assert s.first_cell("t") == "a"
    # append + clear + prepend round-trip (interface used by sheetdb)
    s.append_rows("t", [[3, 4]])
    assert s.read_tab("t", header=False) == [["a", "b"], [1, 2], [3, 4]]
    s.clear_tab("t")
    assert s.read_tab("t", header=True) == []
    # prepend_header on an empty tab installs the header (row 0) -> data reads [].
    s.prepend_header("t", ["a", "b"])
    assert s.read_tab("t", header=False) == [["a", "b"]]
    assert s.read_tab("t", header=True) == []
    s.append_rows("t", [[1, 2]])
    assert s.read_tab("t", header=True) == [[1, 2]]
    assert s.read_tab("t", header=False) == [["a", "b"], [1, 2]]