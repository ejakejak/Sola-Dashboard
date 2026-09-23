"""Master Data module — generic CRUD for materials/products/processes/decorations/vendors/agents/customers.

One resource registry drives list / create / update pages (cards + grouped forms, per DESIGN_SPEC).
Authorization is enforced per route via masterdata.view (list) and <prefix>.create/.update (writes).
All writes are recorded in audit_logs (sheet engine, signalled via full cutover).
"""
from datetime import datetime, timezone
import json
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

from .auth import assert_permission, login_required, require_permission


def _storage():
    return current_app.extensions["storage"]


def _rel():
    from app.sheetdb import SheetRelational

    return SheetRelational(_storage())


# Exact per-table column orders from .planning/2026-09-23-sheetcutover/column_map.txt.
_TABLES = {
    "agents": ["agent_id", "agent_code", "name", "phone", "campus", "faculty", "address", "status", "commission_scheme", "notes"],
    "audit_logs": ["audit_id", "user_id", "timestamp", "action", "entity", "entity_id", "old_value", "new_value"],
    "customers": ["customer_id", "customer_code", "name", "company_name", "pic_name", "phone", "email", "address", "npwp", "customer_type", "source", "notes", "status", "created_at"],
    "decorations": ["decoration_id", "decoration_code", "decoration_name", "category", "pricing_method", "default_cost", "status"],
    "materials": ["material_id", "material_code", "material_name", "category", "specification", "unit_id", "gramasi", "width", "supplier", "status"],
    "processes": ["process_id", "process_code", "process_name", "category", "unit_id", "default_cost", "estimated_duration", "status"],
    "product_categories": ["category_id", "category_name", "description"],
    "products": ["product_id", "product_code", "product_name", "category_id", "unit_id", "description", "status", "created_at", "updated_at"],
    "units": ["unit_id", "unit_code", "unit_name"],
    "vendors": ["vendor_id", "vendor_code", "vendor_name", "vendor_type", "phone", "address", "location", "specialization", "status", "notes"],
}


def _table(name):
    """Return the sheet relation for a table (defined on a fresh engine per call)."""
    cols = _TABLES[name]
    return _rel().define(name, cols, cols[0])


def audit(user_id, action, entity, entity_id=None, old_value=None, new_value=None) -> None:
    """Record a consequential action (spec §27) into the audit_logs sheet tab."""
    _table("audit_logs").insert(
        {
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "old_value": json.dumps(old_value, ensure_ascii=False, default=str) if old_value is not None else None,
            "new_value": json.dumps(new_value, ensure_ascii=False, default=str) if new_value is not None else None,
        }
    )


master_bp = Blueprint("master", __name__, url_prefix="/master-data")

STATUS_OPTIONS = ["active", "inactive"]
CUSTOMER_TYPE_OPTIONS = ["retail", "corporate", "agent-led"]
VENDOR_TYPE_OPTIONS = ["makhloon/penjahit", "sablon", "bahan", "other"]


def _status_field():
    return {"name": "status", "label": "Status", "type": "select", "options": STATUS_OPTIONS}


# ---------------------------------------------------------------------------
# Resource registry
# ---------------------------------------------------------------------------
RESOURCES = [
    {
        "key": "materials",
        "title": "Materials",
        "table": "materials",
        "perm_prefix": "material",
        "entity": "material",
        "id_col": "material_id",
        "search_cols": ["material_code", "material_name", "category", "specification", "supplier"],
        "card_fields": [
            {"name": "material_code", "label": "Code"},
            {"name": "material_name", "label": "Name"},
            {"name": "category", "label": "Category"},
            {"name": "gramasi", "label": "Gramasi"},
            {"name": "width", "label": "Width"},
            {"name": "supplier", "label": "Supplier"},
            {"name": "status", "label": "Status"},
        ],
        "form_fields": [
            {"name": "material_code", "label": "Material Code", "required": True},
            {"name": "material_name", "label": "Material Name", "required": True},
            {"name": "category", "label": "Category"},
            {"name": "specification", "label": "Specification"},
            {"name": "unit_id", "label": "Unit", "type": "select", "lookup": "units"},
            {"name": "gramasi", "label": "Gramasi"},
            {"name": "width", "label": "Width"},
            {"name": "supplier", "label": "Supplier"},
            _status_field(),
        ],
    },
    {
        "key": "products",
        "title": "Products",
        "table": "products",
        "perm_prefix": "product",
        "entity": "product",
        "id_col": "product_id",
        "search_cols": ["product_code", "product_name", "description"],
        "card_fields": [
            {"name": "product_code", "label": "Code"},
            {"name": "product_name", "label": "Name"},
            {"name": "category_id", "label": "Category", "lookup": "categories"},
            {"name": "unit_id", "label": "Unit", "lookup": "units"},
            {"name": "status", "label": "Status"},
        ],
        "form_fields": [
            {"name": "product_code", "label": "Product Code", "required": True},
            {"name": "product_name", "label": "Product Name", "required": True},
            {"name": "category_id", "label": "Category", "type": "select", "lookup": "categories"},
            {"name": "unit_id", "label": "Unit", "type": "select", "lookup": "units"},
            {"name": "description", "label": "Description", "type": "textarea"},
            _status_field(),
        ],
    },
    {
        "key": "processes",
        "title": "Processes",
        "table": "processes",
        "perm_prefix": "process",
        "entity": "process",
        "id_col": "process_id",
        "search_cols": ["process_code", "process_name", "category", "specification"],
        "card_fields": [
            {"name": "process_code", "label": "Code"},
            {"name": "process_name", "label": "Name"},
            {"name": "category", "label": "Category"},
            {"name": "default_cost", "label": "Default Cost", "type": "currency"},
            {"name": "estimated_duration", "label": "Est. Duration"},
            {"name": "status", "label": "Status"},
        ],
        "form_fields": [
            {"name": "process_code", "label": "Process Code", "required": True},
            {"name": "process_name", "label": "Process Name", "required": True},
            {"name": "category", "label": "Category"},
            {"name": "unit_id", "label": "Unit", "type": "select", "lookup": "units"},
            {"name": "default_cost", "label": "Default Cost (IDR)", "type": "number"},
            {"name": "estimated_duration", "label": "Est. Duration"},
            _status_field(),
        ],
    },
    {
        "key": "decorations",
        "title": "Decorations",
        "table": "decorations",
        "perm_prefix": "decoration",
        "entity": "decoration",
        "id_col": "decoration_id",
        "search_cols": ["decoration_code", "decoration_name", "category", "pricing_method"],
        "card_fields": [
            {"name": "decoration_code", "label": "Code"},
            {"name": "decoration_name", "label": "Name"},
            {"name": "category", "label": "Category"},
            {"name": "pricing_method", "label": "Pricing Method"},
            {"name": "default_cost", "label": "Default Cost", "type": "currency"},
            {"name": "status", "label": "Status"},
        ],
        "form_fields": [
            {"name": "decoration_code", "label": "Decoration Code", "required": True},
            {"name": "decoration_name", "label": "Decoration Name", "required": True},
            {"name": "category", "label": "Category"},
            {"name": "pricing_method", "label": "Pricing Method"},
            {"name": "default_cost", "label": "Default Cost (IDR)", "type": "number"},
            _status_field(),
        ],
    },
    {
        "key": "vendors",
        "title": "Vendors",
        "table": "vendors",
        "perm_prefix": "vendor",
        "entity": "vendor",
        "id_col": "vendor_id",
        "search_cols": ["vendor_code", "vendor_name", "vendor_type", "specialization", "location"],
        "card_fields": [
            {"name": "vendor_code", "label": "Code"},
            {"name": "vendor_name", "label": "Name"},
            {"name": "vendor_type", "label": "Type"},
            {"name": "phone", "label": "Phone"},
            {"name": "location", "label": "Location"},
            {"name": "status", "label": "Status"},
        ],
        "form_fields": [
            {"name": "vendor_code", "label": "Vendor Code", "required": True},
            {"name": "vendor_name", "label": "Vendor Name", "required": True},
            {"name": "vendor_type", "label": "Vendor Type", "type": "select", "options": VENDOR_TYPE_OPTIONS},
            {"name": "phone", "label": "Phone"},
            {"name": "address", "label": "Address / Maps URL"},
            {"name": "location", "label": "Location"},
            {"name": "specialization", "label": "Specialization"},
            _status_field(),
            {"name": "notes", "label": "Notes", "type": "textarea"},
        ],
    },
    {
        "key": "agents",
        "title": "Agents",
        "table": "agents",
        "perm_prefix": "agent",
        "entity": "agent",
        "id_col": "agent_id",
        "search_cols": ["agent_code", "name", "campus", "faculty", "phone"],
        "card_fields": [
            {"name": "agent_code", "label": "Code"},
            {"name": "name", "label": "Name"},
            {"name": "phone", "label": "Phone"},
            {"name": "campus", "label": "Campus"},
            {"name": "faculty", "label": "Faculty"},
            {"name": "status", "label": "Status"},
        ],
        "form_fields": [
            {"name": "agent_code", "label": "Agent Code", "required": True},
            {"name": "name", "label": "Name", "required": True},
            {"name": "phone", "label": "Phone"},
            {"name": "campus", "label": "Campus"},
            {"name": "faculty", "label": "Faculty"},
            {"name": "address", "label": "Address"},
            {"name": "commission_scheme", "label": "Commission Scheme"},
            _status_field(),
            {"name": "notes", "label": "Notes", "type": "textarea"},
        ],
    },
    {
        "key": "customers",
        "title": "Customers",
        "table": "customers",
        "perm_prefix": "customer",
        "entity": "customer",
        "id_col": "customer_id",
        "search_cols": [
            "customer_code", "name", "company_name", "pic_name", "phone", "email", "customer_type",
        ],
        "card_fields": [
            {"name": "customer_code", "label": "Code"},
            {"name": "name", "label": "Name"},
            {"name": "company_name", "label": "Company"},
            {"name": "pic_name", "label": "PIC"},
            {"name": "phone", "label": "Phone"},
            {"name": "customer_type", "label": "Type"},
            {"name": "status", "label": "Status"},
        ],
        "form_fields": [
            {"name": "customer_code", "label": "Customer Code", "required": True},
            {"name": "name", "label": "Customer Name", "required": True},
            {"name": "company_name", "label": "Company Name"},
            {"name": "pic_name", "label": "PIC Name"},
            {"name": "phone", "label": "Phone"},
            {"name": "email", "label": "Email"},
            {"name": "address", "label": "Address", "type": "textarea"},
            # NPWP intentionally NOT shown/editable (owner decision 2026-09-22); column left unused in UI.
            {"name": "customer_type", "label": "Type", "type": "select", "options": CUSTOMER_TYPE_OPTIONS},
            {"name": "source", "label": "Source"},
            {"name": "notes", "label": "Notes", "type": "textarea"},
            _status_field(),
        ],
    },
]

_RESOURCE_BY_KEY = {r["key"]: r for r in RESOURCES}


def _get_resource(key):
    res = _RESOURCE_BY_KEY.get(key)
    if res is None:
        abort(404)
    return res


def _lookups_for(res):
    """FK lookup tables (units, product_categories) loaded once per request for select/render."""
    lookups = {"units": {}, "categories": {}}
    for u in _table("units").read_all():
        lookups["units"][u["unit_id"]] = u["unit_code"]
    for c in sorted(
        _table("product_categories").read_all(),
        key=lambda r: str(r.get("category_name") or ""),
    ):
        lookups["categories"][c["category_id"]] = c["category_name"]
    return lookups


def _select_options_for(field, lookups):
    """Resolve a field's choices: fixed options list or a FK lookup table."""
    if field.get("options"):
        return field["options"]
    if field.get("lookup"):
        return lookups.get(field["lookup"], {})
    return None


def _display(field, row, lookups):
    """Human-friendly display value for a card field."""
    value = row[field["name"]]
    if value is None or value == "":
        return "—"
    if field.get("lookup"):
        mapped = lookups.get(field["lookup"], {}).get(value)
        return mapped if mapped is not None else value
    if field.get("type") == "currency":
        try:
            return f"Rp {int(round(float(value))):,}".replace(",", ".")
        except (ValueError, TypeError):
            return value
    return value


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
@master_bp.route("/")
@login_required
@require_permission("masterdata.view")
def index():
    can_create = {
        r["key"]: g.current_user
        and _has(("masterdata.view", f"{r['perm_prefix']}.create"))
        for r in RESOURCES
    }
    return render_template("master_index.html", resources=RESOURCES, can_create=can_create)


def _has(perms):
    from .auth import _user_has_perm

    return _user_has_perm(g.current_user, *perms)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@master_bp.route("/<key>")
@login_required
@require_permission("masterdata.view")
def list_resource(key):
    res = _get_resource(key)
    q = request.args.get("q", "").strip()
    order_col = res["card_fields"][1]["name"]
    rows = _table(res["table"]).read_all()
    if q:
        lq = q.lower()
        rows = [
            row
            for row in rows
            if any(lq in str(row.get(c) or "").lower() for c in res["search_cols"])
        ]
    rows = sorted(rows, key=lambda r: str(r.get(order_col) or ""))
    lookups = _lookups_for(res)
    cards = [
        {
            "id": row[res["id_col"]],
            "title": _display({"name": res["card_fields"][1]["name"]}, row, lookups),
            "fields": [{"label": f["label"], "value": _display(f, row, lookups)} for f in res["card_fields"]],
        }
        for row in rows
    ]
    can_create = _has((f"{res['perm_prefix']}.create",))
    can_edit = _has((f"{res['perm_prefix']}.update",))
    return render_template(
        "master_list.html",
        res=res,
        cards=cards,
        q=q,
        can_create=can_create,
        can_edit=can_edit,
        count=len(cards),
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@master_bp.route("/<key>/new", methods=["GET", "POST"])
@login_required
def create(key):
    res = _get_resource(key)
    assert_permission(f"{res['perm_prefix']}.create")
    lookups = _lookups_for(res)
    if request.method == "POST":
        data, errors = _collect_form(res)
        if not errors:
            rec = _table(res["table"]).insert(data)
            rid = rec[res["id_col"]]
            audit(
                g.current_user["user_id"],
                "CREATE",
                res["entity"],
                entity_id=rid,
                new_value=data,
            )
            flash(f"{res['title'].rstrip('s')} created.", "success")
            return redirect(url_for("master.list_resource", key=key))
        for e in errors:
            flash(e, "danger")
    form_values = dict(request.form) if request.method == "POST" else {}
    return render_template(
        "master_form.html",
        res=res,
        form_values=form_values,
        lookups=lookups,
        mode="new",
    )


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
@master_bp.route("/<key>/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def update(key, rid):
    res = _get_resource(key)
    assert_permission(f"{res['perm_prefix']}.update")
    rel = _table(res["table"])
    row = rel.get(rid)
    if row is None:
        abort(404)
    lookups = _lookups_for(res)
    if request.method == "POST":
        data, errors = _collect_form(res)
        if not errors:
            old = {c: row[c] for c in data}
            rel.update(rid, data)
            audit(
                g.current_user["user_id"],
                "UPDATE",
                res["entity"],
                entity_id=rid,
                old_value=old,
                new_value=data,
            )
            flash(f"{res['title'].rstrip('s')} updated.", "success")
            return redirect(url_for("master.list_resource", key=key))
        for e in errors:
            flash(e, "danger")
    form_values = {f["name"]: row[f["name"]] for f in res["form_fields"]}
    return render_template(
        "master_form.html",
        res=res,
        form_values=form_values,
        lookups=lookups,
        mode="edit",
        rid=rid,
    )


# ---------------------------------------------------------------------------
# Form collection / validation
# ---------------------------------------------------------------------------
def _collect_form(res):
    """Pull form data for the resource's declared fields, casting + validating."""
    data = {}
    errors = []
    for f in res["form_fields"]:
        name = f["name"]
        raw = request.form.get(name, "").strip()
        if f.get("required") and not raw:
            errors.append(f"{f['label']} is required.")
            continue
        if f.get("type") == "select":
            # empty select -> None (keeps NULL)
            data[name] = raw if raw else None
        elif f.get("type") == "number":
            if not raw:
                data[name] = None
            else:
                try:
                    data[name] = float(raw)
                except ValueError:
                    errors.append(f"{f['label']} must be a number.")
                    continue
        elif f.get("lookup"):
            data[name] = int(raw) if raw else None
        else:
            data[name] = raw or None
    return data, errors