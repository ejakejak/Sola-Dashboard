# Task Plan — Deploy Sola Dashboard to Vercel (2026-09-23)

**Project:** Sola Dashboard (`D:/Sola`, Flask 3.1.1)
**Repo target:** github.com/ejakejak/Sola-Dashboard (currently EMPTY)
**Chosen path:** FORCE Vercel (user decision 2026-09-23) — accept serverless trade-offs, adapt code.
**Status:** IN PROGRESS

## Scope decisions (user-approved)
- Target = Vercel only. No Docker/Nginx/PM2 production.
- Uploads to local disk will NOT persist on Vercel → adapt (external storage).
- Boot seeds / editable local settings reworked for serverless.
- Business logic / UI otherwise unchanged.

## Steps
1. [DONE] Audit repo, report stack & Vercel incompatibilities (see findings.md).
2. [IN PROGRESS] LOCAL BASELINE GATE (§5/§15): venv (3.11) + deps + run 87 tests + app boots. No changes until PASS.
3. GIT: init D:/Sola, branch `deployment/vercel`, commit baseline (no secrets).
4. Code adaptation: Vercel WSGI entry (`api/index.py` + `vercel.json`), remove boot-seeds from serverless entry, uploads → external storage, env-only config.
5. Build/test after adaptation (Vercel local build + tests).
6. VERCEL AUTH — BLOCKER: no CLI, no token. Provide Ejak exact auth steps.
7. Deploy preview → test → production.
8. DEPLOYMENT.md + final report.

## External deps (EVA alone cannot do)
- Vercel CLI auth / token (Ejak).
- Storage provider for uploads (Vercel Blob token / S3 / Cloudinary) — Ejak account/decision.
- Approval to push real business system to GitHub (public?).

## Blockers
- None yet.