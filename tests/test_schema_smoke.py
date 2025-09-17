from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_engine_from_env
from app.models import Base
from app.models import scheduled_task, task_execution, task_occurrence  # noqa: F401


def test_schema_migration_applies():
    engine = create_engine_from_env(url="sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert {"scheduled_task", "task_occurrence", "task_execution"}.issubset(tables)

    occ_columns = {col["name"] for col in inspector.get_columns("task_occurrence")}
    assert {"occurrence_key", "scheduled_for", "state"}.issubset(occ_columns)

    uniques = inspector.get_unique_constraints("task_occurrence")
    assert any({"task_id", "occurrence_key"}.issubset(u["column_names"]) for u in uniques)

    indexes = inspector.get_indexes("task_occurrence")
    assert any(idx["name"] == "task_occurrence_task_time_idx" for idx in indexes)

    ddl = Path("migrations/001_scheduler_ledger.sql").read_text()
    assert "CREATE TABLE scheduled_task" in ddl
    assert "CREATE TABLE task_occurrence" in ddl
    assert "CREATE TABLE task_execution" in ddl
