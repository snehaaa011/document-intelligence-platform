"""
tests/conftest.py

Shared pytest fixtures. Uses an in-memory SQLite database for tests so no
external database is required (case study section 37: "Do not require a
paid API just to run unit tests").
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_PROVIDER", "rule_based")

from app.core.database import Base
from app.models import document  # noqa: F401


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def api_client(db_session, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import get_db

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()