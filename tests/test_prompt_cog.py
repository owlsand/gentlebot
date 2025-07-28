import types
from gentlebot.cogs import prompt_cog


def test_personal_snapshot_category_and_fallback(monkeypatch):
    assert any("Personal Snapshot" in t for t in prompt_cog.PROMPT_TYPES)

    monkeypatch.setenv("HF_API_TOKEN", "")
    monkeypatch.setattr(prompt_cog, "FALLBACK_PROMPTS", ["What's your screen time today?"])
    cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())
    prompt = cog.fetch_prompt()
    assert prompt == "What's your screen time today?"
