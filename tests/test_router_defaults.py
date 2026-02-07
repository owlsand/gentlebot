from gentlebot.llm.router import LLMRouter


def test_image_route_defaults_to_free_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("MODEL_IMAGE", raising=False)
    monkeypatch.delenv("GEMINI_IMAGE_RPM", raising=False)
    router = LLMRouter()
    assert router.models["image"] == "gemini-2.5-flash-image"
    assert router.quota.limits["image"].rpm == 10

