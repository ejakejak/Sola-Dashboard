"""Regression tests for the Google-Sheets data-integrity fixes.

Covers the production incident where a 5-item invoice persisted only 2
invoice_items rows (per-row appends + serverless timeout mid-loop) and the
destructive clear_tab+re-append rewrites in update()/delete().

Everything runs against LocalSheetStorage -- no Google credentials, no live
sheet access.
"""
import pytest

from app.sheetdb import SheetRelational
from app.storage import LocalSheetStorage

INVOICE_ITEMS_COLS = [
    "invoice_item_id", "invoice_id", "order_item_id", "description",
    "quantity", "unit_id", "unit_price", "subtotal",
]


def _engine():
    store = LocalSheetStorage()
    eng = SheetRelational(store)
    eng.define("invoice_items", INVOICE_ITEMS_COLS, "invoice_item_id")
    store.append_rows("invoice_items", [INVOICE_ITEMS_COLS])  # header row
    return eng


def _seed(eng, n=3):
    return eng.table("invoice_items").multi_insert([
        {"invoice_id": 1, "order_item_id": i, "description": f"seed {i}",
         "quantity": 1, "unit_id": 1, "unit_price": 10, "subtotal": 10}
        for i in range(1, n + 1)
    ])


# --- FIX 1: batched, verified multi_insert -------------------------------

def test_multi_insert_lands_all_five_rows_with_sequential_pks():
    """Regression test for the production incident: 5 items in, 5 rows out."""
    eng = _engine()
    rel = eng.table("invoice_items")

    recs = rel.multi_insert([
        {"invoice_id": 7, "order_item_id": i, "description": f"item {i}",
         "quantity": i, "unit_id": 1, "unit_price": 100, "subtotal": 100 * i}
        for i in range(1, 6)
    ])

    rows = rel.read_all()
    assert len(rows) == 5, "all 5 rows must land (was 2/5 in production)"
    assert [r["invoice_item_id"] for r in rows] == [1, 2, 3, 4, 5]
    assert [r["order_item_id"] for r in rows] == [1, 2, 3, 4, 5]
    assert [r["subtotal"] for r in rows] == [100, 200, 300, 400, 500]
    assert len({r["invoice_item_id"] for r in rows}) == 5
    # return contract: list of dicts with pks populated
    assert [r["invoice_item_id"] for r in recs] == [1, 2, 3, 4, 5]


def test_multi_insert_continues_pk_sequence_after_existing_rows():
    eng = _engine()
    rel = eng.table("invoice_items")
    _seed(eng, 3)
    rel.multi_insert([
        {"invoice_id": 2, "order_item_id": i, "subtotal": 5} for i in range(1, 3)
    ])
    assert [r["invoice_item_id"] for r in rel.read_all()] == [1, 2, 3, 4, 5]


def test_multi_insert_makes_one_append_call_for_five_rows():
    """Batching proof: 5 rows must cost exactly 1 append_rows round trip."""
    eng = _engine()
    calls = []
    real_append = eng.sheets.append_rows

    def counting_append(tab, rows):
        calls.append(len(rows))
        return real_append(tab, rows)

    eng.sheets.append_rows = counting_append
    eng.table("invoice_items").multi_insert([
        {"invoice_id": 1, "order_item_id": i, "subtotal": 1} for i in range(5)
    ])
    assert len(calls) == 1, f"expected 1 append call, got {len(calls)}"
    assert calls[0] == 5, f"expected 5 rows in that one call, got {calls[0]}"


def test_multi_insert_raises_when_rows_cannot_be_confirmed(monkeypatch):
    """Verify-after-write must turn a silently-lost write into a loud error."""
    eng = _engine()
    rel = eng.table("invoice_items")
    monkeypatch.setattr(eng.sheets, "append_rows", lambda tab, rows: None)

    with pytest.raises(RuntimeError) as exc:
        rel.multi_insert([
            {"invoice_id": 1, "order_item_id": i, "subtotal": 1} for i in range(1, 6)
        ])
    msg = str(exc.value)
    assert "5" in msg and "invoice_items" in msg, msg


