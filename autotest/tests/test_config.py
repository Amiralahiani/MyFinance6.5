"""Tests that autonomous-QA configuration is bounded and secret-safe."""

from __future__ import annotations

from pathlib import Path

import pytest
from myfinance_autotest.config import load_settings


def test_settings_resolve_model_overrides_without_exposing_the_api_key() -> None:
    settings = load_settings(
        environment={
            "GROQ_API_KEY": "secret-only-for-test",
            "GROQ_MODEL_EVALUATOR": "custom-evaluator",
        }
    )

    assert settings.require_groq_api_key() == "secret-only-for-test"
    assert settings.resolved_models["evaluator"] == "custom-evaluator"
    assert settings.safe_summary()["groq"]["api_key_configured"] is True
    assert "secret-only-for-test" not in str(settings.safe_summary())
    assert "secret-only-for-test" not in settings.model_dump_json()


def test_settings_allow_a_missing_key_until_a_groq_call_is_required() -> None:
    settings = load_settings(environment={})

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        settings.require_groq_api_key()


def test_settings_reject_a_missing_required_agent_role(tmp_path: Path) -> None:
    config = tmp_path / "autotest.yaml"
    config.write_text(
        """limits: {max_agent_steps: 1, max_llm_calls_per_test: 0, global_test_timeout_seconds: 1, max_repeated_actions: 1, min_evidence_confidence: 0.5}
endpoints: {api_base_url: http://api, web_base_url: http://web}
groq:
  timeout_seconds: 1
  max_retries: 0
  models:
    generator: {environment: GROQ_MODEL_GENERATOR, default: model}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing roles"):
        load_settings(config, environment={})
