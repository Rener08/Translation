from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.repositories.job_repository import JobRecord
from app.repositories.job_repository import default_job_repository
from app.repositories.session_repository import SessionRepository
from app.services.account_quota_service import resolve_account_identity
import app.main as app_main


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
    _assert_error_response(
        response,
        status_code=401,
        error_code="UNAUTHORIZED",
        retryable=False,
        detail="Unauthorized API request.",
    )


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
    _assert_error_response(
        second,
        status_code=429,
        error_code="RATE_LIMITED",
        retryable=True,
        detail="Rate limit exceeded. Please retry later.",
    )


def test_anonymous_localhost_development_requests_still_work(monkeypatch) -> None:
    monkeypatch.setattr(
        app_main,
        "settings",
        replace(
            get_settings(),
            api_auth_token="",
            api_rate_limit_per_minute=120,
            account_daily_request_limit=0,
            account_max_concurrent_jobs=0,
            account_max_history_sessions=0,
        ),
    )
    with app_main._RATE_LIMIT_LOCK:
        app_main._RATE_LIMIT_BUCKETS.clear()

    monkeypatch.setattr(
        app_main,
        "discover_provider_models",
        lambda **kwargs: ["deepseek-chat"],
    )

    response = client.post(
        "/api/provider/test-connection",
        json={"provider": "deepseek"},
    )
    assert response.status_code == 200


def test_account_daily_request_quota_blocks_second_write_request(monkeypatch) -> None:
    monkeypatch.setattr(
        app_main,
        "settings",
        replace(
            get_settings(),
            api_auth_token="",
            api_rate_limit_per_minute=120,
            account_daily_request_limit=1,
            account_max_concurrent_jobs=0,
            account_max_history_sessions=0,
        ),
    )
    with app_main._RATE_LIMIT_LOCK:
        app_main._RATE_LIMIT_BUCKETS.clear()

    monkeypatch.setattr(
        app_main,
        "discover_provider_models",
        lambda **kwargs: ["deepseek-chat"],
    )

    first = client.post(
        "/api/provider/test-connection",
        json={"provider": "deepseek"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/provider/test-connection",
        json={"provider": "deepseek"},
    )
    _assert_error_response(
        second,
        status_code=429,
        error_code="ACCOUNT_DAILY_REQUEST_LIMIT_EXCEEDED",
        retryable=True,
        detail="该账号今日写入请求数已达上限。",
    )


def test_account_concurrent_job_quota_blocks_job_submission(monkeypatch) -> None:
    monkeypatch.setattr(
        app_main,
        "settings",
        replace(
            get_settings(),
            api_auth_token="",
            api_rate_limit_per_minute=120,
            account_daily_request_limit=0,
            account_max_concurrent_jobs=1,
            account_max_history_sessions=0,
        ),
    )
    with app_main._RATE_LIMIT_LOCK:
        app_main._RATE_LIMIT_BUCKETS.clear()

    account_id = resolve_account_identity(headers={}, client_ip="testclient").account_id
    default_job_repository.upsert_record(
        JobRecord(
            job_id="job-account-limit",
            status="running",
            progress_value=20,
            progress_text="running",
            task_payload={"account_id": account_id},
        )
    )

    response = client.post(
        "/api/jobs/run",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )
    _assert_error_response(
        response,
        status_code=429,
        error_code="ACCOUNT_MAX_CONCURRENT_JOBS_EXCEEDED",
        retryable=True,
        detail="该账号的并发任务数已达上限。",
    )


def test_account_history_session_quota_blocks_job_submission(monkeypatch) -> None:
    monkeypatch.setattr(
        app_main,
        "settings",
        replace(
            get_settings(),
            api_auth_token="",
            api_rate_limit_per_minute=120,
            account_daily_request_limit=0,
            account_max_concurrent_jobs=0,
            account_max_history_sessions=1,
        ),
    )
    with app_main._RATE_LIMIT_LOCK:
        app_main._RATE_LIMIT_BUCKETS.clear()

    account_id = resolve_account_identity(headers={}, client_ip="testclient").account_id
    session_repo = SessionRepository()
    session_repo.upsert_job_session(
        content_context_id="ctx_account_limit",
        account_id=account_id,
        video_id="abc123xyz",
        video_url="https://www.youtube.com/watch?v=abc123xyz",
        video_title="Test video",
        source_mode="subtitle_first",
        source_type="captions",
        translation_provider="deepseek",
        translation_model="deepseek-chat",
        transcript_en_text="Hello",
        transcript_en_segments=[],
        translation_zh_text="你好",
        translation_zh_segments=[],
    )

    response = client.post(
        "/api/jobs/run",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )
    _assert_error_response(
        response,
        status_code=429,
        error_code="ACCOUNT_MAX_HISTORY_SESSIONS_EXCEEDED",
        retryable=True,
        detail="该账号的历史会话数已达上限。",
    )
