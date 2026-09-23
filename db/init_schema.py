#!/usr/bin/env python3
"""SOLA - create the SQLite schema from db/schema.sql into instance/sola.db.

Phase-1 entrypoint. Idempotent (schema.sql uses CREATE TABLE IF NOT EXISTS so a
second run is a no-op). Run directly:

    python db/init_schema.py                     # default instance/sola.db
    python db/init_schema.py --db path --schema path

import_excel.py reuses create_schema() so a single migration run bootstraps the
DB, seeds reference lookups and imports master.xlsx end-to-end.
"""
import argparse
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BASE, "instance", "sola.db")
DEFAULT_SCHEMA = os.path.join(BASE, "db", "schema.sql")


def create_schema(db_path, schema_path=None):
    """Execute schema.sql against db_path, then enforce FKs. Returns conn (closed)."""
    schema_path = schema_path or DEFAULT_SCHEMA
    if not os.path.isfile(schema_path):
        raise FileNotFoundError(f"schema file not found: {schema_path}")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with open(schema_path, encoding="utf-8") as fh:
            conn.executescript(fh.read())
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Init SOLA SQLite schema.")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--schema", default=DEFAULT_SCHEMA)
    args = ap.parse_args()
    create_schema(args.db, args.schema)
    print(f"schema applied to {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())