#!/usr/bin/env python3
"""Phase 5 tests — configurable Workflow Templates + Production.

Covers the whole Phase-5 loop on an ISOLATED temp DB (same schema.sql), so the
real instance/sola.db is never touched:

  workflow templates seeded idempotently + editable (garment default / Mug short /
    Topi variant, ordered steps + completion flag)
  production FROM order -> auto PRD-YYMMDD-NNN code + materialized stages from the
    template + derived overall_progress = completed/total
  advance a stage (pending -> in_progress -> completed with quantities) recomputes
    overall progress + current_stage
  production_updates recorded + audited
  media upload with INTERNAL|CUSTOMER visibility + internal-read permission gate
  QC pass/fail/rework-with-return-to-stage
  additive production permission matrix (ADMIN all; PRODUCTION manage +
    media.internal.read; QC qc.manage; view-only roles cannot write / read INTERNAL)

    python tests/test_app_phase5.py
"""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app import create_app  # noqa: E402
from app.commercial import CATALOG_PRICE_BY_MATERIAL  # noqa: E402
from db.init_schema import create_schema  # noqa: E402
from seed.seed_auth import DEFAULT_PASSWORD, ensure_seeded  # noqa: E402
from seed.seed_production import seed_workflow_templates  # noqa: E402
from seed.seed_catalog import seed_catalog  # noqa: E402

OK, FORBIDDEN, REDIRECT = 200, 403, 302

# Canonical product_categories from the migrated instance DB
CATEGORIES = [
    (15, "Korsa"), (16, "Vest"), (17, "T-Shirt"), (18, "Polo"), (19, "Hoodie"),
    (20, "Jersey"), (21, "Topi"), (22, "Mug"), (23, "Totebag"), (24, "Tumbler"),
    (25, "Goodiebag"), (26, "Blocknote"), (27, "Lanyard"), (28, "Handfan"),
]


def _mkapp(db_path, extra=None):
    cfg = {"TESTING": True, "DATABASE_PATH": db_path, "SECRET_KEY": "test-secret"}
    if extra:
        cfg.update(extra)
    app = create_app(cfg)
    create_schema(db_path)
    ensure_seeded(db_path)
    _seed_categories(db_path)
    _seed_master(db_path)
    seed_workflow_templates(db_path)
    seed_catalog(db_path)
    return app


def _seed_categories(db_path):
    conn = sqlite3.connect(db_path)
    for cid, name in CATEGORIES:
        conn.execute("INSERT OR IGNORE INTO product_categories (category_id, category_name)"
                     " VALUES (?,?)", (cid, name))
    conn.commit()
    conn.close()


