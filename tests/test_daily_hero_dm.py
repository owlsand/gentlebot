"""Tests for the DailyHeroDMCog message generation."""
import os
import asyncio

import pytest
import discord
from discord.ext import commands

from gentlebot.tasks.daily_hero_dm import DailyHeroDMCog


@pytest.fixture()
def cog(monkeypatch):
    os.environ.setdefault("HF_API_TOKEN", "dummy")
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    return DailyHeroDMCog(bot)


def test_generate_message_fallback(cog, monkeypatch):
    def fake_gen(prompt, **kwargs):
        return "Hello there"
    monkeypatch.setattr(cog.hf_client, "text_generation", fake_gen)
    msg = asyncio.run(cog._generate_message("Tester"))
    assert "Daily Hero role until midnight Pacific" in msg


def test_generate_message_success(cog, monkeypatch):
    sample = (
        "Greetings, Tester; your valiant efforts yesterday earned the Daily Hero honour, "
        "which persists until midnight, so cherish this well-deserved laurel in quiet, dignified triumph tonight."
    )
    def fake_gen(prompt, **kwargs):
        return sample
    monkeypatch.setattr(cog.hf_client, "text_generation", fake_gen)
    msg = asyncio.run(cog._generate_message("Tester"))
    assert msg == sample
