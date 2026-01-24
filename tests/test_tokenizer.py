"""Tests for the token estimation utilities."""

from __future__ import annotations

import pytest

from gentlebot.llm.tokenizer import (
    estimate_tokens,
    estimate_tokens_for_messages,
    truncate_to_token_budget,
    split_by_token_budget,
)


class TestEstimateTokens:
    """Tests for the estimate_tokens function."""

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_short_string(self) -> None:
        # "Hello" is 5 chars, should be ~1-2 tokens
        result = estimate_tokens("Hello")
        assert result >= 1

    def test_longer_string(self) -> None:
        # 100 chars should be ~25 tokens (100 / 4)
        text = "a" * 100
        result = estimate_tokens(text)
        assert result == 25

    def test_realistic_sentence(self) -> None:
        # "Hello, world!" is 13 chars, should be ~3 tokens
        result = estimate_tokens("Hello, world!")
        assert result == 3


class TestEstimateTokensForMessages:
    """Tests for the estimate_tokens_for_messages function."""

    def test_empty_messages(self) -> None:
        result = estimate_tokens_for_messages([])
        assert result == 0

    def test_single_message(self) -> None:
        messages = [{"content": "Hello world"}]
        result = estimate_tokens_for_messages(messages)
        # 11 chars / 4 = 2-3 tokens + 4 overhead
        assert result >= 5

    def test_with_system_instruction(self) -> None:
        messages = [{"content": "Hello"}]
        system = "You are a helpful assistant."
        result = estimate_tokens_for_messages(messages, system)
        # Should include both message and system tokens
        assert result > estimate_tokens_for_messages(messages)

    def test_multiple_messages(self) -> None:
        messages = [
            {"content": "Hello"},
            {"content": "World"},
        ]
        result = estimate_tokens_for_messages(messages)
        # Each message adds overhead
        assert result >= 8  # At least 2 tokens + 2*4 overhead


class TestTruncateToTokenBudget:
    """Tests for the truncate_to_token_budget function."""

    def test_within_budget(self) -> None:
        text = "Short text"
        result = truncate_to_token_budget(text, 100)
        assert result == text

    def test_exceeds_budget(self) -> None:
        text = "a" * 100  # 25 tokens
        result = truncate_to_token_budget(text, 10)  # 40 chars
        assert len(result) == 40

    def test_preserve_end(self) -> None:
        text = "start_middle_end"
        result = truncate_to_token_budget(text, 2, preserve_end=True)
        assert result.endswith("end")

    def test_empty_string(self) -> None:
        result = truncate_to_token_budget("", 100)
        assert result == ""


class TestSplitByTokenBudget:
    """Tests for the split_by_token_budget function."""

    def test_within_budget(self) -> None:
        text = "Short text"
        result = split_by_token_budget(text, 100)
        assert result == ["Short text"]

    def test_splits_long_text(self) -> None:
        text = "a" * 200  # 50 tokens
        result = split_by_token_budget(text, 10)  # Split into ~5 chunks
        assert len(result) > 1
        assert "".join(result) == text

    def test_empty_string(self) -> None:
        result = split_by_token_budget("", 100)
        assert result == []
