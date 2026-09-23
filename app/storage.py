"""Pluggable storage abstraction — SOLA Phase 1.

The data source is pluggable via ``STORAGE`` env (default ``sqlite``). Phase 1
introduces the abstraction and wires it into the app factory, but existing
blueprints keep using ``app/db.get_db()`` unchanged. Later phases switch live
reads/writes behind this interface.

Backends:
  * ``Storage``        — abstract interface (Phase 3 surface).
  * ``SqliteStorage``  — wraps the existing ``app/db.get_db()`` connection.
  * ``SheetsStorage``  — skeleton; validates config, data methods raise
                         ``NotImplementedError``. Imports cleanly with no creds.

Selection factory ``get_storage(config)`` lives here so Phase 3 swaps cleanly.
No third-party deps are required at import time for the sqlite path.
"""
from __future__ import annotations

import abc
import os
import time

from .db import audit as _audit
from .db import get_db


class Storage(abc.ABC):
    """Abstract data-access contract that the app routes all reads/writes through.

    Phase 2: the connection seam + transaction control live here. Write
    primitives (execute/insert/update/delete) do NOT implicitly commit — the
    app batches multiple statements then calls ``commit()`` once (matching the
    real transaction pattern), and ``rollback()`` on error. Read primitives
    need no commit.
    """

    name: str = "abstract"

    @abc.abstractmethod
    def connection(self):
        """Return the request-scoped connection for low-level use (execute/
        fetch). Implementations may return a wrapper or the raw connection."""

    @abc.abstractmethod
    def commit(self) -> None:
        """Persist the current transaction (all writes before this point)."""

    @abc.abstractmethod
    def rollback(self) -> None:
        """Discard the current transaction (undo writes since the last commit)."""

    @abc.abstractmethod
    def query(self, sql: str, params=()) -> list:
        """Run a SELECT and return all rows."""

    @abc.abstractmethod
    def execute(self, sql: str, params=()) -> object:
        """Run an arbitrary statement (DDL/DML). Does NOT commit; caller
        decides transaction boundary via commit()/rollback()."""

    @abc.abstractmethod
    def fetchone(self, sql: str, params=()):
        """Run a SELECT and return the first row (or None)."""

    @abc.abstractmethod
    def fetchall(self, sql: str, params=()) -> list:
        """Run a SELECT and return all rows."""

    @abc.abstractmethod
    def insert(self, sql: str, params=()) -> object:
        """Insert a row. Does NOT commit; returns the cursor so ``lastrowid``
        is available before the caller commits (matches app usage)."""

    @abc.abstractmethod
    def update(self, sql: str, params=()) -> object:
        """Update rows. Does NOT commit; returns the cursor/result."""

    @abc.abstractmethod
    def delete(self, sql: str, params=()) -> object:
        """Delete rows. Does NOT commit; returns the cursor/result."""

    @abc.abstractmethod
    def audit(self, user_id, action, entity, entity_id=None,
              old_value=None, new_value=None) -> None:
        """Record a consequential action to the audit log (spec 27)."""


class SqliteStorage(Storage):
    """Delegates to the existing per-request ``app/db.get_db()`` connection.

    Constructing this class does NOT touch the database (no Flask app context
    required), so it is safe to build during ``create_app``. All methods must
    be called inside a Flask app context, matching how the blueprints use
    ``get_db()`` today.
    """

    name = "sqlite"

    # -- private helpers -------------------------------------------------
    @staticmethod
    def _db():
        return get_db()

    # -- interface -------------------------------------------------------
    def connection(self):
        # Return the exact per-request connection get_db() provides today, so
        # blueprints/helpers that take a raw sqlite3.Connection work unchanged.
        return get_db()

    def commit(self):
        self._db().commit()

    def rollback(self):
        self._db().rollback()

    def query(self, sql, params=()):
        return self._db().execute(sql, params).fetchall()

    def execute(self, sql, params=()):
        # No implicit commit — caller owns the transaction boundary.
        return self._db().execute(sql, params)

    def fetchone(self, sql, params=()):
        return self._db().execute(sql, params).fetchone()

    def fetchall(self, sql, params=()):
        return self._db().execute(sql, params).fetchall()

    def insert(self, sql, params=()):
        # Return the cursor so callers can read `.lastrowid` before committing.
        return self._db().execute(sql, params)

    def update(self, sql, params=()):
        return self._db().execute(sql, params)

    def delete(self, sql, params=()):
        return self._db().execute(sql, params)

    def audit(self, user_id, action, entity, entity_id=None,
              old_value=None, new_value=None):
        _audit(user_id, action, entity, entity_id=entity_id,
               old_value=old_value, new_value=new_value)


