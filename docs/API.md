# SOLA — HTTP Route / Endpoint Catalog

Gathered directly from the registered blueprints in `app/`
(`auth.py`, `masterdata.py`, `commercial.py`, `production.py`, `inventory.py`,
`track.py`) and the root route in `app/__init__.py`. All paths are relative to the
app root `http://127.0.0.1:5000`.

Legend: **AUTH** = authenticated session cookie required; **PUBLIC** = no login;
**403** = authenticated but lacks the required permission (returns
`app/templates/403.html`). Anonymous users are redirected to `/login?next=<path>`.

## Public (no login)

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/login` | Login form + authenticate (POST). Success redirects to dashboard or `next`. |
| GET/POST | `/track` | (Phase 7) Customer tracking — enter a `production_code`, see that production's **customer-visible** data. Rate-limited per IP (default 20 lookups/hr, 5-fail cooldown 90s). |
| GET | `/track/media/<code>/<file>` | Serves **CUSTOMER**-visibility media only; INTERNAL media or any mismatch returns 404. |

## Auth (`auth_bp`)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET/POST | `/logout` | AUTH | End session, clear cookie, redirect to `/login`. |

## Dashboard + master data

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/` | AUTH (any role) | (Phase 8) KPI dashboard: 6 live cards, low-stock / overdue / unpaid alerts, recent-updates feed. |
| GET | `/master-data/` | `masterdata.view` | Master-data hub (links to each resource). |
| GET | `/master-data/<key>` | `masterdata.view` | List one resource. `key` ∈ `materials`, `products`, `processes`, `decorations`, `vendors`, `agents`, `customers`. |
| GET/POST | `/master-data/<key>/new` | AUTH + `assert_permission(<res>.create)` | Create form / submit. |
| GET/POST | `/master-data/<key>/<int:rid>/edit` | AUTH + `assert_permission(<res>.update)` | Edit form / submit. |

> For master data the create/update gate is **per-resource** (e.g. `material.create`,
> `product.update`) chosen from the `key`; `masterdata.view` is incidental to reach
> the form. All writes write an `audit_logs` row.

## Commercial loop (`/quotations`, `/orders`, `/invoices`)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/quotations/` | `quotation.view` | Quotation list. |
| GET/POST | `/quotations/new` | `quotation.create` | Create quotation (+ auto line numbering). |
| GET | `/quotations/<int:qid>` | `quotation.view` | Quotation detail. |
| POST | `/quotations/<int:qid>/status` | `quotation.update` | Change status (e.g. approve). |
| POST | `/quotations/<int:qid>/convert` | `quotation.convert` | Convert an **approved** quotation → order (locked to once). |
| GET | `/orders/` | `order.view` | Order list. |
| GET/POST | `/orders/new` | `order.create` | Create order (from quotation or direct). |
| GET | `/orders/<int:oid>` | `order.view` | Order detail. |
| GET | `/invoices/` | `invoice.view` | Invoice list (shows outstanding). |
| POST | `/invoices/from-order/<int:oid>` | `invoice.create` | Generate an invoice from an order. |
| GET | `/invoices/<int:iid>` | `invoice.view` | Invoice detail. |
| POST | `/invoices/<int:iid>/status` | `invoice.update` | Change invoice status. |
| POST | `/invoices/<int:iid>/payment` | `invoice.payment` | Record a payment; outstanding auto-recomputed. |
| GET | `/invoices/<int:iid>/pdf` | `invoice.view` | Download invoice as PDF (fully client-side, no HPP/network data). |

## Production (`/production`)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/production/templates` | `workflow.manage` | Workflow template list. |
| GET/POST | `/production/templates/new` | `workflow.manage` | Create workflow template. |
| GET/POST | `/production/templates/<int:tid>/edit` | `workflow.manage` | Edit workflow template. |
| GET | `/production/` | `production.view` | Production list. |
| GET | `/production/board` | `production.view` | (Phase 8) Kanban board — productions bucketed by current stage. |
| GET | `/production/from-order` | `production.manage` | "Create from order" form. |
| POST | `/production/from-order/<int:oid>` | `production.manage` | Create production → auto-generates `production_code` + stage rows + progress. |
| GET | `/production/<int:pid>` | `production.view` | Production detail (timeline/updates/media/QC). |
| POST | `/production/<int:pid>/stage/<int:sid>/advance` | `production.manage` | Advance a stage; recomputes overall progress. |
| POST | `/production/<int:pid>/updates` | `production.manage` | Post a progress update. |
| POST | `/production/<int:pid>/media` | `production.manage` | Upload photo/video with `INTERNAL`/`CUSTOMER` visibility. |
| GET | `/production/media/<int:mid>/file` | `production.view` (+ `production.media.internal.read` for **INTERNAL** rows, else 403) | Serve an uploaded media file with backend visibility gate. |
| POST | `/production/<int:pid>/qc` | `qc.manage` | Record QC pass / rerun fail / rework return-to-stage. |

## Inventory (`/inventory`)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/inventory` (or `/inventory/`) | `inventory.view` | Stock list with on-hand/reserved + low-stock badge (+ `?low=1` filter). |
| POST | `/inventory/adjust` | `inventory.manage` | Adjust on-hand (delta; cannot go below reserved). |
| POST | `/inventory/reserve` | `inventory.manage` | Reserve stock. |
| POST | `/inventory/release` | `inventory.manage` | Release reservation. |
| POST | `/inventory/issue` | `inventory.manage` | Issue OUT from on-hand. |
| POST | `/inventory/usage` | `inventory.manage` **or** `production.manage` | Record material usage against a production (→ OUT + usage row). |
| GET | `/inventory/movements` | `inventory.view` | Stock-movement ledger. |
| GET | `/inventory/usage-log` | `inventory.view` | Material usage log. |
| GET | `/inventory/productions` | `inventory.manage` **or** `production.manage` | Productions picker for usage recording. |

## Audit & non-HTTP notes

- Every consequential write (create/update/login/logout/payment/Q etc.) appends an
  `audit_logs` row via `app/db.py::audit` (`user_id, timestamp, action, entity,
  entity_id, old_value, new_value`). No plaintext credentials are ever logged.
- `/track` is read-only and intentionally writes **no** audit rows.
- There is **no** JSON API / REST layer — the app is a server-rendered Flask monolith;
  the table above is the full route surface.