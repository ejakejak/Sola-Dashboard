"""SOLA Phase 5 — configurable Workflow Templates + Production (spec §13-17).

Built ON the Phase-2/3-4 app: reuses require_permission() and audit() and the
existing schema tables (production_workflow_templates,
production_workflow_template_steps, production_orders, production_stages,
production_updates, production_media, quality_checks).

FULL CUTOVER: SQLite is gone; every table is a TAB in the live Google Sheet,
accessed through the SheetRelational engine (app.sheetdb). Sheets autosave, so
there is no explicit commit. Every SQL read/insert/update/delete has been ported
to the tab-CRUD seam (find/find_one/get/insert/update/delete).
"""
import json as _json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from .auth import require_permission
from .config import BASE_DIR
from .mediastore import get_media_store


def _storage():
    return current_app.extensions["storage"]


def _rel():
    from app.sheetdb import SheetRelational

    return SheetRelational(_storage())


# Exact per-table column orders from .planning/2026-09-23-sheetcutover/column_map.txt.
_TABLES = {
    "orders": ["order_id", "order_number", "customer_id", "quotation_id", "order_date",
               "deadline", "status", "priority", "subtotal", "discount", "tax",
               "grand_total", "notes", "created_at"],
    "order_items": ["order_item_id", "order_id", "product_id", "variant_id", "material_id",
                    "color_id", "decoration_id", "decoration_position", "decoration_size",
                    "size_id", "quantity", "unit_id", "unit_price", "subtotal", "notes"],
    "product_categories": ["category_id", "category_name", "description"],
    "products": ["product_id", "product_code", "product_name", "category_id", "unit_id",
                 "description", "status", "created_at", "updated_at"],
    "customers": ["customer_id", "customer_code", "name", "company_name", "pic_name",
                  "phone", "email", "address", "npwp", "customer_type", "source",
                  "notes", "status", "created_at"],
    "vendors": ["vendor_id", "vendor_code", "vendor_name", "vendor_type", "phone", "address",
                "location", "specialization", "status", "notes"],
    "users": ["user_id", "username", "full_name", "password_hash", "role_id", "phone",
              "email", "status"],
    "production_orders": ["production_id", "production_code", "order_id", "order_item_id",
                          "product_id", "variant_id", "quantity", "deadline",
                          "current_stage", "overall_progress", "status",
                          "workflow_template_id", "notes", "created_at", "updated_at"],
    "production_stages": ["production_stage_id", "production_id", "stage_id", "stage_name",
                          "sequence", "status", "assigned_user", "assigned_vendor",
                          "start_at", "completed_at", "target_quantity",
                          "completed_quantity", "rejected_quantity", "notes"],
    "production_updates": ["update_id", "production_id", "production_stage_id", "user_id",
                           "timestamp", "progress", "quantity_completed",
                           "quantity_rejected", "notes"],
    "production_workflow_templates": ["workflow_template_id", "template_name",
                                      "product_category_id", "is_default", "status"],
    "production_workflow_template_steps": ["workflow_template_step_id", "workflow_template_id",
                                           "sequence", "stage_name", "is_completion"],
    "production_media": ["media_id", "update_id", "production_id", "file_url", "file_type",
                         "visibility", "uploaded_by", "uploaded_at"],
    "quality_checks": ["qc_id", "production_id", "stage_id", "inspector", "inspected_at",
                       "passed_quantity", "rejected_quantity", "defect_type", "notes",
                       "status", "evidence"],
    "audit_logs": ["audit_id", "user_id", "timestamp", "action", "entity", "entity_id",
                   "old_value", "new_value"],
}


def _table(name):
    """Return the sheet relation for a table (defined on a fresh engine per call)."""
    cols = _TABLES[name]
    return _rel().define(name, cols, cols[0])


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _local_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def _to_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _is_true(v):
    return str(v).strip().lower() in ("1", "true", "yes")


PROD_BP = Blueprint("production", __name__, url_prefix="/production")

