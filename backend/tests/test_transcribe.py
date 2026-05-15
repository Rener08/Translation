from pathlib import Path

from fastapi.testclient import TestClient

from app.config import ROOT_DIR, get_settings
from app.main import app
from app.services.transcription_service import (
    AudioFileNotFoundError,
    AudioFileTooLargeError,
    LocalTranscriptionError,
    TranscriptTooLongError,
    TranscriptionConfigurationError,
    TranscriptionResult,
    TranscriptSegment,
    transcribe_audio_file,
)


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


class FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class FakeInfo:
    def __init__(self, language: str = "en") -> None:
        self.language = language


def test_transcribe_audio_file_returns_transcript(monkeypatch, tmp_path: Path) -> None:
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
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
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
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


def test_transcribe_audio_file_rejects_absolute_paths_outside_tmp() -> None:
    try:
        transcribe_audio_file("C:/Users/Administrator/Desktop/sample.webm")
    except AudioFileNotFoundError as error:
        assert "Absolute audio paths are not allowed" in str(error)
    else:
        raise AssertionError("Expected AudioFileNotFoundError")


def test_transcribe_audio_file_rejects_oversized_audio(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAX_AUDIO_BYTES", "4")
    get_settings.cache_clear()
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
    audio_file.write_bytes(b"audio")

    monkeypatch.setattr(
        "app.services.transcription_service._get_whisper_model",
        lambda: (_ for _ in ()).throw(AssertionError("Whisper model should not load")),
    )

    try:
        transcribe_audio_file(str(audio_file))
    except AudioFileTooLargeError as error:
        assert "MAX_AUDIO_BYTES" in str(error)
    else:
        raise AssertionError("Expected AudioFileTooLargeError")


def test_transcribe_audio_file_rejects_oversized_transcript(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MAX_TRANSCRIPT_CHARS", "10")
    get_settings.cache_clear()
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
    audio_file.write_bytes(b"audio")

    class FakeModel:
        def transcribe(self, audio_path: str, language: str, vad_filter: bool):
            return iter([FakeSegment(0.0, 1.5, "Hello everyone.")]), FakeInfo("en")

    monkeypatch.setattr(
        "app.services.transcription_service._get_whisper_model",
        lambda: FakeModel(),
    )

    try:
        transcribe_audio_file(str(audio_file))
    except TranscriptTooLongError as error:
        assert "MAX_TRANSCRIPT_CHARS" in str(error)
    else:
        raise AssertionError("Expected TranscriptTooLongError")


def test_transcribe_audio_file_surfaces_model_configuration_errors(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
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
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
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
    audio_file = TMP_ROOT / f"{tmp_path.name}-sample.webm"
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
    body = response.json()
    assert body["detail"] == "Audio file was not found: tmp/missing.webm"
    assert body["error_code"] == "AUDIO_FILE_NOT_FOUND"
    assert body["retryable"] is False
    assert isinstance(body["request_id"], str)
    assert body["request_id"]


def test_transcribe_endpoint_returns_limit_error(monkeypatch) -> None:
    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        raise AudioFileTooLargeError(
            "Audio file is 5 bytes, exceeding MAX_AUDIO_BYTES=4."
        )

    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)

    response = client.post(
        "/api/transcribe",
        json={"audio_file_path": "tmp/sample.webm"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["detail"] == "Audio file is 5 bytes, exceeding MAX_AUDIO_BYTES=4."
    assert body["error_code"] == "INVALID_INPUT"
    assert body["retryable"] is False
    assert isinstance(body["request_id"], str)
    assert body["request_id"]


def test_transcribe_endpoint_returns_configuration_error(monkeypatch) -> None:
    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        raise TranscriptionConfigurationError("Failed to load local Whisper model.")

    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)

    response = client.post(
        "/api/transcribe",
        json={"audio_file_path": "tmp/sample.webm"},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Failed to load local Whisper model."
    assert body["error_code"] == "CONFIGURATION_ERROR"
    assert body["retryable"] is False
    assert isinstance(body["request_id"], str)
    assert body["request_id"]


def test_transcribe_endpoint_returns_runtime_error(monkeypatch) -> None:
    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        raise LocalTranscriptionError("Local Whisper transcription failed.")

    monkeypatch.setattr("app.main.transcribe_audio_file", fake_transcribe)

    response = client.post(
        "/api/transcribe",
        json={"audio_file_path": "tmp/sample.webm"},
    )

    assert response.status_code == 502
    body = response.json()
    assert body["detail"] == "Local Whisper transcription failed."
    assert body["error_code"] == "UPSTREAM_ERROR"
    assert body["retryable"] is True
    assert isinstance(body["request_id"], str)
    assert body["request_id"]
