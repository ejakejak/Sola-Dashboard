# SOLA Master Data — Phase 0 Audit Report

Source of truth: Google Sheet `MASTER DATA SOLA 1.0`
- Spreadsheet ID: `1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA`
- Pulled (link-shared, no auth) → `D:/Sola/data/master.xlsx`
- Service account (for write/private access): `ejak-sola@project-8ce84eb6-6b51-48fe-ae3.iam.gserviceaccount.com`

## 1. Workbook inventory

| Sheet | Dim | Rows×Cols | Role |
|---|---|---|---|
| `HPP` | A1:M34 | 34×13 | Pivot cost matrix per product category → material + process costs |
| `MASTER HPP` | A1:C29 | 29×3 | **Authoritative code+price lookup** (ITEM / ITEMID / PRICE) |
| `Sheet3` | A1:F31 | 31×6 | Additional product categories (Topi, Mug, Totebag, Tumbler, Goodiebag, Blocknote, Lanyard, Handfan) |
| `DATABASE AGEN` | A1:E3 | 3×5 | Agents (2 rows) |
| `DATABASE PENJAHITMAKLOON` | A1:D19 | 19×4 | Vendors (penjahit/makloon) |

## 2. Sheet: `MASTER HPP` (authoritative pricing master)

**Materials (→ `materials` + `material_prices`):**

| ITEM | ITEMID | PRICE | Context / note |
|---|---|---|---|
| Cotton Combed 30s | `CC-30S` | 23000 | |
| Cotton Combed 24s | `CC-24S` | 26200 | |
| Cotton Combed 20s | `CC-20S` | 32500 | |
| Cotton Carded 30s | `CD-30S` | 21000 | |
| Cotton Carded 24s | `CD-24S` | 25000 | |
| Piqe PE | `PQ-PE` | 20000 | |
| Piqe CVC | `PQ-CVC` | 29250 | |
| Piqe Cotton | `PQ-CT` | 33000 | |
| American Drill | `DR-AM-KR` | 40500 | **context: Korsa** |
| Nagata Drill | `DR-NT-KR` | 52000 | **context: Korsa** |
| Ribstop Premium | `RB-PR-KR` | 58000 | **context: Korsa** |
| Fleece PE | `FL-PE` | 68000 | |
| Fleece CVC | `FL-CVC` | 89500 | |
| Fleece Cotton | `FL-CT` | 98000 | |
| Baby Terry CVC | `BT-CVC` | 89500 | |
| Baby Terry Cotton | `BT-CT` | 98000 | |
| Jersey | `JR` | 15500 | **normalize: also called "Kaos" in HPP sheet** |
| Jersey + Celana | `JR-CL` | 22000 | |
| American Drill | `DR-AM-VS` | 49200 | **context: Vest** |
| Nagata Drill | `DR-NT-VS` | 60000 | **context: Vest** |
| Ribstop | `RB-PR-VS` | 46000 | **context: Vest** |

**Processes (→ `processes` + `process_prices`):**

| ITEM | ITEMID | PRICE |
|---|---|---|
| Cutting | `CT` | 3000 |
| Jahit | `JT` | 2500 |
| Sablon DTF | `SB-DTF` | 7000 |
| Sablon Rubber | `SB-RB` | 10000 |
| Sablon Plastisol | `SB-PS` | 15000 |
| Bordir Kaos | `BR-KS` | 8000 |
| Bordir Korsa | `BR-KR` | 13000 |

## 3. Sheet: `HPP` (per-category pivot → product types + material/process costs)

Product categories present: **T-Shirt**, **Polo Shirt**, **Korsa/Shirt**, **Hoodie**, **Vest/Rompi**, **Jersey**. Column layout is a *pivot per product group* (a header row names the columns; data rows are materials with per-process costs). This is not a flat table — it must be denormalized per category into (product_type, material, process, cost).