STAGE_STATUSES = ["pending", "in_progress", "completed", "blocked", "cancelled"]
PROD_STATUSES = ["in_progress", "completed", "blocked", "cancelled"]
MEDIA_VISIBILITY = ["INTERNAL", "CUSTOMER"]  # default INTERNAL (DB default)
QC_STATUSES = ["passed", "failed", "rework"]

# Phase 8 — Production Kanban board (DESIGN_SPEC §3.2). Fixed 9 columns in order.
BOARD_COLUMNS = [
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

# current_stage -> canonical column (case-insensitive). Covers the garment-default
# template verbatim plus the short "MATERIAL" alias from the Topi template.
STAGE_TO_COLUMN = {s.upper(): s for s in BOARD_COLUMNS}
STAGE_TO_COLUMN["MATERIAL"] = "MATERIAL PREPARATION"
STAGE_TO_COLUMN["COMPLETED"] = "COMPLETED"

# token per column for the header count badge / accents (DESIGN_SPEC §3.2).
COLUMN_TOKEN = {
    "ORDER": "neutral",
    "MATERIAL PREPARATION": "info",
    "CUTTING": "info",
    "SEWING": "warning",
    "PRINTING": "warning",
    "FINISHING": "warning",
    "QC": "info",
    "PACKING": "warning",
    "COMPLETED": "success",
}


def _board_column(stage, status):
    """Bucket a production row into a BOARD_COLUMNS column.

    Fallback per PHASE8_BRIEF §2: exact/aliased current_stage wins; else the row
    status decides — completed -> COMPLETED, cancelled -> None (excluded from the
    board); an unmapped in-progress stage has no column and lands in ``other``.
    """
    stg = (stage or "").strip().upper()
    if stg in STAGE_TO_COLUMN:
        return STAGE_TO_COLUMN[stg]
    if status == "completed":
        return "COMPLETED"
    if status == "cancelled":
        return None
    return "__other__"


UPLOAD_DIR = BASE_DIR / "app" / "static" / "uploads"  # compatibility alias


def _money(v):
    try:
        return f"{int(round(float(v or 0))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def _today_ymd():
    return date.today().strftime("%y%m%d")


def _next_production_code():
    """PRD-<YYMMDD>-<NNN> sequential per day."""
    prefix = f"PRD-{_today_ymd()}-"
    highest = 0
    for r in _table("production_orders").read_all():
        pc = r.get("production_code") or ""
        if pc.startswith(prefix):
            tail = pc.rsplit("-", 1)[-1]
            if tail.isdigit():
                highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:03d}"


def _has(perm):
    from .auth import _user_has_perm

    return _user_has_perm(g.current_user, perm)


def _default_template():
    """The garment 'default' template (catch-all is_default) or the first active one."""
    tpl = _table("production_workflow_templates")
    active = [r for r in tpl.read_all() if (r.get("status") or "") == "active"]
    defaults = [r for r in active if _is_true(r.get("is_default"))]
    pool = sorted(defaults or active, key=lambda r: _to_num(r.get("workflow_template_id")))
    return pool[0] if pool else None


def _template_steps(template_id):
    rows = _table("production_workflow_template_steps").find(
        workflow_template_id=template_id)
    rows.sort(key=lambda r: _to_num(r.get("sequence")))
    return rows


def _recompute_production(pid):
    """Recompute overall_progress + current_stage + top-level status from stages."""
    prod = _table("production_orders").get(pid)
    if prod is None:
        return
    stages = _table("production_stages").find(production_id=pid)
    stages.sort(key=lambda r: _to_num(r.get("sequence")))
    total = len(stages)
    completed = sum(1 for s in stages if s["status"] == "completed")
    cancelled = sum(1 for s in stages if s["status"] == "cancelled")
    blocked = sum(1 for s in stages if s["status"] == "blocked")
    progress = round((completed / total) * 100, 1) if total else 0.0

    current_stage = prod["current_stage"]
    for s in stages:
        if s["status"] not in ("completed", "cancelled"):
            current_stage = s["stage_name"]
            break
    else:
        current_stage = stages[-1]["stage_name"] if stages else current_stage

    if cancelled == total and total:
        status = "cancelled"
    elif blocked > 0:
        status = "blocked"
    elif completed == total and total:
        status = "completed"
    else:
        status = "in_progress"

    _table("production_orders").update(
        pid,
        {
            "overall_progress": progress,
            "current_stage": current_stage,
            "status": status,
            "updated_at": _now(),
        },
    )


