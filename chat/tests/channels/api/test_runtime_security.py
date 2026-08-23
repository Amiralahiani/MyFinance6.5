import pytest
from fastapi.testclient import TestClient
from myfinance_contracts import SlidingWindowRateLimiter, load_runtime_security_settings
from myfinance_orchestrator.main import app


def test_local_security_settings_keep_public_features_disabled_by_default() -> None:
    settings = load_runtime_security_settings({})

    assert settings.deployment_mode == "local"
    assert settings.rate_limit_per_minute == 0
    assert not settings.is_public


def test_production_security_settings_require_explicit_origins_and_hosts() -> None:
    with pytest.raises(ValueError, match="MYFINANCE_CORS_ORIGINS"):
        load_runtime_security_settings({"MYFINANCE_DEPLOYMENT_MODE": "production"})

    with pytest.raises(ValueError, match="MYFINANCE_ALLOWED_HOSTS"):
        load_runtime_security_settings(
            {
                "MYFINANCE_DEPLOYMENT_MODE": "production",
                "MYFINANCE_CORS_ORIGINS": "https://app.example.test",
            }
        )

    settings = load_runtime_security_settings(
        {
            "MYFINANCE_DEPLOYMENT_MODE": "production",
            "MYFINANCE_CORS_ORIGINS": "https://app.example.test",
            "MYFINANCE_ALLOWED_HOSTS": "app.example.test,api.example.test",
        }
    )
    assert settings.is_public
    assert settings.rate_limit_per_minute == 60

    with pytest.raises(ValueError, match="non-zero MYFINANCE_RATE_LIMIT_PER_MINUTE"):
        load_runtime_security_settings(
            {
                "MYFINANCE_DEPLOYMENT_MODE": "production",
                "MYFINANCE_CORS_ORIGINS": "https://app.example.test",
                "MYFINANCE_ALLOWED_HOSTS": "api.example.test",
                "MYFINANCE_RATE_LIMIT_PER_MINUTE": "0",
            }
        )


def test_sliding_window_rate_limiter_releases_the_next_minute() -> None:
    limiter = SlidingWindowRateLimiter(limit_per_minute=2)

    assert limiter.allows("client", now=100)
    assert limiter.allows("client", now=101)
    assert not limiter.allows("client", now=102)
    assert limiter.allows("client", now=160)


def test_chat_api_adds_non_cacheable_security_headers() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
