from types import SimpleNamespace

from gentlebot.llm.router import LLMRouter


def test_generate_image_returns_final_image(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    router = LLMRouter()

    class DummyQuota:
        def check(self, *a, **k):
            return None

    router.quota = DummyQuota()

    def fake_generate_image(model: str, prompt: str):
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(text="notice"),
                            SimpleNamespace(inline_data=SimpleNamespace(data=b"img1")),
                            SimpleNamespace(text="ignored"),
                            SimpleNamespace(inline_data=SimpleNamespace(data=b"img2")),
                        ]
                    )
                )
            ]
        )

    router.client.generate_image = fake_generate_image
    data = router.generate_image("test")
    assert data == b"img2"