def _stage_progress_bar(stage):
    """Derive a single stage's completion % from completed_quantity/target_quantity."""
    if stage["completed_quantity"] and stage["target_quantity"]:
        try:
            return round(
                float(stage["completed_quantity"]) / float(stage["target_quantity"]) * 100, 0
            )
        except (ZeroDivisionError, ValueError, TypeError):
            return 0
    if stage["status"] == "completed":
        return 100
    return 0


# ---------------------------------------------------------------------------
# WORKFLOW TEMPLATES
# ---------------------------------------------------------------------------
@PROD_BP.route("/templates")
@require_permission("workflow.manage")
def template_list():
    tpl = _table("production_workflow_templates")
    cats = {str(c["category_id"]): c["category_name"]
            for c in _table("product_categories").read_all()}
    steps = _table("production_workflow_template_steps")
    rows = []
    for t in tpl.read_all():
        row = dict(t)
        cid = t.get("product_category_id")
        row["category_name"] = cats.get(str(cid)) if cid is not None else None
        row["step_count"] = len(steps.find(workflow_template_id=t["workflow_template_id"]))
        rows.append(row)
    # ORDER BY t.is_default DESC, t.workflow_template_id
    rows.sort(key=lambda r: (not _is_true(r.get("is_default")),
                             _to_num(r.get("workflow_template_id"))))
    return render_template(
        "workflow_template_list.html", templates=rows, can_manage=_has("workflow.manage")
    )


@PROD_BP.route("/templates/new", methods=["GET", "POST"])
@require_permission("workflow.manage")
def template_new():
    categories = sorted(
        _table("product_categories").read_all(),
        key=lambda r: str(r.get("category_name") or ""),
    )
    if request.method == "POST":
        name = (request.form.get("template_name") or "").strip()
        category_id = request.form.get("product_category_id") or None
        is_default = 1 if request.form.get("is_default") else 0
        if not name:
            flash("Template name is required.", "danger")
        else:
            category_id = int(category_id) if category_id else None
            rec = _table("production_workflow_templates").insert({
                "template_name": name,
                "product_category_id": category_id,
                "is_default": is_default,
                "status": "active",
            })
            tid = rec["workflow_template_id"]
            _save_steps(tid, request)
            audit(g.current_user["user_id"], "CREATE", "workflow_template",
                  entity_id=tid, new_value={"template_name": name})
            flash(f"Workflow template '{name}' created.", "success")
            return redirect(url_for("production.template_edit", tid=tid))
    return render_template("workflow_template_form.html", category_options=categories,
                           t=None, steps=[], form=dict(request.form))


@PROD_BP.route("/templates/<int:tid>/edit", methods=["GET", "POST"])
@require_permission("workflow.manage")
def template_edit(tid):
    t = _table("production_workflow_templates").get(tid)
    if t is None:
        abort(404)
    categories = sorted(
        _table("product_categories").read_all(),
        key=lambda r: str(r.get("category_name") or ""),
    )
    steps = _template_steps(tid)
    if request.method == "POST":
        name = (request.form.get("template_name") or "").strip()
        category_id = request.form.get("product_category_id") or None
        is_default = 1 if request.form.get("is_default") else 0
        if not name:
            flash("Template name is required.", "danger")
        else:
            category_id = int(category_id) if category_id else None
            old = {"template_name": t["template_name"], "is_default": t["is_default"]}
            _table("production_workflow_templates").update(
                tid,
                {"template_name": name, "product_category_id": category_id,
                 "is_default": is_default},
            )
            # full step-set replace (sequence deterministic from the form)
            for s in _table("production_workflow_template_steps").find(
                    workflow_template_id=tid):
                _table("production_workflow_template_steps").delete(
                    s["workflow_template_step_id"])
            _save_steps(tid, request)
            audit(g.current_user["user_id"], "UPDATE", "workflow_template", entity_id=tid,
                  old_value=old,
                  new_value={"template_name": name, "is_default": is_default})
            flash(f"Workflow template '{name}' updated.", "success")
            return redirect(url_for("production.template_list"))
    return render_template("workflow_template_form.html", category_options=categories,
                           t=t, steps=steps, form=dict(request.form))


def _save_steps(tid, req):
    names = req.form.getlist("step_name[]")
    seq = 1
    last = None
    for raw in names:
        stage_name = (raw or "").strip()
        if not stage_name:
            continue
        last = stage_name
        _table("production_workflow_template_steps").insert({
            "workflow_template_id": tid,
            "sequence": seq,
            "stage_name": stage_name,
            "is_completion": 0,
        })
        seq += 1
    # mark the final step as the completion gate
    if last is not None:
        for s in _table("production_workflow_template_steps").find(
                workflow_template_id=tid, stage_name=last):
            _table("production_workflow_template_steps").update(
                s["workflow_template_step_id"], {"is_completion": 1})


# ---------------------------------------------------------------------------
# PRODUCTION LIST / BOARD
# ---------------------------------------------------------------------------
@PROD_BP.route("/")
@require_permission("production.view")
def list_productions():
    q = request.args.get("q", "").strip()
    orders = {str(o["order_id"]): o for o in _table("orders").read_all()}
    custs = {str(c["customer_id"]): c for c in _table("customers").read_all()}
    rows = []
    for p in _table("production_orders").read_all():
        o = orders.get(str(p.get("order_id"))) if p.get("order_id") is not None else None
        c = custs.get(str(o["customer_id"])) if o and o.get("customer_id") is not None else None
        row = dict(p)
        row["order_number"] = o["order_number"] if o else None
        row["customer_name"] = c["name"] if c else None
        row["order_deadline"] = o["deadline"] if o else None
        if q:
            blob = (" ".join([
                str(row.get("production_code") or ""),
                str(row["order_number"] or ""),
                str(row["customer_name"] or ""),
            ])).lower()
            if q.lower() not in blob:
                continue
        rows.append(row)
    rows.sort(key=lambda r: _to_num(r.get("production_id")), reverse=True)
    return render_template("production_list.html", rows=rows, q=q,
                           can_manage=_has("production.manage"))


def _days_left(deadline):
    if not deadline:
        return None
    try:
        d = date.fromisoformat(str(deadline)[:10])
    except ValueError:
        return None
    return (d - date.today()).days


@PROD_BP.route("/board")
@require_permission("production.view")
def board():
    orders = {str(o["order_id"]): o for o in _table("orders").read_all()}
    custs = {str(c["customer_id"]): c for c in _table("customers").read_all()}
    prods_by_id = {str(p.get("product_id")): p for p in _table("products").read_all()}
    users = {str(u["user_id"]): u for u in _table("users").read_all()}

    # pic_name: username of the lowest-sequence in_progress/blocked stage
    by_prod = {}
    for s in _table("production_stages").read_all():
        by_prod.setdefault(str(s.get("production_id")), []).append(s)
    pic = {}
    for pid, srows in by_prod.items():
        srows.sort(key=lambda s: _to_num(s.get("sequence")))
        for s in srows:
            if s.get("status") in ("in_progress", "blocked"):
                uid = s.get("assigned_user")
                u = users.get(str(uid)) if uid is not None else None
                pic[pid] = u["username"] if u else None
                break

    rows = []
    for p in _table("production_orders").read_all():
        o = orders.get(str(p.get("order_id"))) if p.get("order_id") is not None else None
        c = custs.get(str(o["customer_id"])) if o and o.get("customer_id") is not None else None
        pr = prods_by_id.get(str(p.get("product_id"))) if p.get("product_id") is not None else None
        r = dict(p)
        r["order_number"] = o["order_number"] if o else None
        r["priority"] = (o.get("priority") or "normal") if o else "normal"
        r["order_deadline"] = o["deadline"] if o else None
        r["customer_name"] = c["name"] if c else None
        r["product_name"] = pr["product_name"] if pr else None
        r["pic_name"] = pic.get(str(p.get("production_id")))
        rows.append(r)
    rows.sort(key=lambda r: _to_num(r.get("production_id")))

    buckets = {name: [] for name in BOARD_COLUMNS}
    other = []
    for r in rows:
        col = _board_column(r["current_stage"], r["status"])
        r["days_left"] = _days_left(r["deadline"] or r["order_deadline"])
        r["overdue"] = bool(r["days_left"] is not None and r["days_left"] < 0
                            and r["status"] not in ("completed", "cancelled"))
        if col in buckets:
            buckets[col].append(r)
        elif col == "__other__":
            other.append(r)
        # col is None (cancelled) -> omitted from the board
    all_prods = [r for col in BOARD_COLUMNS for r in buckets[col]] + other
    return render_template(
        "production_board.html",
        columns=buckets,
        other=other,
        all_prods=all_prods,
        board_columns=BOARD_COLUMNS,
        column_token=COLUMN_TOKEN,
        can_manage=_has("production.manage"),
        total=len(all_prods),
    )


# ---------------------------------------------------------------------------
# PRODUCTION FROM ORDER
# ---------------------------------------------------------------------------
@PROD_BP.route("/from-order")
@require_permission("production.manage")
def from_order_form():
    custs = {str(c["customer_id"]): c for c in _table("customers").read_all()}
    orders = []
    for o in _table("orders").read_all():
        if o.get("status") == "cancelled":
            continue
        row = dict(o)
        c = custs.get(str(o.get("customer_id"))) if o.get("customer_id") is not None else None
        row["customer_name"] = c["name"] if c else None
        orders.append(row)
    orders.sort(key=lambda r: _to_num(r.get("order_id")), reverse=True)
    templates = [r for r in _table("production_workflow_templates").read_all()
                 if (r.get("status") or "") == "active"]
    templates.sort(key=lambda r: (not _is_true(r.get("is_default")),
                                  _to_num(r.get("workflow_template_id"))))
    return render_template("production_from_order.html", orders=orders,
                           templates=templates)


@PROD_BP.route("/from-order/<int:oid>", methods=["POST"])
@require_permission("production.manage")
def create_from_order(oid):
    """Create ONE production per order-item from the chosen order + template."""
    o = _table("orders").get(oid)
    if o is None:
        abort(404)
    template_id = request.form.get("template_id") or None
    if template_id:
        template = _table("production_workflow_templates").get(int(template_id))
    else:
        template = _default_template()
    if template is None:
        flash("No workflow template available. Seed templates first.", "danger")
        return redirect(url_for("production.list_productions"))
    items = _table("order_items").find(order_id=oid)
    if not items:
        flash("Order has no line items; cannot create production.", "danger")
        return redirect(url_for("production.list_productions"))
    steps = _template_steps(template["workflow_template_id"])
    if not steps:
        flash("Template has no steps; cannot materialize production.", "danger")
        return redirect(url_for("production.list_productions"))

    created_codes = []
    for oi in items:
        code = _next_production_code()
        rec = _table("production_orders").insert({
            "production_code": code,
            "order_id": oid,
            "order_item_id": oi["order_item_id"],
            "product_id": oi["product_id"],
            "variant_id": oi["variant_id"],
            "quantity": oi["quantity"],
            "deadline": o["deadline"],
            "current_stage": steps[0]["stage_name"],
            "overall_progress": 0.0,
            "status": "in_progress",
            "workflow_template_id": template["workflow_template_id"],
            "notes": request.form.get("notes") or None,
            "created_at": _now(),
            "updated_at": _now(),
        })
        pid = rec["production_id"]
        for st in steps:
            _table("production_stages").insert({
                "production_id": pid,
                "stage_id": st["workflow_template_step_id"],
                "stage_name": st["stage_name"],
                "sequence": st["sequence"],
                "status": "pending",
                "target_quantity": oi["quantity"],
            })
        _recompute_production(pid)
        audit(g.current_user["user_id"], "CREATE", "production_order", entity_id=pid,
              new_value={"production_code": code, "order_id": oid,
                         "workflow_template_id": template["workflow_template_id"],
                         "quantity": oi["quantity"]})
        created_codes.append(code)
    flash(f"Production created from order {o['order_number']}: "
          f"{', '.join(created_codes)}.", "success")
    return redirect(url_for("production.list_productions"))


# ---------------------------------------------------------------------------
# PRODUCTION DETAIL
# ---------------------------------------------------------------------------
@PROD_BP.route("/<int:pid>")
@require_permission("production.view")
def detail(pid):
    p = _table("production_orders").get(pid)
    if p is None:
        abort(404)
    orders = {str(o["order_id"]): o for o in _table("orders").read_all()}
    custs = {str(c["customer_id"]): c for c in _table("customers").read_all()}
    users = {str(u["user_id"]): u for u in _table("users").read_all()}
    vendors = {str(v["vendor_id"]): v for v in _table("vendors").read_all()}
    o = orders.get(str(p.get("order_id"))) if p.get("order_id") is not None else None
    c = custs.get(str(o["customer_id"])) if o and o.get("customer_id") is not None else None
    prod = dict(p)
    prod["order_number"] = o["order_number"] if o else None
    prod["customer_name"] = c["name"] if c else None
    prod["company_name"] = c["company_name"] if c else None
    prod["order_deadline"] = o["deadline"] if o else None

    stages = []
    for s in _table("production_stages").find(production_id=pid):
        r = dict(s)
        au = s.get("assigned_user")
        r["pic_name"] = users[str(au)]["username"] if au is not None and str(au) in users else None
        av = s.get("assigned_vendor")
        r["vendor_name"] = vendors[str(av)]["vendor_name"] if av is not None and str(av) in vendors else None
        stages.append(r)
    stages.sort(key=lambda r: _to_num(r.get("sequence")))

    updates = []
    for u in _table("production_updates").find(production_id=pid):
        r = dict(u)
        uid = u.get("user_id")
        r["username"] = users[str(uid)]["username"] if uid is not None and str(uid) in users else None
        updates.append(r)
    updates.sort(key=lambda r: _to_num(r.get("update_id")), reverse=True)

    can_internal = _has("production.media.internal.read")
    # INTERNAL media gated here (backend) — served through a gated route too.
    media = [m for m in _table("production_media").find(production_id=pid)
             if m.get("visibility") == "CUSTOMER" or can_internal]
    media.sort(key=lambda r: _to_num(r.get("media_id")), reverse=True)

    qcs = []
    for q in _table("quality_checks").find(production_id=pid):
        r = dict(q)
        insp = q.get("inspector")
        r["inspector_name"] = users[str(insp)]["username"] if insp is not None and str(insp) in users else None
        qcs.append(r)
    qcs.sort(key=lambda r: _to_num(r.get("qc_id")), reverse=True)

    template = (_table("production_workflow_templates").get(p["workflow_template_id"])
                if p.get("workflow_template_id") is not None else None)
    return render_template(
        "production_detail.html",
        p=prod, stages=stages, updates=updates, media=media, qcs=qcs, template=template,
        stage_statuses=STAGE_STATUSES, media_visibility=MEDIA_VISIBILITY,
        can_manage=_has("production.manage"), can_update=_has("production.update"),
        can_internal=can_internal, can_qc=_has("qc.manage"),
        view_others=stages,  # placeholder for stage-progress mapping
        stage_progress={s["production_stage_id"]: _stage_progress_bar(s) for s in stages},
    )


