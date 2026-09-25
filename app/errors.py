"""App-wide graceful error handling for transient Google-Sheets / network failures.

The data store is live Google Sheets (gspread -> Sheets API). Under quota
(HTTP 429) or server (5xx) pressure — and during brief network blips — gspread /
requests raise exceptions that ``app.storage._transient`` classifies as
transient. Without a handler those bubble to the WSGI layer as a raw HTTP 500,
even though they are not code bugs and a retry would likely succeed.

This module registers ONE app-wide ``Exception`` handler that:
  * leaves standard HTTP errors (403/404/429/401...) to their own handlers/pages;
  * converts a TRANSIENT storage/network error into a logged, friendly flash and
    a 302 redirect (back to referrer or the app root) — never a raw 500;
  * lets GENUINE non-transient programming bugs surface as a real HTTP 500.

Keeping this app-wide (rather than per-blueprint) is deliberate: the Dashboard
home is an app-level ``/`` route (no Blueprint) in ``app/__init__.py``, while
the production / masterdata / inventory / track routes are separate blueprints.
A single handler covers all of them uniformly.
"""

from flask import flash, redirect, request
from werkzeug.exceptions import HTTPException, InternalServerError

from .storage import _transient


def register_graceful_error_handlers(app) -> None:
    """Attach the app-wide transient-error handler to ``app``."""

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        # Standard HTTP errors (403/404/429/401/...) already have their own
        # handlers or default pages — never hijack them into a redirect. Only
        # the 500 path (InternalServerError) is ours to classify.
        if isinstance(exc, HTTPException) and exc.code != 500:
            return exc

        # In production (PROPAGATE_EXCEPTIONS off) Flask wraps the exception a
        # route raised inside InternalServerError(original_exception=<orig>).
        original = getattr(exc, "original_exception", exc) or exc

        if not _transient(original):
            # Genuine bug (KeyError, bad logic, auth mishap...): surface the
            # real 500 so the fault is not silently masked.
            app.logger.exception("unhandled error on %s: %s", request.path, original)
            return InternalServerError(original_exception=original)

        # Transient Google-Sheets / network failure: log, flash, and bounce the
        # user back instead of returning a raw "server overloaded" 500.
        app.logger.exception("transient storage/network error on %s: %s", request.path, original)
        flash("A temporary error occurred. Please try again.", "danger")
        # request.host_url is always absolute -> redirect() never BuildErrors,
        # landing on the app root "/" when there is no referrer.
        return redirect(request.referrer or request.host_url), 302