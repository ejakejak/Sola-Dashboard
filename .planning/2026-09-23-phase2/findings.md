# Findings — Phase 2: Route the App Behind the Storage Abstraction

## D1 — commit semantics change
Phase 1's `SqliteStorage` auto-committed after every write. The real blueprints batch
several DB statements then commit once, and `rollback()` on error (5 sites, all in
inventory.py). To migrate without changing behavior, storage.py write primitives
(execute/insert/update/delete) NO LONGER auto-commit; added `commit()`/`rollback()` to the
interface, plus `connection()` returning the same `get_db()` connection. Phase-1 tests updated
to explicit `storage.commit()`; 7 new Phase-2 contract tests added.

## Blueprint migration pattern
Each blueprint gained two module-level seam helpers and dropped `get_db`:
```python
def _storage():
    return current_app.extensions["storage"]
def _db():
    return _storage().connection()
```
`db = get_db()` -> `db = _db()`; `db.commit()` -> `_storage().commit()`; `db.rollback()` -> `_storage().rollback()`.
`connection()` returns the actual per-request sqlite3.Connection, so all existing
`db.execute(...).fetchone()/.fetchall()` call sites work unchanged. track.py helper now takes `_db()`.
Final audit confirms zero live `get_db()` references and zero `db.commit()/rollback()` remain in blueprints.

## Evidence
- Full suite: 109/109 OK = 87 baseline + 15 phase1 + 7 phase2.
- All 7 blueprint files py_compile clean, helpers present (1x each), no import leftover.