def _seed_master(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO customers (customer_code, name, company_name, address,"
                " customer_type, status) VALUES ('CUST-P5', 'Winda User', 'PT Uji Sola',"
                " 'Jl. Test No.9', 'retail', 'active')")
    cur.execute("INSERT OR IGNORE INTO materials (material_code, material_name, status)"
                " VALUES ('CC-34S', 'Cotton Combed 34s Test', 'active')")
    conn.commit()
    conn.close()


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def _login(client, username="admin"):
    return client.post(
        "/login", data={"username": username, "password": DEFAULT_PASSWORD}
    )


class TestWorkflowTemplates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p5.db")
        self.app = _mkapp(self.db)
        self.c = self.app.test_client()
        _login(self.c, "admin")

    def tearDown(self):
        self._tmp.cleanup()

    def test_01_seeded_templates_idempotent(self):
        tpl = _query(self.db, "SELECT template_name FROM production_workflow_templates"
                              " ORDER BY is_default DESC")
        names = [t["template_name"] for t in tpl]
        self.assertIn("Garment Default", names)
        self.assertIn("Mug Short", names)
        self.assertIn("Topi Variant", names)
        # default flag on garment
        g = _query(self.db, "SELECT is_default FROM production_workflow_templates"
                            " WHERE template_name='Garment Default'")[0]
        self.assertEqual(g["is_default"], 1)
        # steps with completion flag
        gid = _query(self.db, "SELECT workflow_template_id FROM production_workflow_templates"
                              " WHERE template_name='Garment Default'")[0]["workflow_template_id"]
        steps = _query(self.db, "SELECT * FROM production_workflow_template_steps"
                                " WHERE workflow_template_id=? ORDER BY sequence", (gid,))
        self.assertEqual(len(steps), 9)
        self.assertEqual([s["stage_name"] for s in steps],
                         ["ORDER", "MATERIAL PREPARATION", "CUTTING", "SEWING", "PRINTING",
                          "FINISHING", "QC", "PACKING", "COMPLETED"])
        self.assertEqual(steps[-1]["is_completion"], 1)
        self.assertEqual(steps[0]["is_completion"], 0)
        # idempotent re-run
        seed_workflow_templates(self.db)
        self.assertEqual(len(_query(self.db, "SELECT * FROM production_workflow_templates")),
                         len(names), "re-seeding must not duplicate templates")

    def test_02_admin_edit_template(self):
        gid = _query(self.db, "SELECT workflow_template_id FROM production_workflow_templates"
                              " WHERE template_name='Garment Default'")[0]["workflow_template_id"]
        r = self.c.post(f"/production/templates/{gid}/edit", data={
            "template_name": "Garment Default",
            "step_name[]": ["ORDER", "CUTTING", "SEWING", "QC", "PACKING", "COMPLETED"],
        })
        self.assertEqual(r.status_code, REDIRECT)
        steps = _query(self.db, "SELECT stage_name, is_completion FROM production_workflow_template_steps"
                                " WHERE workflow_template_id=? ORDER BY sequence", (gid,))
        self.assertEqual([s["stage_name"] for s in steps],
                         ["ORDER", "CUTTING", "SEWING", "QC", "PACKING", "COMPLETED"])
        self.assertEqual(steps[-1]["is_completion"], 1, "final step stays completion gate")
        # audited
        audits = _query(self.db, "SELECT * FROM audit_logs WHERE entity='workflow_template'"
                                 " AND action='UPDATE'")
        self.assertEqual(len(audits), 1)

    def test_03_workflow_manage_required(self):
        sales = self.app.test_client()
        _login(sales, "sales")
        r = sales.get("/production/templates")
        self.assertEqual(r.status_code, FORBIDDEN, "non-workflow-manager cannot list templates")


class _ProdFlowMixin:
    def _make_order(self, client=None):
        """Backend drill: quotation draft -> approved -> convert -> order. Return oid."""
        client = client or self.c
        mat = _query(self.db, "SELECT material_id FROM materials WHERE material_code='CC-34S'")[0]["material_id"]
        cust = _query(self.db, "SELECT customer_id FROM customers WHERE customer_code='CUST-P5'")[0]["customer_id"]
        price = CATALOG_PRICE_BY_MATERIAL.get(mat, 55000)
        r = client.post("/quotations/new", data={
            "customer_id": str(cust), "discount": "0", "tax": "0",
            "item_product[]": "", "item_material[]": str(mat),
            "item_qty[]": "10", "item_unit[]": "", "item_price[]": str(price),
        })
        self.assertEqual(r.status_code, REDIRECT)
        qid = _query(self.db, "SELECT quotation_id FROM quotations ORDER BY quotation_id DESC LIMIT 1")[0]["quotation_id"]
        client.post(f"/quotations/{qid}/status", data={"status": "approved"})
        client.post(f"/quotations/{qid}/convert", data={"priority": "high", "deadline": "2026-12-01"})
        oid = _query(self.db, "SELECT order_id FROM orders ORDER BY order_id DESC LIMIT 1")[0]["order_id"]
        self.assertIsNotNone(oid)
        return oid


class TestProductionFromOrder(_ProdFlowMixin, unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p5b.db")
        self.app = _mkapp(self.db)
        self.c = self.app.test_client()
        _login(self.c, "admin")

    def tearDown(self):
        self._tmp.cleanup()

    def test_04_from_order_auto_code_stages_progress(self):
        oid = self._make_order()
        default = _query(self.db, "SELECT workflow_template_id FROM production_workflow_templates"
                                  " WHERE is_default=1")[0]["workflow_template_id"]
        r = self.c.post(f"/production/from-order/{oid}", data={"template_id": str(default)})
        self.assertEqual(r.status_code, REDIRECT)
        prods = _query(self.db, "SELECT * FROM production_orders")
        self.assertEqual(len(prods), 1)
        p = prods[0]
        # auto code PRD-YYMMDD-NNN
        import re
        self.assertRegex(p["production_code"], r"^PRD-\d{6}-\d{3}$")
        self.assertEqual(p["order_id"], oid)
        self.assertEqual(p["quantity"], 10)
        self.assertEqual(p["status"], "in_progress")
        self.assertEqual(p["current_stage"], "ORDER")
        # materialized stages from template (9 for garment)
        stages = _query(self.db, "SELECT * FROM production_stages WHERE production_id=? ORDER BY sequence",
                        (p["production_id"],))
        self.assertEqual(len(stages), 9)
        self.assertEqual(stages[0]["status"], "pending")
        self.assertEqual(stages[0]["target_quantity"], 10)
        # derived progress 0
        self.assertEqual(p["overall_progress"], 0.0)

    def test_05_product_catalog_from_order_selling_price(self):
        # catalog seeded into temp DB
        prods = _query(self.db, "SELECT * FROM products ORDER BY product_code")
        self.assertTrue(prods, "products populated from KATALOG")
        variants = _query(self.db, "SELECT * FROM product_variants")
        mug_v = [v for v in variants if "Mug Sablon" in v["variant_name"]]
        self.assertTrue(mug_v, "Mug Sablon variant seeded")
        self.assertIn("SELLING_PRICE=18000", mug_v[0]["notes"], "selling price recorded in notes")

    def test_06_advance_stage_recomputes_progress(self):
        oid = self._make_order()
        default = _query(self.db, "SELECT workflow_template_id FROM production_workflow_templates WHERE is_default=1")[0]["workflow_template_id"]
        self.c.post(f"/production/from-order/{oid}", data={"template_id": str(default)})
        pid = _query(self.db, "SELECT production_id FROM production_orders")[0]["production_id"]
        sid = _query(self.db, "SELECT production_stage_id FROM production_stages WHERE production_id=? AND sequence=1", (pid,))[0]["production_stage_id"]
        # start
        self.c.post(f"/production/{pid}/stage/{sid}/advance",
                    data={"status": "in_progress", "completed_quantity": "0"})
        # complete with quantities
        self.c.post(f"/production/{pid}/stage/{sid}/advance",
                    data={"status": "completed", "completed_quantity": "10", "rejected_quantity": "0"})
        p = _query(self.db, "SELECT * FROM production_orders WHERE production_id=?", (pid,))[0]
        self.assertEqual(p["current_stage"], "MATERIAL PREPARATION")
        # 1 of 9 completed
        self.assertAlmostEqual(p["overall_progress"], round(1 / 9 * 100, 1), places=1)
        # stage timestamps recorded
        st = _query(self.db, "SELECT * FROM production_stages WHERE production_stage_id=?", (sid,))[0]
        self.assertEqual(st["status"], "completed")
        self.assertTrue(st["completed_at"])
        # audits
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE entity='production_stage' AND action='UPDATE'")), 2)

    def test_07_full_completion_sets_completed_status(self):
        oid = self._make_order()
        default = _query(self.db, "SELECT workflow_template_id FROM production_workflow_templates WHERE is_default=1")[0]["workflow_template_id"]
        self.c.post(f"/production/from-order/{oid}", data={"template_id": str(default)})
        pid = _query(self.db, "SELECT production_id FROM production_orders")[0]["production_id"]
        for sid, _seq in [(s["production_stage_id"], s["sequence"]) for s in _query(
                self.db, "SELECT * FROM production_stages WHERE production_id=? ORDER BY sequence", (pid,))]:
            self.c.post(f"/production/{pid}/stage/{sid}/advance",
                        data={"status": "completed", "completed_quantity": "10", "rejected_quantity": "0"})
        p = _query(self.db, "SELECT * FROM production_orders WHERE production_id=?", (pid,))[0]
        self.assertEqual(p["status"], "completed")
        self.assertEqual(p["overall_progress"], 100.0)

    def test_08_production_update_audited(self):
        oid = self._make_order()
        default = _query(self.db, "SELECT workflow_template_id FROM production_workflow_templates WHERE is_default=1")[0]["workflow_template_id"]
        self.c.post(f"/production/from-order/{oid}", data={"template_id": str(default)})
        pid = _query(self.db, "SELECT production_id FROM production_orders")[0]["production_id"]
        r = self.c.post(f"/production/{pid}/updates",
                        data={"progress": "50", "quantity_completed": "5", "quantity_rejected": "1",
                              "notes": "cutting done"})
        self.assertEqual(r.status_code, REDIRECT)
        ups = _query(self.db, "SELECT * FROM production_updates WHERE production_id=?", (pid,))
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0]["progress"], 50.0)
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE entity='production_update' AND action='CREATE'")), 1)


