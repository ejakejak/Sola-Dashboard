"""SOLA Phase 7 — public customer production tracking (/track).

NO login required (intentionally NOT behind require_permission). A customer
enters a production_code (e.g. PRD-260922-001) and is shown ONLY that
production's customer-visible data.

Security (spec §20):
  * Lookup strictly by the unique production_code — no DB primary keys are ever
    emitted (no production_id / media_id / stage_id in the rendered page).
  * Any miss renders the SAME generic "Production not found." message — no
    existence oracle (we can't distinguish "code exists" from "wrong code").
  * Per-IP rate limiting (in-memory sliding window, constants in app/config.py):
      - at most 20 lookups / IP / hour,
      - after 5 consecutive failed lookups a 90s cooldown engages for that IP.
    Blocks return HTTP 429 with a generic message; rate-limit events are logged
    to the server log only (tracking is read-only public — no audit rows).
  * Customer-visible data ONLY. Never rendered: HPP/cost, margin, vendor price,
    internal notes, internal media (visibility == 'INTERNAL'), other customers'
    data, payment/invoice data.
  * CUSTOMER-visibility media is served through /track/media/<code>/<filename>
    which re-validates that the media row belongs to that production AND has
    visibility 'CUSTOMER' before sending bytes (INTERNAL media returns 404).
"""
import logging

from flask import (
    Blueprint,
    abort,
    current_app,
    render_template,
    request,
    send_from_directory,
)

from .config import BASE_DIR

log = logging.getLogger(__name__)


def _rel():
    from app.sheetdb import SheetRelational
    return SheetRelational(current_app.extensions["storage"])


# Column orders (must match .planning/2026-09-23-sheetcutover/column_map.txt).
_PROD_ORDER_COLS = [
    "production_id", "production_code", "order_id", "order_item_id",
    "product_id", "variant_id", "quantity", "deadline", "current_stage",
    "overall_progress", "status", "workflow_template_id", "notes",
    "created_at", "updated_at",
]
_ORDER_COLS = [
    "order_id", "order_number", "customer_id", "quotation_id", "order_date",
    "deadline", "status", "priority", "subtotal", "discount", "tax",
    "grand_total", "notes", "created_at",
]
_ORDER_ITEM_COLS = [
    "order_item_id", "order_id", "product_id", "variant_id", "material_id",
    "color_id", "decoration_id", "decoration_position", "decoration_size",
    "size_id", "quantity", "unit_id", "unit_price", "subtotal", "notes",
]
_PRODUCT_COLS = [
    "product_id", "product_code", "product_name", "category_id", "unit_id",
    "description", "status", "created_at", "updated_at",
]
_VARIANT_COLS = ["variant_id", "product_id", "variant_name", "material_id", "notes"]
_STAGE_COLS = [
    "production_stage_id", "production_id", "stage_id", "stage_name",
    "sequence", "status", "assigned_user", "assigned_vendor", "start_at",
    "completed_at", "target_quantity", "completed_quantity", "rejected_quantity",
    "notes",
]
_UPDATE_COLS = [
    "update_id", "production_id", "production_stage_id", "user_id",
    "timestamp", "progress", "quantity_completed", "quantity_rejected", "notes",
]
_MEDIA_COLS = [
    "media_id", "update_id", "production_id", "file_url", "file_type",
    "visibility", "uploaded_by", "uploaded_at",
]


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _lookup_track_rels():
    """Define + return the production_* rels shared by the lookup + media routes."""
    r = _rel()
    po = r.define("production_orders", _PROD_ORDER_COLS, "production_id")
    orders = r.define("orders", _ORDER_COLS, "order_id")
    items = r.define("order_items", _ORDER_ITEM_COLS, "order_item_id")
    products = r.define("products", _PRODUCT_COLS, "product_id")
    variants = r.define("product_variants", _VARIANT_COLS, "variant_id")
    stages = r.define("production_stages", _STAGE_COLS, "production_stage_id")
    updates = r.define("production_updates", _UPDATE_COLS, "update_id")
    media = r.define("production_media", _MEDIA_COLS, "media_id")
    return po, orders, items, products, variants, stages, updates, media


track_bp = Blueprint("track", __name__, url_prefix="/track")

UPLOAD_DIR = BASE_DIR / "app" / "static" / "uploads"

NOT_FOUND_MSG = "Production not found. Please check the code and try again."
RATE_LIMIT_MSG = (
    "Too many attempts. Please wait a few minutes and try again."
)
PROD_BADGE_CLASS = {
    "pending": "st-pending",
    "in_progress": "st-in_progress",
    "completed": "st-completed",
    "cancelled": "st-cancelled",
    "blocked": "st-partially_paid",
}


@track_bp.app_template_global()
def prod_badge_class(status):
    return PROD_BADGE_CLASS.get(status, "st-normal")


