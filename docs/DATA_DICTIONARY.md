# SOLA — Data dictionary & Excel → DB mapping

Source: `D:/Sola/data/master.xlsx` (from Google Sheet `MASTER DATA SOLA 1.0`, id `1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA`).
Target: relational SQLite DB `D:/Sola/instance/sola.db` (FK enabled). Excel is migration source only — never the runtime store.

## Mappings

### `MASTER HPP` → `materials` + `material_prices` / `processes` + `process_prices`
- `ITEM` → unique master row key (material OR process by lookup set). Materials set + Processes set are disjoint by known item names.
- `ITEMID` → `code` (unique). Suffix `KR`/`VS` denotes Korsa/Vest context.
- `PRICE` → `material_prices.unit_price` (context-keyed) or `process_prices.unit_price`.
- Material context variants (same name, 2 codes) → one `material` row + two `material_prices` rows keyed by `product_category`.

### `HPP` (pivot) → seed `products`, `processes`, `material_prices`, `product_process_maps`, `commission_template`
- Group header (e.g. `T Shirt`) → `products` (canonical category name normalized: `T Shirt`→`T-Shirt`, `Korsa/Shirt`→`Korsa`, `Vest/Rompi`→`Vest`).
- Data row `A=material` → `materials`, `B=material_cost` → `material_prices.unit_price` (category-context). Remaining columns `C..` = per-process costs → `processes` + `product_process_maps(product,process,default_cost)`.
- `Fee`(`Max N`/`% Keuntungan`) → `commission_template` (mode + cap). Not a material/process cost.
- Blank separator rows → skipped.

### `Sheet3` → `products` (Topi, Mug, Totebag, Tumbler, Goodiebag, Blocknote, Lanyard, Handfan) + their material/process maps.
- `-` in a cost cell → nullable (no edge).
- `Kanvas ` → trim to `Kanvas`.

### `DATABASE AGEN` → `agents`
- `NAMA→name`, `ALAMAT→address`, `NOHP→phone` (text, leading-0 restored), `FAKULTAS→faculty`, `KAMPUS/SEKOLAH→campus`.

### `DATABASE PENJAHITMAKLOON` → `vendors` (+ `vendor_capabilities`)
- `NAMA→vendor_name` (type `makhloon/penjahit`), `ALAMAT→address` (maps URL), `NOMOR HP→phone` (text/leading0, `-`→NULL), `SPESIFIKASI→notes` + tokenized into `vendor_capabilities` by detected keyword (Kaos, Polo, Korsa, Vest, Jas Almamater, Jaket, Tas, Sablon, etc.).

## Canonical entity list (spec §26, all seeded/relational)
products, product_variants, materials, material_colors, material_prices, processes, process_prices, decorations, decoration_prices, vendors, vendor_capabilities, customers, agents, quotations, quotation_items, orders, order_items, invoices, invoice_items, payments, production_orders, production_stages, production_updates, production_media, quality_checks, inventory, stock_movements, material_usage, production_workflow_templates, production_workflow_template_steps, commission_templates, users, roles, permissions, user_roles, audit_logs, sizes, colors, units.

## Value normalization rules
- Phone → text with leading `0` restored (source lost it as float).
- `-` → `NULL`.
- `Fee` text → `(commission_mode, commission_cap)`; not money on the item.
- Duplicate item names kept distinct by context code (`KR`/`VS`) — never merged.
- Names trimmed; aliases mapped (`Kaos`→`Jersey`, `Kaos dan Celana`→`Jersey + Celana`).