# DESIGN BRIEF — SOLA Konveksi & Production Dashboard (for @Neo, Designer)

Role: **Designer** (@Neo). You own design direction + UI/UX quality for every screen of the SOLA dashboard. EVA coordinates; REX implements your spec. Build/code executes,but design output/quality is **your call**. Deliver a compact, implementation-ready **design direction + UI spec** — not code.

## Product context
SOLA is a **konveksi/custom merchandise** business (garments: T-Shirt, Polo, Korsa, Hoodie, Vest, Jersey, Topi... / non-garment: Mug, Totebag, Tumbler, Goodiebag, Blocknote, Lanyard, Handfan). A production-management web dashboard. Generic architecture — **not kaos-only**. Operators are non-technical production-floor staff + sales + finance + admin. Spec: `C:/Users/muham/AppData/Local/hermes/cache/documents/doc_dfd0d1a07b14_PROMPT_AI_AGENT_DASHBOARD_KONVEKSI.txt` (esp §21-25).

## Deliverables (a compact design spec doc, e.g. `D:/Sola/docs/DESIGN_SPEC.md`)
1. **Design system**: color tokens mapped to the prompt's status semantics (success/warning/danger/info/neutral — consistent, minimal palette; "too many colors" is a spec anti-goal), typography hierarchy, spacing, cards rounded+shadow, buttons/inputs, badges, empty states. Modern, clean, professional, desktop-first but responsive.
2. **Layout IA**: shell (sidebar nav: Dashboard, Orders, Production Board, Customers, Inventory, Master Data, Invoices, Reports, Tracking↓, roles-gated per spec §24)). KPI cards + charts, NOT giant tables (spec §21。. Global search где applicable。
3. **Screens**: Dashboard home (KPI cards: Active Orders, In Production, Waiting Payment, Ready to Ship, Overdue, Outstanding Invoice + low-stock alert, upcoming deadline, recent updates); Production Board **Kanban** (columns ORDER→MATERIAL→CUTTING→SEWING→PRINTING→FINISHING→QC→PACKING→COMPLETED, cards w/ production code/customer/product/qty/deadline/progress/PIC/priority/status; click→detail); Production detail (timeline; stages openable; INTERNAL vs CUSTOMER media w/ visibility lock); public `/track` (customer-facing, mobile-friendly, **only customer-visible media**, no HPP/margin/internal). Form/grouping, modal/drawer for detail, destructive actions need confirmation.
4. **Component guidance** for REX (interpretable by a coder): table, filter/tabs, kanban card, timeline, progress, status badge, media upload w/ visibility, invoice/PDF print-ready layout… Confirm destructive UI.
5. **Anti-patterns to avoid** (spec §25): giant table-only pages; color overuse; screens full of raw numbers w/o hierarchy; ungrouped long forms; destructive button w/o confirm; exposing HPP/margin/internal on customer view.

## Rules
- Use the prompt's status-color semantics consistently. Keep canvas/tooling as output medium only — design direction is your call.
- Output a spec doc (recommend `D:/Sola/docs/DESIGN_SPEC.md`, but you may choose the path; state it). No code needed (REX implements from your spec). Keep it concise enough for a developer to build each screen faithfully. Numbered screens + token table + kanban/timeline/modal sketches (ASCII or brief notation OK。
- This is a route-through-Neo standing rule: all design/visual work ships via you;do not let REX bypass.**