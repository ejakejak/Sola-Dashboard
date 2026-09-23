# SOLA Dashboard — Vercel Deployment

Migrated from local single-PC (see `docs/DEPLOYMENT.md` for the original) to a
Vercel serverless deployment. **Stack:** Flask 3.1.1 (Python) · Google Sheets
storage (`STORAGE=sheets`) · Vercel Function (Fluid compute).

> Serverless trade-offs (accepted 2026-09-23): the filesystem is read-only and
> ephemeral, so **production media uploads do not persist on Vercel unless a
> cloud media backend is configured** (see "Media uploads" below). All other
> features work: auth, master data, commercial loop, production (non-media),
> inventory, dashboard, `/track`.

## Stack
- Framework: **Flask 3.1.1** (app factory + blueprints)
- Python: 3.11 (local dev) / 3.12+ (Vercel runtime)
- Data store: **Google Sheets** (`STORAGE=sheets`, gspread → Sheets API)
- Entry point: **`wsgi.py`** (Vercel auto-detects the WSGI `app`)
- Build: none (Vercel Python has zero-config Flask detection)
- Runtime deps: `requirements.txt` (pinned)

## How Vercel finds the app
Vercel detects Flask from `requirements.txt` and loads the WSGI `app` instance
from root-level `wsgi.py`. `create_app()` performs **no seeding** and no
filesystem writes, so the serverless request path is stateless. (Seeding only
runs in the local `run.py` / `scripts/`.)

## Environment variables
Set these on the Vercel project (Production, Preview, Development). None are
public; none should ever be committed.

| Variable | Required | Notes |
|---|---|---|
| `FLASK_SECRET_KEY` | **Yes** | Long random value. App fails closed without it. `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SPREADSHEET_ID` | Yes (sheets store) | `1z2cV5CCrc99rve4ObUdouf6Nw_8Qw8MQMr7LExYHNwA` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes (sheets store) | Paste the service-account **JSON** as the value (Vercel has no file path). |
| `STORAGE` | No | `sheets` (default) or `sqlite` (legacy/dev). |
| `MEDIA_STORAGE` | No | `local` (dev). On Vercel, leave unset/`local` → uploads are skipped with a clear message unless a cloud backend is wired (see below). |
| `MEDIA_UPLOAD_DIR` | No | Local only. |

`DATABASE_URL` / `SOLA_HOST` / `SOLA_PORT` / `RATE_LIMIT_*` are optional local
tuning and can be left at defaults on Vercel.

## Local production test (gate before deploy)
```bash
cd D:\Sola
.venv\Scripts\python.exe -m venv .venv      # first time
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -c "import wsgi; print(wsgi.app)"   # entry loads
```
Gate criteria: `wsgi` imports (app boot) with **no error**; 47 routes.

## Deploy
1. Push `deployment/vercel` → `github.com/ejakejak/Sola-Dashboard`.
2. In Vercel → **Add New Project** → import the GitHub repo.
3. Vercel auto-detects Flask; no build command / output dir needed.
   (Add a `vercel.json` with `functions.<wsgi.py>.excludeFiles` only if the
   bundle balloons — see Troubleshooting.)
4. Add the env vars above (Production + Preview).
5. **Deploy Preview** → test → promote to **Production**.

### Via CLI (alternative)
```bash
vercel login            # one-time, browser auth (EVA cannot do this for you)
vercel pull --environment=production
vercel deploy --prod
```

## Media uploads (serverless limitation)
Vercel's filesystem is read-only except `/tmp`. The app writes production
media to disk locally; on Vercel an upload is **skipped with a clear flash
message** unless a cloud backend is configured in `app/mediastore.py`
(`MediaStore` + `get_media_store()`). To enable persistent uploads, wire a
backend (Vercel Blob / S3-compatible) and set `MEDIA_STORAGE` accordingly.

## Troubleshooting
| Symptom | Cause / Fix |
|---|---|
| `RuntimeError: FLASK_SECRET_KEY is not set` | Env var missing on the Vercel project — add it. |
| Upload says "storage is not writable" | Expected on Vercel until a cloud media backend is wired. |
| Bundle too large / build slow | Add `vercel.json` `functions."wsgi.py".excludeFiles` for `tests/`, `dist/`, `_shots/`, `data/`, `.planning/`. |
| Sheets 429 quota | In-memory cache TTL tuned in `app/storage.py` (`_READ_TTL=10`); sheet read limit is 60/min/user — multiple concurrent instances share the quota. |