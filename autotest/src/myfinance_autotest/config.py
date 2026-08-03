"""Safe, explicit configuration for autonomous QA campaigns and Groq.

The API key is read only from the process environment.  It is deliberately
excluded from serialised configuration so traces and reports cannot disclose it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "autotest" / "configs" / "autotest.yaml"
REQUIRED_GROQ_ROLES = ("generator", "planner", "evaluator", "critic", "reporter")


class CampaignLimits(BaseModel):
    max_agent_steps: int = Field(ge=1, le=100)
    max_llm_calls_per_test: int = Field(ge=0, le=100)
    global_test_timeout_seconds: int = Field(ge=1, le=3_600)
    max_repeated_actions: int = Field(ge=1, le=20)
    min_evidence_confidence: float = Field(ge=0, le=1)


class EndpointConfig(BaseModel):
    api_base_url: str = Field(min_length=8)
    web_base_url: str = Field(min_length=8)


class GroqModelConfig(BaseModel):
    environment: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    default: str = Field(min_length=3)


class GroqConfig(BaseModel):
    api_key_environment: str = Field(default="GROQ_API_KEY", pattern=r"^[A-Z][A-Z0-9_]*$")
    timeout_seconds: int = Field(ge=1, le=120)
    max_retries: int = Field(ge=0, le=5)
    models: dict[str, GroqModelConfig]


class AutotestSettings(BaseModel):
    limits: CampaignLimits
    endpoints: EndpointConfig
    groq: GroqConfig
    groq_api_key: str | None = Field(default=None, exclude=True, repr=False)
    resolved_models: dict[str, str]

    def require_groq_api_key(self) -> str:
        """Return the key only to the future backend client, never to reporters."""
        if not self.groq_api_key:
            raise RuntimeError(
                f"Missing {self.groq.api_key_environment}. Define it in the process environment, not in a file."
            )
        return self.groq_api_key

    def safe_summary(self) -> dict[str, object]:
        """Return configuration suitable for a trace or report without secrets."""
        return {
            "limits": self.limits.model_dump(),
            "endpoints": self.endpoints.model_dump(),
            "groq": {
                "api_key_environment": self.groq.api_key_environment,
                "timeout_seconds": self.groq.timeout_seconds,
                "max_retries": self.groq.max_retries,
                "models": self.resolved_models,
                "api_key_configured": bool(self.groq_api_key),
            },
        }


def _load_yaml(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Autotest configuration does not exist: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Autotest configuration must be a YAML object.")
    return payload


def load_settings(
    path: Path = DEFAULT_CONFIG_PATH, *, environment: Mapping[str, str] | None = None
) -> AutotestSettings:
    """Load YAML policy and resolve models/secret from the supplied environment."""
    payload = _load_yaml(path)
    groq = GroqConfig.model_validate(payload.get("groq", {}))
    missing_roles = set(REQUIRED_GROQ_ROLES) - set(groq.models)
    if missing_roles:
        raise ValueError(f"Groq model configuration is missing roles: {', '.join(sorted(missing_roles))}")
    source_environment = environment if environment is not None else os.environ
    resolved_models = {
        role: source_environment.get(model.environment, model.default)
        for role, model in groq.models.items()
    }
    return AutotestSettings(
        limits=CampaignLimits.model_validate(payload.get("limits", {})),
        endpoints=EndpointConfig.model_validate(payload.get("endpoints", {})),
        groq=groq,
        groq_api_key=source_environment.get(groq.api_key_environment) or None,
        resolved_models=resolved_models,
    )
