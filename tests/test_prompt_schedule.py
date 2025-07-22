from datetime import datetime, timedelta
from gentlebot.cogs import prompt_cog


def test_next_run_time_before_schedule():
    tz = prompt_cog.LOCAL_TZ
    now = datetime(2023, 1, 1, 10, 0, tzinfo=tz)
    next_run = prompt_cog.PromptCog(None)._next_run_time(now)
    assert next_run.date() == now.date()
    assert next_run.hour == prompt_cog.SCHEDULE_HOUR
    assert next_run.minute == prompt_cog.SCHEDULE_MINUTE


def test_next_run_time_after_schedule():
    tz = prompt_cog.LOCAL_TZ
    now = datetime(2023, 1, 1, 13, 0, tzinfo=tz)
    next_run = prompt_cog.PromptCog(None)._next_run_time(now)
    assert next_run.date() == now.date() + timedelta(days=1)
    assert next_run.hour == prompt_cog.SCHEDULE_HOUR
    assert next_run.minute == prompt_cog.SCHEDULE_MINUTE