class TestProductionMediaQC(_ProdFlowMixin, unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p5c.db")
        self.app = _mkapp(self.db)
        self.admin = self.app.test_client()
        _login(self.admin, "admin")
        self.oid = self._make_order(self.admin)
        self.c = self.app.test_client()
        _login(self.c, "production")   # production role has manage + media.internal.read
        default = _query(self.db, "SELECT workflow_template_id FROM production_workflow_templates WHERE is_default=1")[0]["workflow_template_id"]
        self.c.post(f"/production/from-order/{self.oid}", data={"template_id": str(default)})
        self.pid = _query(self.db, "SELECT production_id FROM production_orders")[0]["production_id"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_09_media_upload_and_visibility_gate(self):
        # production role uploads an INTERNAL + a CUSTOMER media
        r1 = self.c.post(f"/production/{self.pid}/media",
                         data={"visibility": "INTERNAL", "file": (io.BytesIO(b"internalbinary"), "internal.png")},
                         content_type="multipart/form-data")
        self.assertEqual(r1.status_code, REDIRECT)
        r2 = self.c.post(f"/production/{self.pid}/media",
                         data={"visibility": "CUSTOMER", "file": (io.BytesIO(b"customerbinary"), "cust.png")},
                         content_type="multipart/form-data")
        self.assertEqual(r2.status_code, REDIRECT)
        media = _query(self.db, "SELECT * FROM production_media WHERE production_id=?", (self.pid,))
        self.assertEqual(len(media), 2)
        vis = {m["visibility"] for m in media}
        self.assertEqual(vis, {"INTERNAL", "CUSTOMER"})

        # INTERNAL media row is served; file exists in gitignored uploads dir
        int_mid = [m for m in media if m["visibility"] == "INTERNAL"][0]["media_id"]
        with self.c.get(f"/production/media/{int_mid}/file") as r_int:
            self.assertEqual(r_int.status_code, OK, "PRODUCTION role (internal-read) can fetch INTERNAL media")
        # audited media writes
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE entity='production_media' AND action='CREATE'")), 2)

    def test_10_internal_media_gated_for_view_only_roles(self):
        # production role uploads INTERNAL + CUSTOMER media
        self.c.post(f"/production/{self.pid}/media",
                    data={"visibility": "INTERNAL", "file": (io.BytesIO(b"i"), "i.png")},
                    content_type="multipart/form-data")
        self.c.post(f"/production/{self.pid}/media",
                    data={"visibility": "CUSTOMER", "file": (io.BytesIO(b"c"), "c.png")},
                    content_type="multipart/form-data")
        media = _query(self.db, "SELECT * FROM production_media WHERE production_id=? ORDER BY media_id", (self.pid,))
        int_mid = [m for m in media if m["visibility"] == "INTERNAL"][0]["media_id"]
        cust_mid = [m for m in media if m["visibility"] == "CUSTOMER"][0]["media_id"]

        sales = self.app.test_client()
        _login(sales, "sales")  # production.view only, NO internal-read
        # CUSTOMER media visible to any production.view holder
        with sales.get(f"/production/media/{cust_mid}/file") as resp:
            self.assertEqual(resp.status_code, OK)
        # INTERNAL media -> 403 gate
        self.assertEqual(sales.get(f"/production/media/{int_mid}/file").status_code, FORBIDDEN,
                         "view-only role must NOT read INTERNAL media")

        # DB-level: detail query for sales must not include INTERNAL (backend-filtered)
        r = sales.get(f"/production/{self.pid}")
        self.assertEqual(r.status_code, OK)
        body = r.get_data(as_text=True)
        internal_path = f"/production/media/{int_mid}/file"
        self.assertNotIn(internal_path, body, "INTERNAL media URL must not leak to sales render")
        self.assertIn(f"/production/media/{cust_mid}/file", body, "CUSTOMER media shown to sales")

    def test_11_media_upload_requires_manage(self):
        # sales has view only -> cannot upload media
        sales = self.app.test_client()
        _login(sales, "sales")
        r = sales.post(f"/production/{self.pid}/media",
                       data={"visibility": "CUSTOMER", "file": (io.BytesIO(b"x"), "x.png")},
                       content_type="multipart/form-data")
        self.assertEqual(r.status_code, FORBIDDEN, "view-only role cannot upload media")

    def test_12_qc_pass_rework_return_to_stage(self):
        # qc role records a PASS
        qc = self.app.test_client()
        _login(qc, "qc")
        r = qc.post(f"/production/{self.pid}/qc",
                    data={"status": "passed", "passed_quantity": "10", "rejected_quantity": "0",
                          "defect_type": "", "notes": "ok"})
        self.assertEqual(r.status_code, REDIRECT)
        qcs = _query(self.db, "SELECT * FROM quality_checks WHERE production_id=?", (self.pid,))
        self.assertEqual(len(qcs), 1)
        self.assertEqual(qcs[0]["status"], "passed")

        # advance first two stages
        pid = self.pid
        for sid in [s["production_stage_id"] for s in _query(
                self.db, "SELECT * FROM production_stages WHERE production_id=? AND sequence<=2 ORDER BY sequence", (pid,))]:
            self.c.post(f"/production/{pid}/stage/{sid}/advance",
                        data={"status": "completed", "completed_quantity": "10"})
        p = _query(self.db, "SELECT * FROM production_orders WHERE production_id=?", (pid,))[0]
        self.assertEqual(p["current_stage"], "CUTTING")

        # QC rework -> return to earlier stage (sequence 2 = MATERIAL PREPARATION, now in_progress again)
        seq2 = _query(self.db, "SELECT production_stage_id FROM production_stages WHERE production_id=? AND sequence=2", (pid,))[0]["production_stage_id"]
        r = qc.post(f"/production/{pid}/qc",
                    data={"status": "rework", "return_stage_id": str(seq2),
                          "pass_stage":"", "defect_type": "jahan goyah", "notes": "rework needed"})
        self.assertEqual(r.status_code, REDIRECT)
        ret = _query(self.db, "SELECT * FROM production_stages WHERE production_stage_id=?", (seq2,))[0]
        self.assertEqual(ret["status"], "in_progress", "rework returns stage to in_progress")
        # later completed stages re-opened to pending (sequence 2 is the return, sequence>2 cancelled->pending? we only opened 1&2)
        p2 = _query(self.db, "SELECT status, current_stage FROM production_orders WHERE production_id=?", (pid,))[0]
        self.assertIn(p2["status"], ("in_progress", "blocked"))
        # audited
        self.assertEqual(len(_query(self.db, "SELECT * FROM audit_logs WHERE entity='quality_check' AND action='CREATE'")), 2)

    def test_13_qc_requires_permission(self):
        sales = self.app.test_client()
        _login(sales, "sales")
        r = sales.post(f"/production/{self.pid}/qc", data={"status": "passed"})
        self.assertEqual(r.status_code, FORBIDDEN, "only qc.manage roles may record QC")


class TestProductionPermissions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "sola_p5d.db")
        self.app = _mkapp(self.db)
        self.admin = self.app.test_client()
        _login(self.admin, "admin")

    def tearDown(self):
        self._tmp.cleanup()

    def _perms_for(self, role):
        return {r["permission_code"] for r in _query(
            self.db,
            "SELECT p.permission_code FROM role_permissions rp"
            " JOIN permissions p ON p.permission_id=rp.permission_id"
            " JOIN roles r ON r.role_id=rp.role_id WHERE r.role_code=?",
            (role,))}

    def test_14_matrix(self):
        admin = self._perms_for("ADMIN")
        self.assertTrue({"production.view", "production.manage", "production.update",
                         "production.media.internal.read", "qc.manage", "workflow.manage"} <= admin)
        prod = self._perms_for("PRODUCTION")
        self.assertTrue({"production.view", "production.manage", "production.update",
                         "production.media.internal.read", "workflow.manage"} <= prod)
        self.assertNotIn("qc.manage", prod, "PRODUCTION is not given QC actions")
        qc = self._perms_for("QC")
        self.assertIn("qc.manage", qc)
        self.assertIn("production.view", qc)
        self.assertNotIn("production.manage", qc)
        for ro in ("SALES", "FINANCE", "MANAGEMENT", "WAREHOUSE"):
            perms = self._perms_for(ro)
            self.assertIn("production.view", perms, f"{ro} view-only")
            self.assertNotIn("production.manage", perms, f"{ro} must not manage production")
            self.assertNotIn("production.media.internal.read", perms, f"{ro} must not read INTERNAL media")

    def test_15_idempotent_auth_seed(self):
        ensure_seeded(self.db)  # re-run — no duplication, invariant preserved
        perms = {"production.view", "production.manage", "production.update",
                 "production.media.internal.read", "qc.manage", "workflow.manage"}
        for p in perms:
            self.assertEqual(len(_query(self.db, "SELECT * FROM permissions WHERE permission_code=?", (p,))), 1)
        # ADMIN still holds every permission exactly once
        admin_role = _query(self.db, "SELECT role_id FROM roles WHERE role_code='ADMIN'")[0]["role_id"]
        n = _query(self.db, "SELECT COUNT(*) n FROM role_permissions WHERE role_id=?",
                   (admin_role,))[0]["n"]
        self.assertEqual(n, len(_query(self.db, "SELECT * FROM permissions")),
                         "ADMIN granted every permission")


if __name__ == "__main__":
    unittest.main(verbosity=2)