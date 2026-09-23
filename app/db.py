"""Thin sqlite3 connection helpers + audit_log writer. No ORM — stdlib only."""
import json
import sqlite3
from flask import g, current_app


def get_db() -> sqlite3.Connection:
    """Per-request connection (a multi-threaded Flask dev server needs per-thread handles)."""
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE_PATH"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        g.db = conn
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _json(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def audit(user_id, action, entity, entity_id=None, old_value=None, new_value=None) -> None:
    """Record a consequential action (spec §27). Caller owns the surrounding commit OR we commit here."""
    db = get_db()
    db.execute(
        "INSERT INTO audit_logs (user_id, timestamp, action, entity, entity_id, old_value, new_value)"
        " VALUES (?, datetime('now'), ?, ?, ?, ?, ?)",
        (
            user_id,
            action,
            entity,
            str(entity_id) if entity_id is not None else None,
            _json(old_value),
            _json(new_value),
        ),
    )
    db.commit()