#!/usr/bin/env python3
"""SOLA live Google Sheet <-> SQLite two-way master-data sync.

The Google Sheet 'MASTER DATA SOLA 1.0' (SPREADSHEET_ID) is the SOURCE OF TRUTH
for master data (materials, prices, processes, categories, colors, sizes, units,
agents, vendors, vendor capabilities, commission templates). This module:

  PULL    (-pull)          sheet -> DB : authoritative full-replace of the import
                                        domain, reusing scripts/import_excel.py
                                        normalization (NOT reinvented).
  PUSH    (-push)          DB    -> sheet : opt-in reverse for the FLAT tabs that map
                                        1:1 to app tables (DATABASE AGEN -> agents,
                                        DATABASE PENJAHIT/MAKLOON -> vendors).
  COMPARE (-compare)       report diffs between the sheet and the target DB (no writes).

Tab-name reconciliation: the live sheet's vendor tab is 'DATABASE PENJAHIT/MAKLOON'
(with a slash) while the local xlsx snapshot uses 'DATABASE PENJAHITMAKLOON' (no
slash). import_excel.run_migration_from_workbook resolves this dynamically, so BOTH
sources work through the SAME import path (xlsx path is unchanged / backward-compatible).

Direction of authority (see docs/SYNC.md):
  * PULL  : sheet wins. The import domain tables are re-derived from the sheet.
  * PUSH  : the app wins, but ONLY for agent/vendor rows on their flat tabs. Pivot
            tabs (HPP, Sheet3) and MASTER HPP are pull-only (their layout is a
            derived normalization; reconstructing it from the relational DB would be
            lossy for context-variant codes). NO master value flows down on push.

Safety:
  * -dry-run on PULL runs the import into an isolated TEMP DB (never touches
    D:/Sola/instance/sola.db) and reports counts without committing.
  * -dry-run on PUSH/COMPARE computes the would-be sheet writes without writing.
  * A real PULL/PUSH to the live DB/sheet requires -yes (and never runs in tests).

Exit 0 on success, 1 on any error.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import gspread  # noqa: E402

from scripts import import_excel as imp  # noqa: E402
from scripts.import_excel import (  # noqa: E402
    run_migration_from_workbook,
    REPORT,
)

DEFAULT_SHEET_ID = "1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA"
DEFAULT_CREDENTIALS = os.path.join(BASE, "instance", "sola-509413-service-account.json")
DEFAULT_DB = os.path.join(BASE, "instance", "sola.db")
DEFAULT_SCHEMA = os.path.join(BASE, "db", "schema.sql")
DEFAULT_REPORT = os.path.join(BASE, "migrations", "migration_report.json")

# Live sheet tabs (exact names registered for a helpful read-back / probe).
VENDOR_TAB = "DATABASE PENJAHIT/MAKLOON"
AGENT_TAB = "DATABASE AGEN"


# ---------------------------------------------------------------------------
# Sheet -> openpyxl-compatible adapter (typed cells like openpyxl data_only load)
# ---------------------------------------------------------------------------
class _Cell:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class SheetWorksheet:
    """openpyxl-like view of a gspread worksheet (cached 2D typed values)."""

    def __init__(self, title, values):
        self.title = title
        self._data = values

    @property
    def max_row(self):
        return len(self._data)

    @property
    def max_column(self):
        return max((len(r) for r in self._data), default=0)

    def cell(self, row, column):  # 1-indexed
        if row < 1 or row > len(self._data):
            return _Cell(None)
        r = self._data[row - 1]
        if column < 1 or column > len(r):
            return _Cell(None)
        return _Cell(r[column - 1])


class SheetWorkbook:
    def __init__(self, gs):
        # UNFORMATTED_VALUE reproduces the typed cells openpyxl reads with
        # data_only=True (numbers => int/float, not '23.000' display strings), so
        # import_excel's normalization (phones, '-', Fee, thousand-separators) is
        # identical to the local xlsx path.
        self._tabs = {
            ws.title: SheetWorksheet(ws.title, ws.get_all_values(value_render_option="UNFORMATTED_VALUE"))
            for ws in gs.worksheets()
        }

    @property
    def sheetnames(self):
        return list(self._tabs)

    def __getitem__(self, name):
        return self._tabs[name]


def open_sheet(sheet_id=DEFAULT_SHEET_ID, credentials=DEFAULT_CREDENTIALS):
    creds = credentials or DEFAULT_CREDENTIALS
    if not os.path.isfile(creds):
        raise FileNotFoundError(f"service-account key not found: {creds}")
    gc = gspread.service_account(filename=creds)
    sh = gc.open_by_key(sheet_id or DEFAULT_SHEET_ID)
    return sh


def load_sheet_workbook(gs):
    return SheetWorkbook(gs)


# ---------------------------------------------------------------------------
# PULL
# ---------------------------------------------------------------------------
def pull(sheet_id, credentials, db_path, schema, report_path):
    """sheet -> DB. Full replace of the import domain (authoritative)."""
    sh = open_sheet(sheet_id, credentials)
    wb = load_sheet_workbook(sh)
    return run_migration_from_workbook(wb, db_path, schema, report_path)


def pull_to_temp(sheet_id, credentials, schema=DEFAULT_SCHEMA, report_path=None):
    """Run the pull into an isolated temp DB; returns (payload, temp_file)."""
    tmpdir = tempfile.mkdtemp(prefix="sola_sync_")
    tmp_db = os.path.join(tmpdir, "sola.db")
    tmp_report = report_path or os.path.join(tmpdir, "migration_report.json")
    try:
        payload = pull(sheet_id, credentials, tmp_db, schema, tmp_report)
        payload["_tmpdir"] = tmpdir
        payload["_db"] = tmp_db
        return payload
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# Diff helpers (used by COMPARE and PUSH planning)
# ---------------------------------------------------------------------------
def _digits(v):
    """Canonical 'phone digits' for equality (leading zero stripped)."""
    if v is None:
        return None
    return "".join(ch for ch in str(v) if ch.isdigit()).lstrip("0") or "0"


def _cellstr(v):
    if v is None:
        return None
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return str(v).strip()


def _agent_key(row):
    return imp.norm_text(row.get("name"))


def _vendor_key(row):
    return imp.norm_text(row.get("vendor_name"))


def _load_agents(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM agents")]
    conn.close()
    return rows


def _load_vendors(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM vendors")]
    conn.close()
    return rows


def _sheet_agents(gs):
    """Live sheet agent rows by canonical name."""
    ws = gs.worksheet(AGENT_TAB)
    vals = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    out = {}
    for row in vals[1:]:
        name = imp.norm_text(row[0]) if len(row) >= 1 else None
        if not name:
            continue
        out[name] = {
            "name": name,
            "address": imp.norm_text(row[1]) if len(row) >= 2 else None,
            "phone": _sheet_phone(row[2]) if len(row) >= 3 else None,
            "faculty": imp.norm_text(row[3]) if len(row) >= 4 else None,
            "campus": imp.norm_text(row[4]) if len(row) >= 5 else None,
        }
    return out


def _sheet_vendors(gs):
    """Live sheet vendor rows by canonical name."""
    ws = gs.worksheet(VENDOR_TAB)
    vals = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    out = {}
    for row in vals[1:]:
        name = imp.norm_text(row[0]) if len(row) >= 1 else None
        if not name:
            continue
        out[name] = {
            "name": name,
            "address": imp.norm_text(row[1]) if len(row) >= 2 else None,
            "phone": _sheet_phone(row[2]) if len(row) >= 3 else None,
            "specialization": imp.norm_text(row[3]) if len(row) >= 4 else None,
        }
    return out


AGENT_FIELDS = [("address", 2), ("phone", 3), ("faculty", 4), ("campus", 5)]
VENDOR_FIELDS = [("address", 2), ("phone", 3), ("specialization", 4)]


def _sheet_phone(v):
    """Sheet phone cell -> canonical digits or None ('-' and empty mean NULL)."""
    if v is None:
        return None
    if isinstance(v, str) and v.strip() in ("", "-"):
        return None
    d = _digits(v)
    return None if d in (None, "0") else d


def _diff_flat(sheet_rows, db_rows, key_fn, fields):
    """Diff flat rows keyed by canonical name.

    Returns {"only_sheet":[...], "only_db":[...], "changed":[{name,changed_fields,values}]}.
    """
    only_sheet = []
    only_db = []
    changed = []
    for key, sr in sheet_rows.items():
        if key not in db_rows:
            only_sheet.append(key)
    for key, dr in db_rows.items():
        if key not in sheet_rows:
            only_db.append(key)
        else:
            diffs = []
            vals = {}
            for fname, _col in fields:
                sval = sheet_rows[key].get(fname)
                dval = dr.get(fname)
                if fname == "phone":
                    s_norm, d_norm = _digits(sval), _digits(dval)
                else:
                    s_norm, d_norm = _cellstr(sval), _cellstr(dval)
                if s_norm != d_norm:
                    diffs.append(fname)
                    vals[fname] = {"sheet": sval, "db": dval}
            if diffs:
                changed.append({"name": key, "changed_fields": diffs, "values": vals})
    return {"only_sheet": sorted(only_sheet), "only_db": sorted(only_db), "changed": changed}


def compute_diffs(gs, db_path):
    """sheet vs DB for the flat pushable tabs (agents, vendors)."""
    sa = _sheet_agents(gs)
    da = {_agent_key(a): a for a in _load_agents(db_path)}
    sv = _sheet_vendors(gs)
    dv = {_vendor_key(v): v for v in _load_vendors(db_path)}
    return {
        "agents": _diff_flat(sa, da, _agent_key, AGENT_FIELDS),
        "vendors": _diff_flat(sv, dv, _vendor_key, VENDOR_FIELDS),
    }


# ---------------------------------------------------------------------------
# Reconcile (SAFE live pull): snapshot(sheet) -> live DB by natural keys.
# Never deletes master rows that dependent business tables reference. This is
# the correct semantic for pulling into the running sola.db (which has products,
# variants, inventory, orders, ... FK-referencing the import domain).
# ---------------------------------------------------------------------------
# Tables in the live DB that reference import-domain masters (must stay non-empty
# clears only never run): if ANY has rows, full replace is forbidden.
_FK_DEPENDENT_TABLES = [
    "inventory", "product_variants", "material_colors", "material_usage",
    "stock_movements", "order_items", "quotation_items", "customers", "orders",
    "products", "production_orders", "payments", "invoices",
]


def _ensure_conn(path):
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    return c


def reconcile_from_snapshot(snap_db, live_db):
    """Apply the sheet-snapshot master data into the live DB by natural key (upsert).

    Returns a dict of counts per table: {table: {"inserted": n, "updated": n}}.
    Depended-on business tables are never deleted or re-created; only master
    values are brought in line with the sheet snapshot.
    """
    snap = _ensure_conn(snap_db)
    live = _ensure_conn(live_db)
    try:
        # 1) lookups + categories + materials + processes (parents first)
        def upsert_lookup(table, code_col, name_col):
            ins = upd = 0
            for r in snap.execute(f"SELECT {code_col},{name_col} FROM {table}"):
                code, name = r[0], r[1]
                row = live.execute(f"SELECT rowid FROM {table} WHERE {code_col}=?", (code,)).fetchone()
                if row:
                    live.execute(f"UPDATE {table} SET {name_col}=? WHERE {code_col}=?", (name, code))
                    upd += 1
                else:
                    live.execute(f"INSERT INTO {table}({code_col},{name_col}) VALUES(?,?)", (code, name))
                    ins += 1
            return {"inserted": ins, "updated": upd}

        def upsert_sizes(table):
            ins = upd = 0
            for r in snap.execute(f"SELECT size_code FROM {table}"):
                code = r[0]
                if live.execute(f"SELECT rowid FROM {table} WHERE size_code=?", (code,)).fetchone():
                    upd += 1
                else:
                    live.execute(f"INSERT INTO {table}(size_code) VALUES (?)", (code,))
                    ins += 1
            return {"inserted": ins, "updated": upd}

        res = {}
        res["units"] = upsert_lookup("units", "unit_code", "unit_name")
        res["sizes"] = upsert_sizes("sizes")
        res["colors"] = upsert_lookup("colors", "color_code", "color_name")

        # categories
        cc = {"inserted": 0, "updated": 0}
        for r in snap.execute("SELECT category_name, description FROM product_categories"):
            row = live.execute("SELECT category_id FROM product_categories WHERE category_name=?",
                               (r["category_name"],)).fetchone()
            if row:
                live.execute("UPDATE product_categories SET description=? WHERE category_id=?",
                             (r["description"], row["category_id"]))
                cc["updated"] += 1
            else:
                live.execute("INSERT INTO product_categories(category_name, description) VALUES(?,?)",
                             (r["category_name"], r["description"]))
                cc["inserted"] += 1
        live.commit()
        res["product_categories"] = cc

        snap_cat = {r["category_name"]: r["category_id"] for r in snap.execute("SELECT category_id, category_name FROM product_categories")}
        live_cat = {r["category_name"]: r["category_id"] for r in live.execute("SELECT category_id, category_name FROM product_categories")}

        # materials (by material_code, fallback name)
        mc = {"inserted": 0, "updated": 0}
        for r in snap.execute("SELECT material_id, material_code, material_name, category, status, specification, unit_id, gramasi, width, supplier FROM materials"):
            row = live.execute("SELECT material_id FROM materials WHERE material_code=?",
                               (r["material_code"],)).fetchone()
            if row is None:
                row = live.execute("SELECT material_id FROM materials WHERE material_name=?",
                                   (r["material_name"],)).fetchone()
            if row:
                live.execute(
                    "UPDATE materials SET material_name=?, category=?, status=?, specification=?, gramasi=?, width=?, supplier=? WHERE material_id=?",
                    (r["material_name"], r["category"], r["status"], r["specification"],
                     r["gramasi"], r["width"], r["supplier"], row["material_id"]))
                mc["updated"] += 1
            else:
                cur = live.execute(
                    "INSERT INTO materials(material_code,material_name,category,status,specification,gramasi,width,supplier) VALUES(?,?,?,?,?,?,?,?)",
                    (r["material_code"], r["material_name"], r["category"], r["status"],
                     r["specification"], r["gramasi"], r["width"], r["supplier"]))
                mc["inserted"] += 1
        live.commit()
        res["materials"] = mc

        # material_id map: code -> live id (may differ between snap and live)
        live_mat_code = {r["material_code"]: r["material_id"] for r in live.execute("SELECT material_id, material_code FROM materials")}
        live_mat_name = {r["material_name"]: r["material_id"] for r in live.execute("SELECT material_id, material_name FROM materials")}

        # processes (by process_code)
        pc = {"inserted": 0, "updated": 0}
        for r in snap.execute("SELECT process_code, process_name, default_cost, category, status, estimated_duration, unit_id FROM processes"):
            row = live.execute("SELECT process_id FROM processes WHERE process_code=?", (r["process_code"],)).fetchone()
            if row:
                live.execute("UPDATE processes SET process_name=?, default_cost=?, category=?, status=?, estimated_duration=?, unit_id=? WHERE process_id=?",
                             (r["process_name"], r["default_cost"], r["category"], r["status"],
                              r["estimated_duration"], r["unit_id"], row["process_id"]))
                pc["updated"] += 1
            else:
                live.execute("INSERT INTO processes(process_code,process_name,default_cost,category,status,estimated_duration,unit_id) VALUES(?,?,?,?,?,?,?)",
                             (r["process_code"], r["process_name"], r["default_cost"], r["category"],
                              r["status"], r["estimated_duration"], r["unit_id"]))
                pc["inserted"] += 1
        live.commit()
        res["processes"] = pc
        live_proc = {r["process_code"]: r["process_id"] for r in live.execute("SELECT process_id, process_code FROM processes")}

        def snap_mid(code, name):
            if code in live_mat_code:
                return live_mat_code[code]
            # context code e.g. DR-AM-KR -> material_code may have been stored as-is
            return live_mat_name.get(name)

        # material_prices (match by material+category, update price; else insert)
        mp = {"inserted": 0, "updated": 0}
        for r in snap.execute("SELECT material_id, category_id, unit_price, currency, valid_from FROM material_prices"):
            mrow = snap.execute("SELECT material_code, material_name FROM materials WHERE material_id=?",
                                (r["material_id"],)).fetchone()
            mid = snap_mid(mrow["material_code"], mrow["material_name"])
            if mid is None:
                continue
            cat_name = None
            if r["category_id"]:
                cat_name = snap.execute("SELECT category_name FROM product_categories WHERE category_id=?",
                                        (r["category_id"],)).fetchone()[0]
            cid = live_cat.get(cat_name) if cat_name else None
            row = live.execute("SELECT material_price_id FROM material_prices WHERE material_id=? AND category_id IS ?",
                               (mid, cid)).fetchone()
            if row:
                live.execute("UPDATE material_prices SET unit_price=?, currency=? WHERE material_price_id=?",
                             (r["unit_price"], r["currency"], row["material_price_id"]))
                mp["updated"] += 1
            else:
                live.execute("INSERT INTO material_prices(material_id,category_id,unit_price,currency) VALUES(?,?,?,?)",
                             (mid, cid, r["unit_price"], r["currency"]))
                mp["inserted"] += 1
        live.commit()
        res["material_prices"] = mp

        # process_prices (match by process_id, update / insert)
        pp = {"inserted": 0, "updated": 0}
        for r in snap.execute("SELECT process_id, unit_price, currency, valid_from FROM process_prices"):
            prow = snap.execute("SELECT process_code FROM processes WHERE process_id=?", (r["process_id"],)).fetchone()
            pid = live_proc.get(prow["process_code"]) if prow else None
            if pid is None:
                continue
            row = live.execute("SELECT process_price_id FROM process_prices WHERE process_id=? ORDER BY process_price_id LIMIT 1", (pid,)).fetchone()
            if row:
                live.execute("UPDATE process_prices SET unit_price=?, currency=? WHERE process_price_id=?", (r["unit_price"], r["currency"], row["process_price_id"]))
                pp["updated"] += 1
            else:
                live.execute("INSERT INTO process_prices(process_id, unit_price, currency) VALUES(?,?,?)", (pid, r["unit_price"], r["currency"]))
                pp["inserted"] += 1
        live.commit()
        res["process_prices"] = pp

        # commission_templates (by product_category)
        ct = {"inserted": 0, "updated": 0}
        for r in snap.execute("SELECT product_category_id, commission_mode, commission_cap, commission_pct, status FROM commission_templates"):
            cat_name = snap.execute("SELECT category_name FROM product_categories WHERE category_id=?",
                                    (r["product_category_id"],)).fetchone()[0] if r["product_category_id"] else None
            cid = live_cat.get(cat_name) if cat_name else None
            if cid is None:
                continue
            row = live.execute("SELECT commission_template_id FROM commission_templates WHERE product_category_id=? ORDER BY commission_template_id LIMIT 1", (cid,)).fetchone()
            if row:
                live.execute("UPDATE commission_templates SET commission_mode=?, commission_cap=?, commission_pct=?, status=? WHERE commission_template_id=?",
                             (r["commission_mode"], r["commission_cap"], r["commission_pct"], r["status"], row["commission_template_id"]))
                ct["updated"] += 1
            else:
                live.execute("INSERT INTO commission_templates(product_category_id,commission_mode,commission_cap,commission_pct,status) VALUES(?,?,?,?,?)",
                             (cid, r["commission_mode"], r["commission_cap"], r["commission_pct"], r["status"]))
                ct["inserted"] += 1
        live.commit()
        res["commission_templates"] = ct

        # agents / vendors (by code)
        ag = {"inserted": 0, "updated": 0}
        for r in snap.execute("SELECT agent_code,name,phone,campus,faculty,address,status FROM agents"):
            row = live.execute("SELECT agent_id FROM agents WHERE agent_code=?", (r["agent_code"],)).fetchone()
            if row:
                live.execute("UPDATE agents SET name=?,phone=?,campus=?,faculty=?,address=?,status=? WHERE agent_id=?",
                             (r["name"], r["phone"], r["campus"], r["faculty"], r["address"], r["status"], row["agent_id"]))
                ag["updated"] += 1
            else:
                live.execute("INSERT INTO agents(agent_code,name,phone,campus,faculty,address,status) VALUES(?,?,?,?,?,?,?)",
                             (r["agent_code"], r["name"], r["phone"], r["campus"], r["faculty"], r["address"], r["status"]))
                ag["inserted"] += 1
        live.commit()
        res["agents"] = ag

        vd = {"inserted": 0, "updated": 0}
        live_vendor_code = {}
        for r in snap.execute("SELECT vendor_code,vendor_name,vendor_type,phone,address,specialization,notes,status,location FROM vendors"):
            row = live.execute("SELECT vendor_id FROM vendors WHERE vendor_code=?", (r["vendor_code"],)).fetchone()
            if row:
                live.execute("UPDATE vendors SET vendor_name=?,vendor_type=?,phone=?,address=?,specialization=?,notes=?,status=?,location=? WHERE vendor_id=?",
                             (r["vendor_name"], r["vendor_type"], r["phone"], r["address"],
                              r["specialization"], r["notes"], r["status"], r["location"], row["vendor_id"]))
                live_vendor_code[r["vendor_code"]] = row["vendor_id"]
                vd["updated"] += 1
            else:
                cur = live.execute("INSERT INTO vendors(vendor_code,vendor_name,vendor_type,phone,address,specialization,notes,status,location) VALUES(?,?,?,?,?,?,?,?,?)",
                                   (r["vendor_code"], r["vendor_name"], r["vendor_type"], r["phone"], r["address"],
                                    r["specialization"], r["notes"], r["status"], r["location"]))
                live_vendor_code[r["vendor_code"]] = cur.lastrowid
                vd["inserted"] += 1
        live.commit()
        res["vendors"] = vd

        # vendor_capabilities (by vendor+capability)
        vc = {"inserted": 0, "updated": 0}
        for r in snap.execute("SELECT vendor_id, capability, price, lead_time, capacity, status FROM vendor_capabilities"):
            vrow = snap.execute("SELECT vendor_code FROM vendors WHERE vendor_id=?", (r["vendor_id"],)).fetchone()
            vid = live_vendor_code.get(vrow["vendor_code"]) if vrow else None
            if vid is None:
                continue
            row = live.execute("SELECT vendor_capability_id FROM vendor_capabilities WHERE vendor_id=? AND capability IS ?",
                               (vid, r["capability"])).fetchone()
            if row:
                live.execute("UPDATE vendor_capabilities SET price=?, lead_time=?, capacity=?, status=? WHERE vendor_capability_id=?",
                             (r["price"], r["lead_time"], r["capacity"], r["status"], row["vendor_capability_id"]))
                vc["updated"] += 1
            else:
                live.execute("INSERT INTO vendor_capabilities(vendor_id,capability,price,lead_time,capacity,status) VALUES(?,?,?,?,?,?)",
                             (vid, r["capability"], r["price"], r["lead_time"], r["capacity"], r["status"]))
                vc["inserted"] += 1
        live.commit()
        res["vendor_capabilities"] = vc

        # cost_components (derived from sheet: process cost per category)
        dc = {"inserted": 0, "updated": 0}
        for r in snap.execute("SELECT component_type, ref_id, product_category_id, unit_cost, currency FROM cost_components"):
            cat_name = snap.execute("SELECT category_name FROM product_categories WHERE category_id=?",
                                    (r["product_category_id"],)).fetchone()[0] if r["product_category_id"] else None
            cid = live_cat.get(cat_name) if cat_name else None
            ref = None
            if r["component_type"] == "process":
                prow = snap.execute("SELECT process_code FROM processes WHERE process_id=?", (r["ref_id"],)).fetchone()
                ref = live_proc.get(prow["process_code"]) if prow else None
            elif r["component_type"] == "material":
                mrow = snap.execute("SELECT material_code, material_name FROM materials WHERE material_id=?", (r["ref_id"],)).fetchone()
                ref = snap_mid(mrow["material_code"], mrow["material_name"]) if mrow else None
            if ref is None:
                continue
            row = live.execute(
                "SELECT cost_component_id FROM cost_components WHERE component_type=? AND ref_id=? AND product_category_id IS ? LIMIT 1",
                (r["component_type"], ref, cid)).fetchone()
            if row:
                live.execute("UPDATE cost_components SET unit_cost=?, currency=? WHERE cost_component_id=?",
                             (r["unit_cost"], r["currency"], row["cost_component_id"]))
                dc["updated"] += 1
            else:
                live.execute("INSERT INTO cost_components(component_type,ref_id,product_category_id,unit_cost,currency) VALUES(?,?,?,?,?)",
                             (r["component_type"], ref, cid, r["unit_cost"], r["currency"]))
                dc["inserted"] += 1
        live.commit()
        res["cost_components"] = dc

        live.execute("PRAGMA foreign_key_check")
        live.commit()
        return res
    finally:
        snap.close()
        live.close()


def target_is_replace_safe(db_path):
    """True only if no live table depends on rows of the import domain (fresh DB)."""
    conn = _ensure_conn(db_path)
    try:
        for t in _FK_DEPENDENT_TABLES:
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.OperationalError:
                continue  # table not present (fresh schema) - fine
            if n:
                return False
        return True
    finally:
        conn.close()


def reconcile_result_ok(_result, db_path):
    """'PASS' if the live DB has zero FK violations after reconcile, else 'VIOLATIONS'."""
    conn = _ensure_conn(db_path)
    try:
        v = conn.execute("PRAGMA foreign_key_check").fetchall()
        return "PASS" if not v else f"VIOLATIONS({len(v)})"
    finally:
        conn.close()


def _phone_for_sheet(db_phone):
    """DB phone ('0895391621335') -> value written to sheet (string keeps leading 0)."""
    if db_phone is None:
        return None
    return str(db_phone)


def _append_content(kind, dbrow):
    if kind == "agents":
        return {
            2: dbrow and dbrow.get("address"),
            3: _phone_for_sheet(dbrow and dbrow.get("phone")),
            4: dbrow and dbrow.get("faculty"),
            5: dbrow and dbrow.get("campus"),
        }
    return {
        2: dbrow and dbrow.get("address"),
        3: _phone_for_sheet(dbrow and dbrow.get("phone")),
        4: dbrow and dbrow.get("specialization"),
    }


def plan_push(gs, db_path, diffs):
    """Translate diffs into concrete sheet ops. 'rownum' None => append a new row.

    Only the agents/vendors flat tabs can be pushed (they map 1:1 to DB tables).
    Pivot tabs (HPP, Sheet3) and MASTER HPP are pull-only (see module docstring).
    """
    ops = []

    def resolve(name, tab):
        ws = gs.worksheet(tab)
        vals = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
        for i, row in enumerate(vals[1:], start=2):
            if imp.norm_text(row[0]) == name:
                return i
        return None

    specs = (
        ("agents", AGENT_FIELDS, AGENT_TAB),
        ("vendors", VENDOR_FIELDS, VENDOR_TAB),
    )
    for kind, fields, tab in specs:
        d = diffs[kind]
        # updates to existing rows
        for entry in d["changed"]:
            cols = {fields[i][1]: entry["values"][fname]["db"]
                    for i, (fname, _col) in enumerate(fields)
                    if fname in entry["changed_fields"]}
            if "phone" in entry["changed_fields"]:
                cols[3] = _phone_for_sheet(entry["values"]["phone"]["db"])
            rownum = resolve(entry["name"], tab)
            ops.append({"tab": tab, "name": entry["name"], "rownum": rownum,
                        "cols": cols, "op": "update" if rownum else "append"})
        # rows present in DB but missing from sheet -> append
        for name in d["only_db"]:
            dbrow = next(
                (r for r in (_load_agents(db_path) if kind == "agents" else _load_vendors(db_path))
                 if (_agent_key if kind == "agents" else _vendor_key)(r) == name),
                None,
            )
            cols = {1: name}
            cols.update(_append_content(kind, dbrow))
            cols = {c: v for c, v in cols.items() if v is not None}  # only real values
            rownum = resolve(name, tab)
            ops.append({"tab": tab, "name": name, "rownum": rownum,
                        "cols": cols, "op": "update" if rownum else "append"})
    return ops


def execute_push(gs, ops):
    """Apply planned ops to the live sheet (REAL write - requires -yes)."""
    written = 0
    for op in ops:
        ws = gs.worksheet(op["tab"])
        if op["rownum"]:
            row = op["rownum"]
        else:
            # first empty row below the header (row 1) in the used range
            vals = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
            row = 1 + (max((i for i, r in enumerate(vals[1:], start=2)
                            if any(str(c).strip() for c in r[:4])), default=1))
            row = row + 1
        for col, val in sorted(op["cols"].items()):
            ws.update_cell(row, col, val)
        written += 1
    return written


# ---------------------------------------------------------------------------
# Read-back helpers for reporting
# ---------------------------------------------------------------------------
def db_counts(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("materials", "processes", "product_categories", "material_prices",
                        "commission_templates", "agents", "vendors", "vendor_capabilities",
                        "cost_components", "process_prices")}
    conn.close()
    return counts


# ---------------------------------------------------------------------------
# Live write probe (scratch marker, then revert) - safe to run repeatedly
# ---------------------------------------------------------------------------
def probe_write(sheet_id=DEFAULT_SHEET_ID, credentials=DEFAULT_CREDENTIALS):
    """Write a marker to a far scratch cell on the agent tab, read back, clear.

    Confirms the service account can WRITE the live sheet without changing any
    real business data (EVA's marker-cell pattern).
    """
    sh = open_sheet(sheet_id, credentials)
    ws = sh.worksheet(AGENT_TAB)
    row = ws.row_count
    marker = f"SYNC-PROBE-{os.getpid()}"
    before = ws.cell(row, 1).value
    ws.update_cell(row, 1, marker)
    readback = ws.cell(row, 1).value
    ws.update_cell(row, 1, before if before not in (None, "") else "")
    cleared = ws.cell(row, 1).value
    return {
        "tab": ws.title,
        "cell": f"{row}:1",
        "before": before,
        "wrote": marker,
        "readback": readback,
        "cleared_value": cleared,
        "ok": readback == marker and (cleared in (before, "", None)),
    }


# ---------------------------------------------------------------------------
# CSV-ish name reconciliation not needed; CLI below
# ---------------------------------------------------------------------------
def _json_dump(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def validate_ids():
    missing = []
    if not os.path.isfile(DEFAULT_CREDENTIALS):
        missing.append(f"service-account key (DEFAULT_CREDENTIALS) not found: {DEFAULT_CREDENTIALS}")
    return missing


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="SOLA live sheet <-> SQLite master-data sync. Sheet = SOURCE OF TRUTH for PULL.",
        epilog="At least one of -pull / -push / -compare / -probe-write is required.",
    )
    ap.add_argument("--pull", action="store_true", help="sheet -> DB (safe reconcile by natural key; never deletes live master rows)")
    ap.add_argument("--push", action="store_true", help="DB -> sheet (agents/vendors flat tabs only)")
    ap.add_argument("--compare", action="store_true", help="report sheet<->DB diffs (no writes)")
    ap.add_argument("--replace", action="store_true",
                    help="with --pull: full wipe+replace (ONLY safe on a fresh DB with no dependent business rows; refuses on the live DB)")
    ap.add_argument("--dry-run", action="store_true", help="no real DB/sheet writes (pull runs in temp DB)")
    ap.add_argument("--yes", action="store_true", help="allow a real (non-dry-run) PULL/PUSH")
    ap.add_argument("--probe-write", action="store_true", help="live scratch write/read/revert probe")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--schema", default=DEFAULT_SCHEMA)
    ap.add_argument("--report", default=DEFAULT_REPORT)
    ap.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    ap.add_argument("--credentials", default=DEFAULT_CREDENTIALS)
    args = ap.parse_args(argv)

    wanted = sum(int(b) for b in (args.pull, args.push, args.compare, args.probe_write))
    if wanted == 0:
        ap.error("nothing to do: pass --pull, --push, --compare, or --probe-write")

    try:
        missing = validate_ids()
        if missing:
            raise RuntimeError("; ".join(missing))

        if args.probe_write:
            result = probe_write(args.sheet_id, args.credentials)
            _json_dump({"probe_write": result})
            return 0 if result["ok"] else 1

        # Live read of the sheet (read-only) - always allowed.
        sh = open_sheet(args.sheet_id, args.credentials)
        wb = load_sheet_workbook(sh)
        print(f"[sheet] {sh.title} tabs: {wb.sheetnames}", file=sys.stderr)

        if args.compare:
            print("[compare] loading live sheet into temp DB (read-only)...", file=sys.stderr)
            payload = pull_to_temp(args.sheet_id, args.credentials, args.schema, None)
            tmp_db = payload["_db"]
            # Target DB (default: live sola.db) vs the sheet-representative snapshot.
            diffs = compute_diffs(sh, args.db)
            _json_dump({
                "mode": "compare",
                "sheet_pull_ok": not payload["errors"],
                "target_db": args.db,
                "target_db_counts": db_counts(args.db),
                "sheet_import_counts": {k: v for k, v in payload["rows_imported"].items() if k.endswith("_count")},
                "diffs": diffs,
            })
            shutil.rmtree(payload["_tmpdir"], ignore_errors=True)
            return 0

        if args.pull:
            if args.dry_run:
                print("[pull --dry-run] importing live sheet into isolated TEMP DB (real DB untouched)...",
                      file=sys.stderr)
                payload = pull_to_temp(args.sheet_id, args.credentials, args.schema, args.report)
                report = {"mode": "pull", "dry_run": True,
                          "temp_import_ok": not payload["errors"],
                          "rows_read": payload["rows_read"],
                          "counts": {k: v for k, v in payload["rows_imported"].items() if k.endswith("_count")},
                          "agents": payload["rows_imported"].get("agents"),
                          "vendors": payload["rows_imported"].get("vendors"),
                          "errors": payload["errors"]}
                _json_dump(report)
                shutil.rmtree(payload["_tmpdir"], ignore_errors=True)
                return 0 if not payload["errors"] else 1
            if not args.yes:
                ap.error("real PULL writes to the target DB; pass --yes to confirm (or use --dry-run)")
            # 1) build the canonical sheet snapshot in an isolated temp DB (reuses import_excel normalization).
            print(f"[pull] building live-sheet snapshot in temp DB...", file=sys.stderr)
            payload = pull_to_temp(args.sheet_id, args.credentials, args.schema, None)
            snap_db = payload["_db"]
            try:
                if args.replace:
                    # Destructive full replace - ONLY valid if no business table depends on master rows.
                    if not target_is_replace_safe(args.db):
                        raise RuntimeError(
                            "REPLACE refused: target DB has business rows that FK-reference the import "
                            "domain (inventory/product_variants/orders/etc.). Use safe reconcile "
                            "(plain --pull, default) instead.")
                    print(f"[pull --replace] full wipe+replace into {args.db}...", file=sys.stderr)
                    shutil.copy2(snap_db, args.db)   # snapshot DB is schema-only + re-imported masters
                else:
                    print(f"[pull] safe reconcile seed->live into {args.db} (no deletes)...", file=sys.stderr)
                    result = reconcile_from_snapshot(snap_db, args.db)
                _json_dump({
                    "mode": "pull", "dry_run": False, "replace": args.replace,
                    "db": args.db,
                    "snapshot_counts": {k: v for k, v in payload["rows_imported"].items() if k.endswith("_count")},
                    "reconcile_result": result if not args.replace else "REPLACED",
                    "fk_check": "PASS" if not args.replace and reconcile_result_ok(result, args.db) else None,
                    "errors": payload["errors"],
                })
                return 0
            finally:
                shutil.rmtree(payload["_tmpdir"], ignore_errors=True)

        if args.push:
            diffs = compute_diffs(sh, args.db)
            if args.dry_run:
                ops = plan_push(sh, args.db, diffs)
                _json_dump({"mode": "push", "dry_run": True, "target_db": args.db,
                            "diffs": diffs, "planned_writes": ops,
                            "note": "PUSH writes agents+vendors flat tabs only"})
                return 0
            if not args.yes:
                ap.error("real PUSH writes to the live sheet; pass --yes to confirm (or use --dry-run)")
            ops = plan_push(sh, args.db, diffs)
            written = execute_push(sh, ops)
            _json_dump({"mode": "push", "dry_run": False, "writes_applied": written, "ops": ops})
            return 0
    except Exception as exc:  # noqa: BLE001 - surface any fatal error verbatim
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())