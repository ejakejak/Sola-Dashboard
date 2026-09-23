"""SOLA Phase 8 — Dashboard home (``/``): live KPI cards, alerts, deadlines & feed.

Built ON the verified Phases 0-7 app: reuses the SheetRelational engine
(``app.sheetdb``) and the live tab-store tables (``orders``, ``invoices``,
``production_orders``, ``production_stages``, ``production_updates``,
``inventory``, ``materials``, ``users``) — the Google Sheet is the single
live store (FULL cutover; no SQL, no commit — autosave). Every number derives
from the live sheet on every request (never hard-coded). Status colors follow
DESIGN_SPEC §1.1 tokens via the shared ``.badge`` / ``.progress`` classes.

KPI definitions (matching PHASE8_BRIEF §1 / DESIGN_SPEC §3.1):
  Active Orders       count of orders NOT completed/cancelled
  In Production       count of productions NOT completed/cancelled
  Waiting Payment     count of invoices with outstanding > 0
  Ready to Ship       productions at COMPLETED stage / status completed (no
                      "shipped" flag exists in the schema — documented boundary)
  Overdue             productions past deadline and not completed/cancelled
  Outstanding Invoice sum of invoices.outstanding (IDR)

Low-stock alert reuses the SAME threshold/semantics as the Inventory low-badge
(``inventory.LOW_STOCK_THRESHOLD``) so the two surfaces never disagree.
"""
from datetime import date

from flask import current_app, g, render_template

from .inventory import LOW_STOCK_THRESHOLD


def _rel():
    from app.sheetdb import SheetRelational
    return SheetRelational(current_app.extensions["storage"])


# Column orders from .planning/2026-09-23-sheetcutover/column_map.txt
_COLS = {
    "orders": ["order_id", "order_number", "customer_id", "quotation_id",
               "order_date", "deadline", "status", "priority", "subtotal",
               "discount", "tax", "grand_total", "notes", "created_at"],
    "invoices": ["invoice_id", "invoice_number", "order_id", "customer_id",
                 "invoice_date", "due_date", "subtotal", "discount", "tax",
                 "grand_total", "amount_paid", "outstanding", "status",
                 "created_at"],
    "production_orders": ["production_id", "production_code", "order_id",
                          "order_item_id", "product_id", "variant_id",
                          "quantity", "deadline", "current_stage",
                          "overall_progress", "status",
                          "workflow_template_id", "notes", "created_at",
                          "updated_at"],
    "inventory": ["inventory_id", "material_id", "unit_id", "on_hand",
                  "reserved", "available", "location", "updated_at"],
    "materials": ["material_id", "material_code", "material_name", "category",
                  "specification", "unit_id", "gramasi", "width", "supplier",
                  "status"],
    "production_updates": ["update_id", "production_id", "production_stage_id",
                           "user_id", "timestamp", "progress",
                           "quantity_completed", "quantity_rejected", "notes"],
    "production_stages": ["production_stage_id", "production_id", "stage_id",
                          "stage_name", "sequence", "status", "assigned_user",
                          "assigned_vendor", "start_at", "completed_at",
                          "target_quantity", "completed_quantity",
                          "rejected_quantity", "notes"],
    "users": ["user_id", "username", "full_name", "password_hash", "role_id",
              "phone", "email", "status"],
}


def _define(rel, name):
    return rel.define(name, _COLS[name], pk=_COLS[name][0])


BOARD_STAGES = [
    "ORDER",
    "MATERIAL PREPARATION",
    "CUTTING",
    "SEWING",
    "PRINTING",
    "FINISHING",
    "QC",
    "PACKING",
    "COMPLETED",
]

_ACTIVE_STATUSES = ("completed", "cancelled")


def _money(v):
    try:
        return f"{int(round(float(v or 0))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def _to_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def compute_kpis():
    rel = _rel()
    orders = _define(rel, "orders")
    productions = _define(rel, "production_orders")
    invoices = _define(rel, "invoices")

    active_orders = sum(
        1 for o in orders.read_all() if o.get("status") not in _ACTIVE_STATUSES
    )
    in_production = sum(
        1 for p in productions.read_all()
        if p.get("status") not in _ACTIVE_STATUSES
    )
    open_invoices = [
        inv for inv in invoices.read_all() if _to_num(inv.get("outstanding")) > 0
    ]
    waiting_payment = len(open_invoices)
    ready_to_ship = sum(
        1 for p in productions.read_all()
        if (p.get("status") == "completed" or p.get("current_stage") == "COMPLETED")
        and p.get("status") != "cancelled"
    )
    today = date.today().isoformat()
    overdue = 0
    for p in productions.read_all():
        dl = p.get("deadline")
        if (dl is not None and str(dl) < today
                and p.get("status") not in _ACTIVE_STATUSES):
            overdue += 1
    outstanding_sum = invoices.sum_column("outstanding")
    kpis = [
        {"key": "active_orders", "label": "Active Orders", "value": active_orders,
         "token": "info", "link": "/orders", "sub": "not completed / cancelled"},
        {"key": "in_production", "label": "In Production", "value": in_production,
         "token": "warning", "link": "/production/", "sub": "jobs in the pipeline"},
        {"key": "waiting_payment", "label": "Waiting Payment", "value": waiting_payment,
         "token": "warning", "link": "/invoices/", "sub": "invoices with a balance"},
        {"key": "ready_to_ship", "label": "Ready to Ship", "value": ready_to_ship,
         "token": "success", "link": "/production/", "sub": "completed, not shipped"},
        {"key": "overdue", "label": "Overdue", "value": overdue,
         "token": "danger", "link": "/production/board", "sub": "past deadline"},
        {"key": "outstanding_invoice", "label": "Outstanding Invoice", "value": _money(outstanding_sum),
         "token": "danger", "link": "/invoices/", "sub": "sum owed (IDR)"},
    ]
    return kpis, {"outstanding_sum": outstanding_sum}


