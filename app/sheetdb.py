"""SheetRelational — a Google Sheets-backed relational store for SOLA (Phase 5).

The cutover decision is FULL: SQLite is dropped from the app runtime; the Google
Sheet is the single live store. Sheets cannot execute SQL, so this module models
each relational table as a TAB in the spreadsheet and provides CRUD in Python:

  * tab layout               = header row (column names) + one row per record
  * row identity             = primary key (the first column of the table)
  * read_all / find / find_one / insert / update / delete
  * cell serialization       = json for dict/list columns, str() for None

It is built on top of `app.storage.SheetsStorage` (gspread, open_by_key).
Values are written with value_input_option=USER_ENTERED so numbers stay numbers.

This is intentionally a thin relational adapter, NOT a query engine — blueprints
port their SQL to the seam methods (find/filter/insert/update/delete) which is the
same tab-CRUD model the app already commits to.
"""
from __future__ import annotations

import json
from typing import Any

from .storage import SheetsStorage


def _cell_encode(value: Any) -> Any:
    """Encode a Python value for a sheet cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _cell_decode(value: Any) -> Any:
    """Decode a sheet cell back to a Python value (best effort)."""
    if value is None or value == "":
        return None
    return value


class SheetRelation:
    """A single table (tab) in the spreadsheet."""

    def __init__(self, store: "SheetRelational", tab: str, columns: list[str],
                 pk_col: str = ""):
        self.store = store
        self.tab = tab
        self.columns = list(columns)
        # primary-key column: default to first column when not specified
        self.pk_col = pk_col or (self.columns[0] if self.columns else "")
        self._pk_idx = self.columns.index(self.pk_col) if self.pk_col in self.columns else 0

    # -- low-level ----------------------------------------------------------
    def _all_rows(self) -> list[list]:
        """[(...)] data rows only (header excluded)."""
        return self.store.sheets.read_tab(self.tab, header=True)

    def _rows_with_header(self) -> list[list]:
        return self.store.sheets.read_tab(self.tab, header=False)

    def _write(self, rows: list[list]) -> None:
        """Replace the whole tab body (after header) with `rows`."""
        # We clear then write to keep the engine simple and correct under the
        # full-cutover contract (the sheet is authoritative; no concurrency).
        self.store.sheets.clear_tab(self.tab)
        if not rows:
            self.store.sheets.append_rows(self.tab, [self.columns])
            return
        self.store.sheets.append_rows(self.tab, [self.columns] + rows)

    # -- row helpers ---------------------------------------------------------
    def _to_dict(self, row: list) -> dict:
        d = {}
        for i, col in enumerate(self.columns):
            d[col] = _cell_decode(row[i]) if i < len(row) else None
        return d

    def _to_row(self, record: dict) -> list:
        return [_cell_encode(record.get(c)) for c in self.columns]

    def _find_index(self, rows: list[list], pk_value: Any) -> int | None:
        needle = _cell_encode(pk_value)
        for i, row in enumerate(rows):
            if i < len(row) and _cell_encode(row[self._pk_idx]) == needle:
                return i
        return None

    # -- public API ----------------------------------------------------------
    @staticmethod
    def _val_eq(a, b) -> bool:
        """Lenient equality: numbers compare by numeric value (SQL-ish coercion)."""
        if a == b:
            return True
        try:
            fa, fb = float(str(a)), float(str(b))
            return fa == fb and str(a) not in ("", "None") and str(b) not in ("", "None")
        except (TypeError, ValueError):
            return False

    def read_all(self) -> list[dict]:
        return [self._to_dict(r) for r in self._all_rows()]

    def find(self, **equals) -> list[dict]:
        """All records where the named columns match the given values."""
        rows = self.read_all()
        out = []
        for rec in rows:
            if all(self._val_eq(rec.get(k), v) for k, v in equals.items()):
                out.append(rec)
        return out

    def find_one(self, **equals) -> dict | None:
        rows = self.find(**equals)
        return rows[0] if rows else None

    def get(self, pk_value: Any) -> dict | None:
        return self.find_one(**{self.pk_col: pk_value})

    def insert(self, record: dict) -> dict:
        """Append a record. Local PK + autoincrement if pk is empty and numeric."""
        rec = dict(record)
        if not rec.get(self.pk_col) and self.pk_col:
            existing = [r.get(self.pk_col) for r in self.read_all()]
            nums = [int(v) for v in existing if v is not None and str(v).isdigit()]
            rec[self.pk_col] = (max(nums) + 1) if nums else 1
        self.store.sheets.append_rows(self.tab, [self._to_row(rec)])
        return rec

    def multi_insert(self, records: list[dict]) -> list[dict]:
        return [self.insert(r) for r in records]

    def update(self, pk_value: Any, changes: dict) -> dict | None:
        rows = self._rows_with_header()
        if not rows or not rows[0]:
            return None
        header = rows[0]
        idx = self._find_index(rows[1:], pk_value)
        if idx is None:
            return None
        row = list(rows[idx + 1])
        for col, val in changes.items():
            if col in header:
                row[header.index(col)] = _cell_encode(val)
        rows[idx + 1] = row
        # rewrite body
        self.store.sheets.clear_tab(self.tab)
        self.store.sheets.append_rows(self.tab, rows)
        return self._to_dict(row)

    def delete(self, pk_value: Any) -> bool:
        rows = self._rows_with_header()
        if not rows or not rows[0]:
            return False
        idx = self._find_index(rows[1:], pk_value)
        if idx is None:
            return False
        del rows[idx + 1]
        self.store.sheets.clear_tab(self.tab)
        if len(rows) > 1:
            self.store.sheets.append_rows(self.tab, rows)
        else:
            self.store.sheets.append_rows(self.tab, [rows[0]])
        return True

    # -- aggregation helpers (replaces common SQL) --------------------------
    def count(self, **equals) -> int:
        return len(self.find(**equals))

    def sum_column(self, col: str, **equals) -> float:
        total = 0.0
        for rec in self.find(**equals):
            v = rec.get(col)
            try:
                total += float(v)
            except (TypeError, ValueError):
                continue
        return total


class SheetRelational:
    """Facade: a SheetRelation per table, discovered/created on the sheet."""

    def __init__(self, sheets: SheetsStorage):
        self.sheets = sheets
        self._relations: dict[str, SheetRelation] = {}

    def define(self, tab: str, columns: list[str], pk: str = "") -> SheetRelation:
        rel = SheetRelation(self, tab, columns, pk)
        self._relations[tab] = rel
        return rel

    def table(self, tab: str) -> SheetRelation:
        if tab not in self._relations:
            raise KeyError(f"relation '{tab}' not defined")
        return self._relations[tab]

    @property
    def relations(self) -> dict[str, SheetRelation]:
        return self._relations

    def ensure_tab(self, tab: str, columns: list[str], pk: str = "") -> SheetRelation:
        """Create a real tab if it does not exist; write header row when new."""
        titles = self.sheets.tabs()
        if tab not in titles:
            self.sheets._spreadsheet.add_worksheet(
                title=tab, rows=1, cols=max(len(columns), 1))
            blank = self.sheets.tabs()  # re-query
            self.sheets.append_rows(tab, [columns])
        rel = self.define(tab, columns, pk)
        return rel