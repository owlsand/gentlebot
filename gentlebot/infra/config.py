"""Centralized configuration for cogs and components."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


def _int_env(var: str, default: int) -> int:
    """Return int value from environment variable or default."""
    value = os.getenv(var)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_env(var: str, default: float) -> float:
    """Return float value from environment variable or default."""
    value = os.getenv(var)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_env(var: str, default: bool) -> bool:
    """Return boolean value from environment variable or default."""
    value = os.getenv(var)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for LLM-related settings."""

    max_tokens: int = 150
    temperature: float = 0.6
    cooldown_seconds: int = 10
    max_prompt_length: int = 750

    @classmethod
    def from_env(cls, prefix: str = "") -> "LLMConfig":
        """Create config from environment variables with optional prefix."""
        p = f"{prefix}_" if prefix else ""
        return cls(
            max_tokens=_int_env(f"{p}LLM_MAX_TOKENS", 150),
            temperature=_float_env(f"{p}LLM_TEMPERATURE", 0.6),
            cooldown_seconds=_int_env(f"{p}LLM_COOLDOWN_SECONDS", 10),
            max_prompt_length=_int_env(f"{p}LLM_MAX_PROMPT_LENGTH", 750),
        )



@dataclass(frozen=True)
class ReactionConfig:
    """Configuration for emoji reaction behavior."""

    base_chance: float = 0.02
    mention_chance: float = 0.25
    default_emojis: tuple[str, ...] = ("😂", "🤔", "😅", "🔥", "🙃", "😎")

    @classmethod
    def from_env(cls) -> "ReactionConfig":
        """Create config from environment variables."""
        return cls(
            base_chance=_float_env("REACTION_BASE_CHANCE", 0.02),
            mention_chance=_float_env("REACTION_MENTION_CHANCE", 0.25),
        )


@dataclass(frozen=True)
class ArchiveConfig:
    """Configuration for message archival."""

    enabled: bool = False

    @classmethod
    def from_env(cls) -> "ArchiveConfig":
        """Create config from environment variables."""
        return cls(
            enabled=os.getenv("ARCHIVE_MESSAGES") == "1",
        )


@dataclass
class CogConfig:
    """Container for all cog configurations.

    This class provides a centralized place to access configuration
    for all cogs. It can be instantiated once and passed to cogs
    during initialization for better testability.
    """

    llm: LLMConfig = field(default_factory=LLMConfig.from_env)
    reaction: ReactionConfig = field(default_factory=ReactionConfig.from_env)
    archive: ArchiveConfig = field(default_factory=ArchiveConfig.from_env)

    @classmethod
    def from_env(cls) -> "CogConfig":
        """Create all configs from environment variables."""
        return cls(
            llm=LLMConfig.from_env(),
            reaction=ReactionConfig.from_env(),
            archive=ArchiveConfig.from_env(),
        )


# Global default configuration instance
_default_config: CogConfig | None = None


def get_config() -> CogConfig:
    """Return the global configuration instance.

    Creates the configuration on first access. This allows for lazy
    loading of environment variables.
    """
    global _default_config
    if _default_config is None:
        _default_config = CogConfig.from_env()
    return _default_config


def set_config(config: CogConfig) -> None:
    """Set the global configuration instance.

    Useful for testing or when you need to override defaults.
    """
    global _default_config
    _default_config = config


def reset_config() -> None:
    """Reset the global configuration to reload from environment."""
    global _default_config
    _default_config = None
