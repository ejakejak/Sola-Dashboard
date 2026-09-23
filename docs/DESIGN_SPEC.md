# SOLA — Production Dashboard UI/UX Design Spec

**Version:** 1.0 · **Author:** Neo (Designer) · **Owner decision:** Design direction is final; REX implements from this spec. No code needed.
**Scope:** Internal production-management dashboard (desktop-first) + public customer-facing `/track` page (mobile-friendly). Generic production architecture — not konveksi/T-shirt-only; flows and tokens apply to all garment and non-garment product families.

This spec is the single source of truth for UI/UX. Any deviation or ambiguity is a design bug to raise here, not a developer judgment call.

---

## 1. Design System

### 1.1 Color tokens — status semantics only

**Anti-goal: minimal palette. Exactly 5 semantic status colors + neutral scale + 1 brand accent.** Never invent a new color for a new feature. If it isn't one of the statuses below, it takes the neutral/brand token instead.

Light theme (default). Tokens use semantic names; hex is the reference. All statuses ship with a **base** (for text/icons), **default surface** (badge/soft fill), and **border** (outlined states), plus a 500-strength used for progress/graph fills.

| Token | Base (text/icon) | Surface (badge bg) | Border | 500-strength fill | Meaning |
|-------|------------------|--------------------|--------|-------------------|---------|
| `--brand` | Sola Gold `#CCA300` | `#FFF7CC` (soft gold wash, est.) | `#E6CE68` (gold border, est.) | `#CCA300` | Primary actions, headers, links, active nav, highlights, sidebar accents |
| `--neutral` | text `#0F172A` on light | white `#FFFFFF` / antique-white `#FEFDFD` | `#E2E8F0` | `#94A3B8` | Default, pending, normal, N/A |

**Brand source (client-confirmed, ground truth):** Colors come from the client-provided SOLA logo — an all-white "SOLA" wordmark on a flat gold field (`app/static/assets/sola-logo-1.png`; identical copy `sola-logo-2.png`). Use the logo in the sidebar/nav header and the print-ready PDF invoice header. PRIMARY = **Sola Gold `#CCA300`**; on-color foreground/neutral = **white `#FFFFFF` / antique-white `#FEFDFD`** (on-color text+icons, opposite neutral on light panels). The logo has **no second accent hue** — status-semantic colors (success/warning/danger/info) are a design choice, not read from the logo, and should harmonize on gold/white (avoid loud colors that clash). A derived darker gold, **`#8A6D00`** (near the gold for text-on-light legibility), is an **estimated tint** — label it as an estimate in any shipped token.
| `--info` | Sky `#0284C7` | `#E0F2FE` | `#7DD3FC` | `#0EA5E9` | New/waiting, informational, current stage |
| `--success` | Emerald `#059669` | `#D1FAE5` | `#6EE7B7` | `#10B981` | Completed, confirmed, passed QC, paid |
| `--warning` | Amber `#D97706` | `#FEF3C7` | `#FCD34D` | `#F59E0B` | In progress, imminent, medium priority |
| `--danger` | Rose `#DC2626` | `#FEE2E2` | `#FCA5A5` | `#EF4444` | Overdue, failed QC, rejected, low stock, unpaid, high priority |

**Status → color mapping (apply consistently EVERYWHERE a status appears — badge, dot, Kanban column header accent, chart, KPI):**

| Status / concept | Token |
|------------------|-------|
| Pending / New / N/A | `--neutral` |
| Waiting (payment, material) | `--info` |
| In progress / In production / In **active** stage | `--warning` |
| Confirmed / Completed / Paid / Passed QC / Ready to ship | `--success` |
| Overdue / Failed / Rejected / Low stock / Unpaid invoice | `--danger` |
| Medium priority | `--warning` |
| High priority | `--danger` |
| Normal priority | `--neutral` |
| Current production stage (on timeline) | `--warning` |
| Upcoming stage (timeline) | `--neutral` |

