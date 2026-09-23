"""Vercel entry point — deploys the SOLA Flask app as a Vercel Function.

Vercel auto-detects Flask from requirements.txt and loads the WSGI ``app``
instance from a recognized entrypoint (root-level ``wsgi.py`` qualifies).

Serverless notes:
- ``create_app()`` performs NO seeding and NO filesystem writes; seeding only
  runs in the local ``run.py`` ``main()`` and via ``scripts/``. This keeps the
  serverless request path stateless.
- Requires the ``FLASK_SECRET_KEY`` env var to be set on the Vercel project
  (the app fails closed without it) plus the Google-sheets vars.
"""
from app import create_app

app = create_app()