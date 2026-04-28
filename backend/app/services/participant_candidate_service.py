import re
from dataclasses import dataclass, field
from typing import Literal

from app.services.yt_dlp_service import VideoMetadata

NAME_TOKEN_PATTERN = r"[A-Z][A-Za-z]*[a-z][A-Za-z]*(?:['-][A-Z][A-Za-z]*[a-z][A-Za-z]*)*"
FULL_NAME_PATTERN = re.compile(
    rf"\b{NAME_TOKEN_PATTERN}(?:\s+{NAME_TOKEN_PATTERN}){{1,3}}\b"
)
SITS_DOWN_WITH_PATTERN = re.compile(
    rf"(?P<host>{NAME_TOKEN_PATTERN}(?:\s+{NAME_TOKEN_PATTERN}){{1,3}})\s+"
    rf"sits down with\s+"
    rf"(?P<guest>{NAME_TOKEN_PATTERN}(?:\s+{NAME_TOKEN_PATTERN}){{1,3}})",
)
ROLE_KEYWORDS: dict[str, str] = {
    "guest": "guest",
    "host": "host",
    "interviewer": "host",
    "moderator": "host",
    "speaker": "speaker",
}
ORGANIZATION_SUFFIXES = {
    "AI",
    "Inc",
    "Labs",
    "Lab",
    "Hub",
    "Foundation",
    "University",
    "Studio",
    "Company",
}
LOW_SIGNAL_TERMS = {
    "Intro",
    "Welcome",
    "Wrap",
    "Learn",
    "Benchmarking",
    "Infrastructure",
    "Performance",
    "Generation",
    "Hardware",
    "Kernel",
    "Kernels",
    "Code",
    "Skills",
}


@dataclass
class _CandidateAccumulator:
    name: str
    score: int = 0
    source_fields: set[str] = field(default_factory=set)
    role_hints: set[str] = field(default_factory=set)
    evidence: list[str] = field(default_factory=list)
    cross_field_bonus_applied: bool = False


@dataclass(frozen=True)
class CandidatePerson:
    name: str
    confidence: Literal["high", "medium", "low"]
    source_fields: list[str]
    role_hints: list[str]
    evidence: list[str]


def extract_candidate_people(metadata: VideoMetadata) -> list[CandidatePerson]:
    accumulators: dict[str, _CandidateAccumulator] = {}
    signals = _build_text_signals(metadata)

    for field_name, text in signals:
        for match in FULL_NAME_PATTERN.finditer(text):
            candidate_name = _normalize_spaces(match.group(0))
            if _should_skip_candidate(candidate_name, metadata):
                continue

            accumulator = accumulators.setdefault(
                candidate_name,
                _CandidateAccumulator(name=candidate_name),
            )
            accumulator.score += 2 if field_name == "title" else 1
            accumulator.source_fields.add(field_name)
            _append_evidence(accumulator, text)

    _apply_context_clues(accumulators, signals)

    people: list[CandidatePerson] = []
    for accumulator in accumulators.values():
        if accumulator.score < 2:
            continue

        people.append(
            CandidatePerson(
                name=accumulator.name,
                confidence=_score_to_confidence(accumulator.score),
                source_fields=sorted(accumulator.source_fields),
                role_hints=sorted(accumulator.role_hints),
                evidence=accumulator.evidence[:3],
            )
        )

    return sorted(
        people,
        key=lambda person: (-_confidence_rank(person.confidence), person.name.lower()),
    )


def _build_text_signals(metadata: VideoMetadata) -> list[tuple[str, str]]:
    signals: list[tuple[str, str]] = []

    title = _normalize_spaces(metadata.title)
    if title:
        signals.append(("title", title))

    if metadata.description:
        for raw_line in metadata.description.splitlines():
            line = _normalize_spaces(raw_line)
            if line:
                signals.append(("description", line))

    return signals


def _apply_context_clues(
    accumulators: dict[str, _CandidateAccumulator],
    signals: list[tuple[str, str]],
) -> None:
    for field_name, text in signals:
        role_match = SITS_DOWN_WITH_PATTERN.search(text)
        if role_match:
            host_name = _normalize_spaces(role_match.group("host"))
            guest_name = _normalize_spaces(role_match.group("guest"))
            _boost_candidate(accumulators, host_name, field_name, text, "host", 3)
            _boost_candidate(accumulators, guest_name, field_name, text, "guest", 3)

        for name, accumulator in accumulators.items():
            if name not in text:
                continue

            context_window = _context_window(text, name)
            if re.search(rf"\b{re.escape(name)}\b\s+(?:from|at|of)\s+", text):
                accumulator.score += 2
                _append_evidence(accumulator, text)

            if field_name == "title" and re.search(
                rf"\b{re.escape(name)}\b\s*(?:&|and)\s*", text
            ):
                accumulator.score += 1

            lowered_context = context_window.lower()
            for keyword, role_hint in ROLE_KEYWORDS.items():
                if keyword in lowered_context:
                    accumulator.role_hints.add(role_hint)
                    accumulator.score += 1
                    _append_evidence(accumulator, text)

            if len(accumulator.source_fields) > 1 and not accumulator.cross_field_bonus_applied:
                accumulator.score += 1
                accumulator.cross_field_bonus_applied = True


def _boost_candidate(
    accumulators: dict[str, _CandidateAccumulator],
    name: str,
    field_name: str,
    text: str,
    role_hint: str,
    score_delta: int,
) -> None:
    accumulator = accumulators.get(name)
    if accumulator is None:
        return

    accumulator.role_hints.add(role_hint)
    accumulator.source_fields.add(field_name)
    accumulator.score += score_delta
    _append_evidence(accumulator, text)


def _append_evidence(accumulator: _CandidateAccumulator, text: str) -> None:
    snippet = _normalize_spaces(text)
    if not snippet or snippet in accumulator.evidence:
        return
    accumulator.evidence.append(snippet[:220])


def _context_window(text: str, name: str) -> str:
    index = text.find(name)
    if index < 0:
        return text
    start = max(0, index - 36)
    end = min(len(text), index + len(name) + 36)
    return text[start:end]


def _should_skip_candidate(name: str, metadata: VideoMetadata) -> bool:
    if len(name.split()) < 2:
        return True

    normalized_name = name.casefold()
    blocked_names = {
        value.casefold()
        for value in [
            metadata.uploader,
            metadata.uploader_id,
            metadata.channel,
            metadata.channel_id,
        ]
        if value
    }
    if normalized_name in blocked_names:
        return True

    tokens = name.split()
    if any(token in LOW_SIGNAL_TERMS for token in tokens):
        return True

    if tokens[-1] in ORGANIZATION_SUFFIXES:
        return True

    return False


def _score_to_confidence(score: int) -> Literal["high", "medium", "low"]:
    if score >= 6:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _confidence_rank(confidence: Literal["high", "medium", "low"]) -> int:
    if confidence == "high":
        return 3
    if confidence == "medium":
        return 2
    return 1


def _normalize_spaces(value: str) -> str:
    return " ".join(value.split())
