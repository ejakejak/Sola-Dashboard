"""Simplified auth — SQLite direct (invoice-only app)."""
from datetime import datetime
from functools import wraps
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
import sqlite3

auth_bp = Blueprint("auth", __name__)
SESSION_USER_KEY = "sola_user_id"

def _db():
    conn = sqlite3.connect(current_app.config.get("DATABASE_PATH", "instance/sola.db"))
    conn.row_factory = sqlite3.Row
    return conn

def load_current_user():
    uid = session.get(SESSION_USER_KEY)
    if not uid:
        return None
    conn = _db()
    user = conn.execute("SELECT u.*, r.role_code, r.role_name FROM users u LEFT JOIN roles r ON u.role_id = r.role_id WHERE u.user_id = ?", (uid,)).fetchone()
    conn.close()
    if user is None or user["status"] != "active":
        return None
    out = dict(user)
    out["user_id"] = user["user_id"]
    out["username"] = user["username"]
    out["full_name"] = user["full_name"]
    out["role_code"] = user["role_code"] if user["role_code"] else None
    out["role_name"] = user["role_name"] if user["role_name"] else None
    return out

def _user_has_perm(user, *perms):
    if user is None:
        return False
    role_id = user.get("role_id")
    if not role_id:
        return False
    conn = _db()
    result = conn.execute(
        "SELECT DISTINCT p.permission_code FROM role_permissions rp JOIN permissions p ON rp.permission_id = p.permission_id WHERE rp.role_id = ? AND p.permission_code IN (?)",
        (role_id, ",".join(perms)),
    ).fetchall()
    # SQLite parameter binding for IN requires splitting
    if perms:
        placeholders = ",".join(["?"] * len(perms))
        result = conn.execute(
            f"SELECT DISTINCT p.permission_code FROM role_permissions rp JOIN permissions p ON rp.permission_id = p.permission_id WHERE rp.role_id = ? AND p.permission_code IN ({placeholders})",
            (role_id, *perms)
        ).fetchall()
    conn.close()
    codes = [r["permission_code"] for r in result]
    return any(p in codes for p in perms)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("current_user") is not None:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        conn = _db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user is None or user["status"] != "active" or not check_password_hash(user["password_hash"] or "!", password):
            error = "Invalid username or password."
        else:
            session.clear()
            session[SESSION_USER_KEY] = user["user_id"]
            nxt = request.args.get("next")
            if nxt and nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("index"))
    return render_template("login.html", error=error)

@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

def assert_login():
    if g.get("current_user") is None:
        return redirect(url_for("auth.login", next=request.path))
    return None

def assert_permission(*perms):
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
    def deco(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            u = g.get("current_user")
            if u is None:
                return redirect(url_for("auth.login", next=request.path))
            if u.get("role_code") not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return deco

def require_permission(*perms):
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