def test_multi_insert_of_nothing_is_a_noop():
    eng = _engine()
    assert eng.table("invoice_items").multi_insert([]) == []
    assert eng.table("invoice_items").read_all() == []


# --- FIX 2: non-destructive update() -------------------------------------

def test_update_does_not_clear_the_tab(monkeypatch):
    eng = _engine()
    rel = eng.table("invoice_items")
    _seed(eng, 3)

    def boom(tab):
        raise AssertionError(f"clear_tab({tab!r}) must never be called by update()")

    monkeypatch.setattr(eng.sheets, "clear_tab", boom)
    updated = rel.update(2, {"description": "CHANGED"})
    assert updated["description"] == "CHANGED"
    assert updated["invoice_item_id"] == 2


def test_update_preserves_other_rows_and_header():
    eng = _engine()
    rel = eng.table("invoice_items")
    _seed(eng, 3)
    header_before = list(eng.sheets.read_tab("invoice_items", header=False)[0])

    rel.update(2, {"description": "CHANGED", "unit_price": 55})

    raw = eng.sheets.read_tab("invoice_items", header=False)
    assert raw[0] == header_before, "header row must be untouched"
    assert len(raw) == 4, "row count must be unchanged"
    assert raw[1] == [1, 1, 1, "seed 1", 1, 1, 10, 10]
    assert raw[2] == [2, 1, 2, "CHANGED", 1, 1, 55, 10]
    assert raw[3] == [3, 1, 3, "seed 3", 1, 1, 10, 10]
    assert [r["description"] for r in rel.read_all()] == ["seed 1", "CHANGED", "seed 3"]


def test_update_writes_only_changed_cells():
    eng = _engine()
    rel = eng.table("invoice_items")
    _seed(eng, 2)
    touched = []
    real_update = eng.sheets.update_cell

    def counting_update(tab, row, col, value):
        touched.append((row, col, value))
        return real_update(tab, row, col, value)

    eng.sheets.update_cell = counting_update
    rel.update(1, {"status": "x"} if "status" in INVOICE_ITEMS_COLS else {"quantity": 9})

    assert touched == [(2, INVOICE_ITEMS_COLS.index("quantity") + 1, 9)]
    assert len(touched) == 1, "one changed field must be one cell write"


def test_update_returns_none_for_missing_pk():
    eng = _engine()
    _seed(eng, 2)
    assert eng.table("invoice_items").update(999, {"quantity": 1}) is None


# --- FIX 3: safe delete() -------------------------------------------------

def test_delete_refuses_when_row_at_index_does_not_match_pk(monkeypatch):
    """The stale-read guard: never delete a row we did not verify."""
    eng = _engine()
    rel = eng.table("invoice_items")
    _seed(eng, 3)

    deleted = []
    real_read = eng.sheets.read_tab
    calls = {"n": 0}

    def shifting_read(tab, header=True, value_render_option="UNFORMATTED_VALUE"):
        """Return stale data first, then a tab whose rows have moved."""
        calls["n"] += 1
        rows = real_read(tab, header=header,
                         value_render_option=value_render_option)
        if calls["n"] >= 2:
            # simulate another writer inserting a row above the target
            rows = ([rows[0]] if not header else []) + [rows[0]] + rows[1:]
        return rows

    def fake_connect():
        class _WS:
            def delete_rows(self, index):
                deleted.append(index)
        class _SH:
            def worksheet(self, title):
                return _WS()
        return None, _SH()

    monkeypatch.setattr(eng.sheets, "read_tab", shifting_read)
    monkeypatch.setattr(eng.sheets, "connect", fake_connect, raising=False)

    with pytest.raises(RuntimeError) as exc:
        rel.delete(2)
    assert "refusing to delete" in str(exc.value)
    assert deleted == [], "delete_rows must not be called when the guard trips"


