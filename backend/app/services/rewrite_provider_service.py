from dataclasses import dataclass, field
import time
from typing import Literal

import httpx

from app.config import get_env_str
from app.services.llm_provider_service import (
    coerce_provider_headers,
    build_endpoint_url,
    discover_openai_compatible_model,
    extract_provider_error_message,
    normalize_ollama_base_url,
    provider_default_base_url,
    provider_default_model,
    provider_env_prefix,
    resolve_provider_api_key,
    validate_provider_base_url,
)
from app.services.translation_service import RETRYABLE_STATUS_CODES

SUPPORTED_REWRITE_PROVIDERS = {"openai", "deepseek", "lmstudio", "ollama"}
MAX_REWRITE_REQUEST_ATTEMPTS = 3


def _raise_provider_error(message: str, cause: Exception | None = None) -> None:
    """Lazy import to avoid circular dependency with content_rewrite_service."""
    from app.services.content_rewrite_service import ContentRewriteProviderError

    if cause is not None:
        raise ContentRewriteProviderError(message) from cause
    raise ContentRewriteProviderError(message)


@dataclass(frozen=True)
class RewriteProviderConfig:
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    api_key: str
    base_url: str
    model: str
    extra_headers: dict[str, str] = field(default_factory=dict)


def resolve_rewrite_config(raw_config: dict[str, object] | None) -> RewriteProviderConfig:
    from app.services.content_rewrite_service import ContentRewriteConfigurationError

    config = raw_config or {}
    provider = str(
        config.get("provider")
        or get_env_str("REWRITE_PROVIDER")
        or get_env_str("TRANSLATION_PROVIDER")
        or "ollama"
    ).strip().lower()

    if provider not in SUPPORTED_REWRITE_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_REWRITE_PROVIDERS))
        raise ContentRewriteConfigurationError(
            f"Unsupported rewrite provider '{provider}'. Supported providers: {supported}."
        )

    env_prefix = provider_env_prefix(provider)
    try:
        api_key = resolve_provider_api_key(config, provider, env_prefix)
    except ValueError as error:
        raise ContentRewriteConfigurationError(str(error)) from error

    base_url = str(
        config.get("base_url")
        or get_env_str(f"{env_prefix}_BASE_URL")
        or provider_default_base_url(provider)
    ).strip()
    try:
        base_url = validate_provider_base_url(provider, base_url)
    except ValueError as error:
        raise ContentRewriteConfigurationError(str(error)) from error

    model = str(
        config.get("model")
        or get_env_str(f"{env_prefix}_REWRITE_MODEL")
        or get_env_str(f"{env_prefix}_CHAT_MODEL")
        or get_env_str(f"{env_prefix}_TRANSLATION_MODEL")
        or provider_default_model(provider)
    ).strip()

    extra_headers = coerce_provider_headers(config.get("extra_headers"))
    if not model and provider in {"lmstudio", "ollama"}:
        try:
            model = discover_openai_compatible_model(
                base_url=base_url,
                api_key=api_key,
                extra_headers=extra_headers,
                provider=provider,
            )
        except Exception as error:
            raise ContentRewriteConfigurationError(str(error)) from error

    if not model:
        raise ContentRewriteConfigurationError(
            f"{env_prefix}_REWRITE_MODEL is not set and no model could be discovered for provider '{provider}'."
        )

    typed_provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    if provider == "openai":
        typed_provider = "openai"
    elif provider == "deepseek":
        typed_provider = "deepseek"
    elif provider == "lmstudio":
        typed_provider = "lmstudio"
    else:
        typed_provider = "ollama"

    return RewriteProviderConfig(
        provider=typed_provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        extra_headers=extra_headers,
    )


def rewrite_with_openai_compatible(
    config: RewriteProviderConfig,
    messages: list[dict[str, str]],
    *,
    rewrite_style: str,
    cancellation_checker=None,
) -> str:
    temperature, max_tokens = rewrite_generation_settings(rewrite_style)
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    response = _post_json(
        url=build_endpoint_url(config.base_url, "/chat/completions"),
        headers=_build_headers(config),
        payload=payload,
        provider=config.provider,
        cancellation_checker=cancellation_checker,
    )

    try:
        body = response.json()
    except ValueError as error:
        _raise_provider_error(
            f"{config.provider} returned invalid rewrite JSON.",
            cause=error,
        )

    if not isinstance(body, dict):
        _raise_provider_error(
            f"{config.provider} returned an unexpected rewrite payload."
        )

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        _raise_provider_error(
            f"{config.provider} response did not include rewrite choices."
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        _raise_provider_error(
            f"{config.provider} response choice had an unexpected format."
        )

    message = first_choice.get("message")
    if not isinstance(message, dict):
        _raise_provider_error(
            f"{config.provider} response did not include a message payload."
        )

    content = message.get("content")
    if not isinstance(content, str):
        _raise_provider_error(
            f"{config.provider} response did not include rewrite content."
        )

    return content


def rewrite_with_ollama(
    config: RewriteProviderConfig,
    messages: list[dict[str, str]],
    *,
    rewrite_style: str,
    cancellation_checker=None,
) -> str:
    temperature, max_tokens = rewrite_generation_settings(rewrite_style)
    payload = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    response = _post_json(
        url=build_endpoint_url(normalize_ollama_base_url(config.base_url), "/api/chat"),
        headers=_build_headers(config),
        payload=payload,
        provider=config.provider,
        cancellation_checker=cancellation_checker,
    )

    try:
        body = response.json()
    except ValueError as error:
        _raise_provider_error(
            "ollama returned invalid rewrite JSON.",
            cause=error,
        )

    if not isinstance(body, dict):
        _raise_provider_error(
            "ollama returned an unexpected rewrite payload."
        )

    message = body.get("message")
    if not isinstance(message, dict):
        _raise_provider_error(
            "ollama response did not include a message payload."
        )

    content = message.get("content")
    if not isinstance(content, str):
        _raise_provider_error(
            "ollama response did not include rewrite content."
        )

    return content


def rewrite_generation_settings(rewrite_style: str) -> tuple[float, int]:
    if rewrite_style == "speech_verbatim":
        return 0.7, 32000
    return 0.4, 12000


def _post_json(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    provider: str,
    cancellation_checker: object = None,
) -> httpx.Response:
    last_error_message = ""
    for attempt in range(1, MAX_REWRITE_REQUEST_ATTEMPTS + 1):
        if callable(cancellation_checker) and cancellation_checker():
            _raise_provider_error("Rewrite cancelled.")
        try:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=300.0,
            )
        except httpx.HTTPError as error:
            last_error_message = f"{provider} rewrite request failed: {error}"
            if attempt < MAX_REWRITE_REQUEST_ATTEMPTS:
                time.sleep(0.75 * attempt)
                continue
            _raise_provider_error(last_error_message, cause=error)

        if response.status_code < 400:
            return response

        message = extract_provider_error_message(response)
        last_error_message = message
        if (
            response.status_code in RETRYABLE_STATUS_CODES
            and attempt < MAX_REWRITE_REQUEST_ATTEMPTS
        ):
            time.sleep(0.75 * attempt)
            continue

        _raise_provider_error(message)

    _raise_provider_error(last_error_message or "Rewrite request failed.")


def _build_headers(config: RewriteProviderConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    headers.update(config.extra_headers)
    return headers
