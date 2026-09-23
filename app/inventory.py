"""SOLA Phase 6 — Inventory + Stock Movements (spec §18 / §24 / §27).

Built ON the Phase-2/3-4/5 app: reuses require_permission()/audit() and the
EXISTING schema tables (inventory, stock_movements, material_usage,
materials, production_orders) — no DDL change.

FULL CUTOVER: SQLite is gone; every table is a TAB in the live Google Sheet,
accessed through the SheetRelational engine (app.sheetdb). Sheets have no
transactions and autosave, so the read-modify-write-commit transaction is
replaced by a single composite update: read the current inventory row, compute
the new on_hand/reserved/available in Python, then update(pk, changes) ONCE
(unconditional atomicity is lost by design — the sheet is the store), followed
by stock_movements/material_usage inserts. All guards and error messages are
identical to the SQL version; over-reserve / over-issue / release-exceeds /
below-reserved attempts are still rejected AND audited.

Business rules enforced here (backend only, never UI-hiding alone):
- available = on_hand - reserved; a material with no inventory row is 0/0/0.
- ADJUSTMENT changes on_hand by a signed delta (guard: resulting on_hand must be
  >= reserved so available never goes negative).
- RESERVE moves qty into `reserved` (guard: qty <= available = on_hand - reserved).
- RELEASE (fulfillment, spec §18) moves qty from reserved to OUT: deducts on_hand
  AND clears reserved (guard: qty <= reserved).
- ISSUE (OUT) deducts on_hand directly (guard: qty <= on_hand, no over-issue).
- MATERIAL USAGE (recorded against a production) triggers an OUT movement + on_hand
  deduction (guard: qty <= on_hand), writes material_usage referencing production_id.
- Every accepted movement + every rejected/denied attempt is written to audit_logs
  and stock_movements (accepted).

Low stock: a material is LOW when available <= LOW_STOCK_THRESHOLD (module-level
default, simple per brief — deep Dashboard alerts are Phase 8).
"""
import json as _json

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from .auth import require_permission

INV_BP = Blueprint("inventory", __name__, url_prefix="/inventory")

LOW_STOCK_THRESHOLD = 0          # available <= this  => low-stock warning badge
MOVEMENT_TYPES = ("IN", "OUT", "ADJUSTMENT", "RESERVED", "RELEASED")

_DEFAULT_UNIT = 1  # fallback unit id when neither inventory nor material have one (pcs)


def _storage():
    return current_app.extensions["storage"]


def _rel():
    from app.sheetdb import SheetRelational

    return SheetRelational(_storage())


# Exact per-table column orders from .planning/2026-09-23-sheetcutover/column_map.txt.
_TABLES = {
    "inventory": ["inventory_id", "material_id", "unit_id", "on_hand", "reserved",
                  "available", "location", "updated_at"],
    "materials": ["material_id", "material_code", "material_name", "category",
                  "specification", "unit_id", "gramasi", "width", "supplier", "status"],
    "units": ["unit_id", "unit_code", "unit_name"],
    "stock_movements": ["stock_movement_id", "material_id", "movement_type", "quantity",
                        "unit_id", "reference_type", "reference_id", "moved_by",
                        "moved_at", "notes"],
    "material_usage": ["material_usage_id", "production_id", "material_id", "quantity",
                       "unit_id", "used_at"],
    "production_orders": ["production_id", "production_code", "order_id", "order_item_id",
                          "product_id", "variant_id", "quantity", "deadline",
                          "current_stage", "overall_progress", "status",
                          "workflow_template_id", "notes", "created_at", "updated_at"],
    "orders": ["order_id", "order_number", "customer_id", "quotation_id", "order_date",
               "deadline", "status", "priority", "subtotal", "discount", "tax",
               "grand_total", "notes", "created_at"],
    "customers": ["customer_id", "customer_code", "name", "company_name", "pic_name",
                  "phone", "email", "address", "npwp", "customer_type", "source",
                  "notes", "status", "created_at"],
    "users": ["user_id", "username", "full_name", "password_hash", "role_id", "phone",
              "email", "status"],
    "audit_logs": ["audit_id", "user_id", "timestamp", "action", "entity", "entity_id",
                   "old_value", "new_value"],
}


def _table(name):
    """Return the sheet relation for a table (defined on a fresh engine per call)."""
    cols = _TABLES[name]
    return _rel().define(name, cols, cols[0])


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def audit(user_id, action, entity, entity_id=None, old_value=None, new_value=None) -> None:
    """Record a consequential action (spec §27) into the audit_logs sheet tab."""
    _table("audit_logs").insert(
        {
            "user_id": user_id,
            "timestamp": _now(),
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "old_value": _json.dumps(old_value, ensure_ascii=False, default=str) if old_value is not None else None,
            "new_value": _json.dumps(new_value, ensure_ascii=False, default=str) if new_value is not None else None,
        }
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _has(perm):
    from .auth import _user_has_perm

    return _user_has_perm(g.current_user, perm)


def _num(val, default=None):
    if val is None or str(val).strip() == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _f(val):
    """Coerce a possibly-empty/string numeric to a float, defaulting to 0."""
    return _num(val, 0) or 0


def _int_or_none(val):
    if val is None or str(val).strip() in ("", "None"):
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _material_unit(rel, material_id, row=None):
    """Resolve a stable unit for a material (inventory row > material > fallback)."""
    if row is not None and row.get("unit_id"):
        return row["unit_id"]
    m = rel.table("materials").find_one(material_id=material_id)
    if m and m.get("unit_id"):
        return m["unit_id"]
    return _DEFAULT_UNIT


def _unit_label(rel, unit_id):
    if unit_id is None:
        return ""
    u = rel.table("units").find_one(unit_id=unit_id)
    return (u.get("unit_name") if u else "") or ""


def _inv(rel, material_id):
    """The single-valued inventory row for a material, or None when absent.

    (The SQL version auto-created a 0/0/0 row; the sheet engine autosaves, so
    creation is deferred to the write path to avoid phantom rows on denied
    attempts — absence is equivalent to 0/0/0 for reads and guards.)
    """
    return rel.table("inventory").find_one(material_id=material_id)


def _movement(rel, material_id, mtype, qty, unit_id, ref_type, ref_id, notes, user_id):
    rec = rel.table("stock_movements").insert(
        {
            "material_id": material_id,
            "movement_type": mtype,
            "quantity": qty,
            "unit_id": unit_id,
            "reference_type": ref_type,
            "reference_id": ref_id,
            "moved_by": user_id,
            "moved_at": _now(),
            "notes": notes or None,
        }
    )
    return rec["stock_movement_id"]


def _audit_denied(user_id, action, material_id, details):
    """Audit a REJECTED/guarded operation (spec §27 — attempts are auditable)."""
    audit(user_id, action, "inventory", entity_id=material_id, new_value=details)


def _is_low(available):
    return available is not None and available <= LOW_STOCK_THRESHOLD


def _materials_rows(rel):
    """All active materials joined to their inventory row, with derived numbers."""
    mats = [m for m in rel.table("materials").read_all() if m.get("status") == "active"]
    inv_by_mat = {i.get("material_id"): i for i in rel.table("inventory").read_all()}
    out = []
    for m in sorted(mats, key=lambda r: str(r.get("material_name") or "")):
        i = inv_by_mat.get(m.get("material_id"))
        r = {
            "material_id": m.get("material_id"),
            "material_code": m.get("material_code"),
            "material_name": m.get("material_name"),
            "category": m.get("category"),
            "specification": m.get("specification"),
            "status": m.get("status"),
        }
        if i is None:
            r.update(
                inventory_id=None, unit_id=None, on_hand=0, reserved=0, location=""
            )
        else:
            r.update(
                inventory_id=i.get("inventory_id"),
                unit_id=i.get("unit_id"),
                on_hand=_f(i.get("on_hand")),
                reserved=_f(i.get("reserved")),
                location=i.get("location") or "",
            )
        r["available"] = round(r["on_hand"] - r["reserved"], 4)
        r["low"] = _is_low(r["available"])
        r["unit_name"] = _unit_label(rel, r["unit_id"] or _material_unit(rel, r["material_id"]))
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------
@INV_BP.route("/")
@INV_BP.route("")
@require_permission("inventory.view")
def list_inventory():
    rel = _rel()
    rows = _materials_rows(rel)
    low_only = request.args.get("low") == "1"
    if low_only:
        rows = [r for r in rows if r["low"]]
    total_on_hand = round(sum(r["on_hand"] for r in _materials_rows(rel)), 4)
    total_reserved = round(sum(r["reserved"] for r in _materials_rows(rel)), 4)
    low_count = sum(1 for r in _materials_rows(rel) if r["low"])
    return render_template(
        "inventory.html",
        rows=rows,
        low_only=low_only,
        low_threshold=LOW_STOCK_THRESHOLD,
        low_count=low_count,
        total_on_hand=total_on_hand,
        total_reserved=total_reserved,
        can_manage=_has("inventory.manage"),
        can_usage=_has("inventory.manage") or _has("production.manage"),
    )


# ---------------------------------------------------------------------------
# ADJUST
# ---------------------------------------------------------------------------
@INV_BP.route("/adjust", methods=["POST"])
@require_permission("inventory.manage")
def adjust():
    rel = _rel()
    material_id = _int_or_none(request.form.get("material_id"))
    delta = _num(request.form.get("delta"))
    reason = (request.form.get("reason") or "").strip()
    if material_id is None or delta is None:
        flash("Material and a numeric delta are required.", "danger")
        return _back()
    m = rel.table("materials").find_one(material_id=material_id)
    if m is None:
        abort(404)
    inv_rel = rel.table("inventory")
    row = _inv(rel, material_id)
    inv_id = row["inventory_id"] if row else None
    old_on_hand = _f(row.get("on_hand")) if row else 0
    reserved = _f(row.get("reserved")) if row else 0
    new_on_hand = round(old_on_hand + delta, 4)
    if new_on_hand < reserved:
        _audit_denied(g.current_user["user_id"], "ADJUST_DENIED", material_id, {
            "old_on_hand": old_on_hand, "requested_delta": delta,
            "reserved": reserved, "reason": reason or "",
            "message": "adjustment would push available below reserved stock",
        })
        flash("Cannot adjust below reserved stock (available must stay >= 0).", "danger")
        return _back()
    unit_id = row.get("unit_id") if row else (_material_unit(rel, material_id) or _DEFAULT_UNIT)
    _movement(rel, material_id, "ADJUSTMENT", delta, unit_id, "adjustment",
              material_id, reason or f"Manual adjust by {g.current_user['username']}", g.current_user["user_id"])
    new_avail = round(new_on_hand - reserved, 4)
    changes = {
        "on_hand": new_on_hand, "reserved": reserved, "available": new_avail,
        "unit_id": unit_id, "updated_at": _now(),
    }
    if inv_id is not None:
        inv_rel.update(inv_id, changes)
    else:
        inv_rel.insert({
            "material_id": material_id, "unit_id": unit_id, "on_hand": new_on_hand,
            "reserved": reserved, "available": new_avail, "location": None,
        })
    old_avail = round(old_on_hand - reserved, 4)
    audit(g.current_user["user_id"], "ADJUST", "inventory", entity_id=material_id,
          old_value={"on_hand": old_on_hand, "available": old_avail},
          new_value={"on_hand": new_on_hand, "reserved": reserved,
                     "available": new_avail, "delta": delta, "reason": reason})
    flash(f"Adjusted {m['material_code']} on_hand by {delta:g} → {new_on_hand:g}.", "success")
    return _back()


# ---------------------------------------------------------------------------
# RESERVE
# ---------------------------------------------------------------------------
@INV_BP.route("/reserve", methods=["POST"])
@require_permission("inventory.manage")
def reserve():
    rel = _rel()
    material_id = _int_or_none(request.form.get("material_id"))
    qty = _num(request.form.get("quantity"))
    ref_type = (request.form.get("reference_type") or "order").strip()
    ref_id = _int_or_none(request.form.get("reference_id")) if ref_type != "order" else None
    notes = (request.form.get("notes") or "").strip()
    if material_id is None or qty is None or qty <= 0:
        flash("Material and a positive quantity are required.", "danger")
        return _back()
    m = rel.table("materials").find_one(material_id=material_id)
    if m is None:
        abort(404)
    inv_rel = rel.table("inventory")
    row = _inv(rel, material_id)
    inv_id = row["inventory_id"] if row else None
    on_hand, reserved = (_f(row.get("on_hand")) if row else 0,
                         _f(row.get("reserved")) if row else 0)
    available = round(on_hand - reserved, 4)
    if qty > available:
        _audit_denied(g.current_user["user_id"], "RESERVE_DENIED", material_id, {
            "requested": qty, "available": available, "on_hand": on_hand,
            "reserved": reserved, "message": "over-reserve rejected",
        })
        flash(f"Cannot reserve {qty:g}; only {available:g} available ({on_hand:g} on hand, {reserved:g} reserved).", "danger")
        return _back()
    new_reserved = round(reserved + qty, 4)
    unit_id = row.get("unit_id") if row else (_material_unit(rel, material_id) or _DEFAULT_UNIT)
    _movement(rel, material_id, "RESERVED", qty, unit_id, ref_type, ref_id,
              notes or f"Reserve for {ref_type} ({material_id}) by {g.current_user['username']}", g.current_user["user_id"])
    new_avail = round(on_hand - new_reserved, 4)
    changes = {"reserved": new_reserved, "available": new_avail, "updated_at": _now()}
    if inv_id is not None:
        inv_rel.update(inv_id, changes)
    else:
        inv_rel.insert({
            "material_id": material_id, "unit_id": unit_id, "on_hand": on_hand,
            "reserved": new_reserved, "available": new_avail, "location": None,
        })
    audit(g.current_user["user_id"], "RESERVE", "inventory", entity_id=material_id,
          old_value={"reserved": reserved, "available": available},
          new_value={"reserved": new_reserved, "available": new_avail,
                     "quantity": qty, "reference_type": ref_type, "reference_id": ref_id})
    flash(f"Reserved {qty:g} of {m['material_code']}.", "success")
    return _back()


# ---------------------------------------------------------------------------
# RELEASE (fulfillment -> OUT, clears reserved)
# ---------------------------------------------------------------------------
@INV_BP.route("/release", methods=["POST"])
@require_permission("inventory.manage")
def release():
    rel = _rel()
    material_id = _int_or_none(request.form.get("material_id"))
    qty = _num(request.form.get("quantity"))
    notes = (request.form.get("notes") or "").strip()
    if material_id is None or qty is None or qty <= 0:
        flash("Material and a positive quantity are required.", "danger")
        return _back()
    m = rel.table("materials").find_one(material_id=material_id)
    if m is None:
        abort(404)
    inv_rel = rel.table("inventory")
    row = _inv(rel, material_id)
    inv_id = row["inventory_id"] if row else None
    on_hand, reserved = (_f(row.get("on_hand")) if row else 0,
                         _f(row.get("reserved")) if row else 0)
    if qty > reserved:
        _audit_denied(g.current_user["user_id"], "RELEASE_DENIED", material_id, {
            "requested": qty, "reserved": reserved, "message": "release exceeds reserved",
        })
        flash(f"Cannot release {qty:g}; only {reserved:g} reserved.", "danger")
        return _back()
    new_on_hand = round(on_hand - qty, 4)
    new_reserved = round(reserved - qty, 4)
    unit_id = row.get("unit_id") if row else (_material_unit(rel, material_id) or _DEFAULT_UNIT)
    _movement(rel, material_id, "RELEASED", qty, unit_id, "order", material_id,
              notes or f"Release/fulfillment by {g.current_user['username']}", g.current_user["user_id"])
    new_avail = round(new_on_hand - new_reserved, 4)
    changes = {"on_hand": new_on_hand, "reserved": new_reserved,
               "available": new_avail, "updated_at": _now()}
    if inv_id is not None:
        inv_rel.update(inv_id, changes)
    else:
        inv_rel.insert({
            "material_id": material_id, "unit_id": unit_id, "on_hand": new_on_hand,
            "reserved": new_reserved, "available": new_avail, "location": None,
        })
    audit(g.current_user["user_id"], "RELEASE", "inventory", entity_id=material_id,
          old_value={"on_hand": on_hand, "reserved": reserved},
          new_value={"on_hand": new_on_hand, "reserved": new_reserved,
                     "quantity": qty, "available": new_avail})
    flash(f"Released {qty:g} of {m['material_code']} (OUT, clears reserved).", "success")
    return _back()


# ---------------------------------------------------------------------------
# ISSUE (OUT) — manual deduction, over-issue guarded
# ---------------------------------------------------------------------------
@INV_BP.route("/issue", methods=["POST"])
@require_permission("inventory.manage")
def issue():
    rel = _rel()
    material_id = _int_or_none(request.form.get("material_id"))
    qty = _num(request.form.get("quantity"))
    ref_type = (request.form.get("reference_type") or "order_item").strip()
    ref_id = _int_or_none(request.form.get("reference_id"))
    notes = (request.form.get("notes") or "").strip()
    if material_id is None or qty is None or qty <= 0:
        flash("Material and a positive quantity are required.", "danger")
        return _back()
    m = rel.table("materials").find_one(material_id=material_id)
    if m is None:
        abort(404)
    inv_rel = rel.table("inventory")
    row = _inv(rel, material_id)
    inv_id = row["inventory_id"] if row else None
    on_hand = _f(row.get("on_hand")) if row else 0
    if qty > on_hand:
        _audit_denied(g.current_user["user_id"], "ISSUE_DENIED", material_id, {
            "requested": qty, "on_hand": on_hand, "message": "over-issue rejected",
        })
        flash(f"Cannot issue {qty:g}; only {on_hand:g} on hand.", "danger")
        return _back()
    new_on_hand = round(on_hand - qty, 4)
    reserved = _f(row.get("reserved")) if row else 0
    unit_id = row.get("unit_id") if row else (_material_unit(rel, material_id) or _DEFAULT_UNIT)
    _movement(rel, material_id, "OUT", qty, unit_id, ref_type, ref_id,
              notes or f"Issue (OUT) by {g.current_user['username']}", g.current_user["user_id"])
    new_avail = round(new_on_hand - reserved, 4)
    changes = {"on_hand": new_on_hand, "reserved": reserved,
               "available": new_avail, "updated_at": _now()}
    if inv_id is not None:
        inv_rel.update(inv_id, changes)
    else:
        inv_rel.insert({
            "material_id": material_id, "unit_id": unit_id, "on_hand": new_on_hand,
            "reserved": reserved, "available": new_avail, "location": None,
        })
    audit(g.current_user["user_id"], "ISSUE_OUT", "inventory", entity_id=material_id,
          old_value={"on_hand": on_hand},
          new_value={"on_hand": new_on_hand, "reserved": reserved,
                     "available": new_avail, "quantity": qty,
                     "reference_type": ref_type, "reference_id": ref_id})
    flash(f"Issued {qty:g} of {m['material_code']} (OUT).", "success")
    return _back()


# ---------------------------------------------------------------------------
# MATERIAL USAGE (tied to a production -> OUT + material_usage)
# ---------------------------------------------------------------------------
@INV_BP.route("/usage", methods=["POST"])
@require_permission("inventory.manage", "production.manage")
def material_usage():
    rel = _rel()
    material_id = _int_or_none(request.form.get("material_id"))
    production_id = _int_or_none(request.form.get("production_id"))
    qty = _num(request.form.get("quantity"))
    notes = (request.form.get("notes") or "").strip()
    if material_id is None or qty is None or qty <= 0:
        flash("Material and a positive quantity are required.", "danger")
        return _back()
    m = rel.table("materials").find_one(material_id=material_id)
    if m is None:
        abort(404)
    prod = None
    if production_id:
        p = rel.table("production_orders").find_one(production_id=production_id)
        if p is not None:
            prod = dict(p)
            o = rel.table("orders").find_one(order_id=p.get("order_id"))
            if o is not None:
                c = rel.table("customers").find_one(customer_id=o.get("customer_id"))
                prod["customer_name"] = c.get("name") if c else None
            else:
                prod["customer_name"] = None
    if prod is None:
        flash("Usage must reference an existing production.", "danger")
        return _back()
    inv_rel = rel.table("inventory")
    row = _inv(rel, material_id)
    inv_id = row["inventory_id"] if row else None
    on_hand = _f(row.get("on_hand")) if row else 0
    if qty > on_hand:
        _audit_denied(g.current_user["user_id"], "USAGE_DENIED", material_id, {
            "requested": qty, "on_hand": on_hand, "production_id": production_id,
            "message": "material usage exceeds on_hand",
        })
        flash(f"Cannot consume {qty:g}; only {on_hand:g} on hand.", "danger")
        return _back()
    new_on_hand = round(on_hand - qty, 4)
    reserved = _f(row.get("reserved")) if row else 0
    unit_id = row.get("unit_id") if row else (_material_unit(rel, material_id) or _DEFAULT_UNIT)
    # OUT movement referencing the production + the material_usage record
    _movement(rel, material_id, "OUT", qty, unit_id, "production",
              production_id, notes or f"Material used on {prod['production_code']} by {g.current_user['username']}",
              g.current_user["user_id"])
    new_avail = round(new_on_hand - reserved, 4)
    changes = {"on_hand": new_on_hand, "reserved": reserved,
               "available": new_avail, "updated_at": _now()}
    if inv_id is not None:
        inv_rel.update(inv_id, changes)
    else:
        inv_rel.insert({
            "material_id": material_id, "unit_id": unit_id, "on_hand": new_on_hand,
            "reserved": reserved, "available": new_avail, "location": None,
        })
    mu_rec = rel.table("material_usage").insert({
        "production_id": production_id, "material_id": material_id, "quantity": qty,
        "unit_id": unit_id, "used_at": _now(),
    })
    audit(g.current_user["user_id"], "MATERIAL_USAGE", "inventory", entity_id=material_id,
          new_value={"production_id": production_id, "production_code": prod["production_code"],
                     "material_id": material_id, "quantity": qty,
                     "on_hand": new_on_hand, "material_usage_id": mu_rec["material_usage_id"]})
    flash(f"Recorded {qty:g} {m['material_code']} used on {prod['production_code']} (OUT).", "success")
    return _back()


# ---------------------------------------------------------------------------
# MOVEMENTS + USAGE LOG (view)
# ---------------------------------------------------------------------------
@INV_BP.route("/movements")
@require_permission("inventory.view")
def movements():
    rel = _rel()
    mtype = (request.args.get("type") or "").strip().upper()
    q = request.args.get("q", "").strip()

    def _enrich(r):
        d = dict(r)
        mrow = rel.table("materials").find_one(material_id=r.get("material_id"))
        u = rel.table("users").find_one(user_id=r.get("moved_by"))
        unr = rel.table("units").find_one(unit_id=r.get("unit_id"))
        d["material_code"] = mrow.get("material_code") if mrow else None
        d["material_name"] = mrow.get("material_name") if mrow else None
        d["username"] = u.get("username") if u else None
        d["unit_name"] = unr.get("unit_name") if unr else None
        return d

    rows = [_enrich(r) for r in rel.table("stock_movements").read_all()]
    if mtype in MOVEMENT_TYPES:
        rows = [r for r in rows if r.get("movement_type") == mtype]
    if q:
        lq = q.lower()
        rows = [
            r for r in rows
            if lq in (f"{r.get('material_code') or ''}{r.get('material_name') or ''}{r.get('username') or ''}").lower()
        ]
    rows.sort(key=lambda r: _int_or_none(r.get("stock_movement_id")) or 0, reverse=True)
    rows = rows[:300]
    return render_template("inventory_movements.html", rows=rows, mtype=mtype, q=q,
                           movement_types=MOVEMENT_TYPES,
                           can_manage=_has("inventory.manage") or _has("production.manage"))


@INV_BP.route("/usage-log")
@require_permission("inventory.view")
def usage_log():
    rel = _rel()
    rows = []
    for r in rel.table("material_usage").read_all():
        d = dict(r)
        mrow = rel.table("materials").find_one(material_id=r.get("material_id"))
        p = rel.table("production_orders").find_one(production_id=r.get("production_id"))
        unr = rel.table("units").find_one(unit_id=r.get("unit_id"))
        d["material_code"] = mrow.get("material_code") if mrow else None
        d["material_name"] = mrow.get("material_name") if mrow else None
        d["production_code"] = p.get("production_code") if p else None
        d["unit_name"] = unr.get("unit_name") if unr else None
        rows.append(d)
    rows.sort(key=lambda r: _int_or_none(r.get("material_usage_id")) or 0, reverse=True)
    rows = rows[:300]
    return render_template("inventory_usage.html", rows=rows,
                           can_manage=_has("inventory.manage") or _has("production.manage"))


def _back():
    return redirect(url_for("inventory.list_inventory"))


@INV_BP.route("/productions")
@require_permission("inventory.manage", "production.manage")
def usage_productions():
    """JSON list of productions for the usage modal (reference picker)."""
    from flask import jsonify

    rel = _rel()
    rows = []
    for p in rel.table("production_orders").read_all():
        if str(p.get("status")) == "cancelled":
            continue
        customer_name = None
        o = rel.table("orders").find_one(order_id=p.get("order_id"))
        if o is not None:
            c = rel.table("customers").find_one(customer_id=o.get("customer_id"))
            customer_name = c.get("name") if c else None
        rows.append({"production_id": p.get("production_id"),
                     "production_code": p.get("production_code"),
                     "customer_name": customer_name})
    rows.sort(key=lambda r: _int_or_none(r.get("production_id")) or 0, reverse=True)
    rows = rows[:100]
    return jsonify(rows)