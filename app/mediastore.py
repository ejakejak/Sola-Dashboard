"""Pluggable media (upload) storage for SOLA.

The app writes production media to local disk in development. Vercel's
serverless filesystem is read-only (except /tmp) and ephemeral, so writing to
``app/static/uploads`` would raise on that host. This module adapts media I/O:

- ``LocalMediaStore``  — current behavior (write + send from a directory).
- ``get_media_store()`` — selects the backend from ``MEDIA_STORAGE`` env
  (default ``local``). A future cloud backend (Vercel Blob / S3) plugs in here.
- The call sites wrap saves/sends in ``try/except OSError`` so an unwritable
  filesystem yields a clear user message instead of an HTTP 500.

Business logic and the stored ``file_url`` convention are unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import abort, send_from_directory

BASE_DIR = Path(__file__).resolve().parent.parent


class MediaStore:
    """Abstract media backend: save an upload + serve a stored file."""

    name = "abstract"

    def save(self, upload, stored_name: str) -> None:
        raise NotImplementedError

    def send(self, stored_name: str):
        raise NotImplementedError


class LocalMediaStore(MediaStore):
    """Write/serve media from a directory (the original local behaviour)."""

    name = "local"

    def __init__(self, base_dir: Path):
        self._base = Path(base_dir)

    def _dir(self) -> Path:
        os.makedirs(self._base, exist_ok=True)
        return self._base

    def save(self, upload, stored_name: str) -> None:
        self._dir()
        upload.save(self._base / stored_name)  # may raise OSError (read-only FS)

    def send(self, stored_name: str):
        self._dir()
        return send_from_directory(self._base, stored_name)


def get_media_store() -> MediaStore:
    """Return the configured media backend.

    ``MEDIA_STORAGE`` selects it; default ``local`` keeps dev behaviour
    identical. A non-local value is not yet wired — fail fast with a clear
    message so a serverless deployment surfaces the limitation instead of
    silently losing uploads.
    """
    backend = (os.environ.get("MEDIA_STORAGE") or "local").strip().lower()
    if backend == "local":
        base = os.environ.get(
            "MEDIA_UPLOAD_DIR") or str(BASE_DIR / "app" / "static" / "uploads")
        return LocalMediaStore(base)
    raise RuntimeError(
        f"MEDIA_STORAGE={backend!r} is not configured on this host. Uploads "
        f"are unavailable until a media backend (e.g. Vercel Blob / S3) is "
        f"wired in app/mediastore.py.")