| Category | Material | Cutting | Jahit | Bordir | DTF | Rubber | Plastisol | Zipper | Print&Press |
|---|---|---|---|---|---|---|---|---|---|
| T.Shirt | Cotton Combed 30s | 1500 | 2500 | 8000 | 7000 | 10000 | 15000 | − | − |
| T.Shirt | Cotton Combed 24s | 1500 | 2500 | 8000 | 7000 | 10000 | 15000 | − | − |
| T.Shirt | Cotton Combed 20s | 1500 | 2500 | 8000 | 7000 | 10000 | 15000 | − | − |
| T.Shirt | Cotton Carded 30s | 1500 | 2500 | 8000 | 7000 | 10000 | 15000 | − | − |
| T.Shirt | Cotton Carded 24s | 1500 | 2500 | 8000 | 7000 | 10000 | 15000 | − | − |
| Polo | Piqe PE | 1500 | 7000 | 8000 | 5000 | − | − | − | − |
| Polo | Piqe CVC | 1500 | 7000 | 8000 | 5000 | − | − | − | − |
| Polo | Piqe Cotton | 1500 | 7000 | 8000 | 5000 | − | − | − | − |
| Korsa | American Drill | 3000 | 25000 | 13000 | − | − | − | − | − |
| Korsa | Nagata Drill | 3000 | 25000 | 13000 | − | − | − | − | − |
| Korsa | Ribstop Premium | 3000 | 25000 | 13000 | − | − | − | − | − |
| Hoodie | Fleece PE | 2000 | 7000 | 8000 | 7000 | − | 15000 | 5000 | − |
| Hoodie | Fleece CVC | 2000 | 7000 | 8000 | 7000 | − | 15000 | 5000 | − |
| Hoodie | Fleece Cotton | 2000 | 7000 | 8000 | 7000 | − | 15000 | 5000 | − |
| Hoodie | Baby Terry CVC | 2000 | 7000 | 8000 | 7000 | − | 15000 | 5000 | − |
| Hoodie | Baby Terry Cotton | 2000 | 7000 | 8000 | 7000 | − | 15000 | 5000 | − |
| Vest | American Drill | 3000 | 20000 | 10000 | − | − | − | − | − |
| Vest | Nagata Drill | 3000 | 20000 | 10000 | − | − | − | − | − |
| Vest | Ribstop | 3000 | 20000 | 10000 | − | − | − | − | − |
| Jersey | Kaos (=Jersey) | 1000 | 3000 | − | − | − | − | − | Print&Press 4000 |
| Jersey | Kaos dan Celana (=Jersey+Celana) | 2000 | 8000 | − | − | − | − | − | Print&Press 7000 |

## 4. Sheet: `Sheet3` (more product categories)

| Category | Item | Material cost | Other costs |
|---|---|---|---|
| Topi | American Drill | 4000 | Bordir 5000, DTF 500, Potong&Jahit 12000 |
| Topi | Nagata Drill | 5000 | Bordir 5000, DTF 500, Potong&Jahit 12000 |
| Topi | Raffle | 6500 | Bordir 5000, DTF 500, Potong&Jahit 12000 |
| Mug | Mug Sublim | 11000 | Sublim 2000, Box 900, Sablon `-`→NULL |
| Mug | Mug Sablon | 8500 | Sablon 5000, Box 900, Sublim `-`→NULL |
| Totebag | American Drill | 8000 | DTF 3000, Jahit 2000 |
| Totebag | `Kanvas ` (trailing space) | 12500 | DTF 3000, Jahit 2000 |
| Tumbler | Tumbler A | 14000 | Sablon `-`→NULL |
| Tumbler | Tumbler C | 34000 | Sablon 2000 |
| Goodiebag | Ukuran 20x25 | 450 | Sablon 500, Fee=`% Keuntungan` |
| Goodiebag | Ukuran 25x35 | 1000 | Sablon 500, Fee=`% Keuntungan` |
| Blocknote | A6 | 800 | Jilid&Cetak 800 |
| Blocknote | A5 | 1200 | Jilid&Cetak 1000 |
| Lanyard | Lanyard Only | 10000 | |
| Lanyard | Lanyard & ID Card | 13000 | |
| Handfan | Diameter 15.5 cm | 2500 | |

## 5. Sheet: `DATABASE AGEN` → `agents`

| NAMA | ALAMAT | NOHP (raw) | NOHP normalize | FAKULTAS | KAMPUS/SEKOLAH |
|---|---|---|---|---|---|
| ZAKARIA | MLATI | 895391621335 | `0895391621335` | FISIPOL/PSDK | UGM |
| ARGA | TANGERANG | 85156455465 | `085156455465` | FISIPOL/PSDK | UGM |

## 6. Sheet: `DATABASE PENJAHITMAKLOON` → `vendors` (type=penjahit/makloon)

