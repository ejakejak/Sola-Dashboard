# Task Plan — SOLA Phase 3-4 (REX): Quotation → Order → Invoice → Payment → Invoice PDF

Root: D:/Sola. Interpreter: C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe
SOP: planning-with-files. Build/test phase-by-phase with REAL data from instance/sola.db.
Do NOT build Phase 5+ (track, dashboard analytics, kanban, inventory, deployment).

## Phases (build + test each)
- A. Permissions + seed (additive data: quotation/order/invoice/payment perms → roles; no DDL). Status: complete
- B. Quotation module (auto QUO-YYYY-NNNN, line items, totals, status flow, audit; list/create/detail/conversion). Status: complete
- C. One-shot approved→order conversion (ORD-YYYY-NNNN, lock quote, audit) + order list/detail + direct create boundary. Status: complete
- D. Invoice generated FROM order (INV-YYYY-NNNN, one active invoice/order, no dupe; outstanding=grand-amount_paid). Status: complete
- E. Payment (recompute amount_paid=sum, outstanding, paid≤0; audit each). Status: complete
- F. Invoice PDF (reportlab A4, company block, no NPWP/HPP, ASCII-safe fonts, margins≥12mm). Status: complete
- G. Live smoke on instance/sola.db (real customer + real materials) + SAMPLE_INVOICE.pdf. Status: in_progress
- H. tests/test_app_phase34.py (isolated). Status: complete (9/9 pass)

## Implemented
- app/commercial.py (QUOTE_BP /quotations, ORDER_BP /orders, INVOICE_BP /invoices) + app/invoice_pdf.py
- Templates: quotation_list/form/detail, order_list/form/detail, invoice_list/detail
- app/templates/base.html nav (Quotations/Orders/Invoices), app.css tables/badges/lineitems
- seed/seed_auth.py: +10 perms wired (ADMIN all, SALES full commercial, FINANCE invoice+payment, MANAGEMENT read-only)
- tests/test_app_phase34.py (9 tests)
- Files: D:/Sola/app/commercial.py, app/invoice_pdf.py, app/templates/{quotation,order,invoice}_*.html, tests/test_app_phase34.py