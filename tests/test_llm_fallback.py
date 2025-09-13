from types import SimpleNamespace

import pytest

import gentlebot.llm.router as llm_router
from gentlebot.infra.quotas import RateLimited


def _ok_resp():
    return SimpleNamespace(
        text="ok", usage_metadata=SimpleNamespace(candidates_token_count=0)
    )


def test_fallback_on_quota(monkeypatch):
    router = llm_router.LLMRouter()
    general_model = router.models["general"]

    calls: list[str] = []

    def fake_generate(self, model, messages, **kwargs):
        calls.append(model)
        return _ok_resp()

    monkeypatch.setattr(llm_router.GeminiClient, "generate", fake_generate)

    def fake_check(route, tokens):
        if route == "scheduled":
            raise RateLimited()
        return 0.0

    monkeypatch.setattr(router.quota, "check", fake_check)

    result = router.generate("scheduled", [{"content": "hi"}])
    assert result == "ok"
    assert calls == [general_model]


@pytest.mark.parametrize("status", [429, 500])
def test_fallback_on_error(monkeypatch, status):
    router = llm_router.LLMRouter()
    scheduled_model = router.models["scheduled"]
    general_model = router.models["general"]

    calls: list[str] = []

    def fake_generate(self, model, messages, **kwargs):
        calls.append(model)
        if model == scheduled_model:
            exc = Exception("boom")
            exc.response = SimpleNamespace(status_code=status)
            raise exc
        return _ok_resp()

    monkeypatch.setattr(llm_router.GeminiClient, "generate", fake_generate)
    monkeypatch.setattr(llm_router, "call_with_backoff", lambda fn, **kw: fn())

    result = router.generate("scheduled", [{"content": "hi"}])
    assert result == "ok"
    assert calls == [scheduled_model, general_model]
