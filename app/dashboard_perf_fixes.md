# Performance Fix Plan — Sola Dashboard (Flask / SheetBacked)

Evidence collected from source read (dashboard.py lines 1-291, sheetdb.py, storage.py).

## Critical
1. compute_kpis: productions.read_all() 3×, orders 2×, invoices 2× → 7 full-table reads for 3 tabs (line 101-145).
2. render_dashboard: 6 compute_* called independently → production_orders read 4×, invoices 2×, orders 1×, etc. (line 260-272).
3. compute_recent_updates: builds full indexes (productions/users/stages read_all) just to show 8 items (line 206-241).

## High
4. invoices.sum_column() triggers separate read_all from open_invoices filter (line 130 / 114-116).

## Fixes selected (safe, minimal restructuring)
- A: compute_kpis local reuse (3 reads → 3 reads, loops once).
- B: compute_recent_updates lazy index (4 full reads → 1 updates + targeted).
- C: request-level g-cache shared across compute_* (largest cross-function win).

Implementation: edit dashboard.py only; preserve template + business logic; no schema change.
