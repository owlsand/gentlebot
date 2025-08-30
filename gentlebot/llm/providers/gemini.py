import logging
from typing import List, Dict, Any
from types import SimpleNamespace

try:
    from google import genai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    class _DummyClient:
        def __init__(self, *a, **k):
            pass

        class models:
            @staticmethod
            def generate_content(*a, **k):
                raise RuntimeError("google-genai library not installed")

    class _DummyTypes:
        class GenerateContentConfig:
            def __init__(self, *a, **k):
                pass

        class ThinkingConfig:
            def __init__(self, *a, **k):
                pass

        class Part:
            @staticmethod
            def from_bytes(data: bytes, mime_type: str):
                return data

    genai = SimpleNamespace(Client=_DummyClient, types=_DummyTypes)  # type: ignore

log = logging.getLogger(f"gentlebot.{__name__}")


# Gemini accepts only ``user`` or ``model`` roles; map assistant messages to
# ``model`` and treat all others as ``user``.
ROLE_MAP = {"user": "user", "assistant": "model"}


class GeminiClient:
    """Wrapper around the google-genai client."""

    def __init__(self, api_key: str | None) -> None:
        """Create a Gemini API client.

        Parameters
        ----------
        api_key:
            API key used to authenticate with Gemini.  When not provided the
            client is still created with a dummy key so imports don't fail,
            but requests will error.  This method logs a warning in that case
            to make configuration issues easier to spot.
        """

        if not api_key:
            log.warning("GEMINI_API_KEY not configured; using placeholder key")
            api_key = "test"
        else:
            log.debug("GEMINI_API_KEY provided (%d chars)", len(api_key))

        self.client = genai.Client(api_key=api_key)

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Translate internal message format to Gemini's expected structure.

        The Gemini SDK expects each message as a ``Content`` object with parts that
        are ``Part`` instances (or dictionaries with a ``text`` field).  Previously
        we passed the raw string directly which caused pydantic validation errors
        like ``Input should be a valid dictionary``.  This method now wraps each
        message content in a ``{"text": ...}`` part so the request validates
        correctly.
        """

        converted: List[Dict[str, Any]] = []
        for m in messages:
            role = ROLE_MAP.get(m.get("role", "user"), "user")
            content = m.get("content", "")
            converted.append({"role": role, "parts": [{"text": content}]})
        return converted

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.6,
        json_mode: bool = False,
        thinking_budget: int = 0,
        system_instruction: str | None = None,
    ) -> Any:
        config = genai.types.GenerateContentConfig(
            temperature=temperature, system_instruction=system_instruction
        )
        if json_mode:
            config.response_mime_type = "application/json"
        if thinking_budget:
            config.thinking = genai.types.ThinkingConfig(budget_tokens=thinking_budget)
        content = self._convert_messages(messages)
        try:
            response = self.client.models.generate_content(
                model=model, contents=content, config=config
            )
        except Exception as exc:  # pragma: no cover - optional logging
            log.exception("Gemini API call failed: %s", exc)
            raise
        return response

    def generate_image(self, model: str, prompt: str, *images: bytes) -> Any:
        parts = [prompt]
        for img in images:
            parts.append(genai.types.Part.from_bytes(img, mime_type="image/png"))
        response = self.client.models.generate_content(model=model, contents=parts)
        return response
