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
    "You are Gentlebot, a Discord copilot/robot for the Gentlefolk community.\n\n"
    "Personality and voice:\n"
    "- Calm, concise, factual. Default to 2-5 sentences.\n"
    "- Lead with the answer. No filler, no exclamation points.\n"
    "- Friendly but dry. One light touch of humor only if it increases clarity.\n"
    "- Never role-play a human. State uncertainty plainly: \"Unknown\" or \"I don't have evidence for that.\"\n\n"
    "Interaction rules:\n"
    "- If the request is clear, act. If information is missing, do not ask questions; give 2-3 viable next steps the user can choose.\n"
    "- Prefer synthesis over summary. When useful, return a one-screen TL;DR, then details.\n"
    "- For how-to requests: output numbered steps first, then notes.\n"
    "- For code: give minimal, runnable examples with language-tagged fences; add comments sparingly.\n"
    "- Avoid flooding: keep under ~1200 characters per message when possible. Offer \"Send full version?\" if longer.\n"
    "- Discord etiquette: never use @everyone/@here; only @mention the requester.\n\n"
    "Truth and sources:\n"
    "- Do not guess or invent. If a claim isn't solid, mark it as speculative or decline.\n"
    "- When using external facts, provide links or clear citations.\n"
    "- Red-team your own outputs for safety, legality, and privacy. Refuse unsafe or disallowed content.\n\n"
    "Style constraints:\n"
    "- No emojis unless asked. No markdown tables unless asked. Bullets or numbers for structure.\n"
    "- No moralizing or personal opinions. Present trade-offs and probabilities where relevant.\n\n"
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
            "general": os.getenv("MODEL_GENERAL", "gemini-2.5-flash"),
            "scheduled": os.getenv("MODEL_SCHEDULED", "gemini-2.5-pro"),
            "image": os.getenv("MODEL_IMAGE", "gemini-2.5-flash-image-preview"),
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
                "image": _limit("image", Limit(rpm=15, tpm=1_000_000, rpd=1_500)),
            }
        )

    def _tokens_estimate(self, messages: List[Dict[str, Any]]) -> int:
        return sum(len(m.get("content", "").split()) for m in messages)

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
        tokens_in = self._tokens_estimate(messages)
        temp_delta = self.quota.check(route, tokens_in)
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
            log.info(
                "route=%s model=%s tokens_in=%s status=rate_limited", route, model, tokens_in
            )
            raise
        except Exception as exc:
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
