-- ============================================================
-- SOLA Konveksi & Production Management System — SQLite schema
-- Relational, FK-enabled. Audit-grounded (see docs/AUDIT_REPORT.md).
-- ============================================================
PRAGMA foreign_keys = ON;

-- ---------- Core reference (lookup) ----------
CREATE TABLE IF NOT EXISTS units (
  unit_id   INTEGER PRIMARY KEY,
  unit_code TEXT UNIQUE NOT NULL,        -- pcs, meter, pak, lusin, set, cm...
  unit_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sizes (
  size_id   INTEGER PRIMARY KEY,
  size_code TEXT UNIQUE NOT NULL,        -- S, M, L, XL, AllSize...
  sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS colors (
  color_id   INTEGER PRIMARY KEY,
  color_code TEXT UNIQUE NOT NULL,
  color_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_categories (
  category_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  category_name TEXT UNIQUE NOT NULL,    -- T-Shirt, Polo, Korsa, Hoodie, Vest, Jersey, Topi, Mug...
  description   TEXT
);

CREATE TABLE IF NOT EXISTS products (
  product_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  product_code TEXT UNIQUE NOT NULL,     -- PRD-001...
  product_name TEXT NOT NULL,
  category_id  INTEGER REFERENCES product_categories(category_id),
  unit_id      INTEGER REFERENCES units(unit_id),
  description  TEXT,
  status       TEXT NOT NULL DEFAULT 'active',   -- active|inactive
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS product_variants (
  variant_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id    INTEGER NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
  variant_name  TEXT NOT NULL,          -- e.g. Cotton Combed 24s, Kaos, Mug Sublim
  material_id   INTEGER REFERENCES materials(material_id),
  notes         TEXT,
  UNIQUE(product_id, variant_name)
);

-- ---------- Materials ----------
CREATE TABLE IF NOT EXISTS materials (
  material_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  material_code TEXT UNIQUE NOT NULL,   -- CC-30S, PQ-PE, DR-AM-KR, FL-CVC, BT-CT...
  material_name TEXT NOT NULL,
  category      TEXT,                   -- kaos, pique, drill, fleece, baby terry, mug...
  specification TEXT,
  unit_id       INTEGER REFERENCES units(unit_id),
  gramasi       TEXT,
  width         TEXT,
  supplier      TEXT,
  status        TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS material_colors (
  material_color_id INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id INTEGER NOT NULL REFERENCES materials(material_id) ON DELETE CASCADE,
  color_id    INTEGER NOT NULL REFERENCES colors(color_id) ON DELETE CASCADE,
  UNIQUE(material_id, color_id)
);

-- price is context (product-category) aware: Korsa vs Vest differ for same material
CREATE TABLE IF NOT EXISTS material_prices (
  material_price_id INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id INTEGER NOT NULL REFERENCES materials(material_id) ON DELETE CASCADE,
  category_id INTEGER REFERENCES product_categories(category_id),  -- NULL = default
  unit_id     INTEGER REFERENCES units(unit_id),
  unit_price  REAL NOT NULL,
  currency    TEXT NOT NULL DEFAULT 'IDR',
  valid_from  TEXT NOT NULL DEFAULT (date('now')),
  valid_until TEXT,
  UNIQUE(material_id, category_id, valid_from)
);

-- ---------- Processes & decorations ----------
CREATE TABLE IF NOT EXISTS processes (
  process_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  process_code TEXT UNIQUE NOT NULL,    -- CT, JT, SB-DTF, SB-RB, SB-PS, BR-KS, BR-KR...
  process_name TEXT NOT NULL,
  category     TEXT,
  unit_id      INTEGER REFERENCES units(unit_id),
  default_cost REAL,
  estimated_duration TEXT,
  status       TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS process_prices (
  process_price_id INTEGER PRIMARY KEY AUTOINCREMENT,
  process_id INTEGER NOT NULL REFERENCES processes(process_id) ON DELETE CASCADE,
  unit_id    INTEGER REFERENCES units(unit_id),
  unit_price REAL NOT NULL,
  currency   TEXT NOT NULL DEFAULT 'IDR',
  valid_from TEXT NOT NULL DEFAULT (date('now')),
  valid_until TEXT
);

-- decoration (DTF, Rubber, Plastisol, Bordir, Sublim, Polyflex, Print&P...) detached from product
CREATE TABLE IF NOT EXISTS decorations (
  decoration_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  decoration_code TEXT UNIQUE NOT NULL,
  decoration_name TEXT NOT NULL,
  category        TEXT,
  pricing_method  TEXT,                 -- per-piece, per-size, per-color...
  default_cost    REAL,
  status          TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS decoration_prices (
  decoration_price_id INTEGER PRIMARY KEY AUTOINCREMENT,
  decoration_id INTEGER NOT NULL REFERENCES decorations(decoration_id) ON DELETE CASCADE,
  unit_id       INTEGER REFERENCES units(unit_id),
  unit_price    REAL NOT NULL,
  currency      TEXT NOT NULL DEFAULT 'IDR',
  valid_from    TEXT NOT NULL DEFAULT (date('now')),
  valid_until   TEXT
);

-- cost map: cost component (material/process/decoration/vendor/overhead) -> amount, decomposable by product/variant
CREATE TABLE IF NOT EXISTS cost_components (
  cost_component_id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id       INTEGER REFERENCES products(product_id) ON DELETE CASCADE,
  variant_id       INTEGER REFERENCES product_variants(variant_id) ON DELETE CASCADE,
  component_type   TEXT NOT NULL,       -- material|process|decoration|vendor|overhead|commission
  ref_id           INTEGER,             -- material_id / process_id / decoration_id / vendor_id
  product_category_id INTEGER REFERENCES product_categories(category_id),
  unit_cost        REAL NOT NULL,
  currency         TEXT NOT NULL DEFAULT 'IDR',
  valid_from       TEXT NOT NULL DEFAULT (date('now')),
  valid_until      TEXT,
  notes            TEXT,
  UNIQUE(product_id, variant_id, component_type, ref_id, product_category_id, valid_from)
);

-- commission template (Fee column: 'Max N' cap, '% Keuntungan' percent-of-profit)
CREATE TABLE IF NOT EXISTS commission_templates (
  commission_template_id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_category_id INTEGER REFERENCES product_categories(category_id),
  commission_mode TEXT NOT NULL DEFAULT 'flat_cap',  -- flat_cap | percent_of_profit | none
  commission_cap  REAL,            -- e.g. 5000 / 2000 / 3000
  commission_pct  REAL,            -- for percent_of_profit
  status TEXT NOT NULL DEFAULT 'active'
);

-- ---------- Vendors (penjahit/makloon, printing, etc.) ----------
CREATE TABLE IF NOT EXISTS vendors (
  vendor_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_code  TEXT UNIQUE NOT NULL,
  vendor_name  TEXT NOT NULL,
  vendor_type  TEXT,                -- makhloon/penjahit | sablon | bahan | other
  phone        TEXT,
  address      TEXT,                -- maps URL or text
  location     TEXT,
  specialization TEXT,
  status       TEXT NOT NULL DEFAULT 'active',
  notes        TEXT
);

CREATE TABLE IF NOT EXISTS vendor_capabilities (
  vendor_capability_id INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_id INTEGER NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
  process_id INTEGER REFERENCES processes(process_id),
  capability TEXT,                  -- free-form e.g. "Kaos dan Polo", "Sablon Plastisol"
  price       REAL,
  lead_time   TEXT,
  capacity    TEXT,
  status      TEXT NOT NULL DEFAULT 'active',
  UNIQUE(vendor_id, process_id, capability)
);

-- ---------- Customers, Agents ----------
CREATE TABLE IF NOT EXISTS customers (
  customer_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_code TEXT UNIQUE NOT NULL,
  name          TEXT NOT NULL,
  company_name  TEXT,
  pic_name      TEXT,
  phone         TEXT,
  email         TEXT,
  address       TEXT,
  npwp          TEXT,
  customer_type TEXT,               -- retail | corporate | agent-led
  source        TEXT,
  notes         TEXT,
  status        TEXT NOT NULL DEFAULT 'active',
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agents (
  agent_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_code  TEXT UNIQUE NOT NULL,
  name        TEXT NOT NULL,
  phone       TEXT,
  campus      TEXT,
  faculty     TEXT,
  address     TEXT,
  status      TEXT NOT NULL DEFAULT 'active',
  commission_scheme TEXT,
  notes       TEXT
);

-- ---------- Quotation ----------
CREATE TABLE IF NOT EXISTS quotations (
  quotation_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  quotation_number TEXT UNIQUE NOT NULL,
  customer_id      INTEGER REFERENCES customers(customer_id),
  quotation_date   TEXT NOT NULL DEFAULT (date('now')),
  valid_until      TEXT,
  subtotal         REAL DEFAULT 0,
  discount         REAL DEFAULT 0,
  tax              REAL DEFAULT 0,
  total            REAL DEFAULT 0,
  notes            TEXT,
  status           TEXT NOT NULL DEFAULT 'draft',   -- draft|sent|approved|rejected|converted|cancelled
  created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quotation_items (
  quotation_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  quotation_id INTEGER NOT NULL REFERENCES quotations(quotation_id) ON DELETE CASCADE,
  product_id   INTEGER REFERENCES products(product_id),
  variant_id   INTEGER REFERENCES product_variants(variant_id),
  material_id  INTEGER REFERENCES materials(material_id),
  decoration_id INTEGER REFERENCES decorations(decoration_id),
  specification TEXT,
  quantity     REAL NOT NULL,
  unit_id      INTEGER REFERENCES units(unit_id),
  unit_price   REAL DEFAULT 0,
  subtotal     REAL DEFAULT 0
);

-- ---------- Order ----------
CREATE TABLE IF NOT EXISTS orders (
  order_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  order_number TEXT UNIQUE NOT NULL,          -- ORD-2026-0001
  customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
  quotation_id INTEGER REFERENCES quotations(quotation_id),
  order_date   TEXT NOT NULL DEFAULT (date('now')),
  deadline     TEXT,
  status       TEXT NOT NULL DEFAULT 'confirmed',
  priority     TEXT NOT NULL DEFAULT 'normal',  -- low|normal|high|urgent
  subtotal     REAL DEFAULT 0,
  discount     REAL DEFAULT 0,
  tax          REAL DEFAULT 0,
  grand_total  REAL DEFAULT 0,
  notes        TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
  order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id      INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  product_id    INTEGER REFERENCES products(product_id),
  variant_id    INTEGER REFERENCES product_variants(variant_id),
  material_id   INTEGER REFERENCES materials(material_id),
  color_id      INTEGER REFERENCES colors(color_id),
  decoration_id INTEGER REFERENCES decorations(decoration_id),
  decoration_position TEXT,
  decoration_size     TEXT,
  size_id       INTEGER REFERENCES sizes(size_id),
  quantity      REAL NOT NULL,
  unit_id       INTEGER REFERENCES units(unit_id),
  unit_price    REAL DEFAULT 0,
  subtotal      REAL DEFAULT 0,
  notes         TEXT
);

-- ---------- Invoice & Payment ----------
CREATE TABLE IF NOT EXISTS invoices (
  invoice_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_number TEXT UNIQUE NOT NULL,
  order_id       INTEGER NOT NULL REFERENCES orders(order_id),
  customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
  invoice_date   TEXT NOT NULL DEFAULT (date('now')),
  due_date       TEXT,
  subtotal       REAL DEFAULT 0,
  discount       REAL DEFAULT 0,
  tax            REAL DEFAULT 0,
  grand_total    REAL DEFAULT 0,
  amount_paid    REAL DEFAULT 0,
  outstanding    REAL DEFAULT 0,
  status         TEXT NOT NULL DEFAULT 'draft',  -- draft|issued|partially_paid|paid|overdue|cancelled
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoice_items (
  invoice_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
  order_item_id INTEGER REFERENCES order_items(order_item_id),
  description   TEXT,
  quantity      REAL NOT NULL,
  unit_id       INTEGER REFERENCES units(unit_id),
  unit_price    REAL DEFAULT 0,
  subtotal      REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
  payment_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id   INTEGER NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
  payment_date TEXT NOT NULL DEFAULT (date('now')),
  amount       REAL NOT NULL,
  method       TEXT,                -- transfer|cash|qris|other
  reference    TEXT,
  notes        TEXT,
  created_by   INTEGER REFERENCES users(user_id)
);

-- ---------- Production ----------
CREATE TABLE IF NOT EXISTS production_workflow_templates (
  workflow_template_id INTEGER PRIMARY KEY AUTOINCREMENT,
  template_name TEXT NOT NULL,
  product_category_id INTEGER REFERENCES product_categories(category_id),  -- NULL = catch-all default
  is_default    INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS production_workflow_template_steps (
  workflow_template_step_id INTEGER PRIMARY KEY AUTOINCREMENT,
  workflow_template_id INTEGER NOT NULL REFERENCES production_workflow_templates(workflow_template_id) ON DELETE CASCADE,
  sequence        INTEGER NOT NULL,
  stage_name      TEXT NOT NULL,     -- ORDER, MATERIAL PREPARATION, CUTTING, SEWING, PRINTING, FINISHING, QC, PACKING, COMPLETED
  is_completion   INTEGER NOT NULL DEFAULT 0,
  UNIQUE(workflow_template_id, sequence)
);

CREATE TABLE IF NOT EXISTS production_orders (
  production_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  production_code   TEXT UNIQUE NOT NULL,     -- PRD-260922-001 (customer-facing)
  order_id          INTEGER NOT NULL REFERENCES orders(order_id),
  order_item_id     INTEGER REFERENCES order_items(order_item_id),
  product_id        INTEGER REFERENCES products(product_id),
  variant_id        INTEGER REFERENCES product_variants(variant_id),
  quantity          REAL NOT NULL,
  deadline          TEXT,
  current_stage     TEXT,
  overall_progress  REAL DEFAULT 0,           -- 0..100
  status            TEXT NOT NULL DEFAULT 'in_progress',
  workflow_template_id INTEGER REFERENCES production_workflow_templates(workflow_template_id),
  notes             TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS production_stages (
  production_stage_id INTEGER PRIMARY KEY AUTOINCREMENT,
  production_id       INTEGER NOT NULL REFERENCES production_orders(production_id) ON DELETE CASCADE,
  stage_id            INTEGER,               -- reference to workflow step
  stage_name          TEXT NOT NULL,
  sequence            INTEGER NOT NULL,
  status              TEXT NOT NULL DEFAULT 'pending',  -- pending|in_progress|completed|blocked|cancelled
  assigned_user       INTEGER REFERENCES users(user_id),
  assigned_vendor     INTEGER REFERENCES vendors(vendor_id),
  start_at            TEXT,
  completed_at        TEXT,
  target_quantity     REAL,
  completed_quantity  REAL DEFAULT 0,
  rejected_quantity   REAL DEFAULT 0,
  notes               TEXT
);

CREATE TABLE IF NOT EXISTS production_updates (
  update_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  production_id   INTEGER NOT NULL REFERENCES production_orders(production_id) ON DELETE CASCADE,
  production_stage_id INTEGER REFERENCES production_stages(production_stage_id),
  user_id         INTEGER REFERENCES users(user_id),
  timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
  progress        REAL,               -- 0..100
  quantity_completed REAL,
  quantity_rejected REAL,
  notes           TEXT
);

CREATE TABLE IF NOT EXISTS production_media (
  media_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  update_id    INTEGER REFERENCES production_updates(update_id) ON DELETE CASCADE,
  production_id INTEGER NOT NULL REFERENCES production_orders(production_id) ON DELETE CASCADE,
  file_url     TEXT NOT NULL,
  file_type    TEXT,                  -- image|video
  visibility   TEXT NOT NULL DEFAULT 'INTERNAL',  -- INTERNAL | CUSTOMER
  uploaded_by  INTEGER REFERENCES users(user_id),
  uploaded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quality_checks (
  qc_id            INTEGER PRIMARY KEY AUTOINCREMENT,
  production_id    INTEGER NOT NULL REFERENCES production_orders(production_id),
  stage_id         INTEGER,
  inspector        INTEGER REFERENCES users(user_id),
  inspected_at     TEXT NOT NULL DEFAULT (datetime('now')),
  passed_quantity  REAL DEFAULT 0,
  rejected_quantity REAL DEFAULT 0,
  defect_type      TEXT,
  notes            TEXT,
  status           TEXT NOT NULL DEFAULT 'pending',  -- pending|passed|failed|rework
  evidence         TEXT
);

-- ---------- Inventory ----------
CREATE TABLE IF NOT EXISTS inventory (
  inventory_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id   INTEGER REFERENCES materials(material_id),
  unit_id       INTEGER REFERENCES units(unit_id),
  on_hand       REAL DEFAULT 0,
  reserved      REAL DEFAULT 0,
  available     REAL DEFAULT 0,
  location      TEXT,
  updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(material_id, unit_id, location)
);

CREATE TABLE IF NOT EXISTS stock_movements (
  stock_movement_id INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id   INTEGER REFERENCES materials(material_id),
  movement_type TEXT NOT NULL,        -- IN|OUT|ADJUSTMENT|RESERVED|RELEASED
  quantity      REAL NOT NULL,
  unit_id       INTEGER REFERENCES units(unit_id),
  reference_type TEXT,                -- order|order_item|adjustment|purchase
  reference_id  INTEGER,
  moved_by      INTEGER REFERENCES users(user_id),
  moved_at      TEXT NOT NULL DEFAULT (datetime('now')),
  notes         TEXT
);

CREATE TABLE IF NOT EXISTS material_usage (
  material_usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
  production_id INTEGER REFERENCES production_orders(production_id),
  material_id   INTEGER REFERENCES materials(material_id),
  quantity      REAL NOT NULL,
  unit_id       INTEGER REFERENCES units(unit_id),
  used_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------- Access control & audit ----------
CREATE TABLE IF NOT EXISTS roles (
  role_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  role_code TEXT UNIQUE NOT NULL,     -- ADMIN|SALES|PRODUCTION|WAREHOUSE|QC|FINANCE|MANAGEMENT|CUSTOMER
  role_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS permissions (
  permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
  permission_code TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
  role_permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
  role_id       INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
  permission_id INTEGER NOT NULL REFERENCES permissions(permission_id) ON DELETE CASCADE,
  UNIQUE(role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS users (
  user_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  username   TEXT UNIQUE NOT NULL,
  full_name  TEXT,
  password_hash TEXT,               -- placeholder; auth boundary pluggable
  role_id    INTEGER REFERENCES roles(role_id),
  phone      TEXT,
  email      TEXT,
  status     TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS audit_logs (
  audit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER REFERENCES users(user_id),
  timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
  action      TEXT NOT NULL,
  entity      TEXT NOT NULL,
  entity_id   TEXT,
  old_value   TEXT,
  new_value   TEXT
);

-- index for performance / integrity
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_prod_stages_prod ON production_stages(production_id);
CREATE INDEX IF NOT EXISTS idx_prod_updates_prod ON production_updates(production_id);
CREATE INDEX IF NOT EXISTS idx_media_visibility ON production_media(production_id, visibility);
CREATE INDEX IF NOT EXISTS idx_invoice_order ON invoices(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_quotation_customer ON quotations(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_stock_material ON stock_movements(material_id);
