#!/usr/bin/env python3
"""One-way migration: dump every SQLite table -> its own tab on the live sheet.

Phase 5 full-cutover seed. Reads the CURRENT instance/sola.db and writes each
relational table into a tab of the live spreadsheet as a header(+data) grid via
the SheetRelatable engine. Master-data tabs already present on the sheet
(DATABASE AGEN, DATABASE PENJAHIT/MAKLOON, HPP, MASTER HPP, Sheet3) are NOT
touched by name-collision conflict — we map every app table to a NEW unprefixed
tab unless one already carries data (then we overwrite it, honoring the
full-cutover contract). ALWAYS make a DB backup before running.

Usage:
    PYTHONPATH=. <venv-python> scripts/migrate_to_sheet.py [--db path] [--yes]
Run with --yes to write; without it, print a dry-run plan.
"""
import argparse
import os
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.storage import SheetsStorage  # noqa: E402
from app.sheetdb import SheetRelational  # noqa: E402

DEFAULT_DB = os.path.join(BASE, "instance", "sola.db")


def get_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [r[0] for r in rows]


def get_columns(conn, table):
    return [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def dump_rows(conn, table, columns):
    cols = ",".join(f'"{c}"' for c in columns)
    rows = conn.execute(f'SELECT {cols} FROM "{table}"').fetchall()
    return [list(r) for r in rows]


def build_plan(conn):
    plan = []
    for table in get_tables(conn):
        cols = get_columns(conn, table)
        rows = dump_rows(conn, table, cols)
        plan.append({"tab": table, "columns": cols, "rows": rows})
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--yes", action="store_true", help="write to the sheet")
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f"ERROR: db not found: {args.db}")
        return 1
    conn = sqlite3.connect(args.db)
    plan = build_plan(conn)
    conn.close()

    total_rows = sum(len(p["rows"]) for p in plan)
    print(f"Plan: {len(plan)} tables, {total_rows} rows will be written to the live sheet.")

    # live sheet connection (real gspread)
    sheets = SheetsStorage(
        spreadsheet_id=os.environ.get("SPREADSHEET_ID"),
        credentials_path=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    if not sheets.already_configured:
        print("ERROR: SPREADSHEET_ID / GOOGLE_APPLICATION_CREDENTIALS not set.")
        return 1

    if not args.yes:
        for p in plan:
            print(f"  DRY: will write tab '{p['tab']}' ({len(p['rows'])} rows, "
                  f"{len(p['columns'])} cols)")
        print("Pass --yes to apply.")
        return 0

    rel = SheetRelational(sheets)  # noqa: F841 (engine facade present for future use)
    written = 0
    existing = set(sheets.tabs())  # read the tab list ONCE
    for p in plan:
        # create the tab if it doesn't exist yet (one write), else clear it
        if p["tab"] not in existing:
            sheets.add_tab(p["tab"], None)
        else:
            sheets.clear_tab(p["tab"])
        # write header + all rows in a single append (one write)
        data = [p["columns"]] + [list(r) for r in p["rows"]]
        sheets.append_rows(p["tab"], data)
        written += 1
        time.sleep(0.6)  # stay under the 60 read/min + write quota
    print(f"DONE: wrote {written} tabs to the live sheet.")


if __name__ == "__main__":
    sys.exit(main())