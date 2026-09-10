import socket

import pytest

from atlas import db


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """Tests must not use real credentials, databases or external network connections."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "atlas.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setenv("ATLAS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("ATLAS_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    def blocked(*args, **kwargs):
        raise AssertionError("External network access is forbidden in offline tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    yield
    if db._engine is not None:
        db._engine.dispose()
