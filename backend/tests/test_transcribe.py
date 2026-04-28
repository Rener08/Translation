from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.transcription_service import (
    AudioFileNotFoundError,
    LocalTranscriptionError,
    TranscriptionConfigurationError,
    TranscriptionResult,
    TranscriptSegment,
    transcribe_audio_file,
)


client = TestClient(app)


class FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class FakeInfo:
    def __init__(self, language: str = "en") -> None:
        self.language = language


def test_transcribe_audio_file_returns_transcript(monkeypatch, tmp_path: Path) -> None:
    audio_file = tmp_path / "sample.webm"
    audio_file.write_bytes(b"audio")

    class FakeModel:
        def transcribe(self, audio_path: str, language: str, vad_filter: bool):
            assert audio_path == str(audio_file)
            assert language == "en"
            assert vad_filter is True
            return iter([FakeSegment(0.0, 1.5, "Hello everyone.")]), FakeInfo("en")

    monkeypatch.setattr(
        "app.services.transcription_service._get_whisper_model",
        lambda: FakeModel(),
    )

    result = transcribe_audio_file(str(audio_file))

    assert result == TranscriptionResult(
        language="en",
        text="Hello everyone.",
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=1.5,
                text="Hello everyone.",
            )
        ],
    )


def test_transcribe_audio_file_uses_persistent_cache(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = tmp_path / "sample.webm"
    audio_file.write_bytes(b"audio")
    call_count = 0

    class FakeModel:
        def transcribe(self, audio_path: str, language: str, vad_filter: bool):
            nonlocal call_count
            call_count += 1
            return iter([FakeSegment(0.0, 1.5, "Hello everyone.")]), FakeInfo("en")

    monkeypatch.setattr(
        "app.services.transcription_service._get_whisper_model",
        lambda: FakeModel(),
    )

    first = transcribe_audio_file(str(audio_file))
    second = transcribe_audio_file(str(audio_file))

    assert call_count == 1
    assert first.text == second.text


def test_transcribe_audio_file_requires_existing_file(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.transcription_service._get_whisper_model",
        lambda: object(),
    )

    try:
        transcribe_audio_file("tmp/does-not-exist.webm")
    except AudioFileNotFoundError as error:
        assert "Audio file was not found" in str(error)
    else:
        raise AssertionError("Expected AudioFileNotFoundError")


def test_transcribe_audio_file_surfaces_model_configuration_errors(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = tmp_path / "sample.webm"
    audio_file.write_bytes(b"audio")

    def fail_load_model():
        raise TranscriptionConfigurationError("Failed to load local Whisper model.")

    monkeypatch.setattr(
        "app.services.transcription_service._get_whisper_model",
        fail_load_model,
    )

    try:
        transcribe_audio_file(str(audio_file))
    except TranscriptionConfigurationError as error:
        assert "Failed to load local Whisper model." == str(error)
    else:
        raise AssertionError("Expected TranscriptionConfigurationError")


def test_transcribe_audio_file_surfaces_runtime_errors(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = tmp_path / "sample.webm"
    audio_file.write_bytes(b"audio")

    class FakeModel:
        def transcribe(self, audio_path: str, language: str, vad_filter: bool):
            raise RuntimeError("decoder crashed")

    monkeypatch.setattr(
        "app.services.transcription_service._get_whisper_model",
        lambda: FakeModel(),
    )

    try:
        transcribe_audio_file(str(audio_file))
    except LocalTranscriptionError as error:
        assert "decoder crashed" in str(error)
    else:
        raise AssertionError("Expected LocalTranscriptionError")


def test_transcribe_audio_file_rejects_empty_transcript(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = tmp_path / "sample.webm"
    audio_file.write_bytes(b"audio")

    class FakeModel:
        def transcribe(self, audio_path: str, language: str, vad_filter: bool):
            return iter([FakeSegment(0.0, 0.5, "   ")]), FakeInfo("en")

    monkeypatch.setattr(
        "app.services.transcription_service._get_whisper_model",
        lambda: FakeModel(),
    )

    try:
        transcribe_audio_file(str(audio_file))
    except LocalTranscriptionError as error:
        assert "empty transcript" in str(error).lower()
    else:
        raise AssertionError("Expected LocalTranscriptionError")


def test_transcribe_endpoint_returns_transcript(monkeypatch) -> None:
    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        assert audio_file_path == "tmp/sample.webm"
        return TranscriptionResult(
            language="en",
            text="Hello everyone.",
            segments=[
                TranscriptSegment(
                    index=0,
                    start=0.0,
                    end=1.5,
                    text="Hello everyone.",
                )
            ],
        )

    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)

    response = client.post(
        "/api/transcribe",
        json={"audio_file_path": "tmp/sample.webm"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "language": "en",
        "text": "Hello everyone.",
        "segments": [
            {
                "index": 0,
                "start": 0.0,
                "end": 1.5,
                "text": "Hello everyone.",
            }
        ],
    }


def test_transcribe_endpoint_returns_file_error(monkeypatch) -> None:
    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        raise AudioFileNotFoundError("Audio file was not found: tmp/missing.webm")

    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)

    response = client.post(
        "/api/transcribe",
        json={"audio_file_path": "tmp/missing.webm"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Audio file was not found: tmp/missing.webm"
    }


def test_transcribe_endpoint_returns_configuration_error(monkeypatch) -> None:
    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        raise TranscriptionConfigurationError("Failed to load local Whisper model.")

    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)

    response = client.post(
        "/api/transcribe",
        json={"audio_file_path": "tmp/sample.webm"},
    )

    assert response.status_code == 500


def test_transcribe_endpoint_returns_runtime_error(monkeypatch) -> None:
    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        raise LocalTranscriptionError("Local Whisper transcription failed.")

    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)

    response = client.post(
        "/api/transcribe",
        json={"audio_file_path": "tmp/sample.webm"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Local Whisper transcription failed."}
