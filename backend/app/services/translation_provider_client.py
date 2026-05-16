import logging
import time
from dataclasses import dataclass, field
from typing import Literal

import httpx

from app.config import get_env_str
from app.services.llm_provider_service import (
    coerce_provider_headers,
    provider_default_base_url,
    provider_default_model,
    provider_env_prefix,
    validate_provider_base_url,
)
from app.services.translation_chunking import (
    _translation_output_token_budget,
)
from app.services.translation_text_cleanup import (
    _clean_model_output_text,
    _parse_translated_items_json,
    _try_parse_translation_items_json,
)
from app.services.translation_types import (
    NonJsonTranslationContentError,
    PartialTranslationsContentError,
    RetryableTranslationContentError,
    TranslationChunkItem,
    TranslationError,
    TranslationProviderError,
)

logger = logging.getLogger(__name__)

SUPPORTED_TRANSLATION_PROVIDERS = {"openai", "deepseek", "lmstudio", "ollama"}
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-4.1-mini"
DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"
LMSTUDIO_DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
OLLAMA_DEFAULT_BASE_URL = "http://127.0.0.1:11434"
MAX_TRANSLATION_REQUEST_ATTEMPTS = 3
MAX_TRANSLATION_CONTENT_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
REQUEST_RETRY_BASE_DELAY_SECONDS = 1.0
REQUEST_RETRY_MAX_DELAY_SECONDS = 8.0
CONCURRENCY_BACKOFF_BASE_DELAY_SECONDS = 1.5
CONCURRENCY_BACKOFF_MAX_DELAY_SECONDS = 12.0
AUTH_ERROR_HINTS = (
    "authentication fails",
    "invalid api key",
    "api key is invalid",
    "incorrect api key",
    "unauthorized",
    "invalid authentication",
    "invalid token",
    "invalid_token",
)

TRANSLATION_INSTRUCTIONS = """
You are a professional subtitle translator.
Translate English transcript segments into coherent Simplified Chinese, sentence by sentence.

Rules:
1. Output Simplified Chinese only.
2. Translate every sentence in order and keep the full information from the source.
3. Write naturally in Chinese, but do not compress, summarize, omit, merge, or reorder content.
4. Preserve proper nouns, names, product names, dates, numbers, and titles when appropriate.
5. If a segment contains multiple sentences, translate all of them and keep their order.
6. Keep each translation aligned to its original segment index.
7. Return valid JSON only with this exact shape: {"translations":[{"index":0,"translated_text":"..."}]}.
""".strip()


class TranslationConfigurationError(TranslationError):
    """Raised when translation provider configuration is missing or invalid."""


class TranslationBackpressureError(TranslationProviderError):
    """Raised when the upstream provider signals overload or rate limiting."""


class TranslationAuthenticationError(TranslationProviderError):
    """Raised when upstream credentials are invalid and should fail fast."""


OpenAIConfigurationError = TranslationConfigurationError
OpenAITranslationError = TranslationProviderError


@dataclass(frozen=True)
class TranslationProviderConfig:
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    api_key: str
    base_url: str
    model: str
    extra_headers: dict[str, str] = field(default_factory=dict)


