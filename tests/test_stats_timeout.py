import types

import pytest
from gentlebot.cogs.bigdumper_watcher_cog import BigDumperWatcherCog
from gentlebot.cogs.sports_cog import STATS_TIMEOUT


class DummyResp:
    def __init__(self, data=None):
        self._data = data or {"stats": [{"splits": [{"stat": {"homeRuns": 7}}]}]}

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_fetch_hr_uses_timeout(monkeypatch):
    cog = BigDumperWatcherCog(bot=None)
    called = {}

    def fake_get(url, params=None, timeout=None):
        called['timeout'] = timeout
        return DummyResp()

    monkeypatch.setattr(cog.session, 'get', fake_get)
    hr = cog._fetch_hr()
    assert hr == 7
    assert called['timeout'] == STATS_TIMEOUT
