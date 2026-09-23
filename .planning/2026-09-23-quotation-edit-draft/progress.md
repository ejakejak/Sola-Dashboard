# Progress Log — Quotation Edit Draft (Sola)

## Session: 2026-09-23

### Phase 1: Discovery
- **Status:** complete
- Located Sola app at D:/Sola (Flask). Quotation routes in app/commercial.py (QUOTE_BP).
- Confirmed live store = Google Sheets `MASTER DATA SOLA 1.0` (id 1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA); commercial routes require SheetsStorage.
- QUO-2026-0003 (quotation_id 3): status draft, customer_id 4, first item product 2 / material 65 qty 30 x Rp85000 = Rp2.550.000; second item decoration 5 qty 30 x Rp5000 = Rp150.000; total Rp2.700.000.

### Phase 2: Implementation
- **Status:** complete
- Added `edit(qid)` route (GET/POST, /quotations/<qid>/edit, permission quotation.update) in app/commercial.py. Only status==draft allowed. POST reuses _collect_quotation(), UPDATEs same row (keeps id/number, status forced draft), deletes+re-inserts line items, recomputes totals, audits UPDATE. GET prefills shared form (customer, dates, items); failed POST preserves submitted values.
- Extended app/templates/quotation_form.html for create+edit share (prefill, is_edit branching, additive "Quotation date" field, blank-line clone).
- Added "Edit Draft" button to app/templates/quotation_detail.html (c_update and status==draft only).
- Files: app/commercial.py, app/templates/quotation_form.html, app/templates/quotation_detail.html

### Phase 3: Testing (live sheet)
- **Status:** complete
- Harness scripts: scripts/test_edit_draft_live.py, scripts/test_edit_draft_extra.py
- Ran end-to-end against the real sheet with service-account creds. QUO-2026-0003 first item qty 30 -> 35, saved.
- Result: ALL PASS. Detail shows Edit Draft only on draft + permission; edit GET 200 prefilled (qtys ['35','30'], prices ['85000','5000']); POST redirects to detail; number unchanged QUO-2026-0003; status stays draft; total recomputed Rp 3.125.000; first item subtotal Rp 2.975.000; audit_logs has UPDATE quotation entity_id=3 (old total 2700000 -> new 3125000). Edit Draft HIDDEN on converted (0001) and cancelled (0002).
- Direct sheet readback confirms: quotations row 3 total 3125000 status draft; quotation_items row 3 quantity 35 subtotal 2975000 (rationale: tested per task).

### Regression
- test_*_storage / test_app_phase* failures (SheetsStorage not configured / SqliteStorage assertions) are PRE-EXISTING on baseline (confirmed by stashing my changes and re-running — identical failures). Not caused by this work.

## Test Results
| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| Edit button visible | QUO-2026-0003 detail | shown | shown | PASS |
| Edit hidden non-draft | 0001 converted, 0002 cancelled | hidden | hidden | PASS |
| Edit GET prefill | /quotations/3/edit | 200 prefilled | 200, qtys/prices filled | PASS |
| Edit POST save | first item qty 30->35 | update same quote | redirect to detail | PASS |
| Number unchanged | after save | QUO-2026-0003 | QUO-2026-0003 | PASS |
| Status stays draft | after save | draft | draft | PASS |
| Total recalculated | 35x85000 + 30x5000 | Rp 3.125.000 | Rp 3.125.000 | PASS |
| First item subtotal | 35*85000 | Rp 2.975.000 | Rp 2.975.000 | PASS |
| Audit recorded | edit POST | UPDATE quotation id 3 | row id 101 present | PASS |

## Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-09-23 | MSYS /tmp path unreadable by native python | 1 | use $LOCALAPPDATA/Temp for probe scripts |
| 2026-09-23 | detail /quotations/3 404 on :5000 | 1 | running server uses stale sqlite-era data; test against live sheet |
| 2026-09-23 | "block 'crumb' defined twice" (Jinja) | 1 | keep blocks unconditional; branch inside via is_edit |
| 2026-09-23 | IndentationError in edit() | 3 | rebuild the function via deterministic python splice (patch fuzzy-match kept corrupting) |
| 2026-09-23 | ModuleNotFoundError 'app' | 1 | run with PYTHONPATH=. |

## Delivery
- Not committed, not pushed to GitHub. Awaiting Ejak approval.