class SheetsStorage(Storage):
    """Live Google Sheets backend (Phase 3).

    gspread-based, opened by spreadsheet ID (Sheets API only — no Drive scope,
    see the gspread skill). Import is lazy so the sqlite path never needs
    gspread. Construction is NON-fatal: the app boots with ``STORAGE=sheets``
    even with no creds; only a real data call (or ``connect()``) touches the
    network and can raise.

    A spreadsheet is tab-oriented, not relational: it CANNOT run SQL. So the
    SQL-shaped interface methods (query/execute/fetch*/insert/update/delete/
    connection) raise ``NotImplementedError`` with a clear reason, and the real
    surface is the tab CRUD: ``tabs()``, ``header_row()``, ``read_tab()``,
    ``append_rows()``, ``update_cell()``, ``clear_tab()`` — matching the tab
    model the sync tooling (scripts/sync_sheet.py) already uses.
    """

    name = "sheets"

    _SQL_SHAPED = (
        "{cls} cannot run SQL against a Google Sheet. SheetsStorage is a "
        "tab-oriented backend; use tabs()/header_row()/read_tab()/append_rows()"
        "/update_cell()/clear_tab(). '{method}' is not applicable here.")

    # -- construction / validation -----------------------------------------
    def __init__(self, spreadsheet_id=None, credentials_path=None):
        self.spreadsheet_id = spreadsheet_id
        self.credentials_path = credentials_path
        # Non-fatal readiness check.
        self.missing = []
        if not self.spreadsheet_id:
            self.missing.append("SPREADSHEET_ID")
        cred = self.credentials_path
        if not cred or not os.path.exists(os.path.expanduser(cred)):
            self.missing.append("GOOGLE_APPLICATION_CREDENTIALS")
        # Lazy connection (built on first network use).
        self._client = None
        self._spreadsheet = None
        self._tab_cache: list[str] | None = None
        self._ws_cache: dict | None = None
        self._value_cache: dict[str, tuple] = {}

    @property
    def already_configured(self) -> bool:
        """True when both sheet id and service-account file are present."""
        return not self.missing

    # -- gspread connection (open_by_key, Sheets-only scope) ----------------
    def connect(self):
        """Build + return the authorized gspread client and open the sheet.

        Raises RuntimeError if not configured, and lets gspread's own errors
        surface if the service account lacks access or the id is wrong. Uses
        only the Sheets API (open_by_key), so no Drive scope is required.
        """
        if self._spreadsheet is not None:
            return self._client, self._spreadsheet
        if not self.already_configured:
            raise RuntimeError(
                "SheetsStorage not configured; missing: "
                + (", ".join(self.missing) or "n/a"))
        import gspread  # lazy — sqlite path never imports gspread

        gc = gspread.service_account(filename=self.credentials_path)
        sh = gc.open_by_key(self.spreadsheet_id)
        self._client = gc
        self._spreadsheet = sh
        return gc, sh

    # -- tab-oriented surface ------------------------------------------------
    # Read-caching: the app is a live sheet-backed database, and Google limits
    # reads to 60/min/user. Cache worksheet objects (avoid repeated metadata
    # fetches) and cache per-tab value grids with a short TTL; invalidate on any
    # write. Without this, a single page (auth + dashboard = ~10 tab reads)
    # slams the quota and returns HTTP 429.
    _READ_TTL = 10.0  # seconds; values are re-fetched at most once per TTL per tab

    def _worksheet(self, tab: str):
        """Return a cached gspread Worksheet object (no metadata re-fetch)."""
        _, sh = self.connect()
        if self._ws_cache is None:
            self._ws_cache = {ws.title: ws for ws in sh.worksheets()}
        ws = self._ws_cache.get(tab)
        if ws is None:
            ws = sh.worksheet(tab)
            self._ws_cache[tab] = ws
        return ws

    def _read_cached(self, tab: str):
        now = time.monotonic()
        hit = self._value_cache.get(tab)
        if hit and (now - hit[0]) < self._READ_TTL:
            return hit[1]
        rows = self._worksheet(tab).get_all_values(
            value_render_option="UNFORMATTED_VALUE")
        self._value_cache[tab] = (now, rows)
        return rows

    def _invalidate(self, tab: str) -> None:
        self._value_cache.pop(tab, None)

    def tabs(self) -> list[str]:
        """Exact tab titles in the live workbook (authoritative), cached per
        connect() to avoid hammering the read-request quota (60/min/user)."""
        _, sh = self.connect()
        if self._tab_cache is None:
            self._tab_cache = [ws.title for ws in sh.worksheets()]
        return list(self._tab_cache)

    def refresh_tabs(self) -> list[str]:
        """Force a fresh tab list (after creating/removing tabs)."""
        _, sh = self.connect()
        self._tab_cache = [ws.title for ws in sh.worksheets()]
        return list(self._tab_cache)

    def header_row(self, tab: str) -> list[str]:
        """First row of a tab (its headers)."""
        return self._read_cached(tab)[0] if self._read_cached(tab) else []

    def read_tab(self, tab: str, header: bool = True,
                 value_render_option="UNFORMATTED_VALUE") -> list[list]:
        """All rows of a tab as 2D list (cached); drops the header when True."""
        if value_render_option != "UNFORMATTED_VALUE":
            # non-default render: bypass cache (rare)
            _, sh = self.connect()
            rows = sh.worksheet(tab).get_all_values(
                value_render_option=value_render_option)
            return rows[1:] if (header and rows) else rows
        rows = self._read_cached(tab)
        if header and rows:
            return rows[1:]
        return rows

    def find_tab_by_header(self, expected: list[str]) -> str | None:
        """Return the title of the first tab whose header row matches
        ``expected`` (order-insensitive). None when no tab matches."""
        want = {str(c).strip().lower() for c in expected}
        for title in self.tabs():
            try:
                hdr = [str(c).strip().lower() for c in self.header_row(title)]
            except Exception:
                continue  # skip empty / non-header tabs
            if want <= set(hdr):
                return title
        return None

    def append_rows(self, tab: str, rows: list[list]):
        """Append one-or-more rows to a tab. Values must be plain strings/
        numbers (RAW input) — gspread 6.2.1 mis-serializes USER_ENTERED here."""
        _, sh = self.connect()
        ws = sh.worksheet(tab)
        ws.append_rows(rows)
        self._invalidate(tab)

    def add_tab(self, title: str, header_row: list | None = None) -> None:
        """Create a new tab if it does not exist; optionally write a header row."""
        _, sh = self.connect()
        if title not in self.tabs():
            sh.add_worksheet(title=title, rows=1,
                             cols=max(len(header_row), 1) if header_row else 1)
            self.refresh_tabs()
        if header_row:
            self.append_rows(title, [header_row])

    def update_cell(self, tab: str, row: int, col: int, value):
        """Write a single cell (row/col are 1-indexed, matching Sheets)."""
        _, sh = self.connect()
        ws = sh.worksheet(tab)
        ws.update_cell(row, col, value)
        self._invalidate(tab)

    def clear_tab(self, tab: str):
        """Clear all content in a tab (headers gone too — caller refill)."""
        _, sh = self.connect()
        ws = sh.worksheet(tab)
        ws.clear()
        self._invalidate(tab)

    # -- inherited SQL-shaped surface (not applicable to a sheet) ----------
    def _raise_sql_shaped(self, method: str):
        raise NotImplementedError(
            self._SQL_SHAPED.format(cls=type(self).__name__, method=method))

    def connection(self):
        self._raise_sql_shaped("connection")

    def commit(self):
        self._raise_sql_shaped("commit")

    def rollback(self):
        self._raise_sql_shaped("rollback")

    def query(self, sql, params=()):
        self._raise_sql_shaped("query")

    def execute(self, sql, params=()):
        self._raise_sql_shaped("execute")

    def fetchone(self, sql, params=()):
        self._raise_sql_shaped("fetchone")

    def fetchall(self, sql, params=()):
        self._raise_sql_shaped("fetchall")

    def insert(self, sql, params=()):
        self._raise_sql_shaped("insert")

    def update(self, sql, params=()):
        self._raise_sql_shaped("update")

    def delete(self, sql, params=()):
        self._raise_sql_shaped("delete")

    def audit(self, user_id, action, entity, entity_id=None,
              old_value=None, new_value=None):
        self._raise_sql_shaped("audit")


def get_storage(config):
    """Select the storage backend for the app.

    ``config`` may be a dict-like (e.g. ``app.config``, so tests can override
    ``STORAGE`` via test_config) or an object with the same attributes. Returns
    the configured ``Storage`` instance. Defaults to ``SqliteStorage`` when
    ``STORAGE`` is unset or ``sqlite``. An unrecognized value fails fast.
    """
    def _get(key, default=None):
        if hasattr(config, "get") and callable(config.get):
            return config.get(key, default) or default
        val = getattr(config, key, None)
        return val if val is not None else default

    storage = (_get("STORAGE", "sqlite") or "sqlite")
    storage = str(storage).strip().lower() or "sqlite"

    if storage == "sqlite":
        return SqliteStorage()
    if storage == "sheets":
        return SheetsStorage(
            spreadsheet_id=_get("SPREADSHEET_ID"),
            credentials_path=_get("GOOGLE_APPLICATION_CREDENTIALS"),
        )
    raise ValueError(
        f"Unknown STORAGE backend: {storage!r} (expected 'sqlite' or 'sheets')")