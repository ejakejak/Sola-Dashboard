# PHASE 3–4 DEV BRIEF — SOLA ⇉ Quotation→Order→Invoice(PDF)→Payment [for @REX]

You are Developer (REX) under EVA. Build Phases 3–4 of the SOLA konveksi dashboard in D:/Sola, ON the verified Phase-2 app. Reuse existing generic `require_permission`/`audit()` and the 7 master-data resources(do not redo). You build the commercial loop next. Read first(anchors):
- `docs/DESIGN_SPEC.md` — UI/UX contract: Sola Gold brand, screens 2 (Orders) + 8 (Invoices) + §4.8 (PDF invoice layout, real company block below. 
- `db/schema.sql` — integrity contract. Tables `quotations, quotation_items, orders, order_items, invoices, invoice_items, payments` ALREADY exist — reuse them. Do NOT alter expect a justified additive migration (document why).
- `docs/CATALOG_SOLA_2026.md` — SELLING-price reference (real prices + "sudah termasuk…" + add-ons; for quote unit prices. Do NOT fabricate prices.
.
- `docs/AUDIT_REPORT.md`, `docs/DATA_DICTIONARY.md`, `docs/DEV_BRIEF.md` (non-negotiables.
- Full product spec: `C:/Users/muham/AppData/Local/hermes/cache/documents/doc_dfd0d1a07b14_PROMPT_AI_AGENT_DASHBOARD_KONVEKSI.txt` (§8–12, §22, §25–27.
.
- Interpreter for runs/tests: `C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe`; run app `cd /d/Sola && PYTHONPATH=. <venv-python> run.py` → `http://127.0.0.1:5000`.

## Scope
### Quotation (flow §8)
- list/create/detail. `quotation_number` auto: `QUO-2026-0001`(etc u, sequential. Line items: product/material/variant/decoration/spec/qty/unit_price/subtotal. Compute subtotal/discount/tax/total. Status flow: `draft→sent→approved|rejected→converted→cancelled`. Audit create/update.

### Convert quotation → Sales Order (§9
- Approved quotation can convert ONCE into a Sales Order beside it is consumed/ locked (cannot convert again. `order_number` auto: `ORD-2026-0001`. `order_items`: product/variant/material/color/decoration/position/size/qty/unit_price/subtotal. Statuses per spec, priority, deadline, grand_total. Audit.


### Invoice generated FROM an order (§11
- `invoice_number` auto: `INV-2026-0001`. Auto-calculate subtotal/discount/tax/grand_total, `amount_paid`,`outstanding = grand_total − amount_paid`. Statuses `draft/issued/partially_paid/paid/overdue/cancelled`. due_date. Not a manual re-entry. Audit.

### Payment (per invoice
- Record into `payments` (amount/method/reference/notes; recompute `amount_paid` (sum), recalc outstanding; set `paid` when outstanding≤0. Audit every payment.

### Invoice PDF — reportlab (A4, print-ready, NOT a screenshot
- Company header (real SOLA block from DESIGN_SPEC §4.8: name 'Sola Konveksi Yogyakarta', address 'Jl. Magelang No.KM 7, Mlati Beningan, Sendangadi, Mlati, Sleman Regency, D.I. Yogyakarta 55285, Indonesia', phone '62 823-7127-5988'; brand logo `app/static/assets/sola-logo-1.png` on top; NO NPWP anywhere. Payment notes render under **KETERANGAN PEMBAYARAN**: 'Pembayaran dilakukan secara transfer ke rekening: BCA 4452337111 a.n. Irhami Al Adaby'. Customer bill-to block, line-items table (qty|description|unit price|amount, tabular-nums), subtotal/taxes/discounts/grand total (bold), payment terms + outstanding, footer thanks/note. Margins ≥12 mm; status-neutral black text on white; only the logo uses brand color. **NEVER embed HPP/margin/internal notes on the customer PDF.** Save a SAMPLE invoice PDF as `docs/SAMPLE_INVOICE.pdf` deliverable(.
- reportlab gotcha: Helvetica mangles Unicode glyphs (`•`, `≥`…;; prefer ASCII or embed a Unicode font; wrap cell text as Paragraphs (plain strings don't wrap); set explicit column widths; fix `&amp;` double-escape.

### Pages per Design_Spec
- Orders list + create/detail;row Invoices list + detail + **Print PDF** download (spec §12: Generate/Preview/Download). Cards + grouped forms, not giant ungrouped tables. Backend authorization enforced per role/§24 reuse existing deeper.



## Working method
- Build phase-by-phase inside this delegation: Quotation → conversion → Invoice → Payment → PDF, running tests/smoke after each sub-step with REAL data (a real customer from `instance/sola.db`, real materials/categories from migration). 
- Test every major sub-step: quotation create → convert to order → generate invoice → record payment → outstanding calc → PDF byte-render (read back the PDF file, confirm non-empty PNG/PDF magic + page count.
- You may add a small `tests/test_app_phase34.py` suite; and a live smoke(.
- Follow planning-with-files SOP; update plan progress as you finish phases.


## Report (to EVA, English): per sub-phase: file paths+routes+test results; SAMPLE invoice PDF abs path; verified behaviors(quotation→order→invoice→payment→pdf with real data, outstanding math, PDF renders, no HPP leak); any schema changes + why;; blockers (exact error, not partial success. Distinguish implemented vs boundary-prepared. Never fabricate results — run the real code.; if a hard blocker appears stop and report exactly.



_Refrain: parties don't manufacture business data; unit prices come from the real catalog/master; author. Visa for /track, dashboard analytics, kanban, inventory, deployment are later phases — do NOT build them now_