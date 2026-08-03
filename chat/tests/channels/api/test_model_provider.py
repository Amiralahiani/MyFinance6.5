"""Tests for provider-independent, safe generation parsing."""

from myfinance_orchestrator import model_provider


def test_json_object_discards_non_json_model_output(monkeypatch) -> None:
    monkeypatch.setattr(model_provider, "complete", lambda *args, **kwargs: "not json")

    assert model_provider.json_object("test") is None


def test_json_object_accepts_one_model_object(monkeypatch) -> None:
    monkeypatch.setattr(model_provider, "complete", lambda *args, **kwargs: '{"prompt":"PNB BIAT 2025"}')

    assert model_provider.json_object("test") == {"prompt": "PNB BIAT 2025"}
