"""Verification for the app-wide transient-error handler (app/errors.py).

Proves the core requirement: a ::TRANSIENT:: Google-Sheets / network failure on a
route yields a friendly 302 redirect + flash (NOT a raw 500), while a
::NON-TRANSIENT:: genuine bug (e.g. KeyError) still surfaces as HTTP 500.

The transient error is injected by monkeypatching the public ``track`` blueprint's
storage seam (``app.track._rel``) to raise — track needs no login and funnels
through the SAME SheetRelational seam the protected production / dashboard /
masterdata / inventory routes use, so a failure there exercises the identical
code path the app-wide handler guards.
"""
import sys

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from gspread.exceptions import APIError  # noqa: E402

import app.track as track_mod  # noqa: E402


class _FakeResp:
    status_code = 429

    def json(self):
        return {"error": {"message": "Quota exceeded", "code": 429}}


def _transient_api_error():
    """A gspread APIError resembling the Sheets HTTP-429 rate-limit response."""
    return APIError(_FakeResp())


class _RaisingRels:
    """Stands in for the SheetRelational seam; ``define`` triggers the injection."""

    def __init__(self, exc):
        self._exc = exc

    def define(self, *_a, **_k):
        raise self._exc


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    app = create_app({"TESTING": True, "SECRET_KEY": "test-secret", "STORAGE": "sqlite"})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


TRANSIENT_PAYLOAD = {"code": "PRD-260922-001"}


def test_transient_error_redirects_not_500(monkeypatch, client):
    """A gspread 429 must become a 302 friendly redirect, never a 500."""
    monkeypatch.setattr(
        track_mod, "_rel", lambda: _RaisingRels(_transient_api_error())
    )
    resp = client.post("/track", data=TRANSIENT_PAYLOAD)
    assert resp.status_code == 302, (
        f"expected 302 friendly redirect, got {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:200]!r}"
    )
    assert resp.headers.get("Location")


def test_nontransient_error_still_500(monkeypatch, client):
    """A genuine bug (KeyError) must still surface as HTTP 500."""
    monkeypatch.setattr(track_mod, "_rel", lambda: _RaisingRels(KeyError("missing")))
    resp = client.post("/track", data=TRANSIENT_PAYLOAD)
    assert resp.status_code == 500, (
        f"expected 500 for a non-transient bug, got {resp.status_code}"
    )


def test_boot_smoke_route_count_and_targets(app):
    """App boots and exposes routes for all 5 previously-uncovered surfaces."""
    rules = list(app.url_map.iter_rules())
    assert len(rules) > 0, "app has no routes"
    names = {r.rule for r in rules}
    for needle in ("/production", "/master-data", "/inventory", "/track", "/"):
        assert any(n == needle or n.startswith(needle + "/") for n in names), needle