# Task Plan: Quotation EDIT DRAFT feature (Sola)

## Goal
Add an "Edit Draft" button on the Quotation detail page (shown only when status == "draft") that lets the user edit customer, dates, and line items (add/remove, edit qty/unit/price), with totals recalculated. Saving UPDATES the same quotation (number & id unchanged, status stays draft), reusing the existing Create form/component for UI & logic consistency. Test with QUO-2026-0003: change first item qty 30 -> 35, verify total changes and number unchanged. Do not push to GitHub; report results and await approval.

## Next Step
Implement backend edit route + tests.

## Current Phase
Phase 2 (Implementation)

## Phases
### Phase 1: Discovery & requirements
- [x] Locate Sola app (D:/Sola), identifier used backends, confirm Quotation code path (app/commercial.py, templates/quotation_form.html + quotation_detail.html).
- [x] Verify live data source: Google Sheets backend (MASTER DATA SOLA 1.0), QUO-2026-0003 = draft, first item qty 30 x Rp85000 = Rp2.550.000, total Rp2.700.000.
- [x] Record findings in findings.md
- **Status:** complete

### Phase 2: Implementation
- [x] Add `edit` route (GET/POST) to quotations blueprint; allows only status=="draft"; reuses _collect_quotation(); UPDATE same row (keep id/number/status=draft), replace items, recompute totals, audit UPDATE.
- [x] Extend quotation_form.html to support edit mode (prefill customer/dates/items; reuse same form fields).
- [x] Add "Edit Draft" button in quotation_detail.html when status=="draft" && permission quotation.update.
- **Status:** complete

### Phase 3: Testing & verification (vs QUO-2026-0003)
- [x] Boot app against live sheet (SPREADSHEET_ID + service-account creds).
- [x] GET edit form prefilled; POST qty first item 30 -> 35; verify totals recomputed & number unchanged & status stays draft.
- [x] Verify detail page renders updated data.
- **Status:** complete

### Phase 4: Delivery
- [x] Report file paths, route, test results; do not push to GitHub; await Ejak approval.
- **Status:** complete

## Key Questions
1. Which storage backend is authoritative? -> Live Google Sheets (post-cutover codebase).
2. Does the running server on :5000 reflect latest code? -> It serves stale sqlite-era data (only QUO-2026-0001); authoritative data for QUO-2026-0003 is the sheet.

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Test against live Google Sheet with real creds | QUO-2026-0003 exists only there; codebase requires SheetsStorage |
| Reuse _collect_quotation() + quotation_form.html | Task requires UI + logic consistent with Create |
| Update in place (not create new) | Task requires number/id unchanged, stays draft |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| MSYS /tmp not readable by native python | 1 | use $LOCALAPPDATA/Temp for probe scripts |
| detail /quotations/3 404 on running server | 1 | running :5000 uses stale sqlite-era data; test against live sheet instead |

## Notes
- Do NOT git push. Report and wait for approval.
- Interpreter: C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe