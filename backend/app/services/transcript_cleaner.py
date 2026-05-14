"""Transcript cleaner: removes filler words, markers, and duplicate sentences."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CleanResult:
    cleaned_text: str
    removed_filler_count: int
    removed_marker_count: int
    removed_duplicate_count: int


FILLER_PATTERNS: tuple[str, ...] = (
    r"嗯+",
    r"啊+",
    r"呃+",
    r"对吧[？?]",
    r"你知道吗",
    r"怎么说呢",
    r"就是说",
    r"然后呢",
)

MARKER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\[音乐\]"),
    re.compile(r"\[掌声\]"),
    re.compile(r"\[片头\]"),
    re.compile(r"\[片尾\]"),
    re.compile(r"\[广告\]"),
    re.compile(r"\(music\)", re.IGNORECASE),
)

DEDUP_PREFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(我觉得|我认为|我想)\s*"),
)


def clean_transcript(
    text: str,
    *,
    remove_fillers: bool = True,
    remove_markers: bool = True,
    remove_duplicates: bool = True,
    extra_fillers: tuple[str, ...] = (),
) -> CleanResult:
    """Clean transcript text by removing filler words, markers, and duplicates."""
    current = text or ""
    total_fillers = 0
    total_markers = 0
    total_duplicates = 0

    if remove_fillers:
        current, count = _remove_fillers(current, extra_fillers)
        total_fillers = count

    if remove_markers:
        current, count = _remove_markers(current)
        total_markers = count

    if remove_duplicates:
        current, count = _remove_duplicate_sentences(current)
        total_duplicates = count

    return CleanResult(
        cleaned_text=current,
        removed_filler_count=total_fillers,
        removed_marker_count=total_markers,
        removed_duplicate_count=total_duplicates,
    )


def _remove_fillers(text: str, extra: tuple[str, ...] = ()) -> tuple[str, int]:
    """Remove filler words, return (cleaned_text, removal_count)."""
    count = 0
    result = text
    all_patterns = FILLER_PATTERNS + extra
    for pattern in all_patterns:
        matches = re.findall(pattern, result)
        count += len(matches)
        result = re.sub(pattern, " ", result)
    # Collapse multiple spaces
    result = re.sub(r"\s+", " ", result).strip()
    return result, count


def _remove_markers(text: str) -> tuple[str, int]:
    """Remove [music] style markers, return (cleaned_text, removal_count)."""
    count = 0
    result = text
    for pattern in MARKER_PATTERNS:
        matches = pattern.findall(result)
        count += len(matches)
        result = pattern.sub(" ", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result, count


def _remove_duplicate_sentences(text: str) -> tuple[str, int]:
    """Remove adjacent duplicate sentences, return (cleaned_text, removal_count)."""
    if not text.strip():
        return text, 0

    # Split by sentence-ending punctuation or newlines
    parts = re.split(r"(?<=[。！？；\n])", text)
    parts = [p for p in parts if p.strip()]

    if len(parts) <= 1:
        return text, 0

    deduped: list[str] = []
    count = 0
    for part in parts:
        stripped = part.strip()
        if deduped and _sentence_dedup_key(stripped) == _sentence_dedup_key(deduped[-1]):
            count += 1
            continue
        deduped.append(part)

    result = "".join(deduped)
    return result, count


def _sentence_dedup_key(sentence: str) -> str:
    """Normalize a sentence slightly before comparing for duplication."""
    key = sentence.strip()
    for pattern in DEDUP_PREFIX_PATTERNS:
        key = pattern.sub("", key)
    return key