def _resolve_translation_config(
    raw_config: dict[str, object] | None,
) -> TranslationProviderConfig:
    config = raw_config or {}
    provider = (
        str(config.get("provider") or get_env_str("TRANSLATION_PROVIDER") or "openai")
        .strip()
        .lower()
    )

    if provider not in SUPPORTED_TRANSLATION_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_TRANSLATION_PROVIDERS))
        raise TranslationConfigurationError(
            f"Unsupported translation provider '{provider}'. Supported providers: {supported}."
        )

    env_prefix = provider_env_prefix(provider)
    extra_headers = coerce_provider_headers(config.get("extra_headers"))

    api_key = str(
        config.get("api_key") or get_env_str(f"{env_prefix}_API_KEY") or ""
    ).strip()
    requires_api_key = provider in {"openai", "deepseek"}
    if requires_api_key and not api_key:
        raise TranslationConfigurationError(
            f"{env_prefix}_API_KEY is not set. Add it to your environment, .env file, or request settings."
        )

    default_base_url = provider_default_base_url(provider)
    base_url = str(
        config.get("base_url")
        or get_env_str(f"{env_prefix}_BASE_URL")
        or default_base_url
    ).strip()
    try:
        base_url = validate_provider_base_url(provider, base_url)
    except ValueError as error:
        raise TranslationConfigurationError(str(error)) from error

    default_model = provider_default_model(provider)
    model = str(
        config.get("model")
        or get_env_str(f"{env_prefix}_TRANSLATION_MODEL")
        or default_model
    ).strip()

    if not model and provider in {"lmstudio", "ollama"}:
        model = _discover_openai_compatible_model(
            base_url=base_url,
            api_key=api_key,
            extra_headers=extra_headers,
            provider=provider,
        )

    if not model:
        raise TranslationConfigurationError(
            f"{env_prefix}_TRANSLATION_MODEL is not set and no model could be discovered for provider '{provider}'."
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

    return TranslationProviderConfig(
        provider=typed_provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        extra_headers=extra_headers,
    )


def _translate_chunk_once(
    *,
    config: TranslationProviderConfig,
    chunk: list[TranslationChunkItem],
    attempt: int,
    context_before: list[TranslationChunkItem] | None = None,
    target_indices: set[int] | None = None,
) -> dict[int, str]:
    if config.provider == "openai":
        return _translate_with_openai(
            config=config,
            chunk=chunk,
            attempt=attempt,
            context_before=context_before,
            target_indices=target_indices,
        )
    if config.provider == "deepseek":
        return _translate_with_deepseek(
            config=config,
            chunk=chunk,
            attempt=attempt,
            context_before=context_before,
            target_indices=target_indices,
        )
    if config.provider == "ollama":
        return _translate_with_ollama(
            config=config,
            chunk=chunk,
            attempt=attempt,
            context_before=context_before,
            target_indices=target_indices,
        )
    return _translate_with_local_openai_compatible(
        config=config,
        chunk=chunk,
        attempt=attempt,
        context_before=context_before,
        target_indices=target_indices,
    )


def _translate_with_openai(
    config: TranslationProviderConfig,
    chunk: list[TranslationChunkItem],
    attempt: int,
    context_before: list[TranslationChunkItem] | None = None,
    target_indices: set[int] | None = None,
) -> dict[int, str]:
    payload = {
        "model": config.model,
        "instructions": TRANSLATION_INSTRUCTIONS,
        "input": [
            {
                "role": "user",
                "content": _build_translation_prompt(
                    chunk=chunk,
                    attempt=attempt,
                    context_before=context_before,
                    target_indices=target_indices,
                ),
            }
        ],
        "max_output_tokens": _translation_output_token_budget(chunk),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "segment_translation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "translations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "index": {"type": "integer"},
                                    "translated_text": {
                                        "type": "string",
                                        "description": "The Simplified Chinese translation for this segment.",
                                    },
                                },
                                "required": ["index", "translated_text"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["translations"],
                    "additionalProperties": False,
                },
            }
        },
    }

    response = _post_json(
        url=_build_endpoint_url(config.base_url, "/responses"),
        headers=_build_headers(config),
        payload=payload,
        timeout=120.0,
        provider=config.provider,
        index=chunk[0].index,
    )

    try:
        body = response.json()
    except ValueError as error:
        raise TranslationProviderError(
            f"OpenAI returned invalid translation JSON for segment {chunk[0].index}."
        ) from error

    return _extract_openai_translated_items(body, chunk)


def _translate_with_deepseek(
    config: TranslationProviderConfig,
    chunk: list[TranslationChunkItem],
    attempt: int,
    context_before: list[TranslationChunkItem] | None = None,
    target_indices: set[int] | None = None,
) -> dict[int, str]:
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": TRANSLATION_INSTRUCTIONS,
            },
            {
                "role": "user",
                "content": _build_translation_prompt(
                    chunk=chunk,
                    attempt=attempt,
                    context_before=context_before,
                    target_indices=target_indices,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": _translation_output_token_budget(chunk),
        "temperature": 0,
        "stream": False,
    }

    response = _post_json(
        url=_build_endpoint_url(config.base_url, "/chat/completions"),
        headers=_build_headers(config),
        payload=payload,
        timeout=120.0,
        provider=config.provider,
        index=chunk[0].index,
    )

    try:
        body = response.json()
    except ValueError as error:
        raise TranslationProviderError(
            f"DeepSeek returned invalid translation JSON for segment {chunk[0].index}."
        ) from error

    return _extract_deepseek_translated_items(body, chunk)


def _translate_with_local_openai_compatible(
    config: TranslationProviderConfig,
    chunk: list[TranslationChunkItem],
    attempt: int,
    context_before: list[TranslationChunkItem] | None = None,
    target_indices: set[int] | None = None,
) -> dict[int, str]:
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": TRANSLATION_INSTRUCTIONS,
            },
            {
                "role": "user",
                "content": _build_translation_prompt(
                    chunk=chunk,
                    attempt=attempt,
                    context_before=context_before,
                    target_indices=target_indices,
                ),
            },
        ],
        "max_tokens": max(
            700 if config.provider == "lmstudio" else 0,
            _translation_output_token_budget(chunk),
        ),
        "temperature": 0,
        "stream": False,
    }

    response = _post_json(
        url=_build_endpoint_url(config.base_url, "/chat/completions"),
        headers=_build_headers(config),
        payload=payload,
        timeout=120.0,
        provider=config.provider,
        index=chunk[0].index,
    )

    try:
        body = response.json()
    except ValueError as error:
        raise TranslationProviderError(
            f"{config.provider} returned invalid translation JSON for segment {chunk[0].index}."
        ) from error

    return _extract_local_translated_items(body, provider=config.provider, chunk=chunk)


