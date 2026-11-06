"""Installation smoke checks; no production or synthetic business data."""
from importlib.metadata import version

import clavel
import fastapi
import psycopg


def test_installed_project_and_runtime_dependencies():
    """A clean installation exposes the project and required runtime libraries."""
    assert version("clavel")
    assert clavel.__doc__
    assert callable(fastapi.FastAPI)
    assert callable(psycopg.connect)
