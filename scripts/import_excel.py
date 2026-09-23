#!/usr/bin/env python3
"""SOLA master-data importer: Excel -> relational SQLite (reproducible migration).

Phase 1. Reads the REAL source workbook (read-only, never modified) and writes
a fresh relational SQLite database from db/schema.sql.

Source : D:/Sola/data/master.xlsx   (MASTER DATA SOLA 1.0 - link-shared Google Sheet)
Target : D:/Sola/instance/sola.db   (schema: db/schema.sql)
Report : D:/Sola/migrations/migration_report.json

Normalization guarantees (see docs/AUDIT_REPORT.md, docs/DATA_DICTIONARY.md):
  * phones are stored as TEXT with the leading '0' restored (source floats lost it)
  * '-' placeholders -> NULL
  * 'Fee' strings ('Max N', '% Keuntungan') -> commission_templates (mode/cap),
    never an item cost
  * context-variant material prices (Korsa KR / Vest VS codes) are preserved as
    distinct material_prices rows keyed by product_category - never merged by name
  * aliases mapped at import time: 'Kaos'->'Jersey', 'Kaos dan Celana'->'Jersey + Celana'
  * 'Kanvas ' trailing space trimmed
  * stray M1=31500 on the T-Shirt header row is flagged as a warning, not imported
  * blank separator rows between product groups are skipped and counted

CLI:
    python scripts/import_excel.py --source D:/Sola/data/master.xlsx
Exit 0 on success, 1 on validation failure / any error.
Idempotent: re-running wipes the import-domain tables and re-imports; the source
Excel is never opened for writing.
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db"))
from init_schema import create_schema  # noqa: E402

import openpyxl  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE = os.path.join(BASE, "data", "master.xlsx")
DEFAULT_DB = os.path.join(BASE, "instance", "sola.db")
DEFAULT_SCHEMA = os.path.join(BASE, "db", "schema.sql")
DEFAULT_REPORT = os.path.join(BASE, "migrations", "migration_report.json")

# ---------------------------------------------------------------------------
# Static mappings (data-dictionary derived; not business data invention)
# ---------------------------------------------------------------------------
# Header marker that separates product groups. B column == one of these => this
# row carries the category name (A) and the per-group column meaning (header).
HEADER_B_MARKERS = {"Bahan", "Bahan dan Cetak"}

# group header (A cell) -> canonical product_category name
CAT_MAP = {
    "T Shirt": "T-Shirt",
    "Polo Shirt": "Polo",
    "Korsa/Shirt": "Korsa",
    "Vest/Rompi": "Vest",
    "Jersey": "Jersey",
    "Hoodie": "Hoodie",
    "Topi": "Topi",
    "Mug": "Mug",
    "Totebag": "Totebag",
    "Tumbler": "Tumbler",
    "Goodiebag": "Goodiebag",
    "Blocknote": "Blocknote",
    "Lanyard": "Lanyard",
    "Handfan": "Handfan",
}

# material name aliases -> canonical name (mapped during import)
ALIAS = {
    "Kaos": "Jersey",
    "Kaos dan Celana": "Jersey + Celana",
    "Kanvas ": "Kanvas",
}

# Known processes from MASTER HPP (used to split materials vs processes there).
MASTER_PROCESS_NAMES = {
    "Cutting", "Jahit", "Sablon DTF", "Sablon Rubber", "Sablon Plastisol",
    "Bordir Kaos", "Bordir Korsa",
}

# Tables owned by this importer (wiped on each run for idempotency), in
# FK-safe reverse-dependency order.
IMPORT_DOMAIN = [
    "vendor_capabilities",
    "vendors",
    "agents",
    "cost_components",
    "process_prices",
    "processes",
    "material_prices",
    "materials",
    "commission_templates",
    "product_categories",
    "colors",
    "sizes",
    "units",
]

# ---------------------------------------------------------------------------
# Report state (written to migrations/migration_report.json)
# ---------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.rows_read = {}     # sheet -> content-bearing rows considered
        self.rows_imported = {}  # entity -> rows inserted
        self.duplicates = []    # suppressed / repeated inserts
        self.invalid_rows = []  # rows with bad data (non-numeric cost etc.)
        self.skipped_rows = []  # blank separator rows
        self.normalized = []    # normalization actions taken
        self.warnings = []      # non-fatal anomalies
        self.errors = []        # fatal problems -> exit code 1

    def to_dict(self):
        return {
            "rows_read": self.rows_read,
            "rows_imported": self.rows_imported,
            "duplicates": self.duplicates,
            "invalid_rows": self.invalid_rows,
            "skipped_rows": self.skipped_rows,
            "normalized": self.normalized,
            "warnings": self.warnings,
            "errors": self.errors,
            "counts": {
                "rows_read": sum(self.rows_read.values()),
                "rows_imported": sum(self.rows_imported.values()),
                "duplicates": len(self.duplicates),
                "invalid_rows": len(self.invalid_rows),
                "skipped_rows": len(self.skipped_rows),
                "normalized": len(self.normalized),
                "warnings": len(self.warnings),
                "errors": len(self.errors),
            },
        }


REPORT = Report()


# ---------------------------------------------------------------------------
# Cell / value normalization helpers
# ---------------------------------------------------------------------------
def norm_text(v):
    """Strip; empty/whitespace-only -> None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def canonical_material_name(name):
    """Apply trailing-space trim + alias mapping; returns None-safe."""
    n = norm_text(name)
    if n is None:
        return None
    n = n.rstrip()          # 'Kanvas ' -> 'Kanvas'
    return ALIAS.get(n, n)


