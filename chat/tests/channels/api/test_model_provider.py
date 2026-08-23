"""Tests for provider-independent, safe generation parsing."""

from myfinance_orchestrator import model_provider


def test_json_object_discards_non_json_model_output(monkeypatch) -> None:
    monkeypatch.setattr(model_provider, "complete", lambda *args, **kwargs: "not json")

    assert model_provider.json_object("test") is None


def test_json_object_accepts_one_model_object(monkeypatch) -> None:
    monkeypatch.setattr(model_provider, "complete", lambda *args, **kwargs: '{"prompt":"PNB BIAT 2025"}')

    assert model_provider.json_object("test") == {"prompt": "PNB BIAT 2025"}


def test_complete_uses_groq_only_when_selected(monkeypatch) -> None:
    monkeypatch.setattr(model_provider, "PROVIDER", "groq")
    monkeypatch.setattr(
        model_provider, "_complete_groq", lambda prompt, *, json_mode, max_tokens: "grounded synthesis"
    )

    assert model_provider.complete("official excerpt", json_mode=True) == "grounded synthesis"


def test_groq_without_a_key_falls_back_safely(monkeypatch) -> None:
    monkeypatch.setattr(model_provider, "GROQ_API_KEY", "")

    assert model_provider._complete_groq("official excerpt", max_tokens=40) is None
