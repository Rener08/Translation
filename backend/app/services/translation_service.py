import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.services.persistent_cache_service import (
    build_cache_key,
    load_json_cache,
    store_json_cache,
)
from app.services.translation_chunking import (
    _build_translation_chunks,
    _chunk_translations_are_complete,
    _resolve_translation_chunk_concurrency,
    _segment_to_chunk_item,
    _translation_output_token_budget,
)
from app.services.translation_provider_client import (
    MAX_TRANSLATION_CONTENT_ATTEMPTS,
    RETRYABLE_STATUS_CODES,
    TRANSLATION_INSTRUCTIONS,
    TranslationAuthenticationError,
    TranslationBackpressureError,
    TranslationConfigurationError,
    TranslationProviderConfig,
    _concurrency_backoff_delay,
    _is_authentication_error_message,
    _resolve_translation_config,
    _translate_chunk_once,
    discover_provider_models,
)
from app.services.translation_text_cleanup import (
    _missing_chunk_indices,
    clean_translated_chinese_text,
)
from app.services.translation_types import (
    NonJsonTranslationContentError,
    PartialTranslationsContentError,
    RetryableTranslationContentError,
    TranslationChunkItem,
    TranslationProviderError,
)

# Re-export public API previously accessible from this module
__all__ = [
    "discover_provider_models",
    "TranslationConfigurationError",
    "TranslationBackpressureError",
    "TranslationAuthenticationError",
    "TranslationProviderConfig",
    "TranslationSegment",
    "translate_segments_to_chinese",
    "clean_translated_chinese_text",
]

logger = logging.getLogger(__name__)

TRANSLATION_CACHE_VERSION = 1


@dataclass(frozen=True)
class TranslationSegment:
    index: int
    start: float
    end: float
    source_text: str
    translated_text: str


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
