import types
import asyncio
from gentlebot.cogs import prompt_cog


def test_engagement_bait_category_and_fallback(monkeypatch):
    assert "Engagement Bait" in prompt_cog.PROMPT_CATEGORIES

    monkeypatch.setenv("HF_API_TOKEN", "")
    monkeypatch.setattr(prompt_cog, "FALLBACK_PROMPTS", ["React with an emoji!"])

    def fake_choice(seq):
        if seq == prompt_cog.PROMPT_CATEGORIES:
            return "Engagement Bait"
        return seq[0]

    monkeypatch.setattr(prompt_cog.random, "choice", fake_choice)

    cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())
    prompt = asyncio.run(cog.fetch_prompt())
    assert prompt == "React with an emoji!"
    assert cog.last_category == "Engagement Bait"
