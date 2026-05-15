from fastapi.testclient import TestClient

from app.main import app
from app.services.participant_candidate_service import extract_candidate_people
from app.services.yt_dlp_service import VideoInspectError, VideoMetadata


client = TestClient(app)


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


def test_extract_candidate_people_from_metadata() -> None:
    metadata = VideoMetadata(
        video_id="Z6sqEbg2ETo",
        title="From AI Agents to Faster Kernels: Ben Burtenshaw & Felix LeClair (AI Plumbers #2)",
        uploader="HuggingFace",
        channel="HuggingFace",
        description=(
            "Felix LeClair sits down with Ben Burtenshaw from Hugging Face to discuss "
            "how the Hugging Face Kernels ecosystem makes high-performance kernels easier to build."
        ),
    )

    candidates = extract_candidate_people(metadata)

    assert [candidate.name for candidate in candidates] == [
        "Ben Burtenshaw",
        "Felix LeClair",
    ]
    assert candidates[0].confidence == "high"
    assert candidates[0].role_hints == ["guest"]
    assert candidates[1].role_hints == ["host"]


def test_video_participants_endpoint_returns_candidates(monkeypatch) -> None:
    def fake_inspect(url: str) -> VideoMetadata:
        assert url == "https://www.youtube.com/watch?v=abc123xyz"
        return VideoMetadata(
            video_id="abc123xyz",
            title="Alice Smith and Bob Jones talk compilers",
            uploader="Compiler Channel",
            channel="Compiler Channel",
            description="Alice Smith sits down with Bob Jones to talk about kernels.",
        )

    monkeypatch.setattr("app.main.inspect_video_metadata", fake_inspect)

    response = client.post(
        "/api/video/participants",
        json={"url": "https://youtu.be/abc123xyz?t=12"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "video_id": "abc123xyz",
        "title": "Alice Smith and Bob Jones talk compilers",
        "candidates": [
            {
                "name": "Alice Smith",
                "confidence": "high",
                "source_fields": ["description", "title"],
                "role_hints": ["host"],
                "evidence": [
                    "Alice Smith and Bob Jones talk compilers",
                    "Alice Smith sits down with Bob Jones to talk about kernels.",
                ],
            },
            {
                "name": "Bob Jones",
                "confidence": "high",
                "source_fields": ["description", "title"],
                "role_hints": ["guest"],
                "evidence": [
                    "Alice Smith and Bob Jones talk compilers",
                    "Alice Smith sits down with Bob Jones to talk about kernels.",
                ],
            },
        ],
    }


def test_video_participants_endpoint_returns_yt_dlp_failure(monkeypatch) -> None:
    def fake_inspect(url: str) -> VideoMetadata:
        raise VideoInspectError("Video unavailable")

    monkeypatch.setattr("app.main.inspect_video_metadata", fake_inspect)

    response = client.post(
        "/api/video/participants",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )

    _assert_error_response(
        response,
        status_code=502,
        error_code="UPSTREAM_ERROR",
        retryable=True,
        detail="Failed to inspect video metadata: Video unavailable",
    )
