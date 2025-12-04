from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.scheduler.cron import compute_due_times


def test_cron_handles_dst_forward_gap():
    start = datetime(2024, 3, 9, 8, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=3)
    due_times = compute_due_times(
        "CRON",
        "0 1 * * *",
        "America/Los_Angeles",
        start,
        end,
    )
    expected = [
        datetime(2024, 3, 9, 9, 0, tzinfo=timezone.utc),
        datetime(2024, 3, 10, 9, 0, tzinfo=timezone.utc),
        datetime(2024, 3, 11, 8, 0, tzinfo=timezone.utc),
    ]
    assert due_times[:3] == expected
    assert all(dt.tzinfo is not None for dt in due_times)
    assert len(set(due_times)) == len(due_times)
