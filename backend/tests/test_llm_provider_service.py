import pytest

from app.services.llm_provider_service import (
    coerce_provider_headers,
    validate_provider_base_url,
)


@pytest.fixture(autouse=True)
def isolate_provider_security_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ALLOW_CUSTOM_PROVIDER_BASE_URLS",
        "PROVIDER_BASE_URL_ALLOWLIST",
        "DEPLOYMENT_PROFILE",
        "APP_ENV",
    ):
        monkeypatch.delenv(key, raising=False)


def test_validate_provider_base_url_rejects_openai_http() -> None:
    with pytest.raises(ValueError, match="must use https"):
        validate_provider_base_url("openai", "http://api.openai.com/v1")


def test_validate_provider_base_url_rejects_credentials_in_base_url() -> None:
    with pytest.raises(ValueError, match="must not include username or password"):
        validate_provider_base_url("openai", "https://user:pass@api.openai.com/v1")


def test_validate_provider_base_url_rejects_private_ip_for_local_provider() -> None:
    with pytest.raises(ValueError, match="must point to localhost"):
        validate_provider_base_url("ollama", "http://192.168.1.10:11434")


def test_validate_provider_base_url_rejects_metadata_ip_literal() -> None:
    with pytest.raises(ValueError, match="must not use localhost, loopback, or an IP literal"):
        validate_provider_base_url("openai", "https://169.254.169.254/v1")


def test_validate_provider_base_url_allows_loopback_local_provider_in_development() -> (
    None
):
    assert (
        validate_provider_base_url("ollama", "http://127.0.0.1:11434")
        == "http://127.0.0.1:11434"
    )


def test_validate_provider_base_url_rejects_production_custom_bypass() -> None:
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "production")
        monkeypatch.setenv("ALLOW_CUSTOM_PROVIDER_BASE_URLS", "1")

        with pytest.raises(ValueError, match="must use one of"):
            validate_provider_base_url("openai", "https://llm-proxy.example.com/v1")
    finally:
        monkeypatch.undo()


def test_validate_provider_base_url_allows_allowlisted_custom_url_in_production() -> None:
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "production")
        monkeypatch.setenv(
            "PROVIDER_BASE_URL_ALLOWLIST",
            "https://llm-proxy.example.com, https://api.openai.com",
        )

        assert (
            validate_provider_base_url("openai", "https://llm-proxy.example.com/v1")
            == "https://llm-proxy.example.com/v1"
        )
    finally:
        monkeypatch.undo()


def test_coerce_provider_headers_blocks_dangerous_headers() -> None:
    headers = coerce_provider_headers(
        {
            "Authorization": "Bearer override-me",
            "Host": "malicious.example.com",
            "Content-Length": "999",
            "Connection": "keep-alive",
            "X-Trace-Id": "trace-123",
            "X-Custom": "allowed",
        }
    )

    assert headers == {"X-Trace-Id": "trace-123", "X-Custom": "allowed"}
