"""
core/database.py

SQLAlchemy engine/session setup. Works with SQLite (local dev, default)
or PostgreSQL (production, via DATABASE_URL) with zero code changes -- see
case study section 23/24.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    # Needed for SQLite when accessed from multiple FastAPI worker threads.
    _connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def init_db() -> None:
    """Create tables if they do not already exist. For a real production
    rollout this would be replaced by Alembic migrations (see README
    'Production Improvements')."""
    from app.models import document  # noqa: F401  (ensures model is registered)

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency yielding a scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
