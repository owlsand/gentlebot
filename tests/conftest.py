from __future__ import annotations

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker

from app.db import create_engine_from_env
from app.models import Base
from app.models import scheduled_task, task_occurrence, task_execution  # noqa: F401


@pytest.fixture()
def engine():
    engine = create_engine_from_env(url="sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)