**Neutral grayscale** (for text, borders, backgrounds): `--bg #F8FAFC`, `--surface #FFFFFF`, `--border #E2E8F0`, `--text #0F172A`, `--text-muted #64748B`, `--text-faint #94A3B8`. Use muted/faint for secondary metadata so numbers and statuses carry the visual weight.

> Design rule: color is reserved for **state**, never decoration. A page should read mostly neutral/gray with brand accent on interactive controls and status colors only where a real status exists.

### 1.2 Typography

System font stack for reliability & performance: `Inter, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`. Tabular numerals for all numeric columns (`font-variant-numeric: tabular-nums`) to stop digits jittering in tables/KPIs.

| Token | Size / Weight | Usage |
|-------|---------------|-------|
| `--fs-2xl` | 28px / 700 | Page title |
| `--fs-xl` | 20px / 700 | Section header, KPI value, drawer title |
| `--fs-lg` | 16px / 600 | Card title, dialog title, sidebar item |
| `--fs-md` | 14px / 500 (body) | Default body, table cells, inputs |
| `--fs-sm` | 13px / 500 | Input labels, buttons (primary size), badge text |
| `--fs-xs` | 12px / 500 | Helper text, footer, breadcrumb, timestamps, table column headings |
| `--fs-micro` | 11px / 600 | Created-by tags, meta chips |

Line-height: body `1.5`, headings `1.25`. Numbers/large KPI values use `700`. Never underline body text except real links.

### 1.3 Spacing & layout grid

Base unit **4px**. Use scale: `4 · 8 · 12 · 16 · 24 · 32 · 48`. Page content max-width ~**1440px** centered, with a left sidebar (see §2). Content gutter 24px.

- Card padding: `16px` body / `16px 20px` header.
- Between cards in a grid row: `16px`.
- Section spacing: `24px`.
- Component gap within a card: `12px`.

### 1.4 Cards & surfaces

- White surface (`--surface`), **border `1px solid --border`**, **radius `12px`**, soft shadow `0 1px 2px rgba(15,23,42,.06)`. (Subtle — cards are containers, not decoration.)
- Card anatomy: optional header row (`title left`, `actions right`) + body `16px` padding.
- Clickable cards: hover raises shadow `0 6px 16px rgba(15,23,42,.10)` + `cursor:pointer`; focus ring `2px --brand`.
- KPI card: icon in a tinted rounded square (`40×40`, radius 8) left of a value + label; value 20px bold; small status-aware subline (e.g. "+3 this week" or "2 overdue").

### 1.5 Buttons

| Variant | Style | Use |
|---------|-------|-----|
| Primary | `--brand` bg, white text, radius 8, `14px/500` | Single main action per view |
| Secondary | white bg, 1px `--border`, `--text` | Supporting actions |
| Ghost | transparent text-only | Header actions, toolbar |
| Danger | `--danger` bg, white text | **Destructive only** (delete, cancel order, reject) |
| Danger-ghost | transparent, `--danger` text, `--danger` border on hover | Destructive lightweight |

Sizes: height **36px** (default), **32px** small, **44px** for mobile. Disabled: 40% opacity, not-interactive. Every button: focus-visible ring `2px --brand` offset 2px. Icon buttons `40×40` with tooltip.

### 1.6 Inputs & form controls

- Height 36px, radius 8, border `1px --border`, focus border `--brand` + ring `3px --brand` at 20% opacity, background `--surface`.
- Labels `--fs-sm` weight 500 above field; required marked `*` in `--danger`. Placeholder `--text-faint`. Helper text `--fs-xs` `--text-muted` below.
- States: `error` (border `--danger` + message `--danger`), `disabled` (40% opacity), `readonly`.
- Selects/date pickers follow same control geometry. Combobox with search for customer/product/master lookups (operators type — avoid long dropdowns from memory).
- Toggle/checkbox: `--brand` accent; sizes comfortable for mouse but not oversized.
- Validation on blur + on submit; never block typing mid-keystroke.

### 1.7 Badges & chips