def norm_num(v):
    """Numeric cell -> float or None. Non-finite / non-numeric -> invalid."""
    if v is None:
        return None
    if isinstance(v, bool):
        REPORT.invalid_rows.append(f"non-numeric boolean cell {v!r}")
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "" or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        REPORT.invalid_rows.append(f'non-numeric value {v!r}')
        return None


def norm_phone(v):
    """Phone -> TEXT with leading 0 restored; '-' / empty -> None."""
    if v is None:
        return None
    if isinstance(v, float) or isinstance(v, int):
        digits = str(int(v))           # source stored numeric float, lost leading 0
    else:
        s = str(v).strip()
        if s in ("", "-"):
            return None
        if re.fullmatch(r"\d+(?:\.0+)?", s):   # '8.95...e13'-style numeric repr
            digits = str(int(float(s)))
        else:
            digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    if not digits.startswith("0"):
        digits = "0" + digits
    return digits


def category_name(raw):
    return CAT_MAP.get(norm_text(raw), norm_text(raw))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _insert_or_ignore(db, table, fields, values):
    qs = ",".join(["?"] * len(fields))
    cur = db.execute(
        f"INSERT OR IGNORE INTO {table}({','.join(fields)}) VALUES({qs})", values
    )
    return cur.lastrowid, cur.rowcount  # rowcount 0 => suppressed (duplicate)


def fid(db, table, col, val):
    if val is None:
        return None
    row = db.execute(f"SELECT rowid FROM {table} WHERE {col}=?", (val,)).fetchone()
    return row[0] if row else None


def slugify(name):
    s = re.sub(r"[^A-Za-z0-9]+", "", (name or "")).upper()
    return s or "X"


class MaterialResolver:
    """Give a material_id for a canonical material NAME - ONE master row per name.

    Context-variant prices (Korsa vs Vest vs Topi etc.) live as material_prices
    rows keyed by product_category (decision D2: same name, different context =
    context-PRICE variant, NOT duplicate master rows). Materials created from
    MASTER HPP keep their real ITEMID code; any material only seen in the pivot
    sheets gets a deterministic generated code. When a name is encountered again
    in another context, the existing master row is reused and only a new
    category-keyed price row is added.
    """

    def __init__(self, db, report, counter):
        self.db = db
        self.report = report
        self.counter = counter
        # canonical material name -> material rowid (single master per canonical name)
        self.reg = {}

    def get(self, name, category=None):
        """Return the material master id for name, creating a new material if missing.


        category is ignored for master identity (context is handled by material_prices).
        """
        name = canonical_material_name(name)
        if name is None:
            return None
        if name in self.reg:
            return self.reg[name]
        self.counter += 1
        code = f"MAT-{self.counter:03d}"
        _insert_or_ignore(
            self.db, "materials",
            ("material_code", "material_name", "status"),
            (code, name, "active"),
        )
        mid = fid(self.db, "materials", "material_code", code)
        self.reg[name] = mid
        self.report.normalized.append(
            f'created material "{name}" (code={code})'
        )
        return mid

    def get_master(self, code, name, category=None):
        """MASTER HPP entry: reuse an existing master by canonical name if present, else
        create one with the authoritative ITEMID code. Returns (mid, created_flag)."""
        name = canonical_material_name(name)
        if name in self.reg:
            return self.reg[name], False
        _insert_or_ignore(
            self.db, "materials",
            ("material_code", "material_name", "category", "status"),
            (code, name, category, "active"),
        )
        mid = fid(self.db, "materials", "material_code", code)
        self.reg[name] = mid
        return mid, True


