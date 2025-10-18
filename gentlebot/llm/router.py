"""LLM routing and observability."""
from __future__ import annotations

import logging
import os
import time
from typing import List, Dict, Any

from .providers.gemini import GeminiClient
from ..infra.retries import call_with_backoff
from ..infra.quotas import QuotaGuard, Limit, RateLimited
from dotenv import load_dotenv

log = logging.getLogger(f"gentlebot.{__name__}")

# Ensure environment variables from a local .env are loaded so the Gemini
# API key is available even when this module is imported before bot_config.
load_dotenv()


SYSTEM_INSTRUCTION = (
    "You are Gentlebot, a Discord robot assistant for the Gentlefolk server.\n\n"
    "Personality and voice:\n"
    "- Fun but concise and factual. Default to 2-5 sentences.\n"
    "- Friendly but dry. Light touch of humor only if it increases clarity.\n"
    "Interaction rules:\n"
    "- Avoid flooding: keep under ~1200 characters per message when possible.\n"
    "Style constraints:\n"
    "- Present trade-offs and probabilities where relevant.\n\n"
    "Tools:\n"
    "- No access to tools in this environment."
)

class SafetyBlocked(Exception):
    """Raised when content is blocked for safety."""


class LLMRouter:
    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key is None:
            log.debug("GEMINI_API_KEY environment variable not set")
        self.client = GeminiClient(api_key)
        self.models = {
            "general": os.getenv("MODEL_GENERAL", "gemini-flash-latest"),
            "scheduled": os.getenv("MODEL_SCHEDULED", "gemini-2.5-pro"),
            "image": os.getenv("MODEL_IMAGE", "gemini-2.0-flash-preview-image"),
        }
        def _limit(route: str, default: Limit) -> Limit:
            prefix = f"GEMINI_{route.upper()}_"
            rpm = os.getenv(f"{prefix}RPM")
            tpm = os.getenv(f"{prefix}TPM")
            rpd = os.getenv(f"{prefix}RPD")
            return Limit(
                rpm=int(rpm) if rpm is not None else default.rpm,
                tpm=int(tpm) if tpm is not None else default.tpm,
                rpd=int(rpd) if rpd is not None else default.rpd,
            )

        self.quota = QuotaGuard(
            {
                "general": _limit("general", Limit(rpm=15, tpm=1_000_000, rpd=1_500)),
                "scheduled": _limit("scheduled", Limit(rpm=2, tpm=1_000_000, rpd=1_500)),
                "image": _limit("image", Limit(rpm=10, tpm=1_000_000, rpd=1_500)),
            }
        )

    def _tokens_estimate(
        self, messages: List[Dict[str, Any]], system_instruction: str | None = None
    ) -> int:
        count = sum(len(m.get("content", "").split()) for m in messages)
        if system_instruction:
            count += len(system_instruction.split())
        return count

    def generate(
        self,
        route: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.6,
        think_budget: int = 0,
        json_mode: bool = False,
    ) -> str:
        model = self.models.get(route)
        if not model:
            raise ValueError(f"unknown route {route}")
        tokens_in = self._tokens_estimate(messages, SYSTEM_INSTRUCTION)
        try:
            temp_delta = self.quota.check(route, tokens_in)
        except RateLimited:
            if route == "scheduled":
                log.info(
                    "route=%s model=%s tokens_in=%s status=rate_limited fallback=general",
                    route,
                    model,
                    tokens_in,
                )
                return self.generate(
                    "general", messages, temperature, think_budget, json_mode
                )
            raise
        temp = max(0.0, temperature + temp_delta)
        start = time.time()

        def _call():
            return self.client.generate(
                model=model,
                messages=messages,
                temperature=temp,
                json_mode=json_mode,
                thinking_budget=think_budget,
                system_instruction=SYSTEM_INSTRUCTION,
            )

        try:
            resp = call_with_backoff(_call)
        except RateLimited:
            if route == "scheduled":
                log.info(
                    "route=%s model=%s tokens_in=%s status=rate_limited fallback=general",
                    route,
                    model,
                    tokens_in,
                )
                return self.generate("general", messages, temperature, think_budget, json_mode)
            log.info(
                "route=%s model=%s tokens_in=%s status=rate_limited", route, model, tokens_in
            )
            raise
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if route == "scheduled" and (status == 429 or (status and 500 <= status < 600)):
                log.warning(
                    "route=%s model=%s tokens_in=%s status=%s fallback=general",
                    route,
                    model,
                    tokens_in,
                    status,
                )
                return self.generate("general", messages, temperature, think_budget, json_mode)
            log.exception(
                "route=%s model=%s tokens_in=%s status=error", route, model, tokens_in
            )
            raise

        tokens_out = getattr(getattr(resp, "usage_metadata", None), "candidates_token_count", 0)
        text = getattr(resp, "text", "")
        status = "ok"
        block_reason = None
        if not text:
            status = "blocked"
            block_reason = getattr(resp, "prompt_feedback", None)
            raise SafetyBlocked

        total_ms = (time.time() - start) * 1000
        log.info(
            "route=%s model=%s tokens_in=%s tokens_out=%s ttfb_ms=0 total_ms=%s status=%s block_reason=%s",
            route,
            model,
            tokens_in,
            tokens_out,
            int(total_ms),
            status,
            block_reason,
        )
        return text

    def generate_image(self, prompt: str) -> bytes | None:
        model = self.models.get("image")
        if not model:
            raise ValueError("image model not configured")
        tokens_in = len(prompt.split())
        self.quota.check("image", tokens_in)
        start = time.time()

        def _call():
            return self.client.generate_image(model=model, prompt=prompt)

        try:
            resp = call_with_backoff(_call)
        except RateLimited:
            log.info("route=image model=%s tokens_in=%s status=rate_limited", model, tokens_in)
            raise
        except Exception:
            log.exception(
                "route=image model=%s tokens_in=%s status=error", model, tokens_in
            )
            raise

        data = None
        try:
            # Gemini responses may include textual parts before the actual
            # image data. Walk through all returned parts and capture the
            # final ``inline_data`` block as the effective image result.
            parts = resp.candidates[0].content.parts  # type: ignore[attr-defined]
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    data = inline.data
        except Exception:
            data = None
        total_ms = (time.time() - start) * 1000
        log.info(
            "route=image model=%s tokens_in=%s tokens_out=0 ttfb_ms=0 total_ms=%s status=%s block_reason=%s",
            model,
            tokens_in,
            int(total_ms),
            "ok" if data else "error",
            None,
        )
        if data:
            return data
        return None


router = LLMRouter()