def _translate_with_ollama(
    config: TranslationProviderConfig,
    chunk: list[TranslationChunkItem],
    attempt: int,
    context_before: list[TranslationChunkItem] | None = None,
    target_indices: set[int] | None = None,
) -> dict[int, str]:
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": TRANSLATION_INSTRUCTIONS,
            },
            {
                "role": "user",
                "content": _build_translation_prompt(
                    chunk=chunk,
                    attempt=attempt,
                    context_before=context_before,
                    target_indices=target_indices,
                ),
            },
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
        },
    }

    response = _post_json(
        url=_build_endpoint_url(
            _normalize_ollama_base_url(config.base_url), "/api/chat"
        ),
        headers=_build_headers(config),
        payload=payload,
        timeout=120.0,
        provider=config.provider,
        index=chunk[0].index,
    )

    try:
        body = response.json()
    except ValueError as error:
        raise TranslationProviderError(
            f"{config.provider} returned invalid translation JSON for segment {chunk[0].index}."
        ) from error

    return _extract_ollama_translated_items(body, chunk)


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout: float,
    provider: str,
    index: int,
) -> httpx.Response:
    last_error_message = ""
    saw_backpressure = False

    for attempt in range(1, MAX_TRANSLATION_REQUEST_ATTEMPTS + 1):
        try:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except httpx.HTTPError as error:
            last_error_message = (
                f"{provider} translation request failed for segment {index}: {error}"
            )
            saw_backpressure = True
            if attempt < MAX_TRANSLATION_REQUEST_ATTEMPTS:
                time.sleep(_request_retry_delay(attempt))
                continue
            raise TranslationBackpressureError(last_error_message) from error

        if response.status_code < 400:
            return response

        message = _extract_provider_error_message(response)
        last_error_message = message
        if response.status_code == 401 or _is_authentication_error_message(message):
            raise TranslationAuthenticationError(message)
        if (
            response.status_code in RETRYABLE_STATUS_CODES
            and attempt < MAX_TRANSLATION_REQUEST_ATTEMPTS
        ):
            saw_backpressure = True
            time.sleep(_request_retry_delay(attempt, response))
            continue
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise TranslationBackpressureError(message)

        raise TranslationProviderError(message)

    if saw_backpressure:
        raise TranslationBackpressureError(
            last_error_message or "Translation request was rate limited."
        )
    raise TranslationProviderError(last_error_message or "Translation request failed.")


def _build_headers(config: TranslationProviderConfig) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
    }
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    headers.update(config.extra_headers)
    return headers


