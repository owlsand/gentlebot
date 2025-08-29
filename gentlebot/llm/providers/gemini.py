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


ROLE_MAP = {"user": "user", "assistant": "model", "system": "system"}


class GeminiClient:
    """Wrapper around the google-genai client."""

    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        parts = []
        for m in messages:
            role = ROLE_MAP.get(m.get("role", "user"), "user")
            parts.append({"role": role, "parts": [m.get("content", "")]})
        return parts

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.6,
        json_mode: bool = False,
        thinking_budget: int = 0,
    ) -> Any:
        config = genai.types.GenerateContentConfig(temperature=temperature)
        if json_mode:
            config.response_mime_type = "application/json"
        if thinking_budget:
            config.thinking = genai.types.ThinkingConfig(budget_tokens=thinking_budget)
        content = self._convert_messages(messages)
        response = self.client.models.generate_content(
            model=model,
            contents=content,
            config=config,
        )
        return response

    def generate_image(self, model: str, prompt: str, *images: bytes) -> Any:
        parts = [prompt]
        for img in images:
            parts.append(genai.types.Part.from_bytes(img, mime_type="image/png"))
        response = self.client.models.generate_content(model=model, contents=parts)
        return response
