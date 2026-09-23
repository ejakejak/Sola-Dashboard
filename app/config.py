"""Application configuration — loaded from environment + project .env (no third-party dotenv needed)."""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # D:/Sola
INSTANCE_DIR = BASE_DIR / "instance"

# Editable company / invoice settings (owner-provided block, 2026-09-22).
# Stored in instance/company_settings.json so they can change WITHOUT code edit.
# If that file is absent/malformed we fall back to these defaults.
DEFAULT_COMPANY = {
    "company_name": "Sola Konveksi Yogyakarta",
    "brand_logo": "app/static/assets/sola-logo-1.png",
    "phone": "62 823-7127-5988",
    "address": "Jl. Magelang No.KM 7, Mlati Beningan, Sendangadi, Mlati, Sleman Regency,"
               " D.I. Yogyakarta 55285, Indonesia",
    "maps_url": "https://maps.app.goo.gl/xHd1obgDP7uY97y88",
    "payment_label": "KETERANGAN PEMBAYARAN",
    "payment_note": "Pembayaran dilakukan secara transfer ke rekening: BCA 4452337111 a.n. Irhami Al Adaby",
}


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments, values may be quoted."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        os.environ.setdefault(key, val)


def _load_company_settings() -> dict:
    settings_file = INSTANCE_DIR / "company_settings.json"
    if settings_file.exists():
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = dict(DEFAULT_COMPANY)
                merged.update({k: v for k, v in data.items() if v is not None})
                return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_COMPANY)


class Config:
    def __init__(self):
        _load_dotenv(BASE_DIR / ".env")
        # Secret key for Werkzeug-signed session cookies. MUST come from the
        # environment (.env) — fail-closed rather than ship a hard-coded default
        # (Phase 9 hardening). Copy .env.example → .env and set a real value.
        self.SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
        if not self.SECRET_KEY:
            raise RuntimeError(
                "FLASK_SECRET_KEY is not set. Copy .env.example to .env and set "
                "FLASK_SECRET_KEY to a long random value before starting the app."
            )
        db_url = os.environ.get("DATABASE_URL", "sqlite:///instance/sola.db")
        if db_url.startswith("sqlite:///"):
            path = db_url[len("sqlite:///"):]
            if not os.path.isabs(path):
                path = str(BASE_DIR / path)
            self.DATABASE_PATH = path
        else:
            # allow an absolute filesystem path too
            self.DATABASE_PATH = db_url
        self.COMPANY = _load_company_settings()
        self.INVOICE = {
            "footer_note": "Terima kasih atas kepercayaan Anda.",
        }
        # Phase 7 public /track rate limiting (per-IP, in-memory sliding window; editable).
        self.RATE_LIMIT_WINDOW_SECS = int(os.environ.get("RATE_LIMIT_WINDOW_SECS", "3600"))
        self.RATE_LIMIT_MAX_PER_WINDOW = int(os.environ.get("RATE_LIMIT_MAX_PER_WINDOW", "20"))
        self.RATE_LIMIT_FAILED_THRESHOLD = int(os.environ.get("RATE_LIMIT_FAILED_THRESHOLD", "5"))
        self.RATE_LIMIT_COOLDOWN_SECS = int(os.environ.get("RATE_LIMIT_COOLDOWN_SECS", "90"))
        # Phase 5 — sheet-only cutover. The live Google Sheet is the single
        # store; blueprints route through the sheet engine. Default to "sheets"
        # so the app works with no STORAGE env. (SqliteStorage remains importable
        # as a legacy adapter but is no longer the app's runtime path.)
        self.STORAGE = (os.environ.get("STORAGE", "sheets") or "sheets").strip().lower()
        # Optional Google Sheets backend config (forwarded to SheetsStorage).
        # Absent by default; sheets path is a skeleton in Phase 1.
        self.SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
        self.GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")