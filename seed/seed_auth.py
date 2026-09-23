"""Idempotent seed for roles / permissions / role_permissions / demo users.

Builds ON the existing `roles`/`permissions`/`role_permissions`/`users` tables from
db/schema.sql — NO schema change. Roles + permission matrix per spec §24 with
authorization enforced in the backend (a user has a permission ONLY if their role
is wired to it in role_permissions; nothing is granted by hiding UI).
"""
import sqlite3
from werkzeug.security import generate_password_hash

ROLE_ORDER = [
    "ADMIN", "SALES", "PRODUCTION", "WAREHOUSE", "QC", "FINANCE", "MANAGEMENT", "CUSTOMER",
]

ROLE_NAMES = {
    "ADMIN": "Administrator",
    "SALES": "Sales",
    "PRODUCTION": "Production",
    "WAREHOUSE": "Warehouse",
    "QC": "Quality Control",
    "FINANCE": "Finance",
    "MANAGEMENT": "Management",
    "CUSTOMER": "Customer",
}

# Master-data permission codes (create/update per resource; list shares `masterdata.view`).
PERMISSIONS = [
    "masterdata.view",
    "material.create", "material.update",
    "product.create", "product.update",
    "process.create", "process.update",
    "decoration.create", "decoration.update",
    "vendor.create", "vendor.update",
    "agent.create", "agent.update",
    "customer.create", "customer.update",
    # --- Phase 3-4 commercial loop (additive data, no DDL) ---
    "quotation.view", "quotation.create", "quotation.update", "quotation.convert",
    "order.view", "order.create",
    "invoice.view", "invoice.create", "invoice.update", "invoice.payment",
    # --- Phase 5 production + configurable workflow (spec §24, additive) ---
    # production.view: list/detail/board. manage: create-from-order + stage advances +
    #   updates + media upload. update: edit a production record.
    # production.media.internal.read: may see INTERNAL media (never customer-facing).
    # qc.manage: record QC pass/fail/rework. workflow.manage: CRUD workflow templates.
    "production.view",
    "production.manage",
    "production.update",
    "production.media.internal.read",
    "qc.manage",
    "workflow.manage",
    # --- Phase 6 inventory + stock (additive data, no DDL) ---
    # inventory.view: list inventory / movements / usage. inventory.manage:
    #   adjust on_hand, reserve/release, issue(OUT), record material usage.
    "inventory.view",
    "inventory.manage",
]

# role_code -> set of permission codes. ADMIN is granted every permission below.
ROLE_PERMISSION_MATRIX = {
    "ADMIN": set(PERMISSIONS),  # full access (spec §24)
    "SALES": {
        "masterdata.view",
        "customer.create", "customer.update",
        "agent.create", "agent.update",
        "product.create", "product.update",
        "quotation.view", "quotation.create", "quotation.update", "quotation.convert",
        "order.view", "order.create",
        "invoice.view",
        # Phase 5: sales read-only production visibility
        "production.view",
    },
    "PRODUCTION": {
        "masterdata.view",
        # Phase 5: manage production + internal media read (+ workflow templates)
        "production.view", "production.manage", "production.update",
        "production.media.internal.read", "workflow.manage",
        # Phase 6: production can VIEW inventory and record MATERIAL USAGE against
        #   their productions (usage route is gated by inventory.manage OR production.manage),
        #   but is NOT granted inventory.manage (no free-form adjust/reserve/issue).
        "inventory.view",
    },
    "WAREHOUSE": {
        "masterdata.view",
        "material.create", "material.update",
        "process.create", "process.update",
        # view-only production visibility; no internal media read, no manage
        "production.view",
        # Phase 6: warehouse owns inventory — view + manage (adjust/reserve/release/issue/usage)
        "inventory.view", "inventory.manage",
    },
    "QC": {
        "masterdata.view",
        # Phase 5: QC can view productions and record QC results
        "production.view", "qc.manage",
        # Phase 6: QC view-only on inventory (matches DESIGN_SPEC §2.2 read visibility)
        "inventory.view",
    },
    "FINANCE": {
        "masterdata.view",
        "quotation.view", "order.view",
        "invoice.view", "invoice.create", "invoice.update", "invoice.payment",
        # view-only production (no INTERNAL media / manage)
        "production.view",
        # Phase 6: finance view-only on inventory
        "inventory.view",
    },
    "MANAGEMENT": {
        "masterdata.view",
        "quotation.view", "order.view", "invoice.view",  # read-only commercial
        # Phase 5: management read-only on production; NO internal media / writes
        "production.view",
        # Phase 6: management view-only on inventory (DESIGN_SPEC §2.2 nav)
        "inventory.view",
    },
    "SALES": {   # NOT given inventory.view — Inventory nav is absent for Sales per DESIGN_SPEC §2.2
        "masterdata.view",
        "customer.create", "customer.update",
        "agent.create", "agent.update",
        "product.create", "product.update",
        "quotation.view", "quotation.create", "quotation.update", "quotation.convert",
        "order.view", "order.create",
        "invoice.view",
        # Phase 5: sales read-only production visibility
        "production.view",
    },
    "CUSTOMER": set(),                 # public /track only — no dashboard login
}

