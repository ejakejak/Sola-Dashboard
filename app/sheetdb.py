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

    # NOTE: the old _write() full-tab rewrite (clear_tab + re-append) was removed.
        # It had zero callers and was the remaining carrier of the destructive
        # two-step non-atomic overwrite documented in gspread issue #781, which can
        # lose rows when the read it is based on is stale. Do not reintroduce a
        # whole-tab rewrite to change one row — use update()/delete(), which are
        # targeted and guarded.

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
            # Guard the PK COLUMN index, not the row index. The previous
            # `i < len(row)` compared a row index against a column count, so the
            # scan aborted once i reached the column count — on a 3-column tab
            # only the first 3 rows were ever findable, and update()/delete()
            # silently no-op'd on everything after. Production sheets hit this
            # too: invoice_items has 8 columns, so only its first 8 rows were
            # updatable.
            if self._pk_idx < len(row) and _cell_encode(row[self._pk_idx]) == needle:
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

    def _invalidate(self, tab: str | None = None) -> None:
        """Drop the storage read cache for this tab (no-op on local storage)."""
        fn = getattr(self.store.sheets, "_invalidate", None)
        if callable(fn):
            fn(tab if tab is not None else self.tab)

    def _fresh_rows(self) -> list[list]:
        """Read the tab, bypassing (and invalidating) any cached copy."""
        self._invalidate(self.tab)
        return self._rows_with_header()

    @staticmethod
    def _pk_key(value) -> str:
        """Normalise a pk for comparison (a sheet may return int or str)."""
        return str(value).strip()

    def insert(self, record: dict) -> dict:
        """Append a record. Local PK + autoincrement if pk is empty and numeric."""
        return self._insert_many([record])[0]

    def multi_insert(self, records: list[dict]) -> list[dict]:
        """Append many records in ONE append call; return them with assigned pks.

        Never loops ``insert()``: one append per row is one network round trip
        each, so an N-item request can time out server-side part way through and
        silently persist only some of the rows. One call plus a verify-after-
        write pass turns a partial write into a loud RuntimeError.
        """
        return self._insert_many(list(records))

    def _insert_many(self, records: list[dict]) -> list[dict]:
        """Shared insert path: one tab read, sequential pk allocation, one
        append, then verify every assigned pk actually landed."""
        recs = [dict(r) for r in records]
        if not recs:
            return []
        if self.pk_col and any(not r.get(self.pk_col) for r in recs):
            existing = [r.get(self.pk_col) for r in self.read_all()]
            nums = [int(v) for v in existing if v is not None and str(v).isdigit()]
            next_pk = (max(nums) + 1) if nums else 1
            for rec in recs:
                if not rec.get(self.pk_col):
                    rec[self.pk_col] = next_pk
                    next_pk += 1
        self.store.sheets.append_rows(self.tab, [self._to_row(r) for r in recs])
        self._invalidate(self.tab)
        self._verify_pks_present([r[self.pk_col] for r in recs if self.pk_col in r])
        return recs

    def _verify_pks_present(self, pks) -> None:
        """Verify-after-write: re-read the tab and confirm every pk landed.

        Scans every returned row (including a header row, whose pk cell holds the
        pk column name and so can never match a numeric pk) so this is correct
        for both headered tabs and brand-new ones that have no header yet.
        """
        wanted = [self._pk_key(pk) for pk in pks]
        if not wanted:
            return
        found = {self._pk_key(row[self._pk_idx])
                 for row in self._fresh_rows() if len(row) > self._pk_idx}
        missing = [pk for pk, key in zip(pks, wanted) if key not in found]
        if missing:
            raise RuntimeError(
                f"sheetdb write verification failed on '{self.tab}': wrote "
                f"{len(pks)} row(s) (pks {list(pks)}) but {len(pks) - len(missing)} "
                f"confirmed present; missing pks {missing}")

    def update(self, pk_value: Any, changes: dict) -> dict | None:
        """Update fields on the row with pk==pk_value; return updated row or None.

        Writes only the changed cells via ``update_cell``. The previous
        clear_tab + re-append-the-whole-tab rewrite could clobber unrelated rows
        whenever the read it based itself on was stale.
        """
        rows = self._rows_with_header()
        if not rows or not rows[0]:
            return None
        header = rows[0]
        idx = self._find_index(rows[1:], pk_value)
        if idx is None:
            return None
        sheet_row = idx + 2  # header occupies sheet row 1
        row = list(rows[idx + 1])
        for col, val in changes.items():
            if col in header:
                c = header.index(col) + 1
                self.store.sheets.update_cell(self.tab, sheet_row, c,
                                              _cell_encode(val))
                row[c - 1] = _cell_encode(val)
        self._invalidate(self.tab)
        fresh = self._rows_with_header()
        if len(fresh) > idx + 1:
            return self._to_dict(fresh[idx + 1])
        return self._to_dict(row)

    def delete(self, pk_value: Any) -> bool:
        """Delete the row with pk==pk_value. True if deleted.

        Uses the worksheet's targeted ``delete_rows`` rather than rewriting the
        tab, and re-reads immediately before deleting so a stale index can never
        take out a row other than the intended one.
        """
        rows = self._rows_with_header()
        if not rows or not rows[0]:
            return False
        idx = self._find_index(rows[1:], pk_value)
        if idx is None:
            return False
        row_index = idx + 1  # 0-based; header occupies 0

        # Guard: the tab can shift between the read above and the delete. Re-read
        # fresh and refuse to delete unless this index still holds our pk.
        fresh = self._fresh_rows()
        if len(fresh) <= row_index or len(fresh[row_index]) <= self._pk_idx:
            raise RuntimeError(
                f"sheetdb delete aborted on '{self.tab}': row {row_index + 1} "
                f"disappeared while deleting pk={pk_value!r}")
        if not self._val_eq(fresh[row_index][self._pk_idx], pk_value):
            raise RuntimeError(
                f"sheetdb delete aborted on '{self.tab}': expected pk={pk_value!r} "
                f"at row {row_index + 1} but found "
                f"{fresh[row_index][self._pk_idx]!r}; refusing to delete another row")

        self._delete_row(row_index)
        self._invalidate(self.tab)
        return True

    def _delete_row(self, row_index: int) -> None:
            """Remove sheet row ``row_index`` (0-based, header at 0) in place.

            Prefers the worksheet's targeted ``delete_rows`` so no other row in the
            tab is touched. Backends whose worksheet cannot delete rows in place
            (offline/local fakes) fall back to a header-preserving rewrite.
            """
            connect = getattr(self.store.sheets, "connect", None)
            if callable(connect):
                _, sh = connect()
                ws = sh.worksheet(self.tab)
                delete_rows = getattr(ws, "delete_rows", None)
                if callable(delete_rows):
                    delete_rows(row_index)
                    return
            rows = self._rows_with_header()
            keep = rows[:row_index] + rows[row_index + 1:]
            self.store.sheets.clear_tab(self.tab)
            self.store.sheets.append_rows(self.tab, keep)

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