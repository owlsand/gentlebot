"""Tests for the Gemini image helper."""

from types import SimpleNamespace

from gentlebot.llm.providers import gemini as gemini_module


def test_generate_image_requests_text_and_image(monkeypatch):
    """The image helper should ask Gemini for both text and image outputs."""

    recorded: dict[str, object] = {}

    class DummyModels:
        def generate_content(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace()

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.models = DummyModels()

    def fake_from_bytes(data: bytes, mime_type: str) -> tuple[bytes, str]:
        return (data, mime_type)

    monkeypatch.setattr(
        gemini_module,
        "genai",
        SimpleNamespace(
            Client=DummyClient,
            types=SimpleNamespace(
                GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
                Part=SimpleNamespace(from_bytes=fake_from_bytes),
            ),
        ),
    )

    client = gemini_module.GeminiClient("fake-key")
    client.generate_image("gemini-image", "paint a dragon")

    config = recorded["config"]
    assert getattr(config, "response_modalities") == ["TEXT", "IMAGE"]
    assert recorded["contents"][0] == "paint a dragon"
