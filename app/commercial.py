"""SOLA Phase 3-4 — commercial loop: Quotation → Order → Invoice → Payment (+ PDF).

Built ON the Phase-2 app: reuses generic require_permission() and audit() from
app.auth / app.masterdata, and the existing schema tables (quotations,
quotation_items, orders, order_items, invoices, invoice_items, payments).

Sheet-backed (FULL cutover): all reads/writes go through the SheetRelational
engine (app.sheetdb); the live Google Sheet is the single store — no SQL,
no commit (autosave). Values (QUO/ORD/INV numbering, subtotal/tax/grand_total/
outstanding math, statuses) are computed identically to the previous SQL.

Business rules enforced here (backend):
- Auto sequential numbers QUO/ORD/INV-<YYYY>-NNNN (year-fresh).
- A quotation converts ONCE into a sales order (status -> converted, locked).
- An invoice is generated FROM an order (one open invoice per order — no manual dupe).
- outstanding = grand_total - amount_paid, auto-recomputed on every payment;
  status -> paid when outstanding <= 0.
- Every write (create/status/convert/invoice/payment) is audited via audit().
"""
from datetime import date, datetime, timedelta, timezone
import logging
import time

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

_logger = logging.getLogger(__name__)

from .auth import require_permission
from .invoice_pdf import render_invoice_pdf

# --- sheet column order (authoritative source: .planning/2026-09-23-sheetcutover/column_map.txt)
_TABLES = {
    "quotations": ["quotation_id", "quotation_number", "customer_id", "quotation_date",
                   "valid_until", "subtotal", "discount", "tax", "total", "notes",
                   "status", "created_at"],
    "quotation_items": ["quotation_item_id", "quotation_id", "product_id", "variant_id",
                        "material_id", "decoration_id", "specification", "quantity",
                        "unit_id", "unit_price", "subtotal"],
    "orders": ["order_id", "order_number", "customer_id", "quotation_id", "order_date",
               "deadline", "status", "priority", "subtotal", "discount", "tax",
               "grand_total", "notes", "created_at"],
    "order_items": ["order_item_id", "order_id", "product_id", "variant_id", "material_id",
                    "color_id", "decoration_id", "decoration_position", "decoration_size",
                    "size_id", "quantity", "unit_id", "unit_price", "subtotal", "notes"],
    "invoices": ["invoice_id", "invoice_number", "order_id", "customer_id", "invoice_date",
                 "due_date", "subtotal", "discount", "tax", "grand_total", "amount_paid",
                 "outstanding", "status", "created_at"],
    "invoice_items": ["invoice_item_id", "invoice_id", "order_item_id", "description",
                      "quantity", "unit_id", "unit_price", "subtotal"],
    "payments": ["payment_id", "invoice_id", "payment_date", "amount", "method",
                 "reference", "notes", "created_by"],
    "customers": ["customer_id", "customer_code", "name", "company_name", "pic_name",
                  "phone", "email", "address", "npwp", "customer_type", "source",
                  "notes", "status", "created_at"],
    "materials": ["material_id", "material_code", "material_name", "category",
                  "specification", "unit_id", "gramasi", "width", "supplier", "status"],
    "products": ["product_id", "product_code", "product_name", "category_id", "unit_id",
                 "description", "status", "created_at", "updated_at"],
    "product_variants": ["variant_id", "product_id", "variant_name", "material_id", "notes"],
    "decorations": ["decoration_id", "decoration_code", "decoration_name", "category",
                    "pricing_method", "default_cost", "status"],
    "colors": ["color_id", "color_code", "color_name"],
    "sizes": ["size_id", "size_code", "sort_order"],
    "units": ["unit_id", "unit_code", "unit_name"],
    "users": ["user_id", "username", "full_name", "password_hash", "role_id",
              "phone", "email", "status"],
    "audit_logs": ["audit_id", "user_id", "timestamp", "action", "entity", "entity_id",
                   "old_value", "new_value"],
}


def _storage():
    return current_app.extensions["storage"]


# Re-verify a tab's header at most once per this many seconds (per warm instance)
# so the serverless request path stays cheap while still catching a header that
# is lost/broken later during a long-lived process.
_HEADER_RECHECK_SECS = 300.0


def _ensure_tab_headers(eng) -> None:
    """Validate every _TABLES tab's header row and repair a missing/broken one.

    Prevents the production bug where a tab (e.g. ``quotations``) lost its header
    row: ``read_tab(header=True)`` then swallowed the first record as the header
    (0 rows shown) and the next insert risked a duplicate pk.

    How it works / why it is safe:
      * Cheap guard first: read only cell A1 (cached ~10s by SheetsStorage) and
        compare it to the expected primary-key column. If it already matches, the
        header is present — do nothing (idempotent, zero network on the common
        path once verified this instance).
      * Only when A1 differs does a repair run: the canonical header row is
        inserted at position 1 in the sheet, shifting existing rows DOWN — no
        data is dropped.
      * Per-tab checks are gated by an in-instance ``_HEADER_RECHECK_SECS`` window
        so the check is not repeated on every request.
      * Every failure is logged and swallowed: a validation problem can never
        take down the app or block a request.
    """
    store = eng.sheets
    now = time.monotonic()
    for name, cols in _TABLES.items():
        pk = cols[0]
        last = (store._header_verified or {}).get(name)
        if last is not None and (now - last) < _HEADER_RECHECK_SECS:
            continue  # verified recently; keep the request path stateless
        try:
            first = store.first_cell(name)
            if first is not None and str(first).strip().lower() == str(pk).strip().lower():
                store._header_verified[name] = now  # header already correct
                continue
            # Header missing or data leaked into row 1 -> insert canonical header.
            store.prepend_header(name, cols)
            store._header_verified[name] = now
        except Exception:
            _logger.exception(
                "tab-header self-repair skipped for %s (non-fatal)", name)