def resolve_process(db, name):
    """Return process rowid for a process name, creating if missing (deterministic code)."""
    name = norm_text(name)
    if name is None:
        return None
    pid = fid(db, "processes", "process_name", name)
    if pid:
        return pid
    _insert_or_ignore(
        db, "processes",
        ("process_code", "process_name", "default_cost", "status"),
        (f"PROC-{slugify(name)}", name, None, "active"),
    )
    return fid(db, "processes", "process_name", name)


def ensure_category(db, raw_name):
    """Return category_id for a canonical category name."""
    name = category_name(norm_text(raw_name))
    cid = fid(db, "product_categories", "category_name", name)
    if cid is None:
        _insert_or_ignore(
            db, "product_categories", ("category_name",), (name,)
        )
        cid = fid(db, "product_categories", "category_name", name)
    return cid


def seed_lookups(db):
    for code, name in (("pcs", "Pcs"), ("meter", "Meter"), ("pak", "Pak"), ("set", "Set")):
        _insert_or_ignore(db, "units", ("unit_code", "unit_name"), (code, name))
    for sz in ("S", "M", "L", "XL", "XXL", "AllSize"):
        _insert_or_ignore(db, "sizes", ("size_code",), (sz,))
    for cc in ("Hitam", "Putih", "Navy"):
        _insert_or_ignore(db, "colors", ("color_code", "color_name"), (cc, cc))


def material_context(code):
    """Category context encoded by MASTER HPP ITEMID suffix (KR=Korsa, VS=Vest)."""
    if code and str(code).endswith("-KR"):
        return "Korsa"
    if code and str(code).endswith("-VS"):
        return "Vest"
    return None


# ---------------------------------------------------------------------------
# Sheet importers
# ---------------------------------------------------------------------------
def import_master_hpp(db, ws, resolver):
    """Authoritative ITEM/ITEMID/PRICE lookup for materials and processes."""
    count = 0
    for r in range(2, ws.max_row + 1):
        item = norm_text(ws.cell(row=r, column=1).value)
        code = norm_text(ws.cell(row=r, column=2).value)
        price = norm_num(ws.cell(row=r, column=3).value)
        if not item or not code:
            if item or code:
                REPORT.invalid_rows.append(f"MASTER HPP row {r}: incomplete ({item=}, {code=})")
            continue
        if item in MASTER_PROCESS_NAMES:
            _insert_or_ignore(
                db, "processes",
                ("process_code", "process_name", "default_cost", "status"),
                (code, item, price, "active"),
            )
            pid = fid(db, "processes", "process_code", code)
            _insert_or_ignore(
                db, "process_prices",
                ("process_id", "unit_price"),
                (pid, price),
            )
        else:
            ctx = material_context(code)
            cname = canonical_material_name(item)
            # one material master per canonical name; a code whose name already
            # exists only adds a category-keyed material_price row (decision D2)
            mid, created = resolver.get_master(code, cname, ctx)
            if not created:
                REPORT.normalized.append(
                    f'MASTER HPP "{item}" ({code}) -> reused existing master '
                    f'"{cname}" (context {ctx or "default"})'
                )
            elif ctx:
                REPORT.normalized.append(
                    f'MASTER HPP "{item}" ({code}) -> context category {ctx}'
                )
            cid = ensure_category(db, ctx) if ctx else None
            _insert_or_ignore(
                db, "material_prices",
                ("material_id", "category_id", "unit_price"),
                (mid, cid, price),
            )
        count += 1
    REPORT.rows_read["master_hpp"] = count
    return count


