"""Test fixtures for otterwiki-api.

Adapted from otterwiki's tests/conftest.py to provide the create_app
and test_client fixtures needed by the API tests.
"""

import os

import pytest
import otterwiki.gitstorage


@pytest.fixture
def create_app(tmpdir):
    tmpdir.mkdir("repo")
    _storage = otterwiki.gitstorage.GitStorage(
        path=str(tmpdir.join("repo")), initialize=True
    )
    settings_cfg = str(tmpdir.join("settings.cfg"))
    with open(settings_cfg, "w") as f:
        f.writelines(
            [
                "REPOSITORY = '{}'\n".format(str(_storage.path)),
                "SITE_NAME = 'TEST WIKI'\n",
                "DEBUG = True\n",
                "TESTING = True\n",
                "MAIL_SUPPRESS_SEND = True\n",
                "SECRET_KEY = 'Testing Testing Testing'\n",
            ]
        )
    os.environ["OTTERWIKI_SETTINGS"] = settings_cfg
    from otterwiki.server import app, db, mail, storage

    app._otterwiki_tempdir = storage.path
    app.storage = storage
    app.test_mail = mail
    app.config["TESTING"] = True
    app.config["DEBUG"] = True
    yield app


@pytest.fixture
def test_client(create_app):
    client = create_app.test_client()
    return client
