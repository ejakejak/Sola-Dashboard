"""One-time / on-demand ADMIN password rotation (Phase 9 security hardening).

The default seeded admin login is admin / sola123 (demo only). This script
replaces the ADMIN password so the default never ships as-is in production.

New password sources, in order:
  1. Environment variable  SOLA_ADMIN_PASSWORD   (preferred for automation)
  2. Interactive getpass prompt (twice, to confirm)

Writes:
  * users.password_hash for the 'admin' user (werkzeug scrypt hash)
  * one audit_logs row  action='ADMIN_PASSWORD_ROTATED'  entity='users'
    (the audit row stores only a non-secret marker, never the password)

Usage:
  SOLA_ADMIN_PASSWORD='ChangeMe!2026' python scripts/rotate_admin_password.py
  python scripts/rotate_admin_password.py        # interactive prompt
  python scripts/rotate_admin_password.py --db path/to/sola.db
"""
from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash


DEFAULT_DB = str(Path(__file__).resolve().parent.parent / "instance" / "sola.db")

MIN_LENGTH = 10
FORBIDDEN = {"sola123"}  # the seeded default; never rotate back to it


def _audit_admin_password_rotated(conn: sqlite3.Connection, user_id: int, min_length: int) -> None:
    """Record the rotation WITHOUT storing the plaintext password (spec §27 audit)."""
    conn.execute(
        "INSERT INTO audit_logs (user_id, timestamp, action, entity, entity_id, new_value)"
        " VALUES (?, datetime('now'), 'ADMIN_PASSWORD_ROTATED', 'users', ?, ?)",
        (user_id, user_id, '{"rotated": true}'),
    )


def rotate_admin_password(database_path: str, new_password: str, *, user: str = "admin") -> int:
    """Update the ADMIN password + write an audit row. Returns the admin user_id.

    Idempotent: a user may rotate as many times as needed. The seed script is
    intentionally unchanged in behaviour here — re-seeding does NOT clobber the
    rotated hash because seed_auth never rewrites password_hash on an existing user.
    """
    if len(new_password) < MIN_LENGTH:
        raise SystemExit(
            f"[rotate] ERROR: new password must be at least {MIN_LENGTH} chars "
            f"(got {len(new_password)})."
        )
    if new_password in FORBIDDEN:
        raise SystemExit(
            f"[rotate] ERROR: '{new_password}' is the seeded default and is forbidden. "
            "Pick a unique, strong password."
        )

    conn = sqlite3.connect(database_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        row = conn.execute(
            "SELECT user_id FROM users WHERE username = ?", (user,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"[rotate] ERROR: no user named '{user}' in {database_path}. "
                             "Run the seed step first (init_schema → seed).")
        user_id = row[0]

        new_hash = generate_password_hash(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?", (new_hash, user_id)
        )
        _audit_admin_password_rotated(conn, user_id, MIN_LENGTH)
        conn.commit()
    except SystemExit:
        conn.close()
        raise
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        conn.close()
        raise SystemExit(f"[rotate] ERROR: rotation failed: {exc!r}")
    conn.close()
    return user_id


def _read_interactive() -> str:
    pw1 = getpass.getpass("New ADMIN password: ")
    pw2 = getpass.getpass("Confirm ADMIN password: ")
    if pw1 != pw2:
        raise SystemExit("[rotate] ERROR: passwords do not match.")
    return pw1


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate the SOLA ADMIN password.")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to the SQLite database")
    parser.add_argument(
        "--user", default="admin", help="Username to rotate (default: admin)"
    )
    args = parser.parse_args()

    new_password = os.environ.get("SOLA_ADMIN_PASSWORD")
    if new_password:
        print("[rotate] using SOLA_ADMIN_PASSWORD from environment.")
    else:
        new_password = _read_interactive()
        print("[rotate] password read interactively (confirmation matched).")

    user_id = rotate_admin_password(args.db, new_password, user=args.user)
    print(f"[rotate] OK: password rotated for '{args.user}' (user_id={user_id}).")
    print("[rotate] An 'ADMIN_PASSWORD_ROTATED' audit row was written (no plaintext stored).")
    print(f"[rotate] DB: {args.db}")


if __name__ == "__main__":
    main()