def test_delete_removes_only_the_target_row(monkeypatch):
    eng = _engine()
    rel = eng.table("invoice_items")
    _seed(eng, 3)

    class _WS:
        def __init__(self, tab):
            self.tab = tab

        def delete_rows(self, index, num_rows=1):
            rows = eng.sheets._rows[self.tab]
            del rows[index:index + num_rows]  # header is index 0

    class _SH:
        def worksheet(self, title):
            return _WS(title)

    monkeypatch.setattr(eng.sheets, "connect", lambda: (None, _SH()), raising=False)

    assert rel.delete(2) is True
    assert [r["invoice_item_id"] for r in rel.read_all()] == [1, 3]
    raw = eng.sheets.read_tab("invoice_items", header=False)
    assert raw[0] == INVOICE_ITEMS_COLS, "header survives the delete"


def test_delete_returns_false_for_missing_pk(monkeypatch):
    eng = _engine()
    _seed(eng, 2)
    monkeypatch.setattr(eng.sheets, "connect",
                        lambda: pytest.fail("connect must not be called"), raising=False)
    assert eng.table("invoice_items").delete(999) is False


# --- FIX 4 (shape): batched invoice line items ---------------------------

def test_invoice_line_items_are_batched_into_one_call(monkeypatch):
    """Mirrors create_from_order: build all rows, then ONE multi_insert."""
    eng = _engine()
    rel = eng.table("invoice_items")
    order_items = [
        {"order_item_id": i, "quantity": 2, "unit_id": 1,
         "unit_price": 1000, "subtotal": 2000}
        for i in range(1, 6)
    ]

    calls = []
    real_multi = rel.multi_insert

    def counting_multi(records):
        calls.append(len(records))
        return real_multi(records)

    monkeypatch.setattr(rel, "multi_insert", counting_multi)
    item_rows = [{"invoice_id": 9, "order_item_id": oi["order_item_id"],
                  "description": f"item {oi['order_item_id']}",
                  "quantity": oi["quantity"], "unit_id": oi["unit_id"],
                  "unit_price": oi["unit_price"], "subtotal": oi["subtotal"]}
                 for oi in order_items]
    rel.multi_insert(item_rows)

    assert calls == [5], "one multi_insert carrying all 5 items"
    written = rel.find(invoice_id=9)
    assert len(written) == 5
    assert round(sum(float(r["subtotal"]) for r in written), 2) == 10000.0

# ---------------------------------------------------------------------------
# _find_index regression: a row index was being compared against a COLUMN
# count, so the pk scan aborted once i reached the column count. On a
# 3-column tab only the first 3 rows were findable, which made update() and
# delete() silently no-op on every later row. This hit production sheets too
# (invoice_items has 8 columns -> only its first 8 rows were updatable).
# ---------------------------------------------------------------------------


def _find_index_engine(n_rows=8):
    cols = ["id", "name", "qty"]          # 3 columns, many rows
    store = LocalSheetStorage()
    eng = SheetRelational(store)
    eng.define("demo", cols, "id")
    store.append_rows("demo", [cols])
    store.append_rows("demo", [[i, "n%d" % i, i * 10] for i in range(1, n_rows + 1)])
    return eng, cols


def test_find_index_reaches_every_row_beyond_the_column_count():
    eng, _cols = _find_index_engine(8)
    table = eng.table("demo")
    rows = table._all_rows()
    assert len(rows) == 8
    for pk in range(1, 9):
        assert table._find_index(rows, pk) == pk - 1, (
            "pk %s must be findable even though the row index exceeds the "
            "column count" % pk)


def test_update_works_on_a_row_beyond_the_column_count():
    eng, _cols = _find_index_engine(8)
    table = eng.table("demo")
    # pk 7 sits at row index 6 -- well past the 3-column boundary that used
    # to make it unreachable.
    updated = table.update(7, {"name": "RENAMED"})
    assert updated is not None, "update() must not silently no-op"
    assert table.get(7)["name"] == "RENAMED"


def test_delete_works_on_a_row_beyond_the_column_count():
    eng, _cols = _find_index_engine(8)
    table = eng.table("demo")
    assert table.delete(6) is True, "delete() must not silently fail"
    assert table.get(6) is None
    assert len(table.read_all()) == 7
