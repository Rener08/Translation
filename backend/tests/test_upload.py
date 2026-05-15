from pathlib import Path

from fastapi.testclient import TestClient

from app.config import ROOT_DIR
from app.main import app


client = TestClient(app)


def test_upload_audio_endpoint_saves_file_under_tmp() -> None:
    response = client.post(
        "/api/uploads/audio",
        files={"file": ("demo.m4a", b"audio-bytes", "audio/mp4")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["audio_file_path"].startswith("tmp/upload/")
    assert body["title"] == "demo"
    assert body["original_filename"] == "demo.m4a"
    assert body["byte_count"] == len(b"audio-bytes")

    saved_path = ROOT_DIR / body["audio_file_path"]
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"audio-bytes"


def test_upload_audio_endpoint_rejects_unsupported_suffix() -> None:
    response = client.post(
        "/api/uploads/audio",
        files={"file": ("notes.txt", b"not-audio", "text/plain")},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "INVALID_INPUT"
    assert "Unsupported upload file type" in body["detail"]
