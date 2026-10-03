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
import random
import time

from .db import audit as _audit
from .db import get_db


def _transient(exc: Exception) -> bool:
    """True when ``exc`` is a transient Google-API/network failure worth retrying.

    Retried: HTTP-level transport errors (connection refused, timeout, 5xx from
    requests), built-in connection/timeout errors, and gspread's ``APIError``
    carrying an HTTP 429 (rate-limit) or 5xx status. Everything else — not-found,
    auth failures, logic errors — is left to surface immediately.
    """
    import requests

    if isinstance(exc, (requests.exceptions.RequestException, TimeoutError, ConnectionError)):
        return True
    try:
        from gspread.exceptions import APIError
    except Exception:  # pragma: no cover - gspread always present on the sheets path
        APIError = ()
    if isinstance(exc, APIError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return isinstance(status, int) and (status == 429 or status >= 500)
    return False


def _retry(fn, *args, attempts: int = 5, base: float = 0.5, factor: float = 2.0,
           jitter: float = 0.3, **kwargs):
    """Call ``fn(*args, **kwargs)`` retrying transient failures.

    Exponential backoff with random jitter: 0.5s, 1s, 2s, 4s + jitter. Non-transient
    errors (and the final attempt) propagate immediately so nothing is silently
    swallowed. Stdlib-only (``time`` + ``random``); no new dependencies.
    """
    last = None
    for attempt in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - transient classification below
            if not _transient(exc) or attempt == attempts - 1:
                raise
            last = exc
            delay = base * (factor ** attempt) + (jitter * random.random())
            time.sleep(delay)
    raise last  # pragma: no cover - unreachable when attempts >= 1


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


def _col_type_group(decl: str) -> str:
    """Bucket a declared SQLite column type into int / float / text."""
    d = (decl or "").upper()
    if "INT" in d:
        return "int"
    if any(k in d for k in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return "float"
    return "text"


_ZERO_BY_GROUP = {"int": 0, "float": 0.0, "text": ""}


class _Omit:
    """Sentinel: omit this column from the INSERT so its DEFAULT applies."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()


class _SqliteWorksheet:
    """Minimal gspread-shaped worksheet so ``sheetdb`` takes its targeted
    ``delete_rows`` path instead of rewriting the whole tab.

    Only the one attribute ``SheetRelation._delete_row`` looks for is
    implemented; it is addressed by 0-based row index with the header at 0,
    exactly like gspread.
    """

    def __init__(self, adapter: "SqliteTabAdapter", tab: str):
        self._adapter = adapter
        self._tab = tab

    def delete_rows(self, row_index: int) -> None:
        """Delete the sheet row at 0-based ``row_index`` (header occupies 0)."""
        self._adapter._delete_data_row(self._tab, row_index - 1)


class _SqliteSpreadsheet:
    """gspread-shaped spreadsheet facade (``worksheet(title)`` only)."""

    def __init__(self, adapter: "SqliteTabAdapter"):
        self._adapter = adapter

    def worksheet(self, title: str) -> _SqliteWorksheet:
        return _SqliteWorksheet(self._adapter, title)


class SqliteTabAdapter:
    """Google-Sheets-shaped TAB interface over the existing SQLite tables.

    ``app.sheetdb.SheetRelational`` is the app's only real data path and it
    talks exclusively to a TAB interface (``read_tab`` / ``append_rows`` /
    ``tabs`` / ``header_row`` / ``clear_tab`` / ``update_cell`` /
    ``_invalidate``). This adapter gives the legacy ``SqliteStorage`` backend
    exactly that surface, so ``STORAGE=sqlite`` is a working offline/test
    backend instead of a hard 500. The production Google-Sheets path
    (``STORAGE=sheets`` -> ``SheetsStorage``) is untouched.

    The translation of "tab" onto "table" is:

      * the SCHEMA is the header row — ``header_row()`` is the table's column
        names in declared order, and ``read_tab(header=False)`` prepends them
        virtually so callers that reason about sheet row 1 == header (and
        ``idx + 2``) behave identically;
      * the BODY is the table's rows, ordered by rowid (SQLite's insertion
        order, which is what a sheet append preserves);
      * a tab's data is thus never stored as a header row, so
        ``read_tab(header=True)`` returns every row and
        ``read_tab(header=False)`` returns ``[header] + rows``.

    Values are translated with the same conventions as
    ``app.sheetdb._cell_encode`` / ``_cell_decode``: an empty cell means NULL
    on write and ``""`` on read, numbers stay numeric, and dict/list columns
    stay JSON text. Writes commit immediately (a sheet write is durable the
    moment the API call returns) because ``app.db.close_db`` closes the
    connection without committing.
    """

    def __init__(self, storage: "SqliteStorage"):
        self._storage = storage
        # commercial._ensure_tab_headers persists its verification window here,
        # mirroring SheetsStorage's per-instance state.
        self._header_verified: dict[str, float] = {}

    # -- connection -------------------------------------------------------
    def _db(self):
        return self._storage._db()

    @staticmethod
    def _quote(identifier: str) -> str:
        return '"' + str(identifier).replace('"', '""') + '"'

    def _require_table(self, tab: str) -> None:
        row = self._db().execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (tab,)).fetchone()
        if row is None:
            raise RuntimeError(
                f"sqlite tab '{tab}' does not exist; create the table first "
                "(db/schema.sql + db.init_schema.create_schema)")

    def _table_info(self, tab: str) -> list[tuple]:
        """[(name, declared_type, notnull, has_default)] in declared order."""
        self._require_table(tab)
        rows = self._db().execute(
            f"PRAGMA table_info({self._quote(tab)})").fetchall()
        return [(r[1], r[2], bool(r[3]), r[4] is not None) for r in rows]

    # -- sheetdb tab interface --------------------------------------------
    def tabs(self) -> list[str]:
        return [r[0] for r in self._db().execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY rowid").fetchall()]

    def refresh_tabs(self) -> list[str]:
        return self.tabs()

    def header_row(self, tab: str) -> list[str]:
        return [c[0] for c in self._table_info(tab)]

    def read_tab(self, tab: str, header: bool = True,
                 value_render_option="UNFORMATTED_VALUE") -> list[list]:
        cols = self.header_row(tab)
        if not cols:
            return []
        sel = ", ".join(self._quote(c) for c in cols)
        rows = self._db().execute(
            f"SELECT {sel} FROM {self._quote(tab)} ORDER BY rowid").fetchall()
        grid = [[("" if v is None else v) for v in r] for r in rows]
        if header:
            return grid
        return [list(cols)] + grid

    def append_rows(self, tab: str, rows: list[list]) -> None:
        info = self._table_info(tab)
        db = self._db()
        for row in rows:
            cols, values = [], []
            for i, (cname, decl, notnull, has_default) in enumerate(info):
                raw = row[i] if i < len(row) else None
                value = self._to_db(raw, decl, notnull, has_default)
                if value is _OMIT:
                    continue  # let the column's DEFAULT apply, as SQL would
                cols.append(cname)
                values.append(value)
            if not cols:
                continue
            placeholders = ", ".join("?" * len(cols))
            quoted = ", ".join(self._quote(c) for c in cols)
            db.execute(
                f"INSERT INTO {self._quote(tab)} ({quoted}) "
                f"VALUES ({placeholders})", values)
        db.commit()

    def update_cell(self, tab: str, row: int, col: int, value) -> None:
        """Update one cell. ``row`` is 1-based INCLUDING the header (row 1),
        ``col`` is 1-based — matching ``SheetRelation.update``'s ``idx + 2``."""
        info = self._table_info(tab)
        if col < 1 or col > len(info):
            raise IndexError(
                f"column {col} out of range for sqlite tab '{tab}' "
                f"({len(info)} columns)")
        if row < 2:
            return  # row 1 is the header, which here is the schema itself
        cname, decl, notnull, has_default = info[col - 1]
        db = self._db()
        target = db.execute(
            f"SELECT rowid FROM {self._quote(tab)} ORDER BY rowid "
            "LIMIT 1 OFFSET ?", (row - 2,)).fetchone()
        if target is None:
            return  # no such sheet row
        db.execute(
            f"UPDATE {self._quote(tab)} SET {self._quote(cname)}=? WHERE rowid=?",
            (self._to_db(value, decl, notnull, has_default), target[0]))
        db.commit()

    def clear_tab(self, tab: str) -> None:
        """Delete every row but keep the schema (the tab's header row)."""
        self._require_table(tab)
        db = self._db()
        db.execute(f"DELETE FROM {self._quote(tab)}")
        db.commit()

    def first_cell(self, tab: str):
        """A1 of the tab. The header lives in the schema, so this is the first
        column name — which is what ``_ensure_tab_headers`` compares against."""
        cols = self.header_row(tab)
        return cols[0] if cols else None

    def prepend_header(self, tab: str, header: list) -> None:
        """No-op: this backend's header row IS the table schema, so a header
        can never go missing (and never needs shifting rows down)."""
        return None

    def add_tab(self, title: str, header_row: list | None = None) -> None:
        """Create the table backing ``title`` (idempotent), typed TEXT."""
        cols = list(header_row or [])
        if not cols:
            cols = ["value"]
        existing = {c[0] for c in self._table_info(title)} if self._table_exists(title) else set()
        adds = [c for c in cols if c not in existing]
        if adds:
            quoted = ", ".join(
                f"{self._quote(c)} TEXT" for c in adds)
            self._db().execute(
                f"CREATE TABLE IF NOT EXISTS {self._quote(title)} ({quoted})")
            self._db().commit()

    def find_tab_by_header(self, expected: list[str]) -> str | None:
        want = list(expected)
        for tab in self.tabs():
            try:
                if self.header_row(tab) == want:
                    return tab
            except Exception:
                continue
        return None

    def _invalidate(self, tab: str | None = None) -> None:
        """No-op: SQLite reads are not cached, so there is nothing to drop."""
        return None

    # -- internals --------------------------------------------------------
    def _table_exists(self, tab: str) -> bool:
        return self._db().execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (tab,)).fetchone() is not None

    def _delete_data_row(self, tab: str, data_index: int) -> None:
        """Delete the ``data_index``-th (0-based) data row of the tab."""
        if data_index < 0:
            return  # the header row: it is the schema, not a stored row
        db = self._db()
        target = db.execute(
            f"SELECT rowid FROM {self._quote(tab)} ORDER BY rowid "
            "LIMIT 1 OFFSET ?", (data_index,)).fetchone()
        if target is None:
            return
        db.execute(f"DELETE FROM {self._quote(tab)} WHERE rowid=?", (target[0],))
        db.commit()

    @staticmethod
    def _to_db(value, decl: str, notnull: bool, has_default: bool):
        """Translate one sheet cell value into a SQLite bind parameter.

        Mirrors ``sheetdb._cell_encode``: ``None``/``""`` means "empty cell".
        An empty cell on a NOT NULL column with a DEFAULT is omitted so the
        default applies (exactly what the pre-cutover SQL relied on); on a
        NOT NULL column with no default it becomes the type's zero value,
        since NULL is not storable there at all.
        """
        if value is None or value == "":
            if notnull:
                if has_default:
                    return _OMIT
                return _ZERO_BY_GROUP[_col_type_group(decl)]
            return None
        group = _col_type_group(decl)
        # sheetdb encodes bools as the strings "true"/"false"; SQLite's
        # numeric columns cannot hold them, so restore 1/0.
        if group in ("int", "float") and value in ("true", "false"):
            return 1 if value == "true" else 0
        return value

    # -- gspread-shaped helpers used by sheetdb -----------------------------
    def connect(self):
        """gspread-shaped ``(client, spreadsheet)`` pair so
        ``SheetRelation._delete_row`` performs a targeted row delete instead
        of the destructive clear-and-rewrite fallback."""
        return self, _SqliteSpreadsheet(self)

    @property
    def already_configured(self) -> bool:
        return True


class SqliteStorage(Storage):
    """Delegates to the existing per-request ``app/db.get_db()`` connection.

    Constructing this class does NOT touch the database (no Flask app context
    required), so it is safe to build during ``create_app``. All methods must
    be called inside a Flask app context, matching how the blueprints use
    ``get_db()`` today.

    Besides the SQL surface, it now also exposes ``.sheets`` — a
    ``SqliteTabAdapter`` giving it the Google-Sheets-shaped tab interface
    that ``app.sheetdb.SheetRelational`` speaks, so ``STORAGE=sqlite`` is a
    usable offline/test backend.
    """

    name = "sqlite"

    # -- private helpers -------------------------------------------------
    @staticmethod
    def _db():
        return get_db()

    def __init__(self):
        # Built eagerly but never touches the DB; kept on the instance so
        # commercial's _header_verified window survives across requests.
        self._tab_adapter = SqliteTabAdapter(self)

    # -- Google-Sheets-shaped tab interface (see SqliteTabAdapter) --------
    # ``SheetRelational`` stores this storage as ``store.sheets``, so — exactly
    # like SheetsStorage — SqliteStorage *is* the tab interface. These are thin
    # delegations to SqliteTabAdapter, which holds the real implementation.
    @property
    def sheets(self) -> "SqliteStorage":
        """Self: the tab interface is this object (SheetRelational does
        ``store.sheets``). Returned for callers that reach through it."""
        return self

    @property
    def _header_verified(self) -> dict:
        return self._tab_adapter._header_verified

    @property
    def already_configured(self) -> bool:
        return True

    def tabs(self) -> list[str]:
        return self._tab_adapter.tabs()

    def refresh_tabs(self) -> list[str]:
        return self._tab_adapter.refresh_tabs()

    def header_row(self, tab: str) -> list[str]:
        return self._tab_adapter.header_row(tab)

    def read_tab(self, tab: str, header: bool = True,
                 value_render_option="UNFORMATTED_VALUE") -> list[list]:
        return self._tab_adapter.read_tab(
            tab, header=header, value_render_option=value_render_option)

    def append_rows(self, tab: str, rows: list[list]) -> None:
        self._tab_adapter.append_rows(tab, rows)

    def update_cell(self, tab: str, row: int, col: int, value) -> None:
        self._tab_adapter.update_cell(tab, row, col, value)

    def clear_tab(self, tab: str) -> None:
        self._tab_adapter.clear_tab(tab)

    def first_cell(self, tab: str):
        return self._tab_adapter.first_cell(tab)

    def prepend_header(self, tab: str, header: list) -> None:
        self._tab_adapter.prepend_header(tab, header)

    def add_tab(self, title: str, header_row: list | None = None) -> None:
        self._tab_adapter.add_tab(title, header_row)

    def find_tab_by_header(self, expected: list[str]) -> str | None:
        return self._tab_adapter.find_tab_by_header(expected)

    def connect(self):
        return self._tab_adapter.connect()

    def _invalidate(self, tab: str | None = None) -> None:
        self._tab_adapter._invalidate(tab)


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
        cred = (self.credentials_path or "").strip()
        # Configured when we have a value AND it is either inline service-account
        # JSON (serverless hosts have no file path) or a path that exists.
        if not cred or not (cred.startswith("{") or os.path.exists(os.path.expanduser(cred))):
            self.missing.append("GOOGLE_APPLICATION_CREDENTIALS")
        # Lazy connection (built on first network use).
        self._client = None
        self._spreadsheet = None
        self._tab_cache: list[str] | None = None
        self._ws_cache: dict | None = None
        self._value_cache: dict[str, tuple] = {}
        self._first_cell_cache: dict[str, tuple] = {}
        # Tab names whose header was validated this instance (monotonic time of
        # check). Used by app/commercial._ensure_tab_headers as a cheap guard so
        # the serverless request path does not re-read every header on each
        # request — we re-verify at most once per window.
        self._header_verified: dict[str, float] = {}

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
        import json as _json

        cred = (self.credentials_path or "").strip()
        if cred.startswith("{"):
            # Inline service-account JSON (serverless hosts have no file path).
            gc = gspread.service_account_from_dict(_json.loads(cred))
        else:
            gc = gspread.service_account(filename=cred)
        sh = _retry(gc.open_by_key, self.spreadsheet_id)
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
            self._ws_cache = {ws.title: ws for ws in _retry(sh.worksheets)}
        ws = self._ws_cache.get(tab)
        if ws is None:
            ws = _retry(sh.worksheet, tab)
            self._ws_cache[tab] = ws
        return ws

    def _read_cached(self, tab: str):
        now = time.monotonic()
        hit = self._value_cache.get(tab)
        if hit and (now - hit[0]) < self._READ_TTL:
            return hit[1]
        rows = _retry(self._worksheet(tab).get_all_values,
                      value_render_option="UNFORMATTED_VALUE")
        self._value_cache[tab] = (now, rows)
        return rows

    def _invalidate(self, tab: str) -> None:
        self._value_cache.pop(tab, None)
        self._first_cell_cache.pop(tab, None)

    def first_cell(self, tab: str):
        """Value of the tab's A1 cell (cheap single-cell read, ~10s cached).

        Used as a low-cost header-present guard so tab-header validation does
        not need to pull the full grid on every request.
        """
        now = time.monotonic()
        hit = self._first_cell_cache.get(tab)
        if hit and (now - hit[0]) < self._READ_TTL:
            return hit[1]
        val = _retry(self._worksheet(tab).acell, "A1").value
        self._first_cell_cache[tab] = (now, val)
        return val

    def tabs(self) -> list[str]:
        """Exact tab titles in the live workbook (authoritative), cached per
        connect() to avoid hammering the read-request quota (60/min/user)."""
        _, sh = self.connect()
        if self._tab_cache is None:
            self._tab_cache = [ws.title for ws in _retry(sh.worksheets)]
        return list(self._tab_cache)

    def refresh_tabs(self) -> list[str]:
        """Force a fresh tab list (after creating/removing tabs)."""
        _, sh = self.connect()
        self._tab_cache = [ws.title for ws in _retry(sh.worksheets)]
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
            rows = _retry(sh.worksheet(tab).get_all_values,
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
        _retry(ws.append_rows, rows)
        self._invalidate(tab)

    def prepend_header(self, tab: str, header: list) -> None:
        """Insert ``header`` as the new first row, shifting existing rows down.

        Used to repair a tab whose header row is lost or has data leaked into
        row 1 — the canonical header is inserted at position 1 WITHOUT dropping
        any data. Idempotent callers only invoke this when the header is broken.
        """
        _, sh = self.connect()
        ws = sh.worksheet(tab)
        _retry(ws.insert_row, header, 1)
        self._invalidate(tab)

    def add_tab(self, title: str, header_row: list | None = None) -> None:
        """Create a new tab if it does not exist; optionally write a header row."""
        _, sh = self.connect()
        if title not in self.tabs():
            _retry(sh.add_worksheet, title=title, rows=1,
                   cols=max(len(header_row), 1) if header_row else 1)
            self.refresh_tabs()
        if header_row:
            self.append_rows(title, [header_row])

    def update_cell(self, tab: str, row: int, col: int, value):
        """Write a single cell (row/col are 1-indexed, matching Sheets)."""
        _, sh = self.connect()
        ws = sh.worksheet(tab)
        _retry(ws.update_cell, row, col, value)
        self._invalidate(tab)

    def clear_tab(self, tab: str):
        """Clear all content in a tab (headers gone too — caller refill)."""
        _, sh = self.connect()
        ws = sh.worksheet(tab)
        _retry(ws.clear)
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


class LocalSheetStorage(Storage):
    """In-memory tab store satisfying the sheetdb interface, for running the
    app's sheet-backed blueprints (auth / masterdata / inventory / commercial)
    fully OFFLINE with no Google credentials.

    This is a thin local implementation of the handful of sheet-ish operations
    that ``app.sheetdb.SheetRelational`` and ``app.commercial`` rely on
    (``read_tab`` / ``append_rows`` / ``clear_tab`` / ``prepend_header`` /
    ``first_cell`` / ``tabs`` / ``update_cell``). It deliberately does NOT
    replicate gspread; rows are just native Python lists so the whole HTTP flow
    can run as a fast unit test. Select with ``STORAGE=local`` / ``sqlish`` /
    ``offline``.

    Semantics mirror the live Google Sheet so the caller's column model and the
    ``_ensure_tab_headers`` self-repair behave identically:
      * row 0 of a tab is always the header row; ``read_tab(header=True)``
        returns rows 1..n (pure data), ``header=False`` returns all rows.
      * ``append_rows`` appends data rows (creating the tab if absent).
      * ``first_cell`` returns A1 (None if the tab is empty).
    """

    name = "local"

    def __init__(self):
        # tab -> list[list]; row 0 is the header when present.
        self._rows: dict[str, list[list]] = {}
        self._header_verified: dict[str, float] = {}

    def already_configured(self) -> bool:
        return True

    # -- sheetdb tab interface ----------------------------------------------
    def tabs(self) -> list[str]:
        return list(self._rows.keys())

    def refresh_tabs(self) -> list[str]:
        return self.tabs()

    def header_row(self, tab: str) -> list[str]:
        rows = self._rows.get(tab, [])
        return list(rows[0]) if rows else []

    def read_tab(self, tab: str, header: bool = True, value_render_option="UNFORMATTED_VALUE") -> list[list]:
        rows = self._rows.get(tab, [])
        if header and rows:
            return [list(r) for r in rows[1:]]
        return [list(r) for r in rows]

    def append_rows(self, tab: str, rows: list[list]) -> None:
        self._rows.setdefault(tab, []).extend([list(r) for r in rows])

    def clear_tab(self, tab: str) -> None:
        self._rows[tab] = []

    def first_cell(self, tab: str):
        rows = self._rows.get(tab, [])
        if not rows or not rows[0]:
            return None
        return rows[0][0]

    def prepend_header(self, tab: str, header: list) -> None:
        """Insert a header row at position 0, shifting existing rows down (safe)."""
        self._rows.setdefault(tab, []).insert(0, list(header))

    def update_cell(self, tab: str, row: int, col: int, value) -> None:
        while len(self._rows.setdefault(tab, [])) < row:
            self._rows[tab].append([])
        while len(self._rows[tab][row - 1]) < col:
            self._rows[tab][row - 1].append("")
        self._rows[tab][row - 1][col - 1] = value

    def add_tab(self, title: str, header_row: list | None = None) -> None:
        if title not in self._rows:
            self._rows[title] = []
        if header_row:
            self._rows[title].append(list(header_row))

    def find_tab_by_header(self, expected: list[str]) -> str | None:
        for tab, rows in self._rows.items():
            if rows and rows[0] == list(expected):
                return tab
        return None

    # -- convenience for tests/seeding --------------------------------------
    def seed(self, tab: str, header: list, rows: list[list] | None = None) -> None:
        """Replace a tab wholesale with a header + data rows (test helper)."""
        grid = [list(header)]
        for r in (rows or []):
            grid.append(list(r))
        self._rows[tab] = grid

    # -- inherited SQL-shaped surface (not applicable to a sheet store) -----
    def connection(self):
        raise NotImplementedError("LocalSheetStorage has no SQL connection")

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def query(self, sql, params=()):
        raise NotImplementedError("LocalSheetStorage has no SQL surface")

    def execute(self, sql, params=()):
        raise NotImplementedError("LocalSheetStorage has no SQL surface")

    def fetchone(self, sql, params=()):
        raise NotImplementedError("LocalSheetStorage has no SQL surface")

    def fetchall(self, sql, params=()):
        raise NotImplementedError("LocalSheetStorage has no SQL surface")

    def insert(self, sql, params=()):
        raise NotImplementedError("LocalSheetStorage has no SQL surface")

    def update(self, sql, params=()):
        raise NotImplementedError("LocalSheetStorage has no SQL surface")

    def delete(self, sql, params=()):
        raise NotImplementedError("LocalSheetStorage has no SQL surface")

    def audit(self, user_id, action, entity, entity_id=None,
              old_value=None, new_value=None):
        raise NotImplementedError("LocalSheetStorage has no SQL audit surface")


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
    if storage in ("local", "sqlish", "offline"):
        return LocalSheetStorage()
    raise ValueError(
        f"Unknown STORAGE backend: {storage!r} (expected 'sqlite', 'sheets', or 'local'/'sqlish'/'offline')")