def _client_ip():
    return request.remote_addr or "unknown"


# ---------------------------------------------------------------------------
# Customer-visible data assembly
# ---------------------------------------------------------------------------
def _lookup_customer_view(db, code):
    """Return ONLY the customer-visible production fields (no row ids, no costs)."""
    (po, orders, items, products, variants,
     stages, updates, media) = _lookup_track_rels()

    prod = po.find_one(production_code=code)
    if prod is None:
        return None
    # Production row PK is only used for subsidiary lookups; never rendered.
    pid = prod["production_id"]

    order = orders.get(prod["order_id"]) if prod.get("order_id") else None
    oi = items.get(prod["order_item_id"]) if prod.get("order_item_id") else None
    pd = products.get(prod["product_id"]) if prod.get("product_id") else None
    oi_pd = products.get(oi["product_id"]) if oi and oi.get("product_id") else None
    v = variants.get(prod["variant_id"]) if prod.get("variant_id") else None
    oi_v = variants.get(oi["variant_id"]) if oi and oi.get("variant_id") else None

    product_name = (pd or {}).get("product_name") or (oi_pd or {}).get("product_name")
    variant_name = (v or {}).get("variant_name") or (oi_v or {}).get("variant_name")
    order_date = (order or {}).get("order_date")
    order_deadline = (order or {}).get("deadline")

    # stages: SELECT stage_name, sequence, status ... ORDER BY sequence
    stage_rows = [s for s in stages.find(production_id=pid) if s.get("sequence") is not None]
    stage_rows.sort(key=lambda s: _num(s["sequence"]))
    stage_data = [
        {"stage_name": s["stage_name"], "sequence": s["sequence"], "status": s["status"]}
        for s in stage_rows
    ]

    # latest update: ... ORDER BY update_id DESC LIMIT 1
    update_rows = updates.find(production_id=pid)
    latest_data = None
    if update_rows:
        update_rows.sort(key=lambda u: _num(u.get("update_id")), reverse=True)
        latest = update_rows[0]
        latest_data = {
            "notes": latest.get("notes"),
            "progress": latest.get("progress"),
            "timestamp": latest.get("timestamp"),
        }

    # media: ... WHERE visibility = 'CUSTOMER' ORDER BY media_id DESC
    media_rows = list(media.find(production_id=pid, visibility="CUSTOMER"))
    media_rows.sort(key=lambda m: _num(m.get("media_id")), reverse=True)
    media_data = [
        {"file_url": m["file_url"], "file_type": m["file_type"]}
        for m in media_rows
    ]

    return {
        "production_code": prod["production_code"],
        "product_name": product_name,
        "variant_name": variant_name,
        "quantity": prod["quantity"],
        "order_date": order_date,
        "order_deadline": order_deadline,
        "deadline": prod["deadline"],
        "current_stage": prod["current_stage"],
        "overall_progress": prod["overall_progress"],
        "status": prod["status"],
        "notes": prod["notes"],
        "stages": stage_data,
        "latest_update": latest_data,
        "media": media_data,
    }


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------
@track_bp.route("", methods=["GET", "POST"])
def track():
    limiter = current_app.extensions["rate_limiter"]
    ip = _client_ip()
    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        allowed, reason = limiter.allowed(ip)
        if not allowed:
            log.warning("rate-limit block ip=%s reason=%s", ip, reason)
            return render_template("public_track.html", data=None,
                                   message=RATE_LIMIT_MSG, alert_type="danger",
                                   code=code), 429
        limiter.record_lookup(ip)
        if not code:
            return render_template("public_track.html", data=None,
                                   message="Enter a production code to track.",
                                   alert_type="danger", code=code)
        view = _lookup_customer_view(None, code)
        if view is None:
            limiter.record_failure(ip)
            return render_template("public_track.html", data=None,
                                   message=NOT_FOUND_MSG, alert_type="danger",
                                   code=code)
        limiter.record_success(ip)
        return render_template("public_track.html", data=view,
                               message=None, alert_type=None, code=code)
    return render_template("public_track.html", data=None,
                           message=None, alert_type=None, code="")


@track_bp.route("/media/<path:code>/<path:filename>")
def public_media(code, filename):
    """Serve ONLY CUSTOMER-visibility media for a validated production + media row.

    No DB primary key appears in the URL — the route re-checks that the media row
    belongs to ``code`` and has visibility 'CUSTOMER'; otherwise 404. This keeps
    INTERNAL media un-renderable and un-servable on any public surface.
    """
    po, _orders, _items, _products, _variants, _stages, _updates, media = \
        _lookup_track_rels()
    prod = po.find_one(production_code=code)
    if prod is None:
        abort(404)
    m = media.find_one(production_id=prod["production_id"],
                       file_url=filename, visibility="CUSTOMER")
    if m is None:
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename)