import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import ROOT_DIR
from app.main import app
import app.services.speaker_diarization_service as speaker_diarization_service
from app.services.speaker_diarization_service import (
    SpeakerDiarizationConfigurationError,
    SpeakerDiarizationResult,
    SpeakerDiarizationRuntimeError,
    SpeakerTurn,
    assign_speakers_to_transcript,
    diarize_audio_file,
)
from app.services.transcription_service import TranscriptionResult, TranscriptSegment


client = TestClient(app)
TMP_ROOT = ROOT_DIR / "tmp"
TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _assert_error_response(
    response,
    *,
    status_code: int,
    error_code: str,
    retryable: bool,
    detail: str,
) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail", "error_code", "retryable", "request_id"}
    assert body["detail"] == detail
    assert body["error_code"] == error_code
    assert body["retryable"] is retryable
    assert body["request_id"] == response.headers["x-request-id"]


class FakeTurn:
    def __init__(self, start: float, end: float) -> None:
        self.start = start
        self.end = end


def test_diarize_audio_file_returns_normalized_turns(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
    audio_file.write_bytes(b"audio")

    class FakeAnnotation:
        def itertracks(self, yield_label: bool = False):
            assert yield_label is True
            yield FakeTurn(0.0, 1.2), None, "SPEAKER_07"
            yield FakeTurn(1.2, 2.8), None, "SPEAKER_03"
            yield FakeTurn(2.8, 4.0), None, "SPEAKER_07"

    class FakePipeline:
        def __call__(self, audio_path: str):
            assert audio_path == str(audio_file)
            return FakeAnnotation()

    monkeypatch.setattr(
        "app.services.speaker_diarization_service._get_diarization_pipeline",
        lambda: FakePipeline(),
    )
    monkeypatch.setattr(
        "app.services.speaker_diarization_service._prepare_audio_for_diarization",
        lambda path: path,
    )

    result = diarize_audio_file(str(audio_file))

    assert result == SpeakerDiarizationResult(
        turns=[
            SpeakerTurn(start=0.0, end=1.2, speaker="Speaker 1"),
            SpeakerTurn(start=1.2, end=2.8, speaker="Speaker 2"),
            SpeakerTurn(start=2.8, end=4.0, speaker="Speaker 1"),
        ]
    )
    assert result.speaker_count == 2


def test_diarize_audio_file_collapses_fragmented_speakers(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
    audio_file.write_bytes(b"audio")

    class FakeAnnotation:
        def itertracks(self, yield_label: bool = False):
            assert yield_label is True
            yield FakeTurn(0.0, 18.0), None, "SPEAKER_00"
            yield FakeTurn(18.0, 18.4), None, "SPEAKER_77"
            yield FakeTurn(18.4, 37.0), None, "SPEAKER_00"
            yield FakeTurn(37.0, 55.0), None, "SPEAKER_01"
            yield FakeTurn(55.0, 55.4), None, "SPEAKER_88"
            yield FakeTurn(55.4, 76.0), None, "SPEAKER_01"

    class FakePipeline:
        def __call__(self, audio_path: str):
            assert audio_path == str(audio_file)
            return FakeAnnotation()

    monkeypatch.setattr(
        "app.services.speaker_diarization_service._get_diarization_pipeline",
        lambda: FakePipeline(),
    )
    monkeypatch.setattr(
        "app.services.speaker_diarization_service._prepare_audio_for_diarization",
        lambda path: path,
    )

    result = diarize_audio_file(str(audio_file))

    assert result == SpeakerDiarizationResult(
        turns=[
            SpeakerTurn(start=0.0, end=37.0, speaker="Speaker 1"),
            SpeakerTurn(start=37.0, end=76.0, speaker="Speaker 2"),
        ]
    )
    assert result.speaker_count == 2


def test_diarize_audio_file_rejects_absolute_paths_outside_tmp() -> None:
    try:
        diarize_audio_file("C:/Users/Administrator/Desktop/sample.webm")
    except SpeakerDiarizationRuntimeError as error:
        assert "Absolute audio paths are not allowed" in str(error)
    else:
        raise AssertionError("Expected SpeakerDiarizationRuntimeError")


def test_prepare_audio_for_diarization_uses_killable_subprocess(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
    audio_file.write_bytes(b"audio")
    captured_kwargs: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "app.services.speaker_diarization_service.run_subprocess_killable",
        fake_run,
    )

    result = speaker_diarization_service._prepare_audio_for_diarization(audio_file)

    assert result == audio_file.with_name(f"{audio_file.stem}.diarize.wav")
    assert captured_kwargs["subprocess_timeout"] == 60


def test_assign_speakers_to_transcript_picks_best_overlap() -> None:
    transcript = TranscriptionResult(
        language="en",
        text="Hello there.\nGeneral Kenobi.",
        segments=[
            TranscriptSegment(index=0, start=0.0, end=1.5, text="Hello there."),
            TranscriptSegment(index=1, start=1.5, end=3.2, text="General Kenobi."),
        ],
    )
    diarization = SpeakerDiarizationResult(
        turns=[
            SpeakerTurn(start=0.0, end=1.8, speaker="Speaker 1"),
            SpeakerTurn(start=1.8, end=3.5, speaker="Speaker 2"),
        ]
    )

    result = assign_speakers_to_transcript(transcript, diarization)

    assert result.segments[0].speaker == "Speaker 1"
    assert result.segments[1].speaker == "Speaker 2"


def test_diarize_endpoint_returns_aligned_segments(monkeypatch) -> None:
    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        assert audio_file_path == "tmp/sample.webm"
        return TranscriptionResult(
            language="en",
            text="Hello everyone.\nWelcome back.",
            segments=[
                TranscriptSegment(index=0, start=0.0, end=1.5, text="Hello everyone."),
                TranscriptSegment(index=1, start=1.5, end=3.0, text="Welcome back."),
            ],
        )

    def fake_diarize(audio_file_path: str) -> SpeakerDiarizationResult:
        assert audio_file_path == "tmp/sample.webm"
        return SpeakerDiarizationResult(
            turns=[
                SpeakerTurn(start=0.0, end=1.6, speaker="Speaker 1"),
                SpeakerTurn(start=1.6, end=3.2, speaker="Speaker 2"),
            ]
        )

    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr("app.main.diarize_audio_file", fake_diarize)

    response = client.post(
        "/api/diarize",
        json={"audio_file_path": "tmp/sample.webm"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "language": "en",
        "text": "Hello everyone.\nWelcome back.",
        "speaker_count": 2,
        "turns": [
            {"start": 0.0, "end": 1.6, "speaker": "Speaker 1"},
            {"start": 1.6, "end": 3.2, "speaker": "Speaker 2"},
        ],
        "segments": [
            {
                "index": 0,
                "start": 0.0,
                "end": 1.5,
                "text": "Hello everyone.",
                "speaker": "Speaker 1",
            },
            {
                "index": 1,
                "start": 1.5,
                "end": 3.0,
                "text": "Welcome back.",
                "speaker": "Speaker 2",
            },
        ],
    }


def test_diarize_endpoint_returns_configuration_error(monkeypatch) -> None:
    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        return TranscriptionResult(
            language="en",
            text="Hello everyone.",
            segments=[
                TranscriptSegment(index=0, start=0.0, end=1.5, text="Hello everyone."),
            ],
        )

    def fail_diarize(audio_file_path: str) -> SpeakerDiarizationResult:
        raise SpeakerDiarizationConfigurationError("Missing PYANNOTE_AUTH_TOKEN")

    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr("app.main.diarize_audio_file", fail_diarize)

    response = client.post(
        "/api/diarize",
        json={"audio_file_path": "tmp/sample.webm"},
    )

    _assert_error_response(
        response,
        status_code=500,
        error_code="CONFIGURATION_ERROR",
        retryable=False,
        detail="Missing PYANNOTE_AUTH_TOKEN",
    )
