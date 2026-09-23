# SOLA Katalog 2026 — SELLING-PRICE REFERENCE (source of truth for retail price / margin)

Source: `data/KATALOG-SOLA-2026.pdf` (client-provided 2026-09-22, 20.3 MB image catalog).
Complementary to `master.xlsx` (HPP cost). This catalog is the **SELLING** side → margin per item = selling price − HPP.
Values are IDR, "harga sudah termasuk …" = included decoration/processes; add-ons are per-piece surcharges.
Retail quantity cadence implied; Lanyard states Min. Order 24 pcs.

> Naming variances between catalog and master.xlsx (normalize to master codes, keep catalog as alias):
> `Pige`→`Piqe`, `Rafel`→`Raffle`, `Parasit`→`Parasut` (likely OCR of "Parasut"), `Tumblr/Tumbler`.
> Do NOT duplicate materials; use the MASTER HPP `materials` as canonical and the catalog as the selling price + included-steps reference.

## Company context (from catalog narrative)
- Founded 2014 as **Aby Merch Corner** (garments for communities/events); partnered with Bandung garment distributors; grew to national/international clients.
- Transformed to **SOLA** — tagline **"Your Bright Apparel Partner"** — transparent system, honest quality.
- Product families: CLOTHES (T-Shirt, Polo Shirt, Shirt, Hoodie, Jacket, Bomber, Vest, Work Shirt) + MERCHANDISE (Cap, Mug, Totebag, Tumbler, Lanyard).

## CLOTHES — selling prices (IDR per pcs, incl. noted decoration)

### T-Shirt  (incl. sablon 2 posisi, 4 warna, ≤ A3)
| Item | Price | Notes |
|---|---|---|
| Cotton Combed 30s | 55.000 | |
| Cotton Combed 24s | 60.000 | |
| Cotton Combed 20s | 65.000 | |
| Cotton Carded 30s | 50.000 | |
| Cotton Carded 24s | 55.000 | |
| Polyester (PE) | 35.000 | |
- Add-ons: Lengan panjang +5.000; XXL +5.000, XXXXL +10.000 dst.

### Polo Shirt  (incl. bordir 2 posisi)
| Item | Price |
|---|---|
| Piqe PE (catalog "Pige PE") | 60.000 |
| Piqe CVC ("Pige CVC") | 70.000 |
| Piqe Cotton ("Pige Cotton") | 75.000 |
| Lacoste Cotton | 85.000 |
- Add-ons: Lengan panjang +7.500; Manset +5.000; XXL +5.000, XXXL +10.000 dst.

### Shirt / Korsa  (incl. lengan panjang + bordir 4 posisi)
| Item | Price |
|---|---|
| American Drill | 120.000 |
| Nagata Drill | 130.000 |
| Ribstop Premium | 135.000 |
- Add-ons: Tambah bordir +5.000; Tambah airflow (jaring) +5.000; XXL +5.000, XXXL +10.000 dst.

### Hoodie  (incl. bordir/sablon 2 posisi)
| Item | Price |
|---|---|
| Fleece PE | 120.000 |
| Fleece CVC | 135.000 |
| Baby Terry | 135.000 |
| Fleece Cotton | 140.000 |
- Add-ons: Tambah bordir/sablon +5.000; XXL +5.000, XXXXL +10.000 dst.

### Bomber  (incl. bordir/sablon 2 posisi + zipper + lapisan peles)
| Item | Price |
|---|---|
| Parasut Micro ("Parasit Micro" in PDF) | 125.000 |
| Parasut Taslan ("Parasit Taslan" in PDF) | 135.000 |
- Add-ons: Tambah bordir/sablon +5.000; XXL +5.000, XXXL +10.000 dst.

### Vest  (incl. bordir/sablon 2 posisi + zipper + lapisan peles)
| Item | Price |
|---|---|
| American Drill | 110.000 |
| Nagata Drill | 120.000 |
| Ribstop TR | 110.000 |
| Ribstop Premium | 135.000 |
- Add-ons: Tambah bordir/sablon +5.000; XXL +5.000, XXXL +10.000 dst.

### Work Shirt  (incl. bordir 3 posisi)
| Item | Price |
|---|---|
| American Drill | 100.000 |
| Nagata Drill | 110.000 |
| Ribstop Premium | 120.000 |
- Add-ons: Tambah bordir +5.000; Tambah airflow (jaring) +5.000; XXL +5.000, XXXL +10.000 dst.

## MERCHANDISE — selling prices (IDR per pcs, incl. noted decoration)

### Cap  (incl. bordir 2 posisi)
| Item | Price |
|---|---|
| Drill (master: American Drill) | 30.000 |
| Rafel (master: Raffle) | 40.000 |
| Laken | 55.000 |
- Add-ons: Tambah bordir +5.000.

### Mug  (incl. sablon 2 warna + box)
| Item | Price |
|---|---|
| Mug Sablon | 18.000 |
| Mug Print | 20.000 |
- Add-ons: Tambah warna +3.000.

### Totebag  (incl. sablon 2 warna A4 + zipper)
| Item / size | Price |
|---|---|
| Furing 75gr — 30×25 cm | 5.000 |
| Furing 75gr — 45×35 cm | 8.000 |
| Drill — 45×35 cm | 25.000 |
| Kanvas — 45×35 cm | 30.000 |
- Add-ons: Tambah warna sablon +3.000; Tambah lapisan furing +5.000.

### Tumbler  (incl. sablon 1 warna)
| Item | Price |
|---|---|
| Tumbler A | 24.000 |
| Tumbler B | 30.000 |
| Tumbler C | 50.000 |
- Add-ons: Tambah warna +3.000; Tambah box +3.000.

### Lanyard  (Min. Order 24 pcs)
| Item | Price |
|---|---|
| Lanyard Only | 15.000 |
| Lanyard + ID Card | 18.000 |

## Use in the app (Phase 5+ costing engine)
- Seed/consideration: catalog selling prices inform `SELLING PRICE` and `MARGIN = selling − HPP` (spec §10). Material + process master HPP comes from `master.xlsx`; selling price + "already included" decoration/steps from this catalog. Not to be fabricated; if a discounting/price tiering rule is needed later, define it explicitly and get owner confirmation.
- "Termasuk …" notes map to default included `processes`/`decorations` per product for the HPP→margin confirmation.