@PROD_BP.route("/<int:pid>/stage/<int:sid>/advance", methods=["POST"])
@require_permission("production.manage")
def advance_stage(pid, sid):
    stages_rel = _table("production_stages")
    stage = stages_rel.find_one(production_stage_id=sid, production_id=pid)
    if stage is None:
        abort(404)
    status = request.form.get("status") or stage["status"]
    if status not in STAGE_STATUSES:
        flash("Invalid stage status.", "danger")
        return redirect(url_for("production.detail", pid=pid))

    now = _local_now()
    old = {"status": stage["status"]}

    # assignment + quantities always applied from form
    assigned_user = request.form.get("assigned_user") or stage["assigned_user"]
    assigned_vendor = request.form.get("assigned_vendor") or stage["assigned_vendor"]
    target = _f(request.form.get("target_quantity"), stage["target_quantity"])
    completed = _f(request.form.get("completed_quantity"), stage["completed_quantity"])
    rejected = _f(request.form.get("rejected_quantity"), stage["rejected_quantity"])
    notes = request.form.get("notes") or stage["notes"]

    changes = {"assigned_user": assigned_user, "assigned_vendor": assigned_vendor,
               "target_quantity": target, "completed_quantity": completed,
               "rejected_quantity": rejected, "notes": notes}

    if status == "in_progress" and stage["status"] in ("pending", "blocked"):
        changes["start_at"] = now
        # any earlier pending stage that was skipped is set to cancelled to keep
        # the timeline sequential unless it was already in_progress/completed.
        for s in stages_rel.find(production_id=pid):
            if (_to_num(s.get("sequence")) < _to_num(stage["sequence"])
                    and s.get("status") == "pending"):
                stages_rel.update(s["production_stage_id"], {"status": "cancelled"})
    elif status == "completed":
        if not stage.get("start_at"):
            changes["start_at"] = now  # COALESCE(start_at, ?)
        changes["completed_at"] = now
    elif status == "blocked":
        changes["completed_at"] = None
    changes["status"] = status

    stages_rel.update(sid, changes)
    _recompute_production(pid)
    audit(g.current_user["user_id"], "UPDATE", "production_stage", entity_id=sid,
          old_value=old, new_value={"status": status, "stage": stage["stage_name"]})
    flash(f"Stage '{stage['stage_name']}' → {status}.", "success")
    return redirect(url_for("production.detail", pid=pid))


def _f(val, default):
    if val is None or str(val).strip() == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# PRODUCTION UPDATES
# ---------------------------------------------------------------------------
@PROD_BP.route("/<int:pid>/updates", methods=["POST"])
@require_permission("production.manage")
def add_update(pid):
    p = _table("production_orders").get(pid)
    if p is None:
        abort(404)
    progress = request.form.get("progress") or None
    if progress is not None:
        progress = max(0.0, min(100.0, float(progress or 0)))
    qty_completed = request.form.get("quantity_completed") or None
    qty_rejected = request.form.get("quantity_rejected") or None
    notes = request.form.get("notes") or None
    stage_id = request.form.get("production_stage_id") or None
    rec = _table("production_updates").insert({
        "production_id": pid,
        "production_stage_id": int(stage_id) if stage_id else None,
        "user_id": g.current_user["user_id"],
        "timestamp": _now(),
        "progress": progress,
        "quantity_completed": qty_completed,
        "quantity_rejected": qty_rejected,
        "notes": notes,
    })
    audit(g.current_user["user_id"], "CREATE", "production_update",
          entity_id=rec["update_id"],
          new_value={"production_id": pid, "progress": progress, "qty_completed": qty_completed})
    flash("Production update recorded.", "success")
    return redirect(url_for("production.detail", pid=pid))


# ---------------------------------------------------------------------------
# PRODUCTION MEDIA (visibility-gated)
# ---------------------------------------------------------------------------
@PROD_BP.route("/<int:pid>/media", methods=["POST"])
@require_permission("production.manage")
def upload_media(pid):
    p = _table("production_orders").get(pid)
    if p is None:
        abort(404)
    file = request.files.get("file")
    visibility = request.form.get("visibility") or "INTERNAL"
    if visibility not in MEDIA_VISIBILITY:
        visibility = "INTERNAL"
    if file is None or not file.filename:
        flash("Choose a file to upload.", "danger")
        return redirect(url_for("production.detail", pid=pid))

    fn = secure_filename(file.filename) or "upload.bin"
    ext = Path(fn).suffix.lower()
    ftype = "video" if ext in (".mp4", ".mov", ".webm", ".avi", ".mkv") else "image"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stored = f"prod_{pid}_{stamp}_{fn}"
    try:
        get_media_store().save(file, stored)
    except OSError as e:
        flash(f"Upload failed: media storage is not writable on this host ({e}).", "danger")
        return redirect(url_for("production.detail", pid=pid))
    file_url = url_for("production.media_file", mid=0).rsplit("/0", 1)[0] + f"/{pid}_{stamp}_{fn}"
    rec = _table("production_media").insert({
        "production_id": pid,
        "file_url": stored,
        "file_type": ftype,
        "visibility": visibility,
        "uploaded_by": g.current_user["user_id"],
        "uploaded_at": _now(),
    })
    audit(g.current_user["user_id"], "CREATE", "production_media",
          entity_id=rec["media_id"],
          new_value={"production_id": pid, "visibility": visibility, "file_type": ftype})
    flash(f"Media uploaded ({visibility}).", "success")
    return redirect(url_for("production.detail", pid=pid))


@PROD_BP.route("/media/<int:mid>/file")
@require_permission("production.view")
def media_file(mid):
    m = _table("production_media").get(mid)
    if m is None:
        abort(404)
    # BACKEND gate: INTERNAL media requires the internal-read permission.
    if m["visibility"] == "INTERNAL" and not _has("production.media.internal.read"):
        abort(403)
    try:
        return get_media_store().send(m["file_url"])
    except (OSError, FileNotFoundError):
        abort(404)


# ---------------------------------------------------------------------------
# QC
# ---------------------------------------------------------------------------
@PROD_BP.route("/<int:pid>/qc", methods=["POST"])
@require_permission("qc.manage")
def record_qc(pid):
    p = _table("production_orders").get(pid)
    if p is None:
        abort(404)
    status = request.form.get("status") or "passed"
    if status not in QC_STATUSES:
        status = "passed"
    passed = request.form.get("passed_quantity") or None
    rejected = request.form.get("rejected_quantity") or None
    defect = request.form.get("defect_type") or None
    notes = request.form.get("notes") or None
    evidence = request.form.get("evidence") or None
    stage_id = request.form.get("stage_id") or None
    stage_id = int(stage_id) if stage_id else None

    rec = _table("quality_checks").insert({
        "production_id": pid,
        "stage_id": stage_id,
        "inspector": g.current_user["user_id"],
        "inspected_at": _now(),
        "passed_quantity": passed,
        "rejected_quantity": rejected,
        "defect_type": defect,
        "notes": notes,
        "status": status,
        "evidence": evidence,
    })

    # On rework, allow returning the production to a chosen earlier stage.
    if status == "rework" and request.form.get("return_stage_id"):
        return_sid = int(request.form["return_stage_id"])
        stages_rel = _table("production_stages")
        rs = stages_rel.find_one(production_stage_id=return_sid, production_id=pid)
        if rs is not None:
            rework = {"status": "in_progress", "completed_at": None}
            if not rs.get("start_at"):
                rework["start_at"] = _now()  # COALESCE(start_at, datetime('now'))
            stages_rel.update(return_sid, rework)
            ret_seq = _to_num(rs.get("sequence"))
            # any stages after the return point that were completed get re-opened
            for s in stages_rel.find(production_id=pid):
                if (_to_num(s.get("sequence")) > ret_seq
                        and s.get("status") == "completed"):
                    stages_rel.update(s["production_stage_id"],
                                      {"status": "pending", "completed_at": None})
    _recompute_production(pid)
    audit(g.current_user["user_id"], "CREATE", "quality_check", entity_id=rec["qc_id"],
          new_value={"production_id": pid, "status": status, "stage_id": stage_id,
                     "passed": passed, "rejected": rejected})
    flash(f"QC recorded as {status}.", "success")
    return redirect(url_for("production.detail", pid=pid))