def _parse_pivot_group_header(ws, r):
    """Read a product-group header row -> (category_raw, header_by_col{col:header})."""
    row_hdr = {}
    stray = []
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=r, column=c).value
        if v is None:
            continue
        s = str(v)
        if c == 1:
            continue  # category name (col A)
        if c == 2:
            continue  # 'Bahan' marker
        if s.strip() in ("", "Bahan", "Bahan dan Cetak"):
            continue  # 'Fee' is kept so the fee column can be located
        if isinstance(v, str):
            row_hdr[c] = s.strip()
        else:
            stray.append((openpyxl.utils.get_column_letter(c), v))
    return row_hdr, stray


def _import_pivot(db, ws, sheet_label, resolver, material_col=1, cost_col=2):
    """Generic importer for HPP and Sheet3 pivot sheets."""
    category_raw = None
    header_by_col = {}
    fee_col = None
    data_rows = 0
    content_rows = 0

    for r in range(1, ws.max_row + 1):
        a = norm_text(ws.cell(row=r, column=material_col).value)
        b = ws.cell(row=r, column=cost_col).value

        # empty separator row -> skip (counted)
        if a is None and (b is None or (isinstance(b, str) and not b.strip())):
            REPORT.skipped_rows.append(f"{sheet_label} blank separator row {r}")
            continue
        content_rows += 1

        b_text = norm_text(b)
        if b_text in HEADER_B_MARKERS and a is not None:
            # --- product-group header row ---
            category_raw = a
            header_by_col, stray = _parse_pivot_group_header(ws, r)
            fee_col = next((c for c, h in header_by_col.items() if h == "Fee"), None)
            cat_name = category_name(a)
            REPORT.normalized.append(
                f'{sheet_label} group header {a!r} -> category {cat_name} (row {r})'
            )
            for col, stray_val in stray:
                REPORT.warnings.append(
                    f"{sheet_label} header row {r} stray value in {col} col "
                    f"({stray_val!r}) ignored (no column header)"
                )
            continue

        if not category_raw:
            if a is not None:
                REPORT.invalid_rows.append(
                    f"{sheet_label} row {r}: no active group header before data"
                )
            continue

        # --- data row: material + per-process costs ---
        cat_id = ensure_category(db, category_raw)
        mat_name = canonical_material_name(a)
        if mat_name is None:
            REPORT.invalid_rows.append(f"{sheet_label} row {r}: missing material name")
            continue

        mid = resolver.get(mat_name, category_name(category_raw))
        mat_cost = norm_num(b)
        if mat_cost is not None:
            # category-context material price
            _, rowcount = _insert_or_ignore(
                db, "material_prices",
                ("material_id", "category_id", "unit_price"),
                (mid, cat_id, mat_cost),
            )
            if rowcount == 0:
                REPORT.duplicates.append(
                    f"{sheet_label} row {r}: material price already present "
                    f"({mat_name} @ {mat_cost}, cat={category_name(category_raw)})"
                )

        # per-process costs (all header cols except A, Bahan col, Fee)
        for c, hname in sorted(header_by_col.items()):
            if hname == "Fee":
                continue
            val = norm_num(ws.cell(row=r, column=c).value)
            if val is None:
                continue
            pid = resolve_process(db, hname)
            _insert_or_ignore(
                db, "cost_components",
                ("product_id", "variant_id", "component_type", "ref_id",
                 "product_category_id", "unit_cost"),
                (None, None, "process", pid, cat_id, val),
            )

        # Fee column -> commission_template (mode/cap), never an item cost
        if fee_col is not None:
            fee_val = ws.cell(row=r, column=fee_col).value
            if fee_val is not None and str(fee_val).strip() != "":
                _parse_fee(db, category_name(category_raw), fee_val, f"{sheet_label}:{r}")

        data_rows += 1

    REPORT.rows_read[sheet_label] = content_rows
    REPORT.rows_imported[f"{sheet_label}_data_rows"] = data_rows
    return data_rows


def _fee_signature(fee_val):
    """Normalize a Fee cell into ('mode', cap_or_None) or None if unparseable."""
    if isinstance(fee_val, str):
        s = fee_val.strip()
        m = re.match(r"max\s*([\d.,]+)", s, re.I)
        if m:
            return ("flat_cap", float(re.sub(r"[^\d.]", "", m.group(1))))
        if re.fullmatch(r"\s*%\s*Keuntungan", s, re.I):
            return ("percent_of_profit", None)
        return None
    if isinstance(fee_val, (int, float)) and not isinstance(fee_val, bool):
        # numeric Fee (e.g. HPP I2=5000.0) -> flat cap
        return ("flat_cap", float(fee_val))
    return None


