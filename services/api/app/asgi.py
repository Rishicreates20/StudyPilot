"""The ASGI application as a module-level object, for platforms that import one (Vercel, ADR-052).

Everywhere else the app is created on demand (``uvicorn app.main:create_app --factory``), so that
importing ``app.main`` has no side effects. Importing this module creates the app, which validates
the settings from the environment and fails fast when they are wrong.
"""

from app.main import create_app

app = create_app()
