# Findings & Decisions — Quotation Edit Draft (Sola)

## Requirements (from Trigger message)
- Quotation status "draft": show "Edit Draft" button near "Set Status".
- Edit: customer/PIC, dates (quotation_date & valid_until), line items (description/service, qty, unit, unit price), add/remove item, totals auto-recalculated.
- Save: UPDATE same quotation (NOT create new); number & id unchanged; status stays draft; latest data shown on detail.
- Reuse the same form/component as Create Quotation for UI & logic consistency.
- If status is not draft, hide Edit Draft.
- Test QUO-2026-0003: change first item qty 30 -> 35, save, verify total changes & number unchanged.
- Do NOT push to GitHub. Report test results, wait for approval.

## Research Findings
- Sola app root: D:/Sola (Flask + storage backend).
- Quotation routes: `app/commercial.py` QUOTE_BP (blueprint `/quotations`):
  - `GET /` list, `GET/POST /new` create, `GET /<qid>` detail, `POST /<qid>/status`, `POST /<qid>/convert`.
  - `_collect_quotation()` parses create form (customer_id, quotation_date, valid_until, discount, tax, notes, item lines: product/material/decoration/qty/unit/price; totals = subtotal - discount + tax).
  - Permission decorators: `require_permission("quotation.create"|"view"|"update"|"convert")`.
- Templates: `app/templates/quotation_form.html` (create: customer + valid_until + discount/tax/notes + JS line-item rows), `quotation_detail.html` (line items table + totals + Set Status / Convert forms).
- Schema (db/schema.sql): `quotations(quotation_id, quotation_number, customer_id, quotation_date, valid_until, subtotal, discount, tax, total, notes, status)`; `quotation_items(quotation_item_id, quotation_id, product_id, variant_id, material_id, decoration_id, specification, quantity, unit_id, unit_price, subtotal)`.
- Storage: commercial routes use `SheetRelational` over `current_app.extensions["storage"]` (SheetsStorage). README: source of truth = Google Sheet `MASTER DATA SOLA 1.0` (id `1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA`); service-account key `instance/sola-509413-service-account.json`.
- Live sheet `quotations` tab has 3 rows; **QUO-2026-0003** = quotation_id 3, customer_id 4, status draft, valid_until 2026-09-30, total 2700000. `quotation_items` for it: item_id 3 (product 2, material 65, qty **30**, unit 1, price 85000, subtotal 2550000) + item_id 4 (decoration 5, qty 30, unit 1, price 5000, subtotal 150000).
- The running server on 127.0.0.1:5000 (started 2026-09-23 01:47) serves sqlite-era data (list shows only QUO-2026-0001); to test QUO-2026-0003 we must run against the live sheet backend with creds.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Add `edit(qid)` route (perm quotation.update), GET prefills, POST saves in place | Only drafts editable; reuse existing form fields |
| Reuse `_collect_quotation()` for POST body parse | Logic consistency with create |
| Replace quotation_items (delete all for qid, insert from form) on save | Simpler than per-item diff; matches create item shape |
| Show Edit Draft only when q.status=='draft' and c_update | Requirement + permission gate |
| Test against live sheet (SPREADSHEET_ID + service-account) | QUO-2026-0003 lives there; matches production store |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| MSYS /tmp path not readable by native python.exe | Use $LOCALAPPDATA/Temp |
| Running :5000 detail(latest id) 404/missing QUO-2026-0003 | Stale server; use live-sheet run for the real test |

## Resources
- App: D:/Sola ; routes: app/commercial.py ; templates: app/templates/quotation_form.html, quotation_detail.html
- Interpreter: C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe
- Sheet id: 1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA ; key: D:/Sola/instance/sola-509413-service-account.json
- SOP docs: docs/DESIGN_SPEC.md, docs/DATA_DICTIONARY.md