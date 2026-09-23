# SOLA — User Roles & Permissions

Source of truth: the role/permission matrix defined in `seed/seed_auth.py`
(`ROLE_PERMISSION_MATRIX`) and enforced in the backend by
`app/auth.py::require_permission` on every protected route. The matrix below is
the **effective** configuration that seeds into `role_permissions`.

There are **8 roles**. `CUSTOMER` has no dashboard login — it exists only for the
public `/track` page. Every permission is checked server-side; hiding a button in
the UI is only a surface expression of the same gate.

## Permission codes

| Code | Grants |
|---|---|
| `masterdata.view` | View any master-data list (materials, products, processes, decorations, vendors, agents, customers) |
| `<res>.create` / `<res>.update` | Create / edit that master resource (`material`, `product`, `process`, `decoration`, `vendor`, `agent`, `customer`) |
| `quotation.view` / `.create` / `.update` / `.convert` | View / create / change status / convert-quote→order |
| `order.view` / `order.create` | View / create orders |
| `invoice.view` / `.create` / `.update` / `.payment` | View / generate / change status / record payment & outstanding |
| `production.view` | List / detail / board of productions |
| `production.manage` | Create production from order, advance stages, post updates, upload media |
| `production.update` | Edit a production record |
| `production.media.internal.read` | See **INTERNAL** media (list + file serve); CUSTOMER media visible to all `production.view` holders |
| `qc.manage` | Record QC pass / fail / rework |
| `workflow.manage` | CRUD workflow templates |
| `inventory.view` | View inventory, movements, usage log |
| `inventory.manage` | Adjust stock, reserve / release / issue (OUT), record material usage |

## Effective role matrix

| Role | View master | Create/edit master | Commercial | Production | Media INTERNAL | QC | Workflow | Inventory view | Inventory manage |
|---|---|---|---|---|---|---|---|---|---|
| **ADMIN** | ✓ | ✓ all | ✓ all | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **SALES** | ✓ | customers, agents, products | quotations (all), orders (create), invoice **view only** | view only | — | — | — | — | — |
| **PRODUCTION** | ✓ | — | — | view + manage + update | ✓ | — | ✓ | ✓ | — (may record usage) |
| **WAREHOUSE** | ✓ | materials, processes | — | view only | — | — | — | ✓ | ✓ |
| **QC** | ✓ | — | — | view only | — | ✓ | — | ✓ | — |
| **FINANCE** | ✓ | — | commercial **view only** + invoice create/update/payment | view only | — | — | — | ✓ | — |
| **MANAGEMENT** | ✓ | — | commercial **view only** | view only | — | — | — | ✓ | — |
| **CUSTOMER** | — | — | — | `/track` only | — | — | — | — | — |

## Notes & boundary rules

- **SALES** has **no** `inventory.view` — the inventory navigation is absent for Sales
  (per design spec §2.2).
- **PRODUCTION** can record **material usage** against its own productions (the
  `/inventory/usage` route accepts `inventory.manage` **or** `production.manage`),
  but is **not** granted `inventory.manage` — no free-form adjust/reserve/issue.
- **INTERNAL** media is only listed/served to roles with `production.media.internal.read`
  (gate applied in both the media list SQL and the file-serving route
  `GET /production/media/<id>/file`); CUSTOMER media is visible to any
  `production.view` holder.
- **CUSTOMER** visibility on `/track` is a **separate, public** mechanism — it never
  renders costs, margins, notes, or INTERNAL media; see `docs/API.md`.
- `MANAGEMENT` / `FINANCE` / `QC` / `WAREHOUSE` are **read-only** on commercial data
  except for the explicit create/update/payment permissions in the matrix above.

## Default seed users

| username | role |
|---|---|
| `admin` | ADMIN |
| `sales` | SALES |
| `production` | PRODUCTION |
| `warehouse` | WAREHOUSE |
| `qc` | QC |
| `finance` | FINANCE |
| `management` | MANAGEMENT |
| `customer` | CUSTOMER (no login — `/track` only) |

All seed users share the demo password `sola123` **except** after you run
`scripts/rotate_admin_password.py`, which changes `admin` only. Rotate the admin
password before any real deployment (see `README.md`).