# Default demo credentials (local-first app; document that these must be changed in prod).
DEFAULT_PASSWORD = "sola123"

ADMIN_USER = {
    "username": "admin",
    "full_name": "SOLA Administrator",
    "password": DEFAULT_PASSWORD,
    "role_code": "ADMIN",
    "email": "admin@sola.id",
}

DEMO_USERS = [
    {"username": "sales", "full_name": "Sales Staff", "role_code": "SALES", "email": "sales@sola.id"},
    {"username": "production", "full_name": "Production PIC", "role_code": "PRODUCTION", "email": "production@sola.id"},
    {"username": "warehouse", "full_name": "Warehouse Staff", "role_code": "WAREHOUSE", "email": "warehouse@sola.id"},
    {"username": "qc", "full_name": "QC Inspector", "role_code": "QC", "email": "qc@sola.id"},
    {"username": "finance", "full_name": "Finance Staff", "role_code": "FINANCE", "email": "finance@sola.id"},
    {"username": "management", "full_name": "Management", "role_code": "MANAGEMENT", "email": "management@sola.id"},
    {"username": "customer", "full_name": "Customer", "role_code": "CUSTOMER", "email": "customer@sola.id"},
]


def ensure_seeded(database_path: str, verbose: bool = False) -> dict:
    conn = sqlite3.connect(database_path)
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    # 1) roles
    for code in ROLE_ORDER:
        cur.execute(
            "INSERT OR IGNORE INTO roles (role_code, role_name) VALUES (?, ?)",
            (code, ROLE_NAMES[code]),
        )
    # 2) permissions
    for code in PERMISSIONS:
        cur.execute(
            "INSERT OR IGNORE INTO permissions (permission_code) VALUES (?)", (code,)
        )
    # 3) role_permissions
    linked = 0
    for code, perms in ROLE_PERMISSION_MATRIX.items():
        cur.execute("SELECT role_id FROM roles WHERE role_code = ?", (code,))
        role_id = cur.fetchone()[0]
        for perm in sorted(perms):
            cur.execute(
                "SELECT permission_id FROM permissions WHERE permission_code = ?", (perm,)
            )
            perm_id = cur.fetchone()[0]
            cur.execute(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission_id)"
                " VALUES (?, ?)",
                (role_id, perm_id),
            )
            linked += cur.rowcount

    # 4) users (admin bootstrap + one demo user per role)
    role_id_by_code = {code: None for code in ROLE_ORDER}
    for row in cur.execute("SELECT role_id, role_code FROM roles").fetchall():
        role_id_by_code[row[1]] = row[0]

    users_created = 0
    h = generate_password_hash(DEFAULT_PASSWORD)

    def _upsert_user(ude):
        nonlocal users_created
        existing = cur.execute(
            "SELECT user_id FROM users WHERE username = ?", (ude["username"],)
        ).fetchone()
        if existing:
            cur.execute(
                "UPDATE users SET role_id = ?, full_name = ?, email = ? WHERE user_id = ?",
                (role_id_by_code[ude["role_code"]], ude["full_name"], ude.get("email"), existing[0]),
            )
            return False
        cur.execute(
            "INSERT INTO users (username, full_name, password_hash, role_id, email, status)"
            " VALUES (?, ?, ?, ?, ?, 'active')",
            (
                ude["username"],
                ude["full_name"],
                h,
                role_id_by_code[ude["role_code"]],
                ude.get("email"),
            ),
        )
        users_created += 1
        return True

    _upsert_user(ADMIN_USER)
    for du in DEMO_USERS:
        _upsert_user(du)

    conn.commit()
    summary = {
        "roles": len(ROLE_ORDER),
        "permissions": len(PERMISSIONS),
        "role_permissions_linked": linked,
        "users_created": users_created,
        "default_password": DEFAULT_PASSWORD,
    }
    conn.close()
    if verbose:
        print(
            f"[seed] roles={summary['roles']}, permissions={summary['permissions']}, "
            f"role_permissions={summary['role_permissions_linked']}, new users={summary['users_created']}"
        )
        print(f"[seed] default login: admin / {DEFAULT_PASSWORD} (change in production)")
    return summary


if __name__ == "__main__":
    import os
    from app.config import BASE_DIR

    ensure_seeded(str(BASE_DIR / "instance" / "sola.db"), verbose=True)