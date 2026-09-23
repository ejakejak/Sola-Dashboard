# PHASE 7 DEV BRIEF — SOLA Public Customer Tracking `/track` [for @REX]

You are Developer (REX) under EVA. Build Phase 7 of the SOLA dashboard in D:/Sola — the **public** customer production-tracking page — ON the verified app (Phases 0-6 done; 63 tests green). Reuse generic `get_db()`, existing `production_orders`/`production_stages`/`production_updates`/`production_media` and `products`/`product_variants`/`orders`. Additive; do not redo.

## Read first
- `docs/DESIGN_SPEC.md` — screen 10 (Public tracking `/track`, mobile-first), §1.1 status tokens, and the customer-security constraints in §3.4/4.7.
- `db/schema.sql` — integrity contract (production tables already exist; reuse, no DDL unless documented-additive).
- `docs/DEV_BRIEF.md` (non-negotiables), `docs/AUDIT_REPORT.md`, `docs/DATA_DICTIONARY.md`.
- Full product spec §19 (Customer Production Tracking) + §20 (Security): `C:/Users/muham/AppData/Local/hermes/cache/documents/doc_dfd0d1a07b14_PROMPT_AI_AGENT_DASHBOARD_KONVEKSI.txt`.

## Authorization/run notes
- You're a subagent pinned to `deepseek/deepseek-v4-flash-0731` (cheap — intended; do NOT switch providers).
- Interpreter: `C:/Users/muham/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe`; app: `cd /d/Sola && PYTHONPATH=. <venv-python> run.py` → port 5000 (else 5001). Planning-with-files SOP.

## Scope — implement/test phase-by-phase
1. **Public `/track` GET** (NO login required): a clean, mobile-first form where a customer enters a **Production Code** (e.g. `PRD-260922-001`). This blueprint must NOT be behind `require_permission`.
2. On lookup, show ONLY this production's **customer-visible** data (spec §19): product, quantity, order date, estimated completion (deadline), current stage, overall progress, a **timeline** of stages (status per stage), the **latest customer-visible update**, **customer-visible media only** (`production_media.visibility == 'CUSTOMER'` — NEVER INTERNAL), and important notes. **NEVER render**: HPP/cost, margin, vendor price, internal notes, internal media, other customers' data, payment/invoice data, or DB row ids.
3. **Security / anti-enumeration (spec §20)**: do NOT expose DB primary keys to the customer. Raw/lookup the production strictly by its `production_code` (unique). Generic "Production not found" message for any miss (do NOT reveal whether a code exists vs is wrong). Add **rate limiting**: default sliding-window 20 lookups / IP / hour, and after 5 consecutive failed lookups impose a 90s cooldown for that IP — keep constants in `app/config.py` (editable). If you can't ship a full limiter, at minimum implement a simple in-memory sliding-window IP limiter (module-level dict is fine for a single-process local app) AND reject the 6th rapid wrong guess with a generic message; label it plainly.
4. **Pages**: `/track` form + `/track/result` (or same-page result). Mobile-friendly layout; keep it minimal and clean, using the SOLA brand accent and neutral card style from DESIGN_SPEC (public page may omit the admin sidebar entirely).
5. **Tests** `tests/test_app_phase7.py`: (a) anonymous GET `/track` returns 200 (no login); (b) valid code renders product/qty/timeline + CUSTOMER media, and **counts zero INTERNAL items in the HTML** (grep the rendered HTML for an INTERNAL-only marker/media you intentionally seed); (c) wrong/garbage code → generic not-found (no existence oracle); (d) rate-limit: rapid repeated wrong codes eventually blocked with generic message; (e) the page does not contain prohibited substrings (e.g. 'HPP', 'margin', 'vendor_price', 'internal') in the customer payload. Run the FULL suite (all phases) to confirm no regression.
6. **Nav**: do NOT add `/track` to the admin sidebar (it's public); you may link it from the login page or leave it discoverable by URL.

## Rules
- Customer never sees INTERNAL media or internal data — enforce in the query/rendering layer AND prove via test (e) and (b).
- Audit: tracking itself is read-only public; do not write audit rows for simple lookups (avoid noise), but rate-limit blocks can be logged to server logs only.
- Never invent business data; use real migrated production (`PRD-260922-001` exists) and associate a CUSTOMER-visibility media row in your test setup.
- Additive schema allowed only if documented (prefer reuse).

## Report (English): files+routes+tests; verified behaviors (public no-login 200; valid code shows only customer-visible data incl. only CUSTOMER media; wrong code generic; rate-limit engaged; HTML free of prohibited sticks), permission note (none — public), any schema change + why, blockers (exact error). Distinguish implemented vs boundary-prepared. Never fabricate — run the real code; on a hard blocker stop and report exactly.