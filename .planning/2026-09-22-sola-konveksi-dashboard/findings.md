# Findings & Design Context

## Requirements (from DESIGN_BRIEF + product spec §19–25)
- Modern, clean, professional; desktop-first but responsive. Operators are non-technical floor/sales/finance/admin staff.
- Status colors used consistently: Success / Warning / Danger / Info / Neutral. AntGo: too many colors.
- Generic production architecture — NOT kaos-only. Products span garments (T-Shirt, Polo, Korsa, Hoodie, Vest, Jersey, Topi) + non-garment (Mug, Totebag, Tumbler, Goodiebag, Blocknote, Lanyard, Handfan).
- Dashboard Home = KPI cards + visualizations, NOT giant tables. KPIs: Active Orders, In Production, Waiting Payment, Ready to Ship, Overdue, Outstanding Invoice. Plus: overdue production, low stock alert, unpaid invoice, upcoming deadline, recent production update.
- Production Board = Kanban columns ORDER→MATERIAL→CUTTING→SEWING→PRINTING→FINISHING→QC→PACKING→COMPLETED. Card: Production Code, Customer, Product, Qty, Deadline, Progress, PIC, Priority, Status. Click→Production Detail.
- Production Detail: customer/order/product/qty/deadline/current stage/overall progress + timeline; each stage openable (progress, qty, PIC, vendor, timestamps, notes, customer-visible media, internal media if permitted). INTERNAL vs CUSTOMER media visibility lock.
- Public /track: no login; input Production Code (e.g. PRD-260922-001); shows product/qty/order date/est completion/current stage/overall progress/timeline/latest update/customer-visible media/important notes. MUST NOT show HPP, margin, internal notes, vendor price, internal attachments, other customers, sensitive payment.
- Tracking security (§20): don't expose DB IDs; safe lookup of production code; rate limiting/anti-abuse; no enumerable endpoint; customer gets only their data. Authorization enforced backend (§24), not just hiding buttons.
- Roles (§24): ADMIN (full), SALES (customer/quotation/order/invoice), PRODUCTION (production/stages/progress/media), WAREHOUSE (material/inventory/stock), QC (QC/reject/rework), FINANCE (invoice/payment/financial report), MANAGEMENT (read-only dashboard+reports), CUSTOMER (public tracking only).
- §25 anti-goals: giant table-only pages; too many colors; number-dense screens without hierarchy; long ungrouped forms; destructive button without confirmation. Use cards/tabs/filters/kanban/timeline/charts; modal/drawer for detail; global search.
- Audit data: master materials (Jersey 15500, Cotton Combed 30s 23000, Cotton Carded 24s 25000, Piqe 20000–33000, Fleece 68000–98000, American/Nagata Drill 40500–60000…), processes (Cutting 3000, Jahit 2500, Sablon 7000–15000, Bordir 8000/13000). Production status flows through ORDER/MATERIAL/CUTTING/SEWING/PRINTING/FINISHING/QC/PACKING → COMPLETED.

## Design Context (discoveries)
- HPP units are IDR (thousands); invoice/quote figures render in IDR (Rp) with thousands separators as safety.
- Production code format `PRD-YYMMDD-NNN` — primary token on cards, detail, and /track.
- Priority values → danger (high), warning (medium), neutral (normal). Deadline: danger if overdue, warning if ≤48h to deadline, neutral otherwise.
- Media: INTERNAL visible only to internal staff roles (PRODUCTION/ADMIN etc); CUSTOMER visible to customer + all staff. Locked visitors never present on customer surface.

## Resources
- Spec: `C:/Users/muham/AppData/Local/hermes/cache/documents/doc_dfd0d1a07b14_PROMPT_AI_AGENT_DASHBOARD_KONVEKSI.txt` (§19–25, §26 schema)
- `D:/Sola/docs/DESIGN_BRIEF.md`, `D:/Sola/docs/AUDIT_REPORT.md`