from fastapi.testclient import TestClient

from app.main import app
from app.youtube import parse_youtube_url


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


def test_parse_youtu_be_url() -> None:
    parsed = parse_youtube_url("https://youtu.be/abc123xyz?t=12")
    assert parsed.video_id == "abc123xyz"
    assert parsed.normalized_url == "https://www.youtube.com/watch?v=abc123xyz"


def test_parse_youtube_shorts_url() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/shorts/abc123xyz")
    assert parsed.video_id == "abc123xyz"
    assert parsed.normalized_url == "https://www.youtube.com/watch?v=abc123xyz"


def test_parse_youtube_embed_url() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/embed/abc123xyz")
    assert parsed.video_id == "abc123xyz"
    assert parsed.normalized_url == "https://www.youtube.com/watch?v=abc123xyz"


def test_parse_youtube_live_url() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/live/abc123xyz")
    assert parsed.video_id == "abc123xyz"
    assert parsed.normalized_url == "https://www.youtube.com/watch?v=abc123xyz"


def test_parse_youtube_music_url() -> None:
    parsed = parse_youtube_url("https://music.youtube.com/watch?v=abc123xyz")
    assert parsed.video_id == "abc123xyz"
    assert parsed.normalized_url == "https://www.youtube.com/watch?v=abc123xyz"


def test_parse_youtube_endpoint_returns_video_id() -> None:
    response = client.post(
        "/api/parse-youtube",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz&list=demo"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "video_id": "abc123xyz",
        "normalized_url": "https://www.youtube.com/watch?v=abc123xyz",
    }


def test_parse_youtube_endpoint_rejects_invalid_url() -> None:
    response = client.post(
        "/api/parse-youtube",
        json={"url": "https://example.com/watch?v=abc123xyz"},
    )

    _assert_error_response(
        response,
        status_code=400,
        error_code="INVALID_INPUT",
        retryable=False,
        detail="URL must be a valid YouTube link.",
    )