def compute_low_stock():
    """Tracked materials (rows present in inventory) at/below the low-stock threshold."""
    rel = _rel()
    inventory = _define(rel, "inventory")
    materials = _define(rel, "materials")
    mat_by_id = {}
    for m in materials.read_all():
        mid = str(m.get("material_id"))
        if m.get("status") == "active":
            mat_by_id[mid] = m
    rows = []
    for i in inventory.read_all():
        mid = str(i.get("material_id"))
        mat = mat_by_id.get(mid)
        if mat is None:
            continue
        available = _to_num(i.get("available"))
        if available <= LOW_STOCK_THRESHOLD:
            rows.append({
                "material_id": i.get("material_id"),
                "material_code": mat.get("material_code"),
                "material_name": mat.get("material_name"),
                "available": available,
            })
    rows.sort(key=lambda r: (r["available"], str(r["material_name"] or "")))
    return rows


def compute_upcoming_deadlines(limit=5):
    rel = _rel()
    productions = _define(rel, "production_orders")
    today = None
    rows = []
    for p in productions.read_all():
        dl = p.get("deadline")
        if dl is not None and p.get("status") not in _ACTIVE_STATUSES:
            rows.append(p)
    rows.sort(key=lambda r: (str(r.get("deadline") or ""), _to_num(r.get("production_id"))))
    return [
        {"production_id": r.get("production_id"),
         "production_code": r.get("production_code"),
         "deadline": r.get("deadline"),
         "quantity": r.get("quantity"),
         "current_stage": r.get("current_stage")}
        for r in rows[:limit]
    ]


def compute_unpaid_invoices():
    rel = _rel()
    invoices = _define(rel, "invoices")
    open_invoices = [
        inv for inv in invoices.read_all() if _to_num(inv.get("outstanding")) > 0
    ]
    total = sum(_to_num(inv.get("outstanding")) for inv in open_invoices)
    return {"count": len(open_invoices), "total": total}


def compute_recent_updates(limit=8):
    rel = _rel()
    updates = _define(rel, "production_updates")
    productions = _define(rel, "production_orders")
    users = _define(rel, "users")
    stages = _define(rel, "production_stages")

    prod_by_id = {str(p.get("production_id")): p for p in productions.read_all()}
    user_by_id = {str(u.get("user_id")): u for u in users.read_all()}
    stage_by_id = {str(s.get("production_stage_id")): s for s in stages.read_all()}

    all_updates = sorted(
        updates.read_all(),
        key=lambda r: _to_num(r.get("update_id")),
        reverse=True,
    )
    rows = []
    for u in all_updates[:limit]:
        pid = u.get("production_id")
        prod = prod_by_id.get(str(pid)) if pid is not None else None
        uid = u.get("user_id")
        user = user_by_id.get(str(uid)) if uid is not None else None
        sid = u.get("production_stage_id")
        stage = stage_by_id.get(str(sid)) if sid is not None else None
        rows.append({
            "update_id": u.get("update_id"),
            "production_id": pid,
            "progress": u.get("progress"),
            "quantity_completed": u.get("quantity_completed"),
            "notes": u.get("notes"),
            "timestamp": u.get("timestamp"),
            "production_code": prod.get("production_code") if prod else None,
            "actor": user.get("username") if user else None,
            "stage_name": stage.get("stage_name") if stage else None,
        })
    return rows


def compute_board_snapshot():
    """Active productions bucketed by stage column -> count, for the mini bar chart."""
    rel = _rel()
    productions = _define(rel, "production_orders")
    data = {st: 0 for st in BOARD_STAGES}
    for p in productions.read_all():
        if p.get("status") in _ACTIVE_STATUSES:
            continue
        stage = (p.get("current_stage") or "").strip().upper()
        if stage == "MATERIAL":
            stage = "MATERIAL PREPARATION"
        if stage in data:
            data[stage] += 1
    return data


def render_dashboard():
    """Build and render the real Phase-8 dashboard home (replaces the Phase-0 placeholder).

    Called from the app-level ``/`` route (endpoint ``index``) so ``url_for('index')``
    keeps resolving — the shared helper lives here to keep KPI/alert logic out of
    the app factory (data comes straight from the live sheet store).
    """
    kpis, kpi_meta = compute_kpis()
    low_stock = compute_low_stock()
    deadlines = compute_upcoming_deadlines()
    unpaid = compute_unpaid_invoices()
    updates = compute_recent_updates()
    board_snapshot = compute_board_snapshot()
    low_threshold = LOW_STOCK_THRESHOLD
    try:
        from .production import COLUMN_TOKEN as _column_token
    except Exception:  # pragma: no cover - import guard only
        _column_token = {}
    return render_template(
        "dashboard.html",
        kpis=kpis,
        low_stock=low_stock,
        low_threshold=low_threshold,
        deadlines=deadlines,
        unpaid=unpaid,
        updates=updates,
        board_snapshot=board_snapshot,
        board_stages=BOARD_STAGES,
        column_token=_column_token,
        money=_money,
        current_username=(g.get("current_user")["username"] if g.get("current_user") else None),
    )