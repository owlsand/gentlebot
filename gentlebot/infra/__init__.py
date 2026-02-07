"""Infrastructure utilities for Gentlebot."""
from .cog_base import PoolAwareCog, log_errors, require_pool
from .github_issues import GitHubIssueConfig, get_github_issue_config
from .config import (
    ArchiveConfig,
    CogConfig,
    LLMConfig,
    ReactionConfig,
    get_config,
    reset_config,
    set_config,
)
from .logging import (
    LogContext,
    get_cog_logger,
    get_logger,
    structured_log,
)
from .idempotent import daily_key, idempotent_task, monthly_key, weekly_key
from .quotas import Limit, QuotaGuard, RateLimited
from .retries import async_retry, call_with_backoff, with_retry
from .state_cache import StateCache, get_state_cache
from .transactions import transaction

__all__ = [
    # Cog base classes
    "PoolAwareCog",
    "log_errors",
    "require_pool",
    # GitHub Issues
    "GitHubIssueConfig",
    "get_github_issue_config",
    # Configuration
    "ArchiveConfig",
    "CogConfig",
    "LLMConfig",
    "ReactionConfig",
    "get_config",
    "reset_config",
    "set_config",
    # Idempotency
    "daily_key",
    "idempotent_task",
    "monthly_key",
    "weekly_key",
    # Logging
    "LogContext",
    "get_cog_logger",
    "get_logger",
    "structured_log",
    # Quotas
    "Limit",
    "QuotaGuard",
    "RateLimited",
    # Retries
    "async_retry",
    "call_with_backoff",
    "with_retry",
    # State Cache
    "StateCache",
    "get_state_cache",
    # Transactions
    "transaction",
]
