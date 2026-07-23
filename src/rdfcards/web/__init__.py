"""Flask-based local interface for deck selection and browser study."""

from rdfcards.web.app import create_flask_app
from rdfcards.web.server import create_web_server, run_server

__all__ = [
    "create_flask_app",
    "create_web_server",
    "run_server",
]