- Pill radius `999px`, height 22px, padding `0 8px`, `--fs-xs`/600.
- **Soft style** (default): `<token>--surface` bg + `<token>` text, e.g. Overdue = `--danger--surface` bg + `--danger` text.
- **Solid style** (progress/labels you must read from across the board): `<token>` bg + white text; reserve for the Kanban status tag.
- Optional leading status **dot** (6px, token fill) on board cards.
- `<Dot + label>` and `<icon + label>` composition allowed; never stack two colored chips for the same row unless one is priority and one is status.

### 1.8 Empty states

Never render a bare empty table/board. Show: centered illustration/glyph (neutral tint), a **clear one-line message**, a **single suggested action** when permissions allow, and nothing when they don't.

Examples:
- Kanban column no cards → "No jobs in CUTTING." + ghost "Move another job here".
- /track no record → "We couldn't find that production code. Check the code and try again." + "Enter another code".
- Filter yields nothing → "No results match your filters." + "Clear filters" ghost button.
- Tables empty → icon + "No records yet" + "Create first record" if role permits.

---

## 2. Layout / Information Architecture

### 2.1 App shell

```
┌──────────────────────────────────────────────────────────────┐
│ ┌──────────────┬────────────────────────────────────────────┐ │
│ │ SOLA  logo   │  Topbar: global search │ Notif │ Profile▾ │ │
│ │              ├────────────────────────────────────────────┤ │
│ │  NAV          │  Page region (routing outlet)              │ │
│ │  Dashboard    │  · page title + subtitle                    │ │
│ │  Orders       │  · toolbar (tabs/filters/actions)           │ │
│ │  Production   │  · content (cards, kanban, table, detail)   │ │
│ │  Board        │                                              │ │
│ │  Customers    │                                              │ │
│ │  Inventory    │                                              │ │
│ │  Master Data  │                                              │ │
│ │  Invoices     │                                              │ │
│ │  Reports      │                                              │ │
│ │  ──────────   │  Page footer (muted)                         │ │
│ │  /track ▸     │                                              │ │
│ │  (open)       │                                              │ │
│ └──────────────┴────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

- **Sidebar** fixed `240px`, collapsible to `64px` (icons-only) via a toggle; full page background `--bg`.
- **Topbar** 56px: left = breadcrumb/page title context; center/right = **global search** (cmd/ctrl+K), notifications bell (badge dot for unfiltered count), user menu (name, role chip, sign out).
- **Role chip** in user menu shows the logged role (Admin/Sales/Production/Warehouse/QC/Finance/Management).
- Responsive: below `1024px` sidebar collapses to icons; below `768px` sidebar becomes an off-canvas drawer opened by hamburger. Topbar actions wrap.

### 2.2 Sidebar navigation (roles-gated per spec §24)

Sidebar items, in order, each mapped to roles that may see/use it. **Enforced in backend — the sidebar is only the surface expression of the same gate.** Management is read-only (no create/edit/delete buttons anywhere; destructive controls absent).

| Nav item | Route | Visible roles (§24) |
|----------|-------|---------------------|
| Dashboard | `/` | Admin, Sales, Production, Warehouse, QC, Finance, Management |
| Orders | `/orders` | Admin, Sales, Finance (finance reads payments/invoice portion), Management (read) |
| Production Board | `/production` | Admin, Production, QC, Management (read), Sales (read) |
| Customers | `/customers` | Admin, Sales, Management (read) |
| Inventory | `/inventory` | Admin, Warehouse, Management (read) |
| Master Data | `/master-data` | Admin, Warehouse (materials), Sales (products/customers) — subtree-gated |
| Invoices | `/invoices` | Admin, Finance, Sales (read), Management (read) |
| Reports | `/reports` | Admin, Finance, Management (read) |
| **/track ▸** (public) | `/track` | Public — opens in same tab; no login |

Rules:
- Hidden nav items by role — do **not** show a disabled/dead link for an unauthorized section.
- Within a screen, capability is role-checked per control: e.g. Production sees "Update stage"; QC sees "QC Pass / Reject / Rework"; Sales cannot see the HPP number in Production detail; Finance sees invoice/payment blocks.
- **Finance** sees money (HPP, margin, price, invoice). **Non-finance internal roles** see production/customer data but **not HPP/margin** unless their duty needs it (see §3.3 visibility lock). **Customer** sees only §3.4.

---

## 3. Screens

### 3.1 Dashboard home (`/`)

KPI cards in a **6-column grid** (3×2 on desktop, 2×3 on tablet, stacked on phone). Each card: icon tile + value (bold 20px) + label + small muted subline. Clicking a KPI navigates to the relevant filtered screen.

| KPI | Token | Subline source |
|-----|-------|----------------|
| Active Orders | `--info` | count of orders not completed/cancelled |
| In Production | `--warning` | count of productions in MATERIAL…PACKING |
| Waiting Payment | `--warning` | unpaid confirmed orders/invoices due now |
| Ready to Ship | `--success` | productions at/after QC pass with no open blocker |
| Overdue | `--danger` | overdue productions or orders, count |
| Outstanding Invoice | `--danger` | unpaid invoices total in Rp |

**Below KPIs** — a 12-col grid, priority top-left→bottom-right:

1. **Production Board snapshot** (span 8): compact horizontal Kanban preview (8 stage mini-cols) OR a stage-distribution bar chart (bars colored by status token) + top 3 overdue cards. Click → Production Board. *Not a table.*
2. **Alerts stack** (span 4): three stacked alert cards — **Low stock** (`--danger` icon, "5 items below reorder point", link → Inventory filtered), **Upcoming deadline** (`--warning`, nearest N deadlines w/ production code), **Unpaid invoice** (`--danger`, count + total).
3. **Recent production updates** (span 12): a compact timeline/feed of latest stage updates (production code, stage, PIC, timestamp, thumbnail). Click → Production detail.

Hierarchy: values first, colored statuses second, muted metadata last. No raw-number dumps.

### 3.2 Production Board — Kanban (`/production`)

**9 columns**, fixed order: `ORDER → MATERIAL → CUTTING → SEWING → PRINTING → FINISHING → QC → PACKING → COMPLETED`. Columns scroll **horizontally** within their container; each column header = `name + count` badge (count colored by stage token, e.g. CUTTING default `--info`, COMPLETED `--success`).

**Kanban card** (`214px` wide, white, border 1px `--border`, radius 10, hover raise):
```
┌────────────────────┐
│ ⚑ PRIORITY   [STATUS]│   ← priority dot token + solid status badge
│ PRD-260922-001      │   ← production code (mono, 13px/600)
│ Customer · Product   │   ← sm muted
│ Qty: 90 pcs          │
│ ▓▓▓▓▓░░░ 62% · CUTTING│   ← progress bar 4px + label
│ PIC: Tina · Due 24/09 │   ← xs muted; due in --danger if overdue / --warning if ≤48h
│ 📎 3   🖼 2           │   ← media counts (customer/internal) optional
└────────────────────┘
```
Full card fields (§22): Production code, Customer, Product, Quantity, Deadline, Progress, Priority, Status, PIC. **Entire card is one button** → opens Production Detail (or drawer on mobile).

Column interactions:
- **Drag-and-drop** between adjacent/non-adjacent columns (drag handle = card). On drop → confirm dialog if the move changes stage beyond QC (e.g. to COMPLETED) or regresses.
- **Quick add** ghost card at column bottom (role-gated to Production/Admin).
- Column footer count "X items". Priority cards optionally sort to top within a column via column menu.
- Toolbar: tabs (All / Only overdue / Only high priority), search by code/customer, filter by product family. **Not a giant table** — Kanban is the primary view; a compact table is an alternative toggle only for QA/finance bulk review.

### 3.3 Production Detail (`/production/:code`)

Opens as a **full-page detail** (deep-linkable) with a two-column layout; on mobile it may render as a full-screen drawer.

**Header card:** production code (mono), overall progress bar (token = `--warning` while active, `--success` when 100%), current stage badge, priority badge, and meta (customer, product, qty, order ref, vendor, PIC, deadline, started/updated timestamps). Actions row (role-gated): Update Stage, Edit, Print, Cancel/Delete (danger + confirm).

**Left column — Timeline (primary):** vertical timeline of the 9 stages. Each stage row: status icon (✓ success / dot current / ○ neutral upcoming) + stage name + stage-level progress + key/value pad. **Stages are openable/expandable** (accordion) →

Collapsed row shows: stage name, status, progress %, PIC, qty.
Expanded row reveals: vendor, **timestamps** (started/completed), **notes**, and the stage's media gallery (filtered by visibility, see below), plus stage-specific controls (e.g. QC row: Pass / Reject / Rework buttons).

**Right column — Details & media:**
- **Info card**: order & production fields.
- **Media card**: gallery grid (thumbnails). Each media item carries a visibility tag:
  - **INTERNAL** `--danger`-tinted chip (eye-off icon) — visible ONLY to internal staff (Admin, Production, and any role explicitly granted; **never** to Finance-blocked-of-HPP? no — Internal media = production-internal, visible to staff roles; **never** to Customer).
  - **CUSTOMER** `--success` chip (globe/eye icon) — visible to customer + all internal staff.
  - A **visibility lock** toggle when uploading (default `CUSTOMER`) so a busy operator can't accidentally leak; any change to INTERNAL is explicitly confirmed.
- **Finance block** (Admin/Finance only): HPP breakdown, margin, price. **Hidden entirely for other roles** (no zero/value placeholder needed).

**Media visibility rule (§19–23):** the Customer never receives INTERNAL media. When a stage carries a photo marked INTERNAL, the customer's feed (both /track and any customer-facing export) **does not render it or expose its URL**. Authorization is backend-enforced, not hidden-CHIP-on-frontend.

### 3.4 Public /track (customer-facing)

Route `/track`, **no login**, mobile-first layout (single column, comfortable tap targets ≥44px).

**Flow:**
```
/track
  └─ Code input page:  "Track your order"  [ PRD-XXXXXXX ] [ Track ]
       · hint/pattern text: "Enter your production code from your invoice", example shown.
       · validation inline (format check); results/errors below, never navigate away.
       └─ on valid code → result view (below), same URL fragment
          └─ "Not found?" card → "Check with your sales contact." (no enumeration, no suggestions)
```

**Result view shows ONLY (§19):** Product, Quantity, Order date, Estimated completion, Current stage (badge), Overall progress (bar), **Timeline** (✓/current/○), Latest update (text), **Customer-visible media only**, Important notes (customer field).
**Never renders/exposes:** HPP, margin, vendor price, **internal notes**, **internal media/URLs**, other customers, sensitive payment data.

Security (§20): production code is a **derived public token**, never a raw DB id. Backend lookup rate-limited (e.g. per-IP sliding window), no sequential/enumerable endpoint, and the code is the sole query key. All fields on this page are server-filtered to the CUFF list above — the client never receives disallowed data (no reliance on front-end hiding).

**Visual:** branded, single-column cards, large readable type, status colors preserved (Overdue in `--danger`, Completed in `--success`), timeline same component as internal but showing only customer fields.

### 3.5 Data forms & grouped editing

- **Long forms are always grouped** into labeled sections with a `grouped accordion` or stepped wizard (e.g. New Order = Contact & Shipping → Items → Scheduling & Pricing → Review).
- Recommended grouping per record type:
  - **Order/Quotation:** Customer & Channel → Line items (product, qty, material, decoration, unit price) → Schedule & Priority → Notes.
  - **Production:** Order ref → Product/Workflow template → Stage scheduling → PIC/vendor assignment → Priority & notes.
  - **Invoice:** Billing customer → Line items (pull from order) → Payment terms & notes.
  - **Product/Customer Master:** Identity → Attributes → Notes & media.
- Inline section validation; a section error is surfaced at the section header (badge) — never a wall of inline errors only.
- Two-paned master/detail for line-item-heavy forms (items table on left, selected item editor on right).

### 3.6 Modal vs Drawer for detail & actions

| Show in **drawer** (right slide, 480–560px, or full on mobile) | Show in **modal** (centered dialog) |
|----------------------------------------------------------------|--------------------------------------|
| View/edit a record's fields (production detail on narrow screens, invoice preview) | Confirmation dialogs |
| Quick-create with follow-on context | Destructive confirmations |
| Media gallery lightbox | Bulk-stage-change confirmation |

- Modal/drawer overlay: `rgba(15,23,42,0.5)`; ESC to close; click-outside to close **unless** there'd be data loss → then block with a "Discard changes?" guard.
- Focus trapped; first field autofocused; primary action defaulted to Enter.

### 3.7 Destructive actions — confirmation rule

**Any** action that is irreversible or near-irreversible (delete, cancel order, cancel production, reject → rework, stage-complete regression past QC, override) **must** show a confirmation dialog:
- Title states the consequence plainly ("Cancel production PRD-260922-001?").
- Body: 1–2 sentences on impact (e.g. "Line items reserved will be released.").
- Buttons: [Cancel] (secondary) + [Confirm / Yes, cancel] (**danger**). No "OK" ambiguity.
- For full deletion, the confirm button requires typing nothing extra — but the action is logged to the audit log (§27-style) with actor + timestamp. Consider a 2-step for destructive (confirm → type reason).
- Provide an undo path / audit trail where feasible instead of hard-deleting.

---

## 4. Component Guidance (implementable blueprints)

### 4.1 Data table (compact, used sparingly)

- Used for Master Data, Inventory, Invoices, Customer lists — **not** for production boards.
- Anatomy: toolbar (tabs, filters, search, density/export) → table (sticky header, `--bg` header row, row hover `--neutral--surface`, zebra optional `--bg`@50%) → pagination footer (count, page controls, page-size).
- Columns: sortable by header click (arrow indicator); numeric right-aligned `tabular-nums`; status column uses **badge**, never raw text.
- Row height 44px; an action menu (⋯) on the row for per-row ops (edit, view, print). Key ops as inline icon buttons for the 1–2 most common.

### 4.2 Filters & tabs

- **Tabs:** horizontal underline tabs (active `--brand` underline + weight 600). Used for status views (e.g. Invoices: All / Paid / Unpaid / Overdue).
- **Filters:** a filter bar (chips + "Add filter") → dropdown fields. Active filter chips show token `--neutral--surface`, removable via ×. Global search + sort exposed in the toolbar.
- All filters combine; empty-state explains no matches + "Clear filters".

### 4.3 Kanban card & column

Definitions in §3.2. Reusable: `<ProductionCard>` receives the production object and renders fields exactly in that order. Column accepts drop; DnD library (e.g. dnd-kit) with drag preview as a semi-transparent card clone.

### 4.4 Timeline (stage list)

Shared internal + /track. Data model per stage: `{ name, status: done|current|pending, progress, pic, vendor, startedAt, completedAt, notes, media }`. Render as vertical list with a left rail of status icons connected by a line (rail color = `--success` for passed segment, `--neutral` for upcoming). Current stage emphasized (bold, `--warning` dot).

### 4.5 Progress

Base component: `<Progress value modular>` — 4px bar, `--neutral--surface` track, fill token by state (default `--brand`/`--warning`, `--success` when 100%). Optional label "62%" at right (`--fs-xs`, `tabular-nums`). Circular variant only for KPI donuts (Reports), not for day-to-day.

### 4.6 Status badge

`<Badge token={neutral|info|success|warning|danger} variant={soft|solid} dot? label>` per §1.7. Single source for rendering any status string → mapped via §1.1 table. Do **not** hand-color badges inline anywhere in the app.

### 4.7 Media upload with visibility lock

Upload control: dropzone (dashed border, click-to-browse, multi-select) → list of queued files each with a preview + **visibility selector**: `[👁 Customer] [🔒 Internal]` segmented control, **default Customer**, each row marked. On save, files POST with `visibility` field. Metadata: title, optional caption, captured-by, timestamp, stage link. Uploads blocked while a role lacks permission; INTERNAL media is stored/returned only to allowed roles.

### 4.8 Print-ready PDF invoice layout

Produced by a print/PDF template (A4 portrait). Layout order: (1) company header block (name/address/contact) + **INVOICE** title + invoice no/date; (2) bill-to block (customer) + our details; (3) line-items table (qty | description | unit price | amount) with `tabular-nums`, subtotal, taxes/fees, discounts, **grand total bold**; (4) payment terms + bank/transfer info; (5) footer (thanks, note, scanned-from-print layout). Margins ≥12mm; status-neutral black text on white; only the logo uses brand color. **Never auto-embed INTERNAL/HPP data or customer-hidden notes on the PDF.**

**Company / payment block — client-provided (SOLA, 2026-09-22, ground truth for the template):**
- Company legal name: **Sola Konveksi Yogyakarta**
- Brand: SOLA (logo `app/static/assets/sola-logo-1.png` in header)
- Phone: `62 823-7127-5988`
- Street address (from owner's Google Maps link): **Jl. Magelang No.KM 7, Mlati Beningan, Sendangadi, Mlati, Sleman Regency, D.I. Yogyakarta 55285, Indonesia**
- Payment notes (render under **KETERANGAN PEMBAYARAN**): "Pembayaran dilakukan secara transfer ke rekening: **BCA 4452337111 a.n. Irhami Al Adaby**"
- **NPWP: NOT used (owner confirmed 2026-09-22) — do not render or require NPWP anywhere on invoices or forms.**
- These values are the PDF template's config source (env/config, editable without code change).

---

## 5. Anti-Patterns — never do these (spec §25)

1. **Giant table-only pages.** Production Board must be a Kanban; Dashboard must be KPI cards + charts + feed. Tables only for Master/Inventory/Invoices/Reports, kept compact and filterable.
2. **Color overuse.** Stay within the 5 tokens + brand + neutral. No rainbow states; reserve color for status. A mostly-gray page with the right 2–3 status accents is success.
3. **Number-dense screens without hierarchy.** Always separate value (large) / status (badge) / metadata (muted). Don't dump raw numbers in a grid; group them into KPI cards and summaries.
4. **Long ungrouped forms.** Always group/step long forms with valid section headers and per-section error badges (§3.5).
5. **Destructive buttons without confirmation.** Delete/cancel/reject/regress past QC always confirm with a clear consequence dialog + danger button + audit log (§3.7).
6. **Exposing HPP / margin / internal notes on the customer surface.** Customer view (`/track` + customer PDF exports) renders only the §19 whitelist; INTERNAL media, HPP, margin, vendor price, internal notes, and sensitive payment are never present in the payload sent to the customer (§3.4, §4.7).
7. (Supporting) **Authorization only by hiding buttons.** All gates enforced in backend; sidebar/button visibility is only the surface of the same check (§2.2).

---

## Appendix — Screens checklist (implementer's map)

| # | Screen | Route | Key components |
|----|--------|-------|----------------|
| 1 | Dashboard | `/` | 6 KPI cards, board snapshot/barchart, alert stack, recent feed |
| 2 | Orders | `/orders` | table + tabs(All/Confirmed/Waiting/Completed), filter bar, drawer detail |
| 3 | Production Board | `/production` | 9-col Kanban, draggable cards, toolbar, compact table toggle |
| 4 | Production Detail | `/production/:code` | header, timeline (openable stages), media w/ visibility, finance block |
| 5 | Customers | `/customers` | table + drawer, grouped form |
| 6 | Inventory | `/inventory` | table (on-hand/reserved/available), low-stock badge, movement drawer |
| 7 | Master Data | `/master-data` | gated subtree: materials, products, processes, vendors, agents |
| 8 | Invoices | `/invoices` | table + tabs, preview drawer, Print PDF (§4.8) |
| 9 | Reports | `/reports` | charts (stage distribution, revenue, overdue), export |
| 10 | Public tracking | `/track` | code form + result view, mobile-first, §3.4 security |

*Status-color mapping in §1.1 is the contract — implement tokens once and reuse. End of spec.*