def _is_authentication_error_message(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(hint in lowered for hint in AUTH_ERROR_HINTS)


def _build_endpoint_url(base_url: str, suffix: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith(suffix):
        return normalized
    return f"{normalized}{suffix}"


def _build_translation_prompt(
    *,
    chunk: list[TranslationChunkItem],
    attempt: int,
    context_before: list[TranslationChunkItem] | None = None,
    target_indices: set[int] | None = None,
) -> str:
    retry_note = ""
    if attempt > 1:
        retry_note = (
            "\nPrevious attempt returned unusable output. "
            "Return one non-empty translation item per input index in valid JSON."
        )

    context_lines = [
        f"context_index: {item.index}\ncontext_text: {item.source_text}"
        for item in (context_before or [])
    ]
    lines = [
        f"index: {item.index}\nstart: {item.start}\nend: {item.end}\nsource_text: {item.source_text}"
        for item in chunk
    ]
    target_note = ""
    if target_indices:
        ordered_targets = ", ".join(str(index) for index in sorted(target_indices))
        target_note = (
            f"Only return translations for these target indices: {ordered_targets}.\n"
            "Do not echo context items in the JSON output.\n"
        )
    context_block = ""
    if context_lines:
        context_block = "context:\n\n" + "\n\n".join(context_lines) + "\n\n"

    return (
        "Return JSON only.\n"
        "Translate these transcript segments to Simplified Chinese.\n"
        "Translate every sentence in order.\n"
        "Write coherent Chinese, but do not compress or summarize the source.\n"
        "Return a JSON object with a `translations` array.\n"
        "Each array item must keep the same `index` and include `translated_text`.\n"
        "Do not merge, omit, summarize, or reorder segments.\n"
        + target_note
        + context_block
        + "segments:\n\n"
        + "\n\n".join(lines)
        + retry_note
    )


def _request_retry_delay(
    attempt: int,
    response: httpx.Response | None = None,
) -> float:
    retry_after_header = ""
    if response is not None:
        retry_after_header = str(response.headers.get("Retry-After") or "").strip()
    try:
        retry_after_seconds = float(retry_after_header)
    except ValueError:
        retry_after_seconds = 0.0

    exponential_delay = min(
        REQUEST_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
        REQUEST_RETRY_MAX_DELAY_SECONDS,
    )
    return max(exponential_delay, retry_after_seconds, 0.0)


def _concurrency_backoff_delay(round_number: int) -> float:
    return min(
        CONCURRENCY_BACKOFF_BASE_DELAY_SECONDS * (2 ** (round_number - 1)),
        CONCURRENCY_BACKOFF_MAX_DELAY_SECONDS,
    )


def _extract_openai_translated_items(
    payload: object,
    chunk: list[TranslationChunkItem],
) -> dict[int, str]:
    if not isinstance(payload, dict):
        raise RetryableTranslationContentError(
            "OpenAI returned an unexpected translation payload."
        )

    raw_output_text = payload.get("output_text")
    if isinstance(raw_output_text, str) and raw_output_text.strip():
        return _parse_translated_items_json(raw_output_text, chunk)

    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") != "output_text":
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return _parse_translated_items_json(text, chunk)

    raise RetryableTranslationContentError(
        "OpenAI response did not include translations output."
    )


def _extract_deepseek_translated_items(
    payload: object,
    chunk: list[TranslationChunkItem],
) -> dict[int, str]:
    if not isinstance(payload, dict):
        raise RetryableTranslationContentError(
            "DeepSeek returned an unexpected translation payload."
        )

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RetryableTranslationContentError(
            "DeepSeek response did not include translation choices."
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RetryableTranslationContentError(
            "DeepSeek response choice had an unexpected format."
        )

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise RetryableTranslationContentError(
            "DeepSeek response did not include a message payload."
        )

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RetryableTranslationContentError(
            "DeepSeek response did not include translated content."
        )

    return _parse_translated_items_json(content, chunk)


def _extract_local_translated_items(
    payload: object,
    provider: str,
    chunk: list[TranslationChunkItem],
) -> dict[int, str]:
    if not isinstance(payload, dict):
        raise RetryableTranslationContentError(
            f"{provider} returned an unexpected translation payload."
        )

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RetryableTranslationContentError(
            f"{provider} response did not include translation choices."
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RetryableTranslationContentError(
            f"{provider} response choice had an unexpected format."
        )

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise RetryableTranslationContentError(
            f"{provider} response did not include a message payload."
        )

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RetryableTranslationContentError(
            f"{provider} response did not include translated content."
        )

    cleaned_content = _clean_model_output_text(content)
    if not cleaned_content:
        raise RetryableTranslationContentError(
            f"{provider} response did not include usable translated content."
        )

    parsed_json = _try_parse_translation_items_json(cleaned_content, chunk)
    if parsed_json is not None:
        return parsed_json
    raise RetryableTranslationContentError(
        f"{provider} response did not include structured translation items."
    )


def _extract_ollama_translated_items(
    payload: object,
    chunk: list[TranslationChunkItem],
) -> dict[int, str]:
    if not isinstance(payload, dict):
        raise RetryableTranslationContentError(
            "ollama returned an unexpected translation payload."
        )

    message = payload.get("message")
    if not isinstance(message, dict):
        raise RetryableTranslationContentError(
            "ollama response did not include a message payload."
        )

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RetryableTranslationContentError(
            "ollama response did not include translated content."
        )

    cleaned_content = _clean_model_output_text(content)
    if not cleaned_content:
        raise RetryableTranslationContentError(
            "ollama response did not include usable translated content."
        )

    parsed_json = _try_parse_translation_items_json(cleaned_content, chunk)
    if parsed_json is not None:
        return parsed_json
    raise RetryableTranslationContentError(
        "ollama response did not include structured translation items."
    )


def _discover_openai_compatible_model(
    *,
    base_url: str,
    api_key: str,
    extra_headers: dict[str, str],
    provider: str,
) -> str:
    if provider == "ollama":
        return _discover_ollama_model(
            base_url=base_url,
            api_key=api_key,
            extra_headers=extra_headers,
        )

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(extra_headers)

    models_url = _build_endpoint_url(base_url, "/models")
    try:
        response = httpx.get(models_url, headers=headers, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise TranslationConfigurationError(
            f"Could not discover a model from {provider} at {models_url}: {error}"
        ) from error

    try:
        payload = response.json()
    except ValueError as error:
        raise TranslationConfigurationError(
            f"{provider} model discovery returned invalid JSON."
        ) from error

    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id") or "").strip()
                if model_id:
                    return model_id

        models = payload.get("models")
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("model") or item.get("name") or "").strip()
                if model_id:
                    return model_id

    raise TranslationConfigurationError(
        f"No usable models were discovered for local provider '{provider}'."
    )


def discover_provider_models(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    extra_headers: dict[str, str],
) -> list[str]:
    fallback_models = _provider_fallback_models(provider)
    discovered_models: list[str] = []
    try:
        base_url = validate_provider_base_url(
            provider,
            base_url or provider_default_base_url(provider),
        )
    except ValueError as error:
        raise TranslationConfigurationError(str(error)) from error

    def add_model(candidate: object) -> None:
        model_id = str(candidate).strip()
        if model_id and model_id not in discovered_models:
            discovered_models.append(model_id)

    if provider == "ollama":
        models_url = _build_endpoint_url(
            _normalize_ollama_base_url(base_url),
            "/api/tags",
        )
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers.update(extra_headers)

        try:
            response = httpx.get(models_url, headers=headers, timeout=30.0)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return fallback_models

        if isinstance(payload, dict):
            models = payload.get("models")
            if isinstance(models, list):
                for item in models:
                    if not isinstance(item, dict):
                        continue
                    add_model(item.get("model") or item.get("name"))

        return discovered_models or fallback_models

    models_url = _build_endpoint_url(
        base_url,
        "/models",
    )
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(extra_headers)

    try:
        response = httpx.get(models_url, headers=headers, timeout=30.0)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return fallback_models

    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                add_model(item.get("id"))

        models = payload.get("models")
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict):
                    continue
                add_model(item.get("model") or item.get("name"))

    return discovered_models or fallback_models


def _provider_fallback_models(provider: str) -> list[str]:
    if provider == "openai":
        return [
            OPENAI_DEFAULT_MODEL,
            "gpt-4.1",
            "gpt-4o-mini",
            "gpt-4o",
        ]
    if provider == "deepseek":
        return [
            DEEPSEEK_DEFAULT_MODEL,
            "deepseek-reasoner",
        ]
    return []


def _discover_ollama_model(
    *,
    base_url: str,
    api_key: str,
    extra_headers: dict[str, str],
) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(extra_headers)

    models_url = _build_endpoint_url(_normalize_ollama_base_url(base_url), "/api/tags")
    try:
        response = httpx.get(models_url, headers=headers, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise TranslationConfigurationError(
            f"Could not discover a model from ollama at {models_url}: {error}"
        ) from error

    try:
        payload = response.json()
    except ValueError as error:
        raise TranslationConfigurationError(
            "ollama model discovery returned invalid JSON."
        ) from error

    if isinstance(payload, dict):
        models = payload.get("models")
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("model") or item.get("name") or "").strip()
                if model_id:
                    return model_id

    raise TranslationConfigurationError(
        "No usable models were discovered for local provider 'ollama'."
    )


def _normalize_ollama_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3]
    return normalized


def _extract_provider_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    return f"Translation provider failed with status {response.status_code}."