_fee_seen = {}  # product_category -> fee signature already templated (dedupe)


def _parse_fee(db, cat_name, fee_val, where):
    """Fee -> commission_templates. One template per category; never an item cost.

    Numeric Fee cells are treated as a flat cap. If later rows in the same
    category disagree on the fee, the first is kept and the conflict is flagged.
    """
    sig = _fee_signature(fee_val)
    if sig is None:
        REPORT.warnings.append(f"{where}: unrecognized Fee value {fee_val!r}")
        return
    if cat_name in _fee_seen:
        if _fee_seen[cat_name] != sig:
            REPORT.warnings.append(
                f"{where}: Fee for {cat_name} ({fee_val!r}) differs from first seen "
                f"{_fee_seen[cat_name]}; keeping first"
            )
        return
    mode, cap = sig
    fields, values = ["product_category_id", "commission_mode"], [ensure_category(db, cat_name), mode]
    if cap is not None:
        fields.append("commission_cap")
        values.append(cap)
    _insert_or_ignore(db, "commission_templates", tuple(fields), tuple(values))
    _fee_seen[cat_name] = sig
    if mode == "percent_of_profit":
        REPORT.normalized.append(
            f'{where}: Fee "{fee_val}" -> commission_mode=percent_of_profit for {cat_name}'
        )
    else:
        REPORT.normalized.append(
            f'{where}: Fee "{fee_val}" -> flat_cap cap={cap:g} for {cat_name}'
        )


def import_agents(db, ws):
    count = 0
    for r in range(2, ws.max_row + 1):
        name = norm_text(ws.cell(row=r, column=1).value)
        if not name:
            continue
        phone = norm_phone(ws.cell(row=r, column=3).value)
        addr = norm_text(ws.cell(row=r, column=2).value)
        faculty = norm_text(ws.cell(row=r, column=4).value)
        campus = norm_text(ws.cell(row=r, column=5).value)
        if phone and not phone.startswith("0"):
            REPORT.warnings.append(f"agent row {r}: phone {phone!r} missing leading 0")
        _insert_or_ignore(
            db, "agents",
            ("agent_code", "name", "phone", "campus", "faculty", "address", "status"),
            (f"AGT-{slugify(name)}", name, phone, campus, faculty, addr, "active"),
        )
        if phone:
            REPORT.normalized.append(f"agent {name} phone normalized -> {phone}")
        count += 1
    REPORT.rows_read["agen"] = count
    REPORT.rows_imported["agents"] = count
    return count


_CAP_KEYWORDS = [
    "Kaos", "Polo", "Korsa", "Vest", "Jas Almamater", "Jaket", "Tas",
    "Training", "Sablon", "Mug", "Tumbler", "Samir", "Appron", "Potong", "Pecah belah",
]


def _capabilities_from_spec(spec):
    caps = []
    if not spec:
        return caps
    low = spec.lower()
    for kw in _CAP_KEYWORDS:
        if kw.lower() in low and kw not in caps:
            caps.append(kw)
    return caps


def import_vendors(db, ws):
    count = 0
    for r in range(2, ws.max_row + 1):
        name = norm_text(ws.cell(row=r, column=1).value)
        addr = norm_text(ws.cell(row=r, column=2).value)
        phone = norm_phone(ws.cell(row=r, column=3).value)
        spec = norm_text(ws.cell(row=r, column=4).value)
        if not name and not addr:
            REPORT.skipped_rows.append(f"makloon blank/skip row {r}")
            continue
        _insert_or_ignore(
            db, "vendors",
            ("vendor_code", "vendor_name", "vendor_type", "phone", "address",
             "specialization", "notes", "status"),
            (f"V-{slugify(name or addr)}", name, "penjahit/makloon", phone,
             addr or None, spec, spec, "active"),
        )
        vid = fid(db, "vendors", "vendor_name", name) if name else None
        if phone is None and spec:
            REPORT.normalized.append(
                f"vendor {name}: phone '-' -> NULL while spec remains ({spec})"
            )
        for cap in _capabilities_from_spec(spec):
            _insert_or_ignore(
                db, "vendor_capabilities",
                ("vendor_id", "capability"),
                (vid, cap),
            )
        if phone:
            REPORT.normalized.append(f"vendor {name} phone normalized -> {phone}")
        count += 1
    REPORT.rows_read["makloon"] = count
    REPORT.rows_imported["vendors"] = count
    return count


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def _sheetname_key(name):
    """Normalize a sheet/tab name for slash-insensitive matching.

    The Google Sheet's vendor tab is 'DATABASE PENJAHIT/MAKLOON' (slash), while the
    local xlsx snapshot uses 'DATABASE PENJAHITMAKLOON' (no slash). Strip '/' so the
    same required tab resolves against either source (backward compatible with the
    xlsx-file import path, which legitimately has no slash).
    """
    return (name or "").replace("/", "").replace("\\", "").strip()


def run_migration_from_workbook(wb, db_path, schema_path, report_path):
    """Full migration from an openpyxl-compatible workbook (file OR live sheet adapter).

    Uses the SAME normalization logic and idempotent-wipe semantics as the file-based
    path. `wb` must expose `.sheetnames` and `wb[name]` returning an object with
    `.cell(row, column).value`, `.max_row`, `.max_column`. Returns the report dict.
    """
    global _fee_seen
    _fee_seen = {}
    REPORT.rows_read = {}
    REPORT.rows_imported = {}

    # sanity: required sheets present (slash-insensitive reconciliation)
    required = ["HPP", "MASTER HPP", "Sheet3", "DATABASE AGEN", "DATABASE PENJAHITMAKLOON"]
    present = {_sheetname_key(s) for s in wb.sheetnames}
    for sheet in required:
        if _sheetname_key(sheet) not in present:
            raise ValueError(f"source workbook missing required sheet {sheet!r}")

    def find(name):
        """Actual tab name for a required-sheet key (slash-tolerant)."""
        for s in wb.sheetnames:
            if _sheetname_key(s) == _sheetname_key(name):
                return s
        raise ValueError(f"source workbook missing required sheet {name!r}")

    create_schema(db_path, schema_path)
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA foreign_keys = ON")

    try:
        # ---- idempotent wipe ----
        for table in IMPORT_DOMAIN:
            db.execute(f"DELETE FROM {table}")
        db.commit()

        seed_lookups(db)
        resolver = MaterialResolver(db, REPORT, 0)

        import_master_hpp(db, wb[find("MASTER HPP")], resolver)
        _import_pivot(db, wb[find("HPP")], "HPP", resolver)
        _import_pivot(db, wb[find("Sheet3")], "Sheet3", resolver, material_col=1, cost_col=2)
        import_agents(db, wb[find("DATABASE AGEN")])
        import_vendors(db, wb[find("DATABASE PENJAHITMAKLOON")])

        # ---- integrity verification ----
        fk_violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            REPORT.errors.append(f"foreign_key_check returned {len(fk_violations)} violations")
        for t in ("materials", "processes", "product_categories", "material_prices",
                  "commission_templates", "agents", "vendors", "vendor_capabilities",
                  "cost_components", "process_prices"):
            REPORT.rows_imported[f"{t}_count"] = db.execute(
                f"SELECT COUNT(*) FROM {t}"
            ).fetchone()[0]

        db.commit()
    finally:
        db.close()

    # ---- write report ----
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    payload = REPORT.to_dict()
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def run_migration(source, db_path, schema_path, report_path):
    """Full migration: create schema, clear domain, import, verify. Returns exit code.

    Backward-compatible: same signature/behavior as before (loads the local xlsx
    workbook with openpyxl, then delegates to run_migration_from_workbook).
    """
    if not os.path.isfile(source):
        raise FileNotFoundError(f"source workbook not found: {source}")
    wb = openpyxl.load_workbook(source, data_only=True, read_only=False)
    return run_migration_from_workbook(wb, db_path, schema_path, report_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import SOLA master.xlsx into SQLite.")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="source xlsx (read-only)")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--schema", default=DEFAULT_SCHEMA)
    ap.add_argument("--report", default=DEFAULT_REPORT)
    args = ap.parse_args(argv)

    try:
        payload = run_migration(args.source, args.db, args.schema, args.report)
    except Exception as exc:  # noqa: BLE001 - surface any fatal error
        REPORT.errors.append(f"{type(exc).__name__}: {exc}")
        payload = REPORT.to_dict()
        # still write the report so the failure is inspectable
        os.makedirs(os.path.dirname(args.report), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if not payload["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())