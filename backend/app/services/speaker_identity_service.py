import re
from dataclasses import dataclass
from typing import cast
from typing import Literal

from app.services.participant_candidate_service import CandidatePerson
from app.services.transcription_service import TranscriptSegment, TranscriptionResult


SELF_INTRO_TEMPLATE = r"\b(?:i am|i'm|my name is|this is)\s+{name}\b"


@dataclass(frozen=True)
class SpeakerIdentityMatch:
    speaker_id: str
    display_name: str
    matched_candidate: str | None
    confidence: Literal["high", "medium", "low", "unknown"]
    evidence: list[str]


def resolve_speaker_identities(
    transcript: TranscriptionResult,
    candidates: list[CandidatePerson],
) -> list[SpeakerIdentityMatch]:
    speaker_segments = _group_segments_by_speaker(transcript.segments)
    speaker_ids = sorted(speaker_segments.keys(), key=_speaker_sort_key)
    speaker_stats = {
        speaker_id: _build_speaker_stats(segments)
        for speaker_id, segments in speaker_segments.items()
    }

    scored_matches: list[tuple[int, str, CandidatePerson, list[str]]] = []
    for speaker_id in speaker_ids:
        stats = speaker_stats[speaker_id]
        for candidate in candidates:
            score, evidence = _score_candidate_for_speaker(stats, candidate)
            if score > 0:
                scored_matches.append((score, speaker_id, candidate, evidence))

    assigned_speakers: set[str] = set()
    assigned_candidates: set[str] = set()
    resolved: list[SpeakerIdentityMatch] = []

    for score, speaker_id, candidate, evidence in sorted(
        scored_matches,
        key=lambda item: (-item[0], _speaker_sort_key(item[1]), item[2].name.lower()),
    ):
        if speaker_id in assigned_speakers or candidate.name in assigned_candidates:
            continue
        if score < 6:
            continue

        resolved.append(
            SpeakerIdentityMatch(
                speaker_id=speaker_id,
                display_name=candidate.name,
                matched_candidate=candidate.name,
                confidence=_score_to_confidence(score),
                evidence=evidence[:3],
            )
        )
        assigned_speakers.add(speaker_id)
        assigned_candidates.add(candidate.name)

    remaining_speakers = [
        speaker_id for speaker_id in speaker_ids if speaker_id not in assigned_speakers
    ]
    remaining_candidates = [
        candidate for candidate in candidates if candidate.name not in assigned_candidates
    ]

    for candidate in list(remaining_candidates):
        ranked_options = sorted(
            (
                _score_candidate_for_speaker(speaker_stats[speaker_id], candidate),
                speaker_id,
            )
            for speaker_id in remaining_speakers
        )
        ranked_options.sort(
            key=lambda item: (-item[0][0], _speaker_sort_key(item[1]))
        )
        if not ranked_options:
            continue

        (best_score, best_evidence), best_speaker_id = ranked_options[0]
        next_best_score = ranked_options[1][0][0] if len(ranked_options) > 1 else -1
        if best_score <= 0 or best_score == next_best_score:
            continue

        resolved.append(
            SpeakerIdentityMatch(
                speaker_id=best_speaker_id,
                display_name=candidate.name,
                matched_candidate=candidate.name,
                confidence=_score_to_confidence(best_score),
                evidence=best_evidence[:3],
            )
        )
        assigned_speakers.add(best_speaker_id)
        assigned_candidates.add(candidate.name)
        remaining_speakers = [
            speaker_id for speaker_id in remaining_speakers if speaker_id != best_speaker_id
        ]
        remaining_candidates = [
            item for item in remaining_candidates if item.name != candidate.name
        ]

    if (
        resolved
        and len(remaining_speakers) == 1
        and len(remaining_candidates) == 1
    ):
        candidate = remaining_candidates[0]
        resolved.append(
            SpeakerIdentityMatch(
                speaker_id=remaining_speakers[0],
                display_name=candidate.name,
                matched_candidate=candidate.name,
                confidence="medium",
                evidence=["Only remaining unmatched candidate after stronger assignments."],
            )
        )
        assigned_speakers.add(remaining_speakers[0])

    for speaker_id in speaker_ids:
        if speaker_id in assigned_speakers:
            continue
        resolved.append(
            SpeakerIdentityMatch(
                speaker_id=speaker_id,
                display_name=speaker_id,
                matched_candidate=None,
                confidence="unknown",
                evidence=[],
            )
        )

    return sorted(resolved, key=lambda item: _speaker_sort_key(item.speaker_id))


