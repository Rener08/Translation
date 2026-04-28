from fastapi.testclient import TestClient

from app.main import app
from app.services.participant_candidate_service import CandidatePerson
from app.services.speaker_diarization_service import (
    SpeakerDiarizationResult,
    SpeakerTurn,
)
from app.services.speaker_identity_service import (
    apply_speaker_identities,
    resolve_speaker_identities,
)
from app.services.transcription_service import TranscriptionResult, TranscriptSegment
from app.services.video_source_service import VideoSourceResult
from app.services.yt_dlp_service import VideoMetadata


client = TestClient(app)


def test_resolve_speaker_identities_keeps_unknown_speakers() -> None:
    transcript = TranscriptionResult(
        language="en",
        text=(
            "I'm Felix and I'm here with Ben.\nHappy to be here.\nCan you tell us more?"
        ),
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=1.0,
                text="I'm Felix and I'm here with Ben.",
                speaker="Speaker 1",
            ),
            TranscriptSegment(
                index=1,
                start=1.0,
                end=2.0,
                text="Happy to be here.",
                speaker="Speaker 2",
            ),
            TranscriptSegment(
                index=2,
                start=2.0,
                end=3.0,
                text="Can you tell us more?",
                speaker="Speaker 3",
            ),
        ],
    )
    candidates = [
        CandidatePerson(
            name="Felix LeClair",
            confidence="high",
            source_fields=["description"],
            role_hints=["host"],
            evidence=["Felix LeClair sits down with Ben Burtenshaw."],
        ),
        CandidatePerson(
            name="Ben Burtenshaw",
            confidence="high",
            source_fields=["description"],
            role_hints=["guest"],
            evidence=["Felix LeClair sits down with Ben Burtenshaw."],
        ),
    ]

    identities = resolve_speaker_identities(transcript, candidates)
    resolved = apply_speaker_identities(transcript, identities)

    assert [identity.speaker_id for identity in identities] == [
        "Speaker 1",
        "Speaker 2",
        "Speaker 3",
    ]
    assert resolved.segments[0].speaker == "Felix LeClair"
    assert resolved.segments[1].speaker == "Ben Burtenshaw"
    assert resolved.segments[2].speaker == "Speaker 3"


def test_resolve_speakers_endpoint_returns_named_segments(monkeypatch) -> None:
    def fake_inspect(url: str) -> VideoMetadata:
        assert url == "https://www.youtube.com/watch?v=abc123xyz"
        return VideoMetadata(
            video_id="abc123xyz",
            title="Ben Burtenshaw & Felix LeClair",
            uploader="HuggingFace",
            channel="HuggingFace",
            description="Felix LeClair sits down with Ben Burtenshaw from Hugging Face.",
        )

    def fake_fetch_source(
        url: str,
        source_mode: str = "subtitle_first",
    ) -> VideoSourceResult:
        assert url == "https://www.youtube.com/watch?v=abc123xyz"
        assert source_mode == "force_audio"
        return VideoSourceResult(source_type="audio", audio_file_path="tmp/sample.webm")

    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        assert audio_file_path == "tmp/sample.webm"
        return TranscriptionResult(
            language="en",
            text=(
                "I'm Felix and I'm here with Ben.\n"
                "Thanks for having me.\n"
                "Can you tell us more?"
            ),
            segments=[
                TranscriptSegment(
                    index=0, start=0.0, end=1.2, text="I'm Felix and I'm here with Ben."
                ),
                TranscriptSegment(
                    index=1, start=1.2, end=2.4, text="Thanks for having me."
                ),
                TranscriptSegment(
                    index=2, start=2.4, end=3.0, text="Can you tell us more?"
                ),
            ],
        )

    def fake_diarize(audio_file_path: str) -> SpeakerDiarizationResult:
        assert audio_file_path == "tmp/sample.webm"
        return SpeakerDiarizationResult(
            turns=[
                SpeakerTurn(start=0.0, end=1.2, speaker="Speaker 1"),
                SpeakerTurn(start=1.2, end=2.4, speaker="Speaker 2"),
                SpeakerTurn(start=2.4, end=3.0, speaker="Speaker 3"),
            ]
        )

    monkeypatch.setattr("app.main.inspect_video_metadata", fake_inspect)
    monkeypatch.setattr("app.main.fetch_video_source", fake_fetch_source)
    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr("app.main.diarize_audio_file", fake_diarize)

    response = client.post(
        "/api/video/resolve-speakers",
        json={"url": "https://youtu.be/abc123xyz?t=12"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "video_id": "abc123xyz",
        "title": "Ben Burtenshaw & Felix LeClair",
        "audio_file_path": "tmp/sample.webm",
        "speaker_count": 3,
        "candidates": [
            {
                "name": "Ben Burtenshaw",
                "confidence": "high",
                "source_fields": ["description", "title"],
                "role_hints": ["guest"],
                "evidence": [
                    "Ben Burtenshaw & Felix LeClair",
                    "Felix LeClair sits down with Ben Burtenshaw from Hugging Face.",
                ],
            },
            {
                "name": "Felix LeClair",
                "confidence": "high",
                "source_fields": ["description", "title"],
                "role_hints": ["host"],
                "evidence": [
                    "Ben Burtenshaw & Felix LeClair",
                    "Felix LeClair sits down with Ben Burtenshaw from Hugging Face.",
                ],
            },
        ],
        "speaker_mappings": [
            {
                "speaker_id": "Speaker 1",
                "speaker": "Felix LeClair",
                "matched_candidate": "Felix LeClair",
                "confidence": "high",
                "evidence": ["Self-introduction matched 'felix'."],
            },
            {
                "speaker_id": "Speaker 2",
                "speaker": "Ben Burtenshaw",
                "matched_candidate": "Ben Burtenshaw",
                "confidence": "low",
                "evidence": ["Answer-heavy speaker matches guest role hint."],
            },
            {
                "speaker_id": "Speaker 3",
                "speaker": "Speaker 3",
                "matched_candidate": None,
                "confidence": "unknown",
                "evidence": [],
            },
        ],
        "segments": [
            {
                "index": 0,
                "start": 0.0,
                "end": 1.2,
                "text": "I'm Felix and I'm here with Ben.",
                "speaker_id": "Speaker 1",
                "speaker": "Felix LeClair",
            },
            {
                "index": 1,
                "start": 1.2,
                "end": 2.4,
                "text": "Thanks for having me.",
                "speaker_id": "Speaker 2",
                "speaker": "Ben Burtenshaw",
            },
            {
                "index": 2,
                "start": 2.4,
                "end": 3.0,
                "text": "Can you tell us more?",
                "speaker_id": "Speaker 3",
                "speaker": "Speaker 3",
            },
        ],
    }
