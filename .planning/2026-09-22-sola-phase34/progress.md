# Progress Log — SOLA Phase 3-4 (REX)

Session 2026-09-22. Root D:/Sola. Phase-2 app verified (7/7 tests).

## Phase A — Permissions + seed (complete, no DDL)
- seed/seed_auth.py: PERMISSIONS +10 (quotation.view/create/update/convert, order.view/create, invoice.view/create/update/payment). ADMIN=all, SALES=full commercial, FINANCE=(quotation.view, order.view, invoice.*+payment), MANAGEMENT=read-only (quotation/order/invoice.view). Permissions 15->25; role_permissions 31->linked fields update. ensure_seeded idempotent; ran on instance/sola.db.

## Phase B — Quotation (complete)
- app/commercial.py QUOTE_BP; routes: GET/POST /quotations/, /quotations/new, /quotations/<qid>, POST /quotations/<qid>/status, /quotations/<qid>/convert.
- Auto number QUO-<YYYY>-NNNN year-fresh. Line items (product/variant/material/decoration/spec/qty/unit/price/subtotal). subtotal-discount+tax=total. Status draft|sent|approved|rejected|cancelled (converted only via convert()). Audit CREATE/UPDATE.
- Templates: quotation_list/form/detail.

## Phase C — Convert one-shot -> Order (complete)
- POST /quotations/<id>/convert: only APPROVED, quote locked (status=converted), second convert blocked; copies quote items -> order_items; ORD-<YYYY>-NNNN; priority/deadline/grand_total. Audit CREATE order + CONVERT quotation. Order list/detail + direct create boundary (/orders/new with product/color/size/decoration/position).

## Phase D — Invoice from order (complete)
- POST /invoices/from-order/<oid>: blocks cancelled/pending orders and duplicate active invoice; copies order+items -> invoice+invoice_items (description built w/ product/material/color/size/decoration). INV-<YYYY>-NNNN. amount_paid=0, outstanding=grand_total, status draft. Audit CREATE invoice.

## Phase E — Payment (complete)
- POST /invoices/<iid>/payment: insert payments row (amount/method/reference/notes/created_by=current_user); recompute amount_paid=SUM, outstanding=grand_total-amount_paid; paid when <=0 else partially_paid. Issue required before payment. Audit CREATE payment each time.

## Phase F — Invoice PDF (complete)
- app/invoice_pdf.py: reportlab A4 portrait, margins 14mm (>=12), Arial TTF for Unicode, logo top, company block (Sola Konveksi Yogyakarta / address / phone), INVOICE ref, bill-to, line-items table (qty|desc|unit price|amount tabular), subtotal/discount/tax/grand-total bold, KETERANGAN PEMBAYARAN + BCA 4452337111 a.n. Irhami Al Adaby, outstanding, footer. NO NPWP/HPP/margin/internal. Get route /invoices/<iid>/pdf returns bytes.

## Phase G — Live smoke (complete) REAL data from instance/sola.db
- scripts/smoke_phase34.py: real customer "Live Smoke Customer"(id2) + real material CC-30S(id33, Cotton Combed 30s, catalog 55.000). Full loop via Flask test client on the real DB:
  quote QUO-2026-0001 (12 x 55.000 = 660.000) -> approved -> ORD-2026-0001 (grand 660.000, high, locked, not duped) -> INV-2026-0001 (outstanding 660.000, no dupe) -> issue -> partial 330.000 (outstanding 330.000, partially_paid) -> rest 330.000 -> paid outstanding 0.
  PDF rendered 1 page A4, 130089 bytes, magic %PDF, company block + payment note + logo(gold) present; NPWP/HPP/margin/Komisi absent. Wrote docs/SAMPLE_INVOICE.pdf.
- Read routes render 200 (real DB) under admin; permission surface verified for management/finance/warehouse role nav gating.

## Phase H — tests (complete)
- tests/test_app_phase34.py: 9 isolated tests (temp DB) pass: navigation gate, create+audit+numbering, bad conversion requires approved, one-shot lock, invoice from order + no dupe, payment+outstanding+paid, PDF renders + no HPP, finance role 403 on convert, management read-only.

## Schema changes
- NONE (DDL). Only additive permission data seeding in seed_auth.py (justified, reuses existing permissions table).

## Blockers
- None.

## Deliverables
- SAMPLE invoice PDF: D:/Sola/docs/SAMPLE_INVOICE.pdf (130089 bytes, 1 page)
- Exact routes in app/commercial.py (blueprints quotations/orders/invoices).