def _rel():
    """Build a SheetRelational engine over the app's sheet storage (all tables defined)."""
    from app.sheetdb import SheetRelational
    eng = SheetRelational(_storage())
    for name, cols in _TABLES.items():
        eng.define(name, cols, cols[0])
    _ensure_tab_headers(eng)
    return eng


def audit(user_id, action, entity, entity_id=None, old_value=None, new_value=None) -> None:
    """Record a consequential action (spec §27) into the audit_logs sheet tab."""
    import json
    rel = _rel()
    rel.table("audit_logs").insert({
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "old_value": json.dumps(old_value, ensure_ascii=False, default=str) if old_value is not None else None,
        "new_value": json.dumps(new_value, ensure_ascii=False, default=str) if new_value is not None else None,
    })


QUOTE_BP = Blueprint("quotations", __name__, url_prefix="/quotations")
ORDER_BP = Blueprint("orders", __name__, url_prefix="/orders")
INVOICE_BP = Blueprint("invoices", __name__, url_prefix="/invoices")


def _register_unexpected_handler(bp):
    """Surface a friendly flash instead of a raw gateway/crash on unexpected
    exceptions (e.g. the transient Google-Sheets 429/5xx that bypass the retry),
    while ALWAYS logging the real error so it is not silently swallowed."""

    @bp.errorhandler(Exception)
    def _unexpected(exc):
        _logger.exception("unhandled error in commercial route: %s", exc)
        flash("A temporary error occurred. Please try again.", "danger")
        # host_url is always absolute, so redirect() uses it directly (never a
        # url_for BuildError) and lands on the app root / homepage by default.
        return redirect(request.referrer or request.host_url), 302


for _bp in (QUOTE_BP, ORDER_BP, INVOICE_BP):
    _register_unexpected_handler(_bp)

QUO_STATUSES = ["draft", "sent", "approved", "rejected", "converted", "cancelled"]
ORD_STATUSES = ["pending", "confirmed", "in_production", "completed", "cancelled"]
INV_PRIORITY = ["low", "normal", "high", "urgent"]
INV_STATUSES = ["draft", "issued", "partially_paid", "paid", "overdue", "cancelled"]
PAY_METHODS = ["transfer", "cash", "qris", "other"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _year():
    return date.today().strftime("%Y")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(v):
    try:
        return f"{int(round(float(v or 0))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def _next_number(prefix, table, col):
    """Return next '<PREFIX>-<YYYY>-NNNN' sequential value (year-fresh)."""
    rel = _rel()
    pat = f"{prefix}-{_year()}-"
    highest = 0
    for r in rel.table(table).read_all():
        v = str(r.get(col) or "")
        if not v.startswith(pat):
            continue
        tail = v.rsplit("-", 1)[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}-{_year()}-{highest + 1:04d}"


def _fmt_number(value):
    try:
        return str(int(value)) if float(value) == int(float(value)) else f"{value:g}"
    except (TypeError, ValueError):
        return str(value)


def _compact(items):
    parts = []
    for k in ("product", "variant", "material", "color", "size", "decoration", "position", "spec"):
        if items.get(k):
            parts.append(str(items[k]))
    return " · ".join(parts)


def _order_item_description(rel, oi):
    """Human line-item description (customer-facing, no cost data)."""
    if oi is None:
        return "Item"
    products = rel.table("products")
    variants = rel.table("product_variants")
    materials = rel.table("materials")
    colors = rel.table("colors")
    sizes = rel.table("sizes")
    decorations = rel.table("decorations")
    units = rel.table("units")
    row = {
        "product_name": (products.get(oi["product_id"]) or {}).get("product_name") if oi.get("product_id") else None,
        "variant_name": (variants.get(oi["variant_id"]) or {}).get("variant_name") if oi.get("variant_id") else None,
        "material_name": (materials.get(oi["material_id"]) or {}).get("material_name") if oi.get("material_id") else None,
        "color_name": (colors.get(oi["color_id"]) or {}).get("color_name") if oi.get("color_id") else None,
        "size_code": (sizes.get(oi["size_id"]) or {}).get("size_code") if oi.get("size_id") else None,
        "decoration_name": (decorations.get(oi["decoration_id"]) or {}).get("decoration_name") if oi.get("decoration_id") else None,
        "decoration_position": oi.get("decoration_position"),
        "decoration_size": oi.get("decoration_size"),
        "notes": oi.get("notes"),
        "quantity": oi.get("quantity"),
        "unit_price": oi.get("unit_price"),
        "subtotal": oi.get("subtotal"),
        "unit_code": (units.get(oi["unit_id"]) or {}).get("unit_code") if oi.get("unit_id") else None,
    }
    bit = []
    if row["product_name"]:
        bit.append(row["product_name"])
    if row["variant_name"]:
        bit.append(row["variant_name"])
    if row["material_name"]:
        bit.append(row["material_name"])
    if row["color_name"]:
        bit.append("Warna " + row["color_name"])
    if row["size_code"]:
        bit.append("Ukuran " + row["size_code"])
    if row["decoration_name"]:
        deco = row["decoration_name"]
        if row["decoration_position"]:
            deco += " (" + row["decoration_position"] + ")"
        if row["decoration_size"]:
            deco += " " + str(row["decoration_size"])
        bit.append("Bordir/Sablon: " + deco)
    if row["notes"]:
        bit.append("Catatan: " + str(row["notes"]))
    return " · ".join(bit) if bit else "Item"


def _opts(rel, table, order_by=None, active=False):
    """SELECT * FROM <table> [WHERE status='active'] ORDER BY <order_by> (in Python)."""
    t = rel.table(table)
    rows = t.read_all()
    if active:
        rows = [r for r in rows if r.get("status") == "active"]
    if order_by:
        rows = sorted(rows, key=lambda r: str(r.get(order_by) or ""))
    return rows


# ---------------------------------------------------------------------------
# QUOTATION
# ---------------------------------------------------------------------------
@QUOTE_BP.route("/")
@require_permission("quotation.view")
def list():
    q = request.args.get("q", "").strip()
    rel = _rel()
    lq = q.lower()
    rows = []
    for qr in rel.table("quotations").read_all():
        cust = rel.table("customers").get(qr.get("customer_id")) if qr.get("customer_id") else None
        name = cust["name"] if cust else None
        if q and (lq not in str(qr.get("quotation_number") or "").lower()
                  and (name is None or lq not in str(name).lower())):
            continue
        row = dict(qr)
        row["customer_name"] = name
        row["item_count"] = rel.table("quotation_items").count(quotation_id=qr["quotation_id"])
        rows.append(row)
    rows.sort(key=lambda r: _num(r.get("quotation_id")), reverse=True)
    return render_template("quotation_list.html", rows=rows, q=q,
                           can_create=_has("quotation.create"), can_update=_has("quotation.update"))


@QUOTE_BP.route("/new", methods=["GET", "POST"])
@require_permission("quotation.create")
def create():
    rel = _rel()
    customers = _opts(rel, "customers", order_by="name")
    materials = _opts(rel, "materials", order_by="material_name", active=True)
    products = _opts(rel, "products", order_by="product_name")
    variants = _opts(rel, "product_variants", order_by="variant_name")
    decorations = _opts(rel, "decorations", order_by="decoration_name", active=True)
    units = _opts(rel, "units", order_by="unit_code")

    if request.method == "POST":
        data, errors = _collect_quotation()
        if not errors:
            num = _next_number("QUO", "quotations", "quotation_number")
            rec = rel.table("quotations").insert({
                "quotation_number": num,
                "customer_id": data["customer_id"],
                "quotation_date": data["quotation_date"],
                "valid_until": data["valid_until"],
                "subtotal": data["subtotal"],
                "discount": data["discount"],
                "tax": data["tax"],
                "total": data["total"],
                "notes": data["notes"],
                "status": "draft",
            })
            qid = rec["quotation_id"]
            for it in data["items"]:
                rel.table("quotation_items").insert({
                    "quotation_id": qid,
                    "product_id": it["product_id"],
                    "variant_id": it["variant_id"],
                    "material_id": it["material_id"],
                    "decoration_id": it["decoration_id"],
                    "specification": it["specification"],
                    "quantity": it["quantity"],
                    "unit_id": it["unit_id"],
                    "unit_price": it["unit_price"],
                    "subtotal": it["subtotal"],
                })
            audit(g.current_user["user_id"], "CREATE", "quotation", entity_id=qid,
                  new_value={"quotation_number": num, "customer_id": data["customer_id"], "total": data["total"]})
            flash(f"Quotation {num} created.", "success")
            return redirect(url_for("quotations.detail", qid=qid))
        for e in errors:
            flash(e, "danger")

    return render_template("quotation_form.html", customers=customers, materials=materials,
                           products=products, variants=variants, decorations=decorations,
                           units=units, modes=QUO_STATUSES, form=dict(request.form))


def _collect_quotation():
    errors = []
    customer_id = request.form.get("customer_id") or None
    if customer_id is None:
        errors.append("Customer is required.")
    quotation_date = request.form.get("quotation_date") or date.today().isoformat()
    valid_until = request.form.get("valid_until") or None
    discount = _float_or(request.form.get("discount"), 0.0)
    tax = _float_or(request.form.get("tax"), 0.0)
    notes = request.form.get("notes") or None

    item_rows = []
    names = request.form.getlist("item_product[]")
    if not names:
        errors.append("Add at least one line item.")
    for idx, _pid in enumerate(names):
        qty = _float_or(_at(request.form, f"item_qty[]", idx), None)
        price = _float_or(_at(request.form, f"item_price[]", idx), 0.0)
        if qty is None or qty <= 0:
            errors.append(f"Item {idx + 1}: quantity must be a positive number.")
            continue
        material = _at(request.form, f"item_material[]", idx) or None
        price = price if price and price > 0 else (_catalog_price(material) or 0)
        item_rows.append({
            "product_id": _at(request.form, f"item_product[]", idx) or None,
            "variant_id": _at(request.form, f"item_variant[]", idx) or None,
            "material_id": material,
            "decoration_id": _at(request.form, f"item_decoration[]", idx) or None,
            "specification": _at(request.form, f"item_spec[]", idx) or None,
            "quantity": qty,
            "unit_id": _at(request.form, f"item_unit[]", idx) or None,
            "unit_price": price,
            "subtotal": round(qty * price, 2),
        })
    subtotal = round(sum(i["subtotal"] for i in item_rows), 2)
    total = round(subtotal - discount + tax, 2)
    data = {
        "customer_id": int(customer_id) if customer_id else None,
        "quotation_date": quotation_date, "valid_until": valid_until,
        "discount": discount, "tax": tax, "notes": notes,
        "subtotal": subtotal, "total": total,
        "items": item_rows,
    }
    return data, errors


@QUOTE_BP.route("/<int:qid>")
@require_permission("quotation.view")
def detail(qid):
    rel = _rel()
    qd = rel.table("quotations").get(qid)
    if qd is None:
        abort(404)
    q = dict(qd)
    cust = rel.table("customers").get(q.get("customer_id")) if q.get("customer_id") else None
    for k in ("customer_name", "company_name", "phone", "address"):
        q[k] = cust[k] if (cust and k in cust) else None
    items = []
    for qi in sorted(rel.table("quotation_items").find(quotation_id=qid),
                     key=lambda r: _num(r.get("quotation_item_id"))):
        m = rel.table("materials").get(qi["material_id"]) if qi.get("material_id") else None
        p = rel.table("products").get(qi["product_id"]) if qi.get("product_id") else None
        v = rel.table("product_variants").get(qi["variant_id"]) if qi.get("variant_id") else None
        d = rel.table("decorations").get(qi["decoration_id"]) if qi.get("decoration_id") else None
        u = rel.table("units").get(qi["unit_id"]) if qi.get("unit_id") else None
        row = dict(qi)
        row["material_name"] = m["material_name"] if m else None
        row["product_name"] = p["product_name"] if p else None
        row["variant_name"] = v["variant_name"] if v else None
        row["decoration_name"] = d["decoration_name"] if d else None
        row["unit_code"] = u["unit_code"] if u else None
        items.append(row)
    order = rel.table("orders").find_one(quotation_id=qid)
    return render_template("quotation_detail.html", q=q, items=items, order=order,
                           modes=QUO_STATUSES, c_create=_has("quotation.create"),
                           c_update=_has("quotation.update"), c_convert=_has("quotation.convert"))


@QUOTE_BP.route("/<int:qid>/edit", methods=["GET", "POST"])
@require_permission("quotation.update")
def edit(qid):
    rel = _rel()
    q = rel.table("quotations").get(qid)
    if q is None:
        abort(404)
    if q["status"] != "draft":
        flash("Only DRAFT quotations can be edited.", "danger")
        return redirect(url_for("quotations.detail", qid=qid))

    customers = _opts(rel, "customers", order_by="name")
    materials = _opts(rel, "materials", order_by="material_name", active=True)
    products = _opts(rel, "products", order_by="product_name")
    variants = _opts(rel, "product_variants", order_by="variant_name")
    decorations = _opts(rel, "decorations", order_by="decoration_name", active=True)
    units = _opts(rel, "units", order_by="unit_code")

    if request.method == "POST":
        data, errors = _collect_quotation()
        if not errors:
            rel.table("quotations").update(qid, {
                "customer_id": data["customer_id"],
                "quotation_date": data["quotation_date"],
                "valid_until": data["valid_until"],
                "subtotal": data["subtotal"],
                "discount": data["discount"],
                "tax": data["tax"],
                "total": data["total"],
                "notes": data["notes"],
                "status": "draft",
            })
            # Replace line items (delete all for this quote, re-insert from form).
            for it in rel.table("quotation_items").find(quotation_id=qid):
                rel.table("quotation_items").delete(it["quotation_item_id"])
            for it in data["items"]:
                rel.table("quotation_items").insert({
                    "quotation_id": qid,
                    "product_id": it["product_id"],
                    "variant_id": it["variant_id"],
                    "material_id": it["material_id"],
                    "decoration_id": it["decoration_id"],
                    "specification": it["specification"],
                    "quantity": it["quantity"],
                    "unit_id": it["unit_id"],
                    "unit_price": it["unit_price"],
                    "subtotal": it["subtotal"],
                })
            audit(g.current_user["user_id"], "UPDATE", "quotation", entity_id=qid,
                  old_value={"status": q["status"], "total": q["total"]},
                  new_value={"status": "draft", "total": data["total"]})
            flash(f"Quotation {q['quotation_number']} updated.", "success")
            return redirect(url_for("quotations.detail", qid=qid))
        for e in errors:
            flash(e, "danger")

    # GET (or failed POST): prefill the shared form with the existing quote.
    # On a failed POST we keep the user's submitted values so nothing is lost.
    if request.method == "POST":
        prefill_form = dict(request.form)
        names = request.form.getlist("item_product[]")
        mats = request.form.getlist("item_material[]")
        decos = request.form.getlist("item_decoration[]")
        qtys = request.form.getlist("item_qty[]")
        units = request.form.getlist("item_unit[]")
        prices = request.form.getlist("item_price[]")
        edit_items = []
        for i in range(len(names)):
            edit_items.append({
                "product_id": names[i] if i < len(names) else None,
                "variant_id": None,
                "material_id": mats[i] if i < len(mats) else None,
                "decoration_id": decos[i] if i < len(decos) else None,
                "quantity": qtys[i] if i < len(qtys) else None,
                "unit_id": units[i] if i < len(units) else None,
                "unit_price": prices[i] if i < len(prices) else None,
                "specification": None,
            })
    else:
        prefill_form = {
            "customer_id": q.get("customer_id"),
            "quotation_date": q.get("quotation_date"),
            "valid_until": q.get("valid_until"),
            "discount": q.get("discount"),
            "tax": q.get("tax"),
            "notes": q.get("notes"),
        }
        edit_items = []
        for qi in sorted(rel.table("quotation_items").find(quotation_id=qid),
                         key=lambda r: _num(r.get("quotation_item_id"))):
            edit_items.append({
                "product_id": qi.get("product_id"),
                "variant_id": qi.get("variant_id"),
                "material_id": qi.get("material_id"),
                "decoration_id": qi.get("decoration_id"),
                "quantity": qi.get("quantity"),
                "unit_id": qi.get("unit_id"),
                "unit_price": qi.get("unit_price"),
                "specification": qi.get("specification"),
            })
    return render_template("quotation_form.html", customers=customers, materials=materials,
                           products=products, variants=variants, decorations=decorations,
                           units=units, modes=QUO_STATUSES, form=prefill_form, q=q,
                           edit_items=edit_items, is_edit=True)

@QUOTE_BP.route("/<int:qid>/status", methods=["POST"])
@require_permission("quotation.update")
def set_status(qid):
    rel = _rel()
    q = rel.table("quotations").get(qid)
    if q is None:
        abort(404)
    status = request.form.get("status")
    if status not in QUO_STATUSES or status == "converted":
        flash("Invalid status.", "danger")
        return redirect(url_for("quotations.detail", qid=qid))
    allowed = {"draft", "sent", "approved", "rejected", "cancelled"}  # converted only via convert()
    if status not in allowed:
        flash("Invalid status transition.", "danger")
        return redirect(url_for("quotations.detail", qid=qid))
    rel.table("quotations").update(qid, {"status": status})
    audit(g.current_user["user_id"], "UPDATE", "quotation", entity_id=qid,
          old_value={"status": q["status"]}, new_value={"status": status})
    flash(f"Quotation {q['quotation_number']} marked {status}.", "success")
    return redirect(url_for("quotations.detail", qid=qid))


@QUOTE_BP.route("/<int:qid>/convert", methods=["POST"])
@require_permission("quotation.convert")
def convert(qid):
    rel = _rel()
    q = rel.table("quotations").get(qid)
    if q is None:
        abort(404)
    if q["status"] != "approved":
        flash("Only an APPROVED quotation can be converted to an order.", "danger")
        return redirect(url_for("quotations.detail", qid=qid))
    existing = rel.table("orders").find_one(quotation_id=qid)
    if existing:
        flash("This quotation is already converted to an order.", "danger")
        return redirect(url_for("quotations.detail", qid=qid))
    q_items = rel.table("quotation_items").find(quotation_id=qid)
    if not q_items:
        flash("Quotation has no line items; cannot convert.", "danger")
        return redirect(url_for("quotations.detail", qid=qid))

    num = _next_number("ORD", "orders", "order_number")
    deadline = request.form.get("deadline") or None
    priority = request.form.get("priority") or "normal"
    if priority not in INV_PRIORITY:
        priority = "normal"
    grand_total = round(float(q["total"] or 0), 2)
    rec = rel.table("orders").insert({
        "order_number": num,
        "customer_id": q["customer_id"],
        "quotation_id": qid,
        "order_date": date.today().isoformat(),
        "deadline": deadline,
        "status": "confirmed",
        "priority": priority,
        "subtotal": q["subtotal"],
        "discount": q["discount"],
        "tax": q["tax"],
        "grand_total": grand_total,
        "notes": q["notes"],
    })
    oid = rec["order_id"]
    for qi in q_items:
        rel.table("order_items").insert({
            "order_id": oid,
            "product_id": qi["product_id"],
            "variant_id": qi["variant_id"],
            "material_id": qi["material_id"],
            "decoration_id": qi["decoration_id"],
            "decoration_position": None,
            "decoration_size": None,
            "size_id": None,
            "quantity": qi["quantity"],
            "unit_id": qi["unit_id"],
            "unit_price": qi["unit_price"],
            "subtotal": qi["subtotal"],
            "notes": qi["specification"],
        })
    rel.table("quotations").update(qid, {"status": "converted"})
    audit(g.current_user["user_id"], "CONVERT", "quotation", entity_id=qid,
          new_value={"order_id": oid, "order_number": num})
    audit(g.current_user["user_id"], "CREATE", "order", entity_id=oid,
          new_value={"order_number": num, "quotation_id": qid, "grand_total": grand_total})
    flash(f"Quotation {q['quotation_number']} converted to {num}.", "success")
    return redirect(url_for("orders.detail", oid=oid))


# ---------------------------------------------------------------------------
# ORDER
# ---------------------------------------------------------------------------
@ORDER_BP.route("/")
@require_permission("order.view")
def list():
    q = request.args.get("q", "").strip()
    rel = _rel()
    lq = q.lower()
    rows = []
    for o in rel.table("orders").read_all():
        cust = rel.table("customers").get(o.get("customer_id")) if o.get("customer_id") else None
        name = cust["name"] if cust else None
        if q and (lq not in str(o.get("order_number") or "").lower()
                  and (name is None or lq not in str(name).lower())):
            continue
        row = dict(o)
        row["customer_name"] = name
        row["item_count"] = rel.table("order_items").count(order_id=o["order_id"])
        rows.append(row)
    rows.sort(key=lambda r: _num(r.get("order_id")), reverse=True)
    return render_template("order_list.html", rows=rows, q=q,
                           can_create=_has("order.create"))


@ORDER_BP.route("/new", methods=["GET", "POST"])
@require_permission("order.create")
def create():
    rel = _rel()
    customers = _opts(rel, "customers", order_by="name")
    materials = _opts(rel, "materials", order_by="material_name", active=True)
    products = _opts(rel, "products", order_by="product_name")
    variants = _opts(rel, "product_variants", order_by="variant_name")
    decorations = _opts(rel, "decorations", order_by="decoration_name", active=True)
    colors = _opts(rel, "colors", order_by="color_name")
    sizes = sorted(rel.table("sizes").read_all(),
                   key=lambda r: (_num(r.get("sort_order")), str(r.get("size_code") or "")))
    units = _opts(rel, "units", order_by="unit_code")

    if request.method == "POST":
        data, errors = _collect_order()
        if not errors:
            num = _next_number("ORD", "orders", "order_number")
            rec = rel.table("orders").insert({
                "order_number": num,
                "customer_id": data["customer_id"],
                "order_date": date.today().isoformat(),
                "deadline": data["deadline"],
                "status": "confirmed",
                "priority": data["priority"],
                "subtotal": data["subtotal"],
                "discount": data["discount"],
                "tax": data["tax"],
                "grand_total": data["total"],
                "notes": data["notes"],
            })
            oid = rec["order_id"]
            for it in data["items"]:
                rel.table("order_items").insert({
                    "order_id": oid,
                    "product_id": it["product_id"],
                    "variant_id": it["variant_id"],
                    "material_id": it["material_id"],
                    "color_id": it["color_id"],
                    "decoration_id": it["decoration_id"],
                    "decoration_position": it["dec_position"],
                    "decoration_size": it["dec_size"],
                    "size_id": it["size_id"],
                    "quantity": it["quantity"],
                    "unit_id": it["unit_id"],
                    "unit_price": it["unit_price"],
                    "subtotal": it["subtotal"],
                    "notes": it["notes"],
                })
            audit(g.current_user["user_id"], "CREATE", "order", entity_id=oid,
                  new_value={"order_number": num, "customer_id": data["customer_id"], "grand_total": data["total"]})
            flash(f"Order {num} created.", "success")
            return redirect(url_for("orders.detail", oid=oid))
        for e in errors:
            flash(e, "danger")

    return render_template("order_form.html", customers=customers, materials=materials,
                           products=products, variants=variants, decorations=decorations,
                           colors=colors, sizes=sizes, units=units, priorities=INV_PRIORITY,
                           form=dict(request.form))


def _collect_order():
    errors = []
    customer_id = request.form.get("customer_id") or None
    if customer_id is None:
        errors.append("Customer is required.")
    deadline = request.form.get("deadline") or None
    priority = request.form.get("priority") or "normal"
    if priority not in INV_PRIORITY:
        priority = "normal"
    discount = _float_or(request.form.get("discount"), 0.0)
    tax = _float_or(request.form.get("tax"), 0.0)
    notes = request.form.get("notes") or None

    item_rows = []
    if not request.form.getlist("item_product[]"):
        errors.append("Add at least one line item.")
    for idx, _pid in enumerate(request.form.getlist("item_product[]")):
        qty = _float_or(_at(request.form, f"item_qty[]", idx), None)
        price = _float_or(_at(request.form, f"item_price[]", idx), 0.0)
        if qty is None or qty <= 0:
            errors.append(f"Item {idx + 1}: quantity must be a positive number.")
            continue
        material = _at(request.form, f"item_material[]", idx) or None
        price = price if price and price > 0 else (_catalog_price(material) or 0)
        item_rows.append({
            "product_id": _at(request.form, f"item_product[]", idx) or None,
            "variant_id": _at(request.form, f"item_variant[]", idx) or None,
            "material_id": material,
            "color_id": _at(request.form, f"item_color[]", idx) or None,
            "decoration_id": _at(request.form, f"item_decoration[]", idx) or None,
            "dec_position": _at(request.form, f"item_position[]", idx) or None,
            "dec_size": _at(request.form, f"item_decsize[]", idx) or None,
            "size_id": _at(request.form, f"item_size[]", idx) or None,
            "quantity": qty,
            "unit_id": _at(request.form, f"item_unit[]", idx) or None,
            "unit_price": price,
            "subtotal": round(qty * price, 2),
            "notes": _at(request.form, f"item_notes[]", idx) or None,
        })
    subtotal = round(sum(i["subtotal"] for i in item_rows), 2)
    total = round(subtotal - discount + tax, 2)
    data = {
        "customer_id": int(customer_id) if customer_id else None,
        "deadline": deadline, "priority": priority,
        "discount": discount, "tax": tax, "notes": notes,
        "subtotal": subtotal, "total": total, "items": item_rows,
    }
    return data, errors


@ORDER_BP.route("/<int:oid>")
@require_permission("order.view")
def detail(oid):
    rel = _rel()
    od = rel.table("orders").get(oid)
    if od is None:
        abort(404)
    o = dict(od)
    cust = rel.table("customers").get(o.get("customer_id")) if o.get("customer_id") else None
    for k in ("customer_name", "company_name", "phone", "address"):
        o[k] = cust[k] if (cust and k in cust) else None
    items = []
    for oi in sorted(rel.table("order_items").find(order_id=oid),
                     key=lambda r: _num(r.get("order_item_id"))):
        m = rel.table("materials").get(oi["material_id"]) if oi.get("material_id") else None
        p = rel.table("products").get(oi["product_id"]) if oi.get("product_id") else None
        v = rel.table("product_variants").get(oi["variant_id"]) if oi.get("variant_id") else None
        d = rel.table("decorations").get(oi["decoration_id"]) if oi.get("decoration_id") else None
        co = rel.table("colors").get(oi["color_id"]) if oi.get("color_id") else None
        s = rel.table("sizes").get(oi["size_id"]) if oi.get("size_id") else None
        u = rel.table("units").get(oi["unit_id"]) if oi.get("unit_id") else None
        row = dict(oi)
        row["material_name"] = m["material_name"] if m else None
        row["product_name"] = p["product_name"] if p else None
        row["variant_name"] = v["variant_name"] if v else None
        row["decoration_name"] = d["decoration_name"] if d else None
        row["color_name"] = co["color_name"] if co else None
        row["size_code"] = s["size_code"] if s else None
        row["unit_code"] = u["unit_code"] if u else None
        items.append(row)
    invoices = sorted(rel.table("invoices").find(order_id=oid),
                      key=lambda r: _num(r.get("invoice_id")))
    quotation = rel.table("quotations").get(o["quotation_id"]) if o.get("quotation_id") else None
    return render_template("order_detail.html", o=o, items=items, invoices=invoices,
                           quotation=quotation, priorities=INV_PRIORITY,
                           c_invoice=_has("invoice.create"))


# ---------------------------------------------------------------------------
# INVOICE
# ---------------------------------------------------------------------------
@INVOICE_BP.route("/")
@require_permission("invoice.view")
def list():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    rel = _rel()
    lq = q.lower()
    rows = []
    for i in rel.table("invoices").read_all():
        order = rel.table("orders").get(i.get("order_id")) if i.get("order_id") else None
        cust = rel.table("customers").get(i.get("customer_id")) if i.get("customer_id") else None
        company_name = cust["company_name"] if cust else None
        if q and not (lq in str(i.get("invoice_number") or "").lower()
                      or (cust and lq in str(cust.get("name") or "").lower())
                      or (company_name and lq in str(company_name).lower())):
            continue
        if status and str(i.get("status") or "") != status:
            continue
        row = dict(i)
        row["order_number"] = order["order_number"] if order else None
        row["customer_name"] = cust["name"] if cust else None
        row["order_status"] = order["status"] if order else None
        rows.append(row)
    rows.sort(key=lambda r: _num(r.get("invoice_id")), reverse=True)
    return render_template("invoice_list.html", rows=rows, q=q, status=status,
                           statuses=INV_STATUSES, can_print=_has("invoice.view"))


@INVOICE_BP.route("/from-order/<int:oid>", methods=["POST"])
@require_permission("invoice.create")
def create_from_order(oid):
    rel = _rel()
    o = rel.table("orders").get(oid)
    if o is None:
        abort(404)
    if o["status"] in ("cancelled", "pending"):
        flash(f"Cannot invoice an order with status '{o['status']}'.", "danger")
        return redirect(url_for("orders.detail", oid=oid))
    active = [iv for iv in rel.table("invoices").find(order_id=oid) if iv.get("status") != "cancelled"]
    if active:
        flash("An active invoice already exists for this order.", "danger")
        return redirect(url_for("orders.detail", oid=oid))

    num = _next_number("INV", "invoices", "invoice_number")
    grand_total = round(float(o["grand_total"] or 0), 2)
    due = date.today() + timedelta(days=14)
    rec = rel.table("invoices").insert({
        "invoice_number": num,
        "order_id": oid,
        "customer_id": o["customer_id"],
        "invoice_date": date.today().isoformat(),
        "due_date": due.isoformat(),
        "subtotal": o["subtotal"],
        "discount": o["discount"],
        "tax": o["tax"],
        "grand_total": grand_total,
        "amount_paid": 0,
        "outstanding": grand_total,
        "status": "draft",
    })
    iid = rec["invoice_id"]
    o_items = rel.table("order_items").find(order_id=oid)
    for oi in o_items:
        desc = _order_item_description(rel, oi)
        rel.table("invoice_items").insert({
            "invoice_id": iid,
            "order_item_id": oi["order_item_id"],
            "description": desc,
            "quantity": oi["quantity"],
            "unit_id": oi["unit_id"],
            "unit_price": oi["unit_price"],
            "subtotal": oi["subtotal"],
        })
    audit(g.current_user["user_id"], "CREATE", "invoice", entity_id=iid,
          new_value={"invoice_number": num, "order_id": oid, "grand_total": grand_total,
                     "outstanding": grand_total})
    flash(f"Invoice {num} generated from order {o['order_number']}.", "success")
    return redirect(url_for("invoices.detail", iid=iid))


@INVOICE_BP.route("/<int:iid>")
@require_permission("invoice.view")
def detail(iid):
    rel = _rel()
    id_ = rel.table("invoices").get(iid)
    if id_ is None:
        abort(404)
    i = dict(id_)
    order = rel.table("orders").get(i.get("order_id")) if i.get("order_id") else None
    cust = rel.table("customers").get(i.get("customer_id")) if i.get("customer_id") else None
    i["order_number"] = order["order_number"] if order else None
    for k in ("customer_name", "company_name", "phone", "address"):
        i[k] = cust[k] if (cust and k in cust) else None
    items = sorted(rel.table("invoice_items").find(invoice_id=iid),
                   key=lambda r: _num(r.get("invoice_item_id")))
    payments = []
    for py in sorted(rel.table("payments").find(invoice_id=iid),
                     key=lambda r: _num(r.get("payment_id"))):
        u = rel.table("users").get(py["created_by"]) if py.get("created_by") else None
        row = dict(py)
        row["username"] = u["username"] if u else None
        payments.append(row)
    return render_template("invoice_detail.html", i=i, items=items, payments=payments,
                           methods=PAY_METHODS, statuses=INV_STATUSES,
                           c_payment=_has("invoice.payment"), c_update=_has("invoice.update"))


@INVOICE_BP.route("/<int:iid>/status", methods=["POST"])
@require_permission("invoice.update")
def set_status(iid):
    rel = _rel()
    i = rel.table("invoices").get(iid)
    if i is None:
        abort(404)
    status = request.form.get("status")
    if status not in ("issued", "cancelled"):
        flash("Only 'issued' or 'cancelled' can be set manually.", "danger")
        return redirect(url_for("invoices.detail", iid=iid))
    rel.table("invoices").update(iid, {"status": status})
    audit(g.current_user["user_id"], "UPDATE", "invoice", entity_id=iid,
          old_value={"status": i["status"]}, new_value={"status": status, "status_set": "manual"})
    flash(f"Invoice {i['invoice_number']} marked {status}.", "success")
    return redirect(url_for("invoices.detail", iid=iid))


@INVOICE_BP.route("/<int:iid>/payment", methods=["POST"])
@require_permission("invoice.payment")
def add_payment(iid):
    rel = _rel()
    i = rel.table("invoices").get(iid)
    if i is None:
        abort(404)
    if i["status"] == "cancelled":
        flash("Cannot record payment on a cancelled invoice.", "danger")
        return redirect(url_for("invoices.detail", iid=iid))
    if i["status"] == "draft":
        flash("Issue the invoice before recording payment.", "danger")
        return redirect(url_for("invoices.detail", iid=iid))
    amount = _float_or(request.form.get("amount"), None)
    if amount is None or amount <= 0:
        flash("Payment amount must be a positive number.", "danger")
        return redirect(url_for("invoices.detail", iid=iid))
    method = request.form.get("method") or "transfer"
    if method not in PAY_METHODS:
        method = "transfer"
    reference = request.form.get("reference") or None
    notes = request.form.get("notes") or None

    rec = rel.table("payments").insert({
        "invoice_id": iid,
        "payment_date": request.form.get("payment_date") or date.today().isoformat(),
        "amount": amount,
        "method": method,
        "reference": reference,
        "notes": notes,
        "created_by": g.current_user["user_id"],
    })
    paid = round(rel.table("payments").sum_column("amount", invoice_id=iid), 2)
    outstanding = round(float(i["grand_total"] or 0) - paid, 2)
    if outstanding <= 0.005:
        status = "paid"
    elif paid > 0:
        status = "partially_paid"
    else:
        status = i["status"]
    rel.table("invoices").update(iid, {"amount_paid": paid, "outstanding": outstanding, "status": status})
    audit(g.current_user["user_id"], "CREATE", "payment", entity_id=rec["payment_id"],
          new_value={"invoice_id": iid, "amount": amount, "method": method,
                     "paid_after": paid, "outstanding_after": outstanding, "status": status})
    flash(f"Payment Rp {_money(amount)} recorded. Outstanding: Rp {_money(outstanding)} ({status}).", "success")
    return redirect(url_for("invoices.detail", iid=iid))


@INVOICE_BP.route("/<int:iid>/pdf")
@require_permission("invoice.view")
def pdf(iid):
    rel = _rel()
    inv = rel.table("invoices").get(iid)
    if inv is None:
        abort(404)
    company = __import__("flask", fromlist=["current_app"]).current_app.config.get("COMPANY", {})
    payload = render_invoice_pdf(rel, iid, company=company)
    return send_file(
        __import__("io").BytesIO(payload),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"{inv['invoice_number']}.pdf",
    )


# ---------------------------------------------------------------------------
# low-level helpers
# ---------------------------------------------------------------------------
def _at(form, key, idx):
    values = form.getlist(key)
    return values[idx].strip() if idx < len(values) else ""


def _float_or(value, default):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _has(perm):
    from .auth import _user_has_perm

    return _user_has_perm(g.current_user, perm)


CATALOG_PRICE_BY_MATERIAL = {
    # material_id -> selling unit price (Rp) derived from docs/CATALOG_SOLA_2026.md.
    # Only confident family/price mappings included; others fall back to manual entry.
    33: 55000,   # CC-30S Cotton Combed 30s (T-Shirt incl. sablon)
    34: 60000,   # CC-24S Cotton Combed 24s
    35: 65000,   # CC-20S Cotton Combed 20s
    36: 50000,   # CD-30S Cotton Carded 30s
    37: 55000,   # CD-24S Cotton Carded 24s
    38: 60000,   # PQ-PE Piqe PE (Polo incl. bordir 2 posisi)
    39: 70000,   # PQ-CVC Piqe CVC
    40: 75000,   # PQ-CT Piqe Cotton
    41: 120000,  # DR-AM-KR American Drill (Korsa incl. lengan+4 bordir)
    42: 130000,  # DR-NT-KR Nagata Drill
    43: 135000,  # RB-PR-KR Ribstop Premium
    44: 120000,  # FL-PE Fleece PE (Hoodie incl. bordir/sablon 2)
    45: 135000,  # FL-CVC Fleece CVC
    46: 140000,  # FL-CT Fleece Cotton
    47: 135000,  # BT-CVC Baby Terry CVC
    48: 135000,  # BT-CT Baby Terry Cotton
    51: 135000,  # RB-PR-VS Ribstop Premium (Vest incl. bordir/sablon 2+zipper)
    52: 40000,   # RAFFLE (Cap incl. bordir 2 posisi)
    53: 20000,   # Mug Sublim (incl. sablon 2 warna + box)
    54: 18000,   # Mug Sablon
    55: 30000,   # Kanvas (Totebag 45x35 incl. sablon 2 warna + zipper)
    56: 24000,   # Tumbler A (incl. sablon 1 warna)
    57: 50000,   # Tumbler C
    62: 15000,   # Lanyard Only (Min. Order 24 pcs)
    63: 18000,   # Lanyard & ID Card
}


def _catalog_price(material_id):
    """Catalog selling price for a material_id, else None (fall back to manual)."""
    if not material_id:
        return None
    return CATALOG_PRICE_BY_MATERIAL.get(int(material_id))