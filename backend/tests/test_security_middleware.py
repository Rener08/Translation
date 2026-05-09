from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
import app.main as app_main


client = TestClient(app)


def test_api_token_auth_blocks_missing_token(monkeypatch) -> None:
    monkeypatch.setattr(
        app_main,
        "settings",
        replace(get_settings(), api_auth_token="demo-token", api_rate_limit_per_minute=120),
    )
    with app_main._RATE_LIMIT_LOCK:
        app_main._RATE_LIMIT_BUCKETS.clear()

    response = client.post(
        "/api/jobs/run",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )
    assert response.status_code == 401


def test_api_token_auth_accepts_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr(
        app_main,
        "settings",
        replace(get_settings(), api_auth_token="demo-token", api_rate_limit_per_minute=120),
    )
    with app_main._RATE_LIMIT_LOCK:
        app_main._RATE_LIMIT_BUCKETS.clear()

    response = client.post(
        "/api/jobs/run",
        headers={"Authorization": "Bearer demo-token"},
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )
    assert response.status_code in {202, 502}


def test_rate_limit_blocks_excess_write_requests(monkeypatch) -> None:
    monkeypatch.setattr(
        app_main,
        "settings",
        replace(get_settings(), api_auth_token="", api_rate_limit_per_minute=1),
    )
    with app_main._RATE_LIMIT_LOCK:
        app_main._RATE_LIMIT_BUCKETS.clear()

    first = client.post(
        "/api/jobs/run",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )
    assert first.status_code in {202, 400, 422, 502}

    second = client.post(
        "/api/jobs/run",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )
    assert second.status_code == 429
