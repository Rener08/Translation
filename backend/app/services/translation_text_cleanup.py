import json
import re

from app.services.translation_types import (
    NonJsonTranslationContentError,
    PartialTranslationsContentError,
    TranslationChunkItem,
)

THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
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


def _missing_chunk_indices(
    chunk: list[TranslationChunkItem],
    translations_by_index: dict[int, str],
) -> list[int]:
    return [
        item.index
        for item in chunk
        if not str(translations_by_index.get(item.index) or "").strip()
    ]


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
