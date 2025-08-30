"""Ensure LLMRouter sends the Gentlebot persona as system instruction."""
from types import SimpleNamespace

import gentlebot.llm.router as llm_router


def test_router_includes_system_instruction(monkeypatch):
    captured: dict[str, str | None] = {}

    def fake_generate(
        self,
        model: str,
        messages,
        temperature: float = 0.6,
        json_mode: bool = False,
        thinking_budget: int = 0,
        system_instruction: str | None = None,
    ):
        captured["system_instruction"] = system_instruction
        return SimpleNamespace(text="ok", usage_metadata=SimpleNamespace(candidates_token_count=0))

    monkeypatch.setattr(llm_router.GeminiClient, "generate", fake_generate)

    router = llm_router.LLMRouter()
    router.generate("general", [{"content": "hi"}])

    assert captured["system_instruction"].startswith(
        "You are Gentlebot, a Discord copilot/robot for the Gentlefolk community."
    )


def test_quota_counts_system_instruction(monkeypatch):
    captured: dict[str, int] = {}

    def fake_generate(
        self,
        model: str,
        messages,
        temperature: float = 0.6,
        json_mode: bool = False,
        thinking_budget: int = 0,
        system_instruction: str | None = None,
    ):
        return SimpleNamespace(
            text="ok", usage_metadata=SimpleNamespace(candidates_token_count=0)
        )

    def fake_check(route: str, tokens: int) -> float:
        captured["tokens_in"] = tokens
        return 0.0

    monkeypatch.setattr(llm_router.GeminiClient, "generate", fake_generate)
    router = llm_router.LLMRouter()
    monkeypatch.setattr(router.quota, "check", fake_check)

    router.generate("general", [{"content": "hi"}])

    expected = len("hi".split()) + len(llm_router.SYSTEM_INSTRUCTION.split())
    assert captured["tokens_in"] == expected

