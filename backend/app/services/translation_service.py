import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import cast
from typing import Literal

import httpx

from app.config import ROOT_DIR, get_env_str
from app.services.persistent_cache_service import (
    build_cache_key,
    load_json_cache,
    store_json_cache,
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
THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
TARGET_TRANSLATION_CHUNK_WORDS = 500
MAX_TRANSLATION_CHUNK_WORDS = 800
MAX_TRANSLATION_SEGMENTS_PER_CHUNK = 40
DEFAULT_TRANSLATION_CHUNK_CONCURRENCY = 5
MAX_TRANSLATION_CHUNK_CONCURRENCY = 10
TRANSLATION_CACHE_VERSION = 1
SENTENCE_END_PATTERN = re.compile(r"[.!?。！？…][\"')\]]*$")
CHINESE_STAGE_DIRECTION_PATTERN = re.compile(
    r"(?:\[|【|\()\s*(?:音乐|音樂|掌声|掌聲|笑声|笑聲|鼓掌|片头音乐|片尾音乐|背景音乐|bgm|music|applause|laughter)\s*(?:\]|】|\))",
    re.IGNORECASE,
)
CHINESE_AD_LINE_PATTERN = re.compile(
    r"^(?:欢迎订阅|歡迎訂閱|记得订阅|記得訂閱|点赞|點贊|关注|關注|打开小铃铛|打開小鈴鐺|感谢观看|感謝觀看|本期视频由|本期影片由|下载.*app|下載.*app|赞助|贊助|推广|推廣|广告|廣告).*$"
)
CHINESE_FILLER_PATTERNS = [
    re.compile(
        r"^(?:嗯+|呃+|啊+|唉+|哎+|欸+|诶+|这个|那个|就是|然后|所以|你知道吗?|大家知道吗?|好吧|那麼|那么|其实)$"
    ),
    re.compile(r"^(?:嗯+|呃+|啊+|唉+|哎+|欸+|诶+)[，、。,.!！?？]*$"),
]
CHINESE_PREFIX_FILLER_PATTERN = re.compile(
    r"^(?:嗯+|呃+|啊+|唉+|哎+|欸+|诶+|这个|那个|就是|然后|所以|其实|那麼|那么)[，、：: ]*"
)
SPEAKER_LABEL_LINE_PATTERN = re.compile(r"^发言人\s*\d+\s*$")
PUNCTUATION_ONLY_LINE_PATTERN = re.compile(r"^[\s，。、！？；：,.!?…>＞]+$")
REPEATED_FILLER_TOKEN_PATTERN = re.compile(
    r"(?P<token>就|我|你|他|她|它|那|这|那个|这个|然后|就是|所以|其实|对吧|真的|呃|嗯|啊|哎|欸|诶)(?:[，、\s]+(?P=token)){1,}"
)
INLINE_PAUSE_TOKEN_PATTERN = re.compile(
    r"(?:(?<=^)|(?<=[，、。！？；：,.!?\s]))(?:呃+|嗯+|啊+|哎+|欸+|诶+)(?:[~～…，、。！？；：,.!?\s]*)"
)
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


class TranslationError(Exception):
    """Base error for translation failures."""


class TranslationConfigurationError(TranslationError):
    """Raised when translation provider configuration is missing or invalid."""


class TranslationProviderError(TranslationError):
    """Raised when the upstream translation provider fails."""


class RetryableTranslationContentError(TranslationProviderError):
    """Raised when the provider returns retryable but unusable content."""


class NonJsonTranslationContentError(RetryableTranslationContentError):
    """Raised when the provider returns non-JSON translation content."""


class PartialTranslationsContentError(RetryableTranslationContentError):
    """Raised when the provider returns a partial structured translation payload."""

    def __init__(
        self,
        message: str,
        *,
        partial_translations: dict[int, str],
        missing_indices: list[int],
    ) -> None:
        super().__init__(message)
        self.partial_translations = partial_translations
        self.missing_indices = missing_indices


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


@dataclass(frozen=True)
class TranslationSegment:
    index: int
    start: float
    end: float
    source_text: str
    translated_text: str


@dataclass(frozen=True)
class TranslationChunkItem:
    index: int
    start: float
    end: float
    source_text: str


def translate_segments_to_chinese(
    segments: list[dict[str, object]],
    translation_config: dict[str, object] | None = None,
) -> list[TranslationSegment]:
    config = _resolve_translation_config(translation_config)
    cached_result = _load_cached_translation_result(segments, config)
    if cached_result is not None:
        return cached_result
    chunk_items = [_segment_to_chunk_item(segment) for segment in segments]
    chunks = _build_translation_chunks(chunk_items)
    if not chunks:
        return []

    chunk_concurrency = _resolve_translation_chunk_concurrency(
        raw_config=translation_config,
        chunk_count=len(chunks),
    )
    if chunk_concurrency == 1:
        translated = _translate_chunks_serially(chunks, config)
        _store_cached_translation_result(segments, config, translated)
        return translated

    try:
        translated_chunks = _translate_chunks_with_adaptive_concurrency(
            chunks=chunks,
            config=config,
            initial_concurrency=chunk_concurrency,
        )
    except TranslationProviderError as error:
        if isinstance(error, TranslationAuthenticationError):
            raise
        logger.warning(
            "Concurrent translation failed for provider %s; retrying serially: %s",
            config.provider,
            error,
        )
        translated = _translate_chunks_serially(chunks, config)
        _store_cached_translation_result(segments, config, translated)
        return translated

    translated = [translation for chunk in translated_chunks for translation in chunk]
    _store_cached_translation_result(segments, config, translated)
    return translated


def _translate_chunks_with_adaptive_concurrency(
    *,
    chunks: list[list[TranslationChunkItem]],
    config: TranslationProviderConfig,
    initial_concurrency: int,
) -> list[list[TranslationSegment]]:
    current_concurrency = max(1, min(initial_concurrency, len(chunks)))
    backoff_round = 1

    while current_concurrency > 1:
        try:
            with ThreadPoolExecutor(max_workers=current_concurrency) as executor:
                return list(
                    executor.map(
                        lambda chunk: _translate_chunk_with_fallbacks(chunk, config),
                        chunks,
                    )
                )
        except TranslationBackpressureError as error:
            next_concurrency = max(1, (current_concurrency + 1) // 2)
            logger.warning(
                "Provider %s reported backpressure at concurrency %s; backing off to %s: %s",
                config.provider,
                current_concurrency,
                next_concurrency,
                error,
            )
            if next_concurrency == current_concurrency:
                break
            time.sleep(_concurrency_backoff_delay(backoff_round))
            current_concurrency = next_concurrency
            backoff_round += 1

    return [_translate_chunk_with_fallbacks(chunk, config) for chunk in chunks]


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

    env_prefix = _provider_env_prefix(provider)
    extra_headers = _coerce_headers(config.get("extra_headers"))

    api_key = str(
        config.get("api_key") or get_env_str(f"{env_prefix}_API_KEY") or ""
    ).strip()
    requires_api_key = provider in {"openai", "deepseek"}
    if requires_api_key and not api_key:
        raise TranslationConfigurationError(
            f"{env_prefix}_API_KEY is not set. Add it to your environment, .env file, or request settings."
        )

    default_base_url = _provider_default_base_url(provider)
    base_url = str(
        config.get("base_url")
        or get_env_str(f"{env_prefix}_BASE_URL")
        or default_base_url
    ).strip()

    default_model = _provider_default_model(provider)
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


def _translate_chunk(
    chunk: list[TranslationChunkItem],
    config: TranslationProviderConfig,
) -> list[TranslationSegment]:
    if not chunk:
        return []

    translations_by_index: dict[int, str] = {}
    last_error: RetryableTranslationContentError | None = None

    for attempt in range(1, MAX_TRANSLATION_CONTENT_ATTEMPTS + 1):
        try:
            translations_by_index = _translate_chunk_once(
                config=config,
                chunk=chunk,
                attempt=attempt,
            )
        except PartialTranslationsContentError as error:
            last_error = error
            translations_by_index = dict(error.partial_translations)
            if translations_by_index:
                try:
                    translations_by_index.update(
                        _retry_missing_chunk_items(
                            chunk=chunk,
                            config=config,
                            partial_translations=translations_by_index,
                            attempt=attempt,
                        )
                    )
                except RetryableTranslationContentError as retry_error:
                    last_error = retry_error
                else:
                    if _chunk_translations_are_complete(chunk, translations_by_index):
                        break
                    last_error = PartialTranslationsContentError(
                        f"{config.provider} returned incomplete translations for chunk starting at segment {chunk[0].index}.",
                        partial_translations=translations_by_index,
                        missing_indices=_missing_chunk_indices(
                            chunk, translations_by_index
                        ),
                    )
            if attempt < MAX_TRANSLATION_CONTENT_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            raise TranslationProviderError(str(last_error)) from error
        except NonJsonTranslationContentError as error:
            last_error = error
            if attempt < MAX_TRANSLATION_CONTENT_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            raise TranslationProviderError(str(error)) from error
        except RetryableTranslationContentError as error:
            last_error = error
            if attempt < MAX_TRANSLATION_CONTENT_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            raise TranslationProviderError(str(error)) from error

        if _chunk_translations_are_complete(chunk, translations_by_index):
            break

        last_error = RetryableTranslationContentError(
            f"{config.provider} returned incomplete translations for chunk starting at segment {chunk[0].index}."
        )
        if attempt < MAX_TRANSLATION_CONTENT_ATTEMPTS:
            time.sleep(0.5 * attempt)
            continue
        raise TranslationProviderError(str(last_error))

    if not translations_by_index and last_error is not None:
        raise TranslationProviderError(str(last_error))

    return [
        TranslationSegment(
            index=item.index,
            start=item.start,
            end=item.end,
            source_text=item.source_text,
            translated_text=translations_by_index[item.index],
        )
        for item in chunk
    ]


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


def _retry_missing_chunk_items(
    *,
    chunk: list[TranslationChunkItem],
    config: TranslationProviderConfig,
    partial_translations: dict[int, str],
    attempt: int,
) -> dict[int, str]:
    missing_indices = _missing_chunk_indices(chunk, partial_translations)
    if not missing_indices:
        return {}

    missing_items = [item for item in chunk if item.index in set(missing_indices)]
    leading_context = _leading_context_items(chunk, first_missing_index=missing_indices[0])
    return _translate_chunk_once(
        config=config,
        chunk=missing_items,
        attempt=max(attempt + 1, 2),
        context_before=leading_context,
        target_indices=set(missing_indices),
    )


def _missing_chunk_indices(
    chunk: list[TranslationChunkItem],
    translations_by_index: dict[int, str],
) -> list[int]:
    return [
        item.index
        for item in chunk
        if not str(translations_by_index.get(item.index) or "").strip()
    ]


def _leading_context_items(
    chunk: list[TranslationChunkItem],
    *,
    first_missing_index: int,
    max_items: int = 2,
) -> list[TranslationChunkItem]:
    missing_position = next(
        (position for position, item in enumerate(chunk) if item.index == first_missing_index),
        None,
    )
    if missing_position is None or missing_position <= 0:
        return []
    start = max(0, missing_position - max_items)
    return chunk[start:missing_position]


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


def _translation_cache_key(
    segments: list[dict[str, object]],
    config: TranslationProviderConfig,
) -> str:
    normalized_segments = [
        {
            "index": int(str(segment.get("index") or 0)),
            "start": float(str(segment.get("start") or 0)),
            "end": float(str(segment.get("end") or 0)),
            "text": str(segment.get("text") or "").strip(),
        }
        for segment in segments
    ]
    return build_cache_key(
        {
            "version": TRANSLATION_CACHE_VERSION,
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "extra_headers": config.extra_headers,
            "instructions": TRANSLATION_INSTRUCTIONS,
            "segments": normalized_segments,
        }
    )


def _load_cached_translation_result(
    segments: list[dict[str, object]],
    config: TranslationProviderConfig,
) -> list[TranslationSegment] | None:
    payload = load_json_cache("translation", _translation_cache_key(segments, config))
    if not isinstance(payload, list):
        return None

    translations: list[TranslationSegment] = []
    for item in payload:
        if not isinstance(item, dict):
            return None
        translations.append(
            TranslationSegment(
                index=int(str(item.get("index") or 0)),
                start=float(str(item.get("start") or 0)),
                end=float(str(item.get("end") or 0)),
                source_text=str(item.get("source_text") or "").strip(),
                translated_text=str(item.get("translated_text") or "").strip(),
            )
        )

    if not translations:
        return None
    return translations


def _store_cached_translation_result(
    segments: list[dict[str, object]],
    config: TranslationProviderConfig,
    translations: list[TranslationSegment],
) -> None:
    store_json_cache(
        "translation",
        _translation_cache_key(segments, config),
        [
            {
                "index": item.index,
                "start": item.start,
                "end": item.end,
                "source_text": item.source_text,
                "translated_text": item.translated_text,
            }
            for item in translations
        ],
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


def _parse_translated_items_json(
    value: str,
    chunk: list[TranslationChunkItem],
) -> dict[int, str]:
    translated_items = _try_parse_translation_items_json(value, chunk)
    if translated_items is None:
        raise NonJsonTranslationContentError(
            "Translation provider returned non-JSON translation output."
        )
    missing_indices = _missing_chunk_indices(chunk, translated_items)
    if missing_indices:
        raise PartialTranslationsContentError(
            f"Translation provider returned incomplete translations for indices {', '.join(str(index) for index in missing_indices)}.",
            partial_translations=translated_items,
            missing_indices=missing_indices,
        )
    return translated_items


def _try_parse_translation_items_json(
    value: str,
    chunk: list[TranslationChunkItem],
) -> dict[int, str] | None:
    normalized = _clean_model_output_text(value)
    if not normalized:
        return None

    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        payload = None
        for extracted in reversed(_extract_json_object_candidates(normalized)):
            try:
                candidate_payload = json.loads(extracted)
            except json.JSONDecodeError:
                continue
            translated_items = _translation_items_from_payload(candidate_payload, chunk)
            if translated_items:
                return translated_items
        return None

    return _translation_items_from_payload(payload, chunk)


def _clean_model_output_text(value: str) -> str:
    normalized = THINK_BLOCK_PATTERN.sub("", value).strip()
    normalized = normalized.replace("</think>", "").strip()
    normalized = normalized.removeprefix("```json").removeprefix("```")
    normalized = normalized.removesuffix("```").strip()
    return normalized


def clean_translated_chinese_text(value: str) -> str:
    normalized = _clean_model_output_text(value)
    if not normalized:
        return ""

    normalized = CHINESE_STAGE_DIRECTION_PATTERN.sub("", normalized)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")

    cleaned_lines: list[str] = []
    last_line = ""
    for raw_line in normalized.split("\n"):
        line = _clean_chinese_line(raw_line)
        if not line:
            continue
        if line == last_line:
            continue
        cleaned_lines.append(line)
        last_line = line

    return "\n".join(cleaned_lines).strip()


def _clean_chinese_line(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""

    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"^[>＞]+\s*", "", normalized)
    if SPEAKER_LABEL_LINE_PATTERN.match(normalized):
        return ""
    normalized = re.sub(
        r"[（(]\s*(?:音乐|音樂|掌声|掌聲|笑声|笑聲|鼓掌|广告|廣告|赞助|贊助)\s*[)）]",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:音乐|音樂|掌声|掌聲|笑声|笑聲|鼓掌|背景音乐|片头音乐|片尾音乐)[:：]?",
        "",
        normalized,
    )
    normalized = CHINESE_PREFIX_FILLER_PATTERN.sub("", normalized)
    normalized = re.sub(
        r"(?:^|[，、。,.!?！？])(?:嗯+|呃+|啊+|唉+|哎+|欸+|诶+)(?=$|[，、。,.!?！？])",
        "",
        normalized,
    )
    normalized = _remove_inline_pause_tokens(normalized)
    normalized = re.sub(
        r"(?:^|[，、。,.!?！？])(?:这个|那个|就是|然后|所以)(?=[，、。,.!?！？])",
        "",
        normalized,
    )
    normalized = _collapse_repeated_filler_tokens(normalized)
    normalized = re.sub(r"[，、]{2,}", "，", normalized)
    normalized = re.sub(r"[。]{2,}", "。", normalized)
    normalized = re.sub(r"\s*([，。！？；：])\s*", r"\1", normalized)
    normalized = normalized.strip(" ，、；：")

    if not normalized:
        return ""
    if PUNCTUATION_ONLY_LINE_PATTERN.match(normalized):
        return ""
    if CHINESE_AD_LINE_PATTERN.match(normalized):
        return ""
    if any(pattern.match(normalized) for pattern in CHINESE_FILLER_PATTERNS):
        return ""

    return normalized.strip()


def _collapse_repeated_filler_tokens(value: str) -> str:
    collapsed = value
    while True:
        updated = REPEATED_FILLER_TOKEN_PATTERN.sub(
            lambda match: match.group("token"), collapsed
        )
        if updated == collapsed:
            return updated
        collapsed = updated


def _remove_inline_pause_tokens(value: str) -> str:
    cleaned = INLINE_PAUSE_TOKEN_PATTERN.sub("", value)
    cleaned = re.sub(r"([：:])\s*(?:[，、。！？；：,.!?…~～]+)", r"\1", cleaned)
    cleaned = re.sub(r"^[，、。！？；：,.!?…~～\s]+", "", cleaned)
    return cleaned


def _extract_json_object_candidates(value: str) -> list[str]:
    candidates: list[str] = []
    depth = 0
    start_index = -1

    for index, char in enumerate(value):
        if char == "{":
            if depth == 0:
                start_index = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start_index != -1:
                candidates.append(value[start_index : index + 1])
                start_index = -1

    return candidates


def _translation_items_from_payload(
    payload: object,
    chunk: list[TranslationChunkItem],
) -> dict[int, str] | None:
    if not isinstance(payload, dict):
        return None

    single_item_translation = _single_item_translation_from_payload(payload, chunk)
    if single_item_translation is not None:
        return single_item_translation

    translations = payload.get("translations")
    if not isinstance(translations, list) or not translations:
        return None

    expected_indices = {item.index for item in chunk}
    translated_items: dict[int, str] = {}
    for item in translations:
        if not isinstance(item, dict):
            continue

        index_value = item.get("index")
        translated_text = str(item.get("translated_text") or "").strip()
        if translated_text in {"", "...", "…"}:
            continue

        try:
            index = int(str(index_value).strip())
        except (TypeError, ValueError):
            continue

        if index not in expected_indices:
            continue

        translated_items[index] = translated_text

    return translated_items or None


def _single_item_translation_from_payload(
    payload: dict[str, object],
    chunk: list[TranslationChunkItem],
) -> dict[int, str] | None:
    if len(chunk) != 1:
        return None

    translated_text = str(
        payload.get("translated_text") or payload.get("translation") or ""
    ).strip()
    if translated_text in {"", "...", "…"}:
        return None

    return {chunk[0].index: translated_text}


def _segment_to_chunk_item(segment: dict[str, object]) -> TranslationChunkItem:
    index = _as_int(segment.get("index"))
    start = _as_float(segment.get("start"))
    end = _as_float(segment.get("end"))
    source_text = str(segment.get("text") or "").strip()

    if not source_text:
        raise TranslationProviderError(
            f"Segment {index} is missing source text and cannot be translated."
        )

    return TranslationChunkItem(
        index=index,
        start=start,
        end=end,
        source_text=source_text,
    )


def _build_translation_chunks(
    items: list[TranslationChunkItem],
) -> list[list[TranslationChunkItem]]:
    if not items:
        return []

    chunks: list[list[TranslationChunkItem]] = []
    current_chunk: list[TranslationChunkItem] = []
    current_word_count = 0

    for item in items:
        item_word_count = _word_count(item.source_text)
        exceeds_target = (
            current_chunk
            and current_word_count + item_word_count > TARGET_TRANSLATION_CHUNK_WORDS
        )
        exceeds_hard_limit = current_chunk and (
            current_word_count + item_word_count > MAX_TRANSLATION_CHUNK_WORDS
            or len(current_chunk) >= MAX_TRANSLATION_SEGMENTS_PER_CHUNK
        )

        if exceeds_hard_limit or (
            exceeds_target and _ends_sentence(current_chunk[-1].source_text)
        ):
            chunks.append(current_chunk)
            current_chunk = []
            current_word_count = 0

        current_chunk.append(item)
        current_word_count += item_word_count

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _chunk_translations_are_complete(
    chunk: list[TranslationChunkItem],
    translations_by_index: dict[int, str],
) -> bool:
    expected_indices = {item.index for item in chunk}
    if set(translations_by_index.keys()) != expected_indices:
        return False

    return all(translations_by_index[item.index].strip() for item in chunk)


def _word_count(value: str) -> int:
    return len(value.split())


def _ends_sentence(value: str) -> bool:
    return bool(SENTENCE_END_PATTERN.search(value.strip()))


def _translation_output_token_budget(chunk: list[TranslationChunkItem]) -> int:
    word_count = sum(_word_count(item.source_text) for item in chunk)
    estimated_tokens = 160 + (word_count * 3)
    return max(400, min(1200, estimated_tokens))


def _resolve_translation_chunk_concurrency(
    *,
    raw_config: dict[str, object] | None,
    chunk_count: int,
) -> int:
    if chunk_count <= 1:
        return 1

    configured_value = (
        (raw_config or {}).get("chunk_concurrency")
        or get_env_str("TRANSLATION_CHUNK_CONCURRENCY")
        or DEFAULT_TRANSLATION_CHUNK_CONCURRENCY
    )
    parsed = _as_int(configured_value)
    if parsed < 1:
        parsed = 1
    if parsed > MAX_TRANSLATION_CHUNK_CONCURRENCY:
        parsed = MAX_TRANSLATION_CHUNK_CONCURRENCY
    return min(parsed, chunk_count)


def _translate_chunks_serially(
    chunks: list[list[TranslationChunkItem]],
    config: TranslationProviderConfig,
) -> list[TranslationSegment]:
    return [
        translation
        for chunk in chunks
        for translation in _translate_chunk_with_fallbacks(chunk, config)
    ]


def _translate_chunk_with_fallbacks(
    chunk: list[TranslationChunkItem],
    config: TranslationProviderConfig,
) -> list[TranslationSegment]:
    try:
        return _translate_chunk(chunk, config)
    except TranslationBackpressureError:
        raise
    except TranslationProviderError as error:
        if isinstance(error, TranslationAuthenticationError) or _is_authentication_error_message(str(error)):
            raise
        if len(chunk) <= 1:
            raise

        midpoint = len(chunk) // 2
        left_chunk = chunk[:midpoint]
        right_chunk = chunk[midpoint:]
        if not left_chunk or not right_chunk:
            raise

        logger.warning(
            "Translation chunk starting at segment %s failed for provider %s; retrying as %s + %s smaller chunks: %s",
            chunk[0].index,
            config.provider,
            len(left_chunk),
            len(right_chunk),
            error,
        )
        return _translate_chunk_with_fallbacks(
            left_chunk, config
        ) + _translate_chunk_with_fallbacks(
            right_chunk,
            config,
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

    def add_model(candidate: object) -> None:
        model_id = str(candidate).strip()
        if model_id and model_id not in discovered_models:
            discovered_models.append(model_id)

    if provider == "ollama":
        models_url = _build_endpoint_url(
            _normalize_ollama_base_url(base_url or _provider_default_base_url(provider)),
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
        base_url or _provider_default_base_url(provider),
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


def _provider_env_prefix(provider: str) -> str:
    if provider == "openai":
        return "OPENAI"
    if provider == "deepseek":
        return "DEEPSEEK"
    if provider == "lmstudio":
        return "LMSTUDIO"
    return "OLLAMA"


def _provider_default_base_url(provider: str) -> str:
    if provider == "openai":
        return OPENAI_DEFAULT_BASE_URL
    if provider == "deepseek":
        return DEEPSEEK_DEFAULT_BASE_URL
    if provider == "lmstudio":
        return LMSTUDIO_DEFAULT_BASE_URL
    return OLLAMA_DEFAULT_BASE_URL


def _provider_default_model(provider: str) -> str:
    if provider == "openai":
        return OPENAI_DEFAULT_MODEL
    if provider == "deepseek":
        return DEEPSEEK_DEFAULT_MODEL
    return ""


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


def _coerce_headers(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    headers: dict[str, str] = {}
    for key, header_value in value.items():
        normalized_key = str(key).strip()
        normalized_value = str(header_value).strip()
        if not normalized_key or not normalized_value:
            continue
        headers[normalized_key] = normalized_value
    return headers


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0
        try:
            return int(stripped)
        except ValueError:
            return 0
    text_value = str(value).strip()
    if not text_value:
        return 0
    try:
        return int(text_value)
    except ValueError:
        return 0


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0.0
        try:
            return float(stripped)
        except ValueError:
            return 0.0
    text_value = str(value).strip()
    if not text_value:
        return 0.0
    try:
        return float(text_value)
    except ValueError:
        return 0.0
