# Findings — Sola Dashboard → Vercel (audit, 2026-09-23)

## Repository reality
- **GitHub `ejakejak/Sola-Dashboard` is EMPTY** (one 16-byte README, 1 commit). The real app is `D:/Sola` which is **not** a git repo.
- 47 URL routes registered. Flask 3.1.1, Python 3.11.

## Stack (verified from code)
- Framework: Flask 3.1.1 (app-factory + blueprints), NOT stateless.
- Runtime storage: **Google Sheets** (Phase-5 full cutover, `STORAGE=sheets` default; gspread → Sheets API, open_by_key). SQLite = legacy adapter only.
- Filesystem uploads: `app/production.py` writes to `app/static/uploads/` (`file.save`) and serves via `send_from_directory`. ~100 real PNGs present.
- In-memory: per-IP rate limiter (`IpLimiter`) + per-instance sheet caches.
- Boot: `run.py` re-runs seeds (auth/production/catalog) each start.
- Local editable settings: `instance/company_settings.json`.
- Invoice PDF via reportlab.
- Service-account JSON + `.env` correctly gitignored.

## Vercel compatibility verdict (grounded)
**NOT compatible as-is.** Vercel Python runtime = serverless, ephemeral filesystem, stateless. Blockers:
1. Uploads → local disk: fragments vanish after request. Core production feature. (spec §2/§9 "local filesystem persistence" + §15)
2. Long-running single Flask process (docs explicitly: "local-first, single-process... remote multi-user deployment out of scope by design").
3. Boot seeds / editable local settings don't map to serverless.

User decision 2026-09-23: **FORCE Vercel anyway** — accept trade-offs, adapt.

## Baseline gate result (spec §5/§15)
- App BOOTS: PASS (both `STORAGE=sheets` and `STORAGE=sqlite`; 47 routes).
- Test suite: **RED — PRE-EXISTING DRIFT** (not caused by this work). 128 tests: 75 errors+5 failures (default=sheets) OR 68 errors (default=sqlite). Cause: Phase-5 cutover flipped config default to `sheets` but old sqlite test modules (`test_phase2_storage`, etc.) assert `sqlite` default; sheets test modules (`test_phase5_sheetdb`) assert `sheets` default. NEITHER default satisfies both; each module must pin `STORAGE` explicitly. README's "87 tests OK" is stale.

## External blockers (EVA alone cannot resolve)
1. **Vercel auth** — no CLI, no token. Need Ejak to install + login (or push repo & link via GitHub).
2. **Uploads storage on Vercel** — need provider decision + token: Vercel Blob (same account) / Cloudinary / S3 / GCS.
3. **Push proprietary SOLA code to GitHub** — repo currently empty; needs Ejak confirmation (private?).

## Planned adaptation (provider-independent core)
- `vercel.json` + `api/index.py` (WSGI serverless entry; no boot seeds in serverless entry).
- Uploads → MediaStore abstraction (local impl for dev + cloud impl behind token).
- Fix test-drift: pin `STORAGE` per test module.
- Env-only config (no FS reads at runtime except static shipped assets).