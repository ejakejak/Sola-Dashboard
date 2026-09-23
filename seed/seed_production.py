"""Idempotent seed for configurable production workflow templates (spec §14).

Builds ON the existing production_workflow_templates /
production_workflow_template_steps tables from db/schema.sql — NO DDL change.

Seeds three development-config scenarios (config-derived scaffolding, not
invented business data) so production-from-order has templates to materialize:

  * garment  (default catch-all, product_category_id NULL, is_default=1)
      ORDER → MATERIAL PREPARATION → CUTTING → SEWING → PRINTING → FINISHING
        → QC → PACKING → COMPLETED
  * Mug short (product_category_id=22)
      ORDER → PRINTING → QC → PACKING → COMPLETED
  * Topi variant (product_category_id=21)
      ORDER → MATERIAL → CUTTING → SEWING → EMBROIDERY → QC → PACKING → COMPLETED

Idempotent: re-runs are no-ops (won't duplicate a template it can already find
by name). The final step of every template is flagged is_completion=1.

Because it runs as a seed (not the app request context), this module talks to
sqlite3 directly — the same callable is reused by run.py bootstrap and tests.
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BASE_DIR, "instance", "sola.db")

# (template_name, product_category_id or None, default bool) -> ordered stage names
# Stage tuples: (sequence, stage_name, is_completion) sequence is 1-based.
TEMPLATE_SCENARIOS = [
    (
        "Garment Default",
        None,  # catch-all default
        True,
        [
            "ORDER", "MATERIAL PREPARATION", "CUTTING", "SEWING", "PRINTING",
            "FINISHING", "QC", "PACKING", "COMPLETED",
        ],
    ),
    (
        "Mug Short",
        22,  # product_categories.category_id for Mug
        False,
        ["ORDER", "PRINTING", "QC", "PACKING", "COMPLETED"],
    ),
    (
        "Topi Variant",
        21,  # product_categories.category_id for Topi
        False,
        ["ORDER", "MATERIAL", "CUTTING", "SEWING", "EMBROIDERY", "QC", "PACKING", "COMPLETED"],
    ),
]


def seed_workflow_templates(database_path: str, verbose: bool = False) -> dict:
    conn = sqlite3.connect(database_path)
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    created = 0
    steps_created = 0
    for name, category_id, is_default, stages in TEMPLATE_SCENARIOS:
        # find existing template by (name, category) to stay idempotent
        row = cur.execute(
            "SELECT workflow_template_id FROM production_workflow_templates"
            " WHERE template_name = ? AND product_category_id IS ?",
            (name, category_id),
        ).fetchone()
        if row is not None:
            continue
        cur.execute(
            "INSERT INTO production_workflow_templates"
            " (template_name, product_category_id, is_default, status) VALUES (?,?,?, 'active')",
            (name, category_id, 1 if is_default else 0),
        )
        tid = cur.lastrowid
        created += 1
        n = len(stages)
        for seq, stage_name in enumerate(stages, start=1):
            cur.execute(
                "INSERT INTO production_workflow_template_steps"
                " (workflow_template_id, sequence, stage_name, is_completion)"
                " VALUES (?,?,?,?)",
                (tid, seq, stage_name, 1 if seq == n else 0),
            )
            steps_created += 1

    conn.commit()
    conn.close()
    summary = {"templates_created": created, "steps_created": steps_created}
    if verbose:
        print(
            f"[seed-workflow] templates created={created}, steps seeded={steps_created} "
            f"(idempotent — re-runs skip existing)"
        )
    return summary


if __name__ == "__main__":
    seed_workflow_templates(DEFAULT_DB, verbose=True)