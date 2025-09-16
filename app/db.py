"""Database engine and session utilities for the scheduler ledger."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


DEFAULT_SQLITE_URL = "sqlite+pysqlite:///:memory:"


def _register_sqlite_functions(engine: Engine) -> None:
    """Ensure SQLite provides Postgres-compatible helper functions."""

    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @event.listens_for(engine, "connect")
    def _connect(dbapi_connection, _record) -> None:  # type: ignore[override]
        dbapi_connection.create_function("now", 0, _now)


def create_engine_from_env(echo: bool = False, url: Optional[str] = None) -> Engine:
    """Create the SQLAlchemy engine using ``DATABASE_URL`` or an explicit URL."""

    database_url = url or os.environ.get("DATABASE_URL") or DEFAULT_SQLITE_URL
    connect_args = {}
    if database_url.startswith("sqlite"):  # pragma: no branch - deterministic
        connect_args["check_same_thread"] = False
    engine = create_engine(database_url, future=True, echo=echo, pool_pre_ping=True, connect_args=connect_args)
    if engine.dialect.name == "sqlite":
        _register_sqlite_functions(engine)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a configured session factory for the provided engine."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_engine() -> Engine:
    """Convenience accessor used by scripts to lazily create an engine."""

    if not hasattr(get_engine, "_engine"):
        setattr(get_engine, "_engine", create_engine_from_env())
    return getattr(get_engine, "_engine")


SessionLocal = create_session_factory(get_engine())


@contextmanager
def session_scope(session_factory: sessionmaker[Session] = SessionLocal) -> Iterator[Session]:
    """Provide a transactional scope for DB operations."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
