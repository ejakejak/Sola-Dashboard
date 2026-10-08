"""SOLA dashboard — minimal Invoice-only Flask app (simplified 2026-10-08)."""
from flask import Flask, g, redirect, render_template, request, url_for

from .config import Config
from .db import close_db


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    cfg = Config()
    app.config["DATABASE_PATH"] = cfg.DATABASE_PATH
    app.config["SECRET_KEY"] = cfg.SECRET_KEY
    app.config["COMPANY"] = cfg.COMPANY
    app.config["INVOICE"] = cfg.INVOICE
    app.config["STORAGE"] = cfg.STORAGE
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)

    # SQLite storage only — no Google Sheets / complex engine
    from .storage import get_storage
    app.extensions["storage"] = get_storage(app.config)

    from .auth import auth_bp, load_current_user
    from .commercial import INVOICE_BP

    app.register_blueprint(auth_bp)
    app.register_blueprint(INVOICE_BP)

    @app.before_request
    def _load_user():
        g.current_user = load_current_user()

    @app.template_global()
    def can(permission: str) -> bool:
        user = getattr(g, "current_user", None)
        if user is None:
            return False
        from .auth import _user_has_perm
        return _user_has_perm(user, permission)

    @app.route("/", methods=["GET"])
    def index():
        if g.get("current_user") is None:
            return redirect(url_for("auth.login", next=request.path))
        return redirect(url_for("invoices.list"))

    @app.errorhandler(403)
    def forbidden(_err):
        return render_template("403.html"), 403

    from .errors import register_graceful_error_handlers
    register_graceful_error_handlers(app)

    @app.errorhandler(404)
    def not_found(_err):
        return render_template("404.html"), 404

    @app.context_processor
    def inject_globals():
        return {
            "COMPANY": app.config.get("COMPANY", {}),
            "current_username": (
                g.get("current_user")["username"] if g.get("current_user") else None
            ),
            "current_role_name": (
                g.get("current_user")["role_name"] if g.get("current_user") else None
            ),
            "current_role_code": (
                g.get("current_user")["role_code"] if g.get("current_user") else None
            ),
            "can": can,
        }

    return app