| NAMA | ALAMAT (maps URL) | NOHP raw | NOHP normalize | SPESIFIKASI |
|---|---|---|---|---|
| Eni Purwanti | maps URL | 89608085909 | `089608085909` | Kaos dan Polo |
| Linda | maps URL | 82136764015 | `082136764015` | Kaos, polo, korsa, makloon potong korsa |
| Giyanti | maps URL | 85737672613 | `085737672613` | Jas Almamater, korsa |
| Nur | maps URL | 85726376791 | `085726376791` | Kaos, polo, training, jaket |
| Utari | maps URL | 882008801006 | `0882008801006` | Kaos, polo, training |
| Duwi | maps URL | `-` | **NULL** | Kaos, polo, training |
| Tini | maps URL | 87739603584 | `087739603584` | Tas, Samir, Appron |
| Mas Pupung | maps URL | `-` | **NULL** | Korsa, Vest, Jas Almamater |
| Bu Lungsi | maps URL | 85647526660 | `085647526660` | Kaos, Polo, Jaket |
| Mba Tari | maps URL | 85743313377 | `085743313377` | Kaos, Polo, Jaket, Korsa |
| Pandu | maps URL | 88983234508 | `088983234508` | Korsa, Vest, Makloon Potong |
| Nurul | maps URL | 85927423426 | `085927423426` | Korsa, Vest |
| Mas Muji | maps URL | 8161401207 | `08161401207` | Korsa, Vest, Jas Almamater |
| Mas Triyono | maps URL | 85877147663 | `085877147663` | Korsa, Vest, Jas Almamater |
| Ahmadi | maps URL | 8562859619 | `08562859619` | Sablon Plastisol, Rubber |
| Mas Agus | maps URL | 85105033440 | `085105033440` | Sablon Mug, Tumber, Pecah belah |
| Mas Marji | maps URL | 85878816177 | `085878816177` | Sablon Tas |

Note: vendor specialization strings map → candidate `VendorCapability` (Sewing/Kaos/Polo, Korsa, Vest, Jas Almamater, Sablon*). This is a many-to-many; the raw string is preserved as a note + tokenized into capabilities.

## 7. Findings / normalization rules (from the prompt's required categories)

1. **Phone as TEXT**: all `NOHP`/`NOMOR HP` values are numeric floats with leading `0` stripped → store padded with leading `0` as text.
2. **`-` placeholder → NULL**: no record, `NULL` value (Mug/Tumbler sablon or sublim; Duwi & Mas Pupung phone).
3. **Fee column is a string, not a number**: `Max 5000/2000/3000` → a *commission cap* attribute; `% Keuntungan` → *percent-of-profit* commission mode. Neither is a numeric fee. See DECISION below.
4. **Same name, context-specific price**: `American Drill`, `Nagata Drill`, `Ribstop` appear under both Korsa (`*KR`) and Vest (`*VS`) with different prices → material price must be keyed by (material, product-context) or modeled as distinct material price variants. Do NOT merge — they are context variants.
5. **Name inconsistency**: `Jersey` (master) == `Kaos` (HPP row) both 15500 → canonical name `Jersey`; and `Jersey + Celana` == `Kaos dan Celana`. Map aliases during migration.
6. **Trailing-space typo**: `Kanvas ` → trim to `Kanvas`.
7. **Stray cell**: `M1=31500` on the T-Shirt header row (no column header) — flagged, NOT imported as a price row; likely a stray subtotal. Record in migration warnings.
8. **Blank separator rows** between product groups (`HPP` rows 5,8,13,18,23,26,31; `Sheet3` rows 5,9,13,17,21,25,29) → skipped (not errors).
9. **Pivot layout**: `HPP`/`Sheet3` column meaning changes per product-group header → parse per-group, not as one flat table.
10. **No duplicate phone collisions** among vendors/agents after normalization.

## 8. Open decisions (labeled, not silently defaulted)
- **D1 — Fee modeling**: `Fee` in source is a commission indicator, not a true cost. Default: model as `commission_cap` (int, NULL if none) + `commission_mode` ('flat_cap' | 'percent_of_profit' | NULL). HPP contributes it to the product-type's default commission template, not to materials/processes.
- **D2 — Context-variant material prices**: default `material_prices(material_id, product_category, unit_price)` with the Korsa/Vest disambiguation carried by `product_category`. Source `ITEMID` suffix (`KR`/`VS`) is the disambiguator.
- **D3 — Product catalog seeding**: derive initial `products` (T-Shirt, Polo, Korsa, Hoodie, Vest, Jersey, Topi, Mug, Totebag, Tumbler, Goodiebag, Blocknote, Lanyard, Handfan) + default `production_workflow_templates` from these categories.