def apply_speaker_identities(
    transcript: TranscriptionResult,
    identities: list[SpeakerIdentityMatch],
) -> TranscriptionResult:
    display_name_by_id = {
        identity.speaker_id: identity.display_name for identity in identities
    }

    return TranscriptionResult(
        language=transcript.language,
        text=transcript.text,
        segments=[
            TranscriptSegment(
                index=segment.index,
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker=display_name_by_id.get(segment.speaker or "", segment.speaker),
            )
            for segment in transcript.segments
        ],
    )


def _group_segments_by_speaker(
    segments: list[TranscriptSegment],
) -> dict[str, list[TranscriptSegment]]:
    grouped: dict[str, list[TranscriptSegment]] = {}
    for segment in segments:
        if not segment.speaker:
            continue
        grouped.setdefault(segment.speaker, []).append(segment)
    return grouped


def _build_speaker_stats(segments: list[TranscriptSegment]) -> dict[str, object]:
    combined_text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    leading_text = " ".join(
        segment.text.strip() for segment in segments[:20] if segment.text.strip()
    )
    question_count = sum(segment.text.strip().endswith("?") for segment in segments)
    question_ratio = question_count / len(segments) if segments else 0.0

    return {
        "segments": segments,
        "combined_text": combined_text,
        "leading_text": leading_text,
        "question_ratio": question_ratio,
    }


def _score_candidate_for_speaker(
    speaker_stats: dict[str, object],
    candidate: CandidatePerson,
) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    combined_text = str(speaker_stats["combined_text"])
    leading_text = str(speaker_stats["leading_text"])
    lower_combined_text = combined_text.lower()
    lower_leading_text = leading_text.lower()
    first_name = candidate.name.split()[0].lower()
    full_name = candidate.name.lower()

    for name_variant, bonus in ((full_name, 10), (first_name, 8)):
        pattern = re.compile(SELF_INTRO_TEMPLATE.format(name=re.escape(name_variant)))
        if pattern.search(lower_leading_text):
            score += bonus
            evidence.append(f"Self-introduction matched '{name_variant}'.")
            break

    if re.search(rf"\b{re.escape(full_name)}\b", lower_combined_text):
        score += 2
        evidence.append(f"Speaker text explicitly mentions '{candidate.name}'.")

    role_hints = set(candidate.role_hints)
    question_ratio_value = speaker_stats["question_ratio"]
    question_ratio = (
        cast(float, question_ratio_value)
        if isinstance(question_ratio_value, (int, float))
        else 0.0
    )
    if "host" in role_hints and question_ratio >= 0.18:
        score += 2
        evidence.append("Question-heavy speaker matches host role hint.")
    if "guest" in role_hints and question_ratio <= 0.1:
        score += 1
        evidence.append("Answer-heavy speaker matches guest role hint.")

    return score, evidence


def _score_to_confidence(score: int) -> Literal["high", "medium", "low", "unknown"]:
    if score >= 8:
        return "high"
    if score >= 6:
        return "medium"
    if score > 0:
        return "low"
    return "unknown"


def _speaker_sort_key(speaker_id: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", speaker_id)
    if match:
        return int(match.group(1)), speaker_id
    return 10_000, speaker_id
