"""SOLA dashboard — Flask application factory (Phase 2: backbone + auth + master data)."""
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
    # Phase 1 — storage backend selection. app.config keys let test_config
    # override STORAGE; the factory (app/storage.py) defaults to sqlite.
    app.config["STORAGE"] = cfg.STORAGE
    app.config["SPREADSHEET_ID"] = cfg.SPREADSHEET_ID
    app.config["GOOGLE_APPLICATION_CREDENTIALS"] = cfg.GOOGLE_APPLICATION_CREDENTIALS
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)

    # Phase 1 — pluggable storage backend exposed to extensions. Blueprints
    # still use get_db() directly this phase; later phases route through this.
    from .storage import get_storage

    app.extensions["storage"] = get_storage(app.config)

    from .auth import auth_bp, load_current_user
    from .masterdata import master_bp
    from .commercial import INVOICE_BP, ORDER_BP, QUOTE_BP
    from .production import PROD_BP
    from .inventory import INV_BP
    from .track import track_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(master_bp)
    app.register_blueprint(QUOTE_BP)
    app.register_blueprint(ORDER_BP)
    app.register_blueprint(INVOICE_BP)
    app.register_blueprint(PROD_BP)
    app.register_blueprint(INV_BP)

    # Phase 7 — public /track rate limiter (in-memory per-IP; constants editable
    # in app/config.py or overridden via env/test config).
    app.config.setdefault("RATE_LIMIT_WINDOW_SECS", cfg.RATE_LIMIT_WINDOW_SECS)
    app.config.setdefault("RATE_LIMIT_MAX_PER_WINDOW", cfg.RATE_LIMIT_MAX_PER_WINDOW)
    app.config.setdefault("RATE_LIMIT_FAILED_THRESHOLD", cfg.RATE_LIMIT_FAILED_THRESHOLD)
    app.config.setdefault("RATE_LIMIT_COOLDOWN_SECS", cfg.RATE_LIMIT_COOLDOWN_SECS)
    from .ratelimit import IpLimiter

    app.register_blueprint(track_bp)
    app.extensions["rate_limiter"] = IpLimiter(
        window_secs=app.config["RATE_LIMIT_WINDOW_SECS"],
        max_per_window=app.config["RATE_LIMIT_MAX_PER_WINDOW"],
        fail_threshold=app.config["RATE_LIMIT_FAILED_THRESHOLD"],
        cooldown_secs=app.config["RATE_LIMIT_COOLDOWN_SECS"],
    )

    @app.before_request
    def _load_user():
        g.current_user = load_current_user()

    @app.template_global()
    def can(permission: str) -> bool:
        """Template-level permission check (surface expression of the backend gate only)."""
        user = getattr(g, "current_user", None)
        if user is None:
            return False
        from .auth import _user_has_perm

        return _user_has_perm(user, permission)

    # Phase 8 — Dashboard home (KPI + alerts + feed). Real logic in app/dashboard.py.
    @app.route("/", methods=["GET"])
    def index():
        if g.get("current_user") is None:
            return redirect(url_for("auth.login", next=request.path))
        from .dashboard import render_dashboard

        return render_dashboard()

    @app.errorhandler(403)
    def forbidden(_err):
        return render_template("403.html"), 403

    # App-wide graceful handling of transient Google-Sheets / network failures
    # (production, masterdata, inventory, track blueprints + dashboard "/").
    # Non-transient bugs still surface as real HTTP 500. See app/errors.py.
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