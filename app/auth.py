"""Authentication + authorization (backend-enforced, spec §24 / §25.7).

Session-cookie based (Flask session). Roles and permissions are resolved from the
DB on every request — hiding a button is nowhere near enough; every protected
route re-checks the role/permission server-side (abort 403 / redirect to login).

Sheet-backed: all reads/writes go through the SheetRelational engine
(app.sheetdb), with each table modeled as a tab in the live spreadsheet.
"""
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

# --- sheet column order (authoritative source: .planning/2026-09-23-sheetcutover/column_map.txt)
_USERS = ["user_id", "username", "full_name", "password_hash", "role_id",
          "phone", "email", "status"]
_ROLES = ["role_id", "role_code", "role_name"]
_ROLE_PERMISSIONS = ["role_permission_id", "role_id", "permission_id"]
_PERMISSIONS = ["permission_id", "permission_code"]
_AUDIT_LOGS = ["audit_id", "user_id", "timestamp", "action", "entity",
               "entity_id", "old_value", "new_value"]


def _storage():
    return current_app.extensions["storage"]


def _rel():
    """Build a SheetRelational engine over the app's sheet-backed storage."""
    from app.sheetdb import SheetRelational
    sheets = _storage()
    eng = SheetRelational(sheets)
    eng.define("users", _USERS)
    eng.define("roles", _ROLES)
    eng.define("role_permissions", _ROLE_PERMISSIONS)
    eng.define("permissions", _PERMISSIONS)
    eng.define("audit_logs", _AUDIT_LOGS)
    return eng


def _json(value):
    import json
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _audit(user_id, action, entity, entity_id=None, old_value=None,
           new_value=None) -> None:
    """Sheet-backed audit_logs writer (same signature as db.audit)."""
    rel = _rel()
    rel.table("audit_logs").insert({
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "old_value": _json(old_value),
        "new_value": _json(new_value),
    })


auth_bp = Blueprint("auth", __name__)

SESSION_USER_KEY = "sola_user_id"


def load_current_user():
    """Fetch the logged-in user (with role) for the current request; None if not authenticated."""
    uid = session.get(SESSION_USER_KEY)
    if not uid:
        return None
    rel = _rel()
    user = rel.table("users").find_one(user_id=uid)
    if user is None or user["status"] != "active":
        return None
    # LEFT JOIN roles r ON u.role_id = r.role_id  (in Python)
    role = None
    if user.get("role_id") is not None:
        role = rel.table("roles").find_one(role_id=user["role_id"])
    out = dict(user)
    out["role_code"] = role["role_code"] if role is not None else None
    out["role_name"] = role["role_name"] if role is not None else None
    return out


def _user_has_perm(user, *perms) -> bool:
    if user is None:
        return False
    role_id = user.get("role_id")
    if role_id is None:
        return False
    rel = _rel()
    # role_permissions rp JOIN permissions p ON p.permission_id = rp.permission_id
    rp = rel.table("role_permissions").find(role_id=role_id)
    if not rp:
        return False
    perms_by_id = {
        p["permission_id"]: p["permission_code"]
        for p in rel.table("permissions").read_all()
    }
    # ... WHERE rp.role_id = ? AND p.permission_code IN (...)
    for row in rp:
        code = perms_by_id.get(row["permission_id"])
        if code in perms:
            return True
    return False


# ---------------------------------------------------------------------------
# Runtime gates (usable both as decorators and inline inside routes)
# ---------------------------------------------------------------------------
def assert_login():
    """Must be authenticated, else redirect to login preserving the next URL."""
    if g.get("current_user") is None:
        return redirect(url_for("auth.login", next=request.path))
    return None


def assert_permission(*perms):
    """Must be authenticated AND hold >=1 of the named permissions, else 403."""
    if g.get("current_user") is None:
        abort(403)
    if not _user_has_perm(g.current_user, *perms):
        abort(403)
    return None


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        redirect_resp = assert_login()
        if redirect_resp is not None:
            return redirect_resp
        return f(*args, **kwargs)

    return wrapped


def require_role(*roles):
    """Restrict to one of the given role codes (e.g. require_role('ADMIN','MANAGEMENT'))."""

    def deco(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            u = g.get("current_user")
            if u is None:
                return redirect(url_for("auth.login", next=request.path))
            if u["role_code"] not in roles:
                abort(403)
            return f(*args, **kwargs)

        return wrapped

    return deco


def require_permission(*perms):
    """Restrict to a user holding >=1 of the given permission codes."""

    def deco(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            u = g.get("current_user")
            if u is None:
                return redirect(url_for("auth.login", next=request.path))
            if not _user_has_perm(u, *perms):
                abort(403)
            return f(*args, **kwargs)

        return wrapped

    return deco


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("current_user") is not None:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        rel = _rel()
        user = rel.table("users").find_one(username=username)
        if user is None or user["status"] != "active" or not check_password_hash(
            user["password_hash"] or "!", password
        ):
            error = "Invalid username or password."
        else:
            session.clear()
            session[SESSION_USER_KEY] = user["user_id"]
            _audit(
                user["user_id"],
                "LOGIN",
                "session",
                entity_id=user["user_id"],
                new_value={"username": user["username"]},
            )
            nxt = request.args.get("next")
            if nxt and nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("index"))
    return render_template("login.html", error=error)


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    uid = g.current_user["user_id"]
    try:
        _audit(uid, "LOGOUT", "session", entity_id=uid)
    except Exception:
        pass
    session.clear()
    return redirect(url_for("auth.login"))