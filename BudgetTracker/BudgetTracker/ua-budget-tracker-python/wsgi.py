"""WSGI entry point: gunicorn wsgi:app OR waitress-serve --call tracker:create_app."""

from tracker import create_app

app = create_app()
