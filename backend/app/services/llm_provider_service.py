import ipaddress
import re
from urllib.parse import urlsplit
from typing import Literal

import httpx

from app.config import get_env_str


OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-4.1-mini"
DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"
LMSTUDIO_DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
OLLAMA_DEFAULT_BASE_URL = "http://127.0.0.1:11434"
CUSTOM_PROVIDER_BASE_URLS_ENV = "ALLOW_CUSTOM_PROVIDER_BASE_URLS"
ALLOWED_REMOTE_PROVIDER_DOMAINS: dict[str, tuple[str, ...]] = {
    "openai": ("openai.com",),
    "deepseek": ("deepseek.com",),
}

THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def build_endpoint_url(base_url: str, suffix: str) -> str:
    normalized_base = str(base_url or "").rstrip("/")
    normalized_suffix = str(suffix or "").strip()
    if not normalized_suffix.startswith("/"):
        normalized_suffix = f"/{normalized_suffix}"
    return f"{normalized_base}{normalized_suffix}"


def validate_provider_base_url(provider: str, base_url: str) -> str:
    normalized_provider = str(provider or "").strip().lower()
    normalized_base_url = str(base_url or "").strip()
    if not normalized_base_url:
        raise ValueError("base_url must not be empty.")

    parsed = urlsplit(normalized_base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("base_url must use http or https.")

    host = str(parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("base_url must include a host.")

    if _custom_provider_base_urls_enabled():
        return normalized_base_url

    if normalized_provider in {"lmstudio", "ollama"}:
        if not _is_loopback_host(host):
            raise ValueError(
                f"{normalized_provider} base_url must point to localhost or 127.0.0.1 / ::1."
            )
        return normalized_base_url

    allowed_domains = ALLOWED_REMOTE_PROVIDER_DOMAINS.get(normalized_provider, ())
    if not allowed_domains:
        return normalized_base_url

    if any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        return normalized_base_url

    raise ValueError(
        f"{normalized_provider} base_url must use one of: {', '.join(allowed_domains)}."
    )


def clean_model_output_text(value: str) -> str:
    normalized = str(value or "").replace("\r\n", "\n").strip()
    normalized = THINK_BLOCK_PATTERN.sub("", normalized).strip()
    if normalized.startswith("```"):
        normalized = _strip_markdown_code_fence(normalized)
    return normalized.strip()


def provider_env_prefix(provider: str) -> Literal["OPENAI", "DEEPSEEK", "LMSTUDIO", "OLLAMA"]:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "openai":
        return "OPENAI"
    if normalized_provider == "deepseek":
        return "DEEPSEEK"
    if normalized_provider == "lmstudio":
        return "LMSTUDIO"
    return "OLLAMA"


def provider_default_base_url(provider: str) -> str:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "openai":
        return OPENAI_DEFAULT_BASE_URL
    if normalized_provider == "deepseek":
        return DEEPSEEK_DEFAULT_BASE_URL
    if normalized_provider == "lmstudio":
        return LMSTUDIO_DEFAULT_BASE_URL
    return OLLAMA_DEFAULT_BASE_URL


def provider_default_model(provider: str) -> str:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "openai":
        return OPENAI_DEFAULT_MODEL
    if normalized_provider == "deepseek":
        return DEEPSEEK_DEFAULT_MODEL
    return ""


def normalize_ollama_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3].rstrip("/")
    return normalized


def extract_provider_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error_payload = payload.get("error")
        if isinstance(error_payload, dict):
            error_message = error_payload.get("message")
            if isinstance(error_message, str) and error_message.strip():
                return error_message.strip()
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    text_payload = response.text.strip()
    if text_payload:
        return text_payload
    return f"Provider request failed with status {response.status_code}."


def coerce_provider_headers(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    headers: dict[str, str] = {}
    for key, raw_value in value.items():
        normalized_key = str(key or "").strip()
        normalized_value = str(raw_value or "").strip()
        if not normalized_key or not normalized_value:
            continue
        headers[normalized_key] = normalized_value
    return headers


def discover_openai_compatible_model(
    *,
    base_url: str,
    api_key: str,
    extra_headers: dict[str, str],
    provider: str,
) -> str:
    validate_provider_base_url(provider, base_url)
    models_url = build_endpoint_url(base_url, "/models")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(extra_headers)

    try:
        response = httpx.get(models_url, headers=headers, timeout=20.0)
    except httpx.HTTPError as error:
        raise ValueError(
            f"Failed to discover {provider} model from {models_url}: {error}"
        ) from error

    if response.status_code >= 400:
        message = extract_provider_error_message(response)
        raise ValueError(
            f"Failed to discover {provider} model from {models_url}: {message}"
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise ValueError(
            f"Failed to discover {provider} model from {models_url}: invalid JSON response."
        ) from error

    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    model_id = str(item.get("id") or "").strip()
                    if model_id:
                        return model_id

    raise ValueError(
        f"No model id discovered from {models_url}. Provide an explicit model name."
    )


def _strip_markdown_code_fence(value: str) -> str:
    normalized = value.strip()
    if not normalized.startswith("```"):
        return normalized

    first_newline = normalized.find("\n")
    if first_newline < 0:
        return normalized.strip("`").strip()

    body = normalized[first_newline + 1 :]
    if body.endswith("```"):
        body = body[:-3]
    return body.strip()


def _custom_provider_base_urls_enabled() -> bool:
    return get_env_str(CUSTOM_PROVIDER_BASE_URLS_ENV).lower() in {"1", "true", "yes", "on"}


def _is_loopback_host(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
