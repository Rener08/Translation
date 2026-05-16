from app.config import get_env_str
from app.services.translation_text_cleanup import SENTENCE_END_PATTERN
from app.services.translation_types import TranslationChunkItem

TARGET_TRANSLATION_CHUNK_WORDS = 500
MAX_TRANSLATION_CHUNK_WORDS = 800
MAX_TRANSLATION_SEGMENTS_PER_CHUNK = 40
DEFAULT_TRANSLATION_CHUNK_CONCURRENCY = 5
MAX_TRANSLATION_CHUNK_CONCURRENCY = 10


def _word_count(value: str) -> int:
    return len(value.split())


def _ends_sentence(value: str) -> bool:
    return bool(SENTENCE_END_PATTERN.search(value.strip()))


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


def _segment_to_chunk_item(segment: dict[str, object]) -> TranslationChunkItem:
    index = _as_int(segment.get("index"))
    start = _as_float(segment.get("start"))
    end = _as_float(segment.get("end"))
    source_text = str(segment.get("text") or "").strip()

    if not source_text:
        raise ValueError(
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


def _translation_output_token_budget(chunk: list[TranslationChunkItem]) -> int:
    word_count = sum(_word_count(item.source_text) for item in chunk)
    estimated_tokens = 200 + (word_count * 4)
    return max(500, min(4000, estimated_tokens))


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
