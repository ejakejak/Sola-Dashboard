"""SOLA dashboard — simplified Invoice-only app."""
import os
from app import create_app
from app.config import Config
from seed.seed_auth import ensure_seeded

app = create_app()

def main():
    cfg = Config()
    ensure_seeded(cfg.DATABASE_PATH, verbose=True)
    host = os.environ.get("SOLA_HOST", "127.0.0.1")
    port = int(os.environ.get("SOLA_PORT", "5000"))
    app.run(host=host, port=port, debug=False)

if __name__ == "__main__":
    main()
