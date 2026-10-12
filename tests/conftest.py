import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from masterpayroll import create_app  # noqa: E402


@pytest.fixture()
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite://", "ADMIN_PASSWORD": "prof123",
                      "TESTING": True, "TESTING_NO_CSRF": True})
    yield app


@pytest.fixture()
def docente(app):
    c = app.test_client()
    r = c.post("/login", data={"username": "docente", "password": "prof123"})
    assert r.status_code == 302
    return c
