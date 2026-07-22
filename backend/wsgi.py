"""Gunicorn entry point for production (see DEPLOY.md at the repo root):

    gunicorn --workers 1 --threads 8 --bind 127.0.0.1:5000 wsgi:app

One worker process on purpose: the background agent jobs live in an in-process
ThreadPoolExecutor and SQLite allows a single writer — threads scale the request
handling, extra processes would just add write contention.
"""
from app import app  # noqa: F401 — loads .env and registers all routes
from database import init_db

init_db()
