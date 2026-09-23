"""Idempotent seed: products + product_variants from the SOLA retail catalog.

Source of truth for the SELLING side: docs/CATALOG_SOLA_2026.md (extracted from
the client's data/KATALOG-SOLA-2026.pdf, provided 2026-09-22). master.xlsx stays
the HPP/cost side — this module never touches material costs.

Owner authorization (Ejak, 2026-09-22): the products table is empty; seed
products/variants from the real catalog. Selling prices are real business data
(a catalog reference), not fabrication.

Design (no DDL change):
- One `products` row per product family (T-Shirt, Polo, Shirt/Korsa, Hoodie,
  Bomber, Vest, Work Shirt, Cap, Mug, Totebag, Tumbler, Lanyard). `product_code`
  is our stable unique seed key.
- `product_variants`: one row per catalog item (e.g. Cotton Combed 24s, Piqe CVC,
  American Drill, Mug Sablon, Tumbler A...). Each is linked to its master HPP
  `material` by code where one exists (keeps cost side canonical); otherwise
  material_id is NULL.
- `product_variants.notes` carries the SELLING price + the catalog's
  "harga sudah termasuk…" included steps + add-ons, clearly labeled
  (SELLING_PRICE / INCLUDED / ADDONS). Notes, not a price column — avoids DDL and
  keeps the price obviously SELLING, never HPP.
- product_categories for Bomber / Work Shirt (absent from the seeded set) are
  inserted idempotently so every catalog family maps to a category.

Idempotent: keys on product_code and (product_id, variant_name), INSERT OR
IGNORE. Re-runnable.
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BASE_DIR, "instance", "sola.db")

# Each family: (product_code, category_name, product_name) -> list of
# (variant_name, master_material_code_or_None, selling_price_idr, included_note, addons)
CATALOG = {
    "PRD-TS1": (
        "T-Shirt", "T-Shirt",
        [
            ("Cotton Combed 30s", "CC-30S", 55000,
             "sablon 2 posisi, 4 warna, <=A3",
             "Lengan panjang +5.000; XXL +5.000, XXXXL +10.000 dst."),
            ("Cotton Combed 24s", "CC-24S", 60000,
             "sablon 2 posisi, 4 warna, <=A3",
             "Lengan panjang +5.000; XXL +5.000, XXXXL +10.000 dst."),
            ("Cotton Combed 20s", "CC-20S", 65000,
             "sablon 2 posisi, 4 warna, <=A3",
             "Lengan panjang +5.000; XXL +5.000, XXXXL +10.000 dst."),
            ("Cotton Carded 30s", "CD-30S", 50000,
             "sablon 2 posisi, 4 warna, <=A3",
             "Lengan panjang +5.000; XXL +5.000, XXXXL +10.000 dst."),
            ("Cotton Carded 24s", "CD-24S", 55000,
             "sablon 2 posisi, 4 warna, <=A3",
             "Lengan panjang +5.000; XXL +5.000, XXXXL +10.000 dst."),
            ("Polyester (PE)", None, 35000,
             "sablon 2 posisi, 4 warna, <=A3",
             "Lengan panjang +5.000; XXL +5.000, XXXXL +10.000 dst."),
        ],
    ),
    "PRD-PS1": (
        "Polo", "Polo Shirt",
        [
            ("Piqe PE", "PQ-PE", 60000, "bordir 2 posisi", "Lengan panjang +7.500; Manset +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Piqe CVC", "PQ-CVC", 70000, "bordir 2 posisi", "Lengan panjang +7.500; Manset +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Piqe Cotton", "PQ-CT", 75000, "bordir 2 posisi", "Lengan panjang +7.500; Manset +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Lacoste Cotton", None, 85000, "bordir 2 posisi", "Lengan panjang +7.500; Manset +5.000; XXL +5.000, XXXL +10.000 dst."),
        ],
    ),
    "PRD-KS1": (
        "Korsa", "Shirt / Korsa",
        [
            ("American Drill", "DR-AM-KR", 120000, "lengan panjang + bordir 4 posisi", "Tambah bordir +5.000; airflow (jaring) +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Nagata Drill", "DR-NT-KR", 130000, "lengan panjang + bordir 4 posisi", "Tambah bordir +5.000; airflow (jaring) +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Ribstop Premium", "RB-PR-KR", 135000, "lengan panjang + bordir 4 posisi", "Tambah bordir +5.000; airflow (jaring) +5.000; XXL +5.000, XXXL +10.000 dst."),
        ],
    ),
    "PRD-HO1": (
        "Hoodie", "Hoodie",
        [
            ("Fleece PE", "FL-PE", 120000, "bordir/sablon 2 posisi", "Tambah bordir/sablon +5.000; XXL +5.000, XXXXL +10.000 dst."),
            ("Fleece CVC", "FL-CVC", 135000, "bordir/sablon 2 posisi", "Tambah bordir/sablon +5.000; XXL +5.000, XXXXL +10.000 dst."),
            ("Baby Terry", "BT-CVC", 135000, "bordir/sablon 2 posisi", "Tambah bordir/sablon +5.000; XXL +5.000, XXXXL +10.000 dst."),
            ("Fleece Cotton", "FL-CT", 140000, "bordir/sablon 2 posisi", "Tambah bordir/sablon +5.000; XXL +5.000, XXXXL +10.000 dst."),
        ],
    ),
    "PRD-BB1": (
        "Bomber", "Bomber",
        [
            ("Parasut Micro", None, 125000, "bordir/sablon 2 posisi + zipper + lapisan peles", "Tambah bordir/sablon +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Parasut Taslan", None, 135000, "bordir/sablon 2 posisi + zipper + lapisan peles", "Tambah bordir/sablon +5.000; XXL +5.000, XXXL +10.000 dst."),
        ],
    ),
    "PRD-VS1": (
        "Vest", "Vest",
        [
            ("American Drill", "DR-AM-KR", 110000, "bordir/sablon 2 posisi + zipper + lapisan peles", "Tambah bordir/sablon +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Nagata Drill", "DR-NT-KR", 120000, "bordir/sablon 2 posisi + zipper + lapisan peles", "Tambah bordir/sablon +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Ribstop TR", "RB-PR-VS", 110000, "bordir/sablon 2 posisi + zipper + lapisan peles", "Tambah bordir/sablon +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Ribstop Premium", "RB-PR-KR", 135000, "bordir/sablon 2 posisi + zipper + lapisan peles", "Tambah bordir/sablon +5.000; XXL +5.000, XXXL +10.000 dst."),
        ],
    ),
    "PRD-WS1": (
        "Work Shirt", "Work Shirt",
        [
            ("American Drill", "DR-AM-KR", 100000, "bordir 3 posisi", "Tambah bordir +5.000; airflow (jaring) +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Nagata Drill", "DR-NT-KR", 110000, "bordir 3 posisi", "Tambah bordir +5.000; airflow (jaring) +5.000; XXL +5.000, XXXL +10.000 dst."),
            ("Ribstop Premium", "RB-PR-KR", 120000, "bordir 3 posisi", "Tambah bordir +5.000; airflow (jaring) +5.000; XXL +5.000, XXXL +10.000 dst."),
        ],
    ),
    "PRD-CP1": (
        "Topi", "Cap",
        [
            ("Drill", "DR-AM-KR", 30000, "bordir 2 posisi", "Tambah bordir +5.000."),
            ("Raffle", "MAT-001", 40000, "bordir 2 posisi", "Tambah bordir +5.000."),
            ("Laken", None, 55000, "bordir 2 posisi", "Tambah bordir +5.000."),
        ],
    ),
    "PRD-MG1": (
        "Mug", "Mug",
        [
            ("Mug Sablon", "MAT-003", 18000, "sablon 2 warna + box", "Tambah warna +3.000."),
            ("Mug Print (Sublim)", "MAT-002", 20000, "sablon 2 warna + box", "Tambah warna +3.000."),
        ],
    ),
    "PRD-TB1": (
        "Totebag", "Totebag",
        [
            ("Furing 30x25", None, 5000, "sablon 2 warna A4 + zipper", "Tambah warna sablon +3.000; lapisan furing +5.000."),
            ("Furing 45x35", None, 8000, "sablon 2 warna A4 + zipper", "Tambah warna sablon +3.000; lapisan furing +5.000."),
            ("Drill 45x35", "DR-AM-KR", 25000, "sablon 2 warna A4 + zipper", "Tambah warna sablon +3.000; lapisan furing +5.000."),
            ("Kanvas 45x35", "MAT-004", 30000, "sablon 2 warna A4 + zipper", "Tambah warna sablon +3.000; lapisan furing +5.000."),
        ],
    ),
    "PRD-TM1": (
        "Tumbler", "Tumbler",
        [
            ("Tumbler A", "MAT-005", 24000, "sablon 1 warna", "Tambah warna +3.000; box +3.000."),
            ("Tumbler B", None, 30000, "sablon 1 warna", "Tambah warna +3.000; box +3.000."),
            ("Tumbler C", "MAT-006", 50000, "sablon 1 warna", "Tambah warna +3.000; box +3.000."),
        ],
    ),
    "PRD-LY1": (
        "Lanyard", "Lanyard",
        [
            ("Lanyard Only", "MAT-011", 15000, "Min. Order 24 pcs; sablon 1 warna", "—"),
            ("Lanyard + ID Card", "MAT-012", 18000, "Min. Order 24 pcs; sablon 1 warna", "—"),
        ],
    ),
}


def _fmt_price(v):
    return f"{v:,}".replace(",", ".")


def seed_catalog(database_path: str, verbose: bool = False) -> dict:
    conn = sqlite3.connect(database_path)
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    # 1) ensure Bomber / Work Shirt categories exist (additive reference rows)
    for cat_name in ("Bomber", "Work Shirt"):
        cur.execute(
            "INSERT OR IGNORE INTO product_categories (category_name, description)"
            " VALUES (?, ?)",
            (cat_name, "Selling-family from KATALOG-SOLA-2026 (SELLING side)"),
        )

    _cid = {}
    for r in cur.execute("SELECT category_id, category_name FROM product_categories").fetchall():
        _cid[r[1]] = r[0]

    # 2) material code -> material_id (master HPP canonical)
    _mid = {}
    for r in cur.execute("SELECT material_id, material_code FROM materials").fetchall():
        _mid[r[1]] = r[0]

    products_created = 0
    variants_created = 0

    for code, (cat_key, product_name, items) in CATALOG.items():
        category_id = _cid.get(cat_key)
        cur.execute(
            "INSERT OR IGNORE INTO products (product_code, product_name, category_id,"
            " description, status) VALUES (?,?,?,?, 'active')",
            (code, product_name, category_id,
             f"Selling family '{product_name}' from KATALOG-SOLA-2026; SELLING side."),
        )
        if cur.rowcount:
            products_created += 1
        row = cur.execute("SELECT product_id FROM products WHERE product_code=?", (code,)).fetchone()
        pid = row[0]

        for (variant_name, mat_code, price, included, addons) in items:
            material_id = _mid.get(mat_code) if mat_code else None
            notes = (
                f"SELLING_PRICE={price} IDR/pcs; INCLUDED={included}; "
                f"ADDONS={addons}"
            )
            done = cur.execute(
                "INSERT OR IGNORE INTO product_variants"
                " (product_id, variant_name, material_id, notes) VALUES (?,?,?,?)",
                (pid, variant_name, material_id, notes),
            )
            if done.rowcount:
                variants_created += 1

    conn.commit()
    conn.close()
    summary = {
        "products_created": products_created,
        "variants_created": variants_created,
        "families": len(CATALOG),
    }
    if verbose:
        print(
            f"[seed-catalog] families={len(CATALOG)}, new products={products_created}, "
            f"new variants={variants_created} (idempotent)"
        )
        print("[seed-catalog] SELLING price stored in product_variants.notes (SELLING_PRICE=...); "
              "master.xlsx stays the HPP/cost side.")
    return summary


if __name__ == "__main__":
    import sys

    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    seed_catalog(db, verbose=True)