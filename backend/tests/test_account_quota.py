from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.repositories.account_quota_repository import AccountQuotaRepository
from app.repositories.job_repository import JobRecord, JobRepository
from app.repositories.session_repository import SessionRepository
from app.services.account_quota_service import (
    AccountQuotaService,
    resolve_account_identity,
)


def _use_tmp_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.services.persistent_cache_service.CACHE_ROOT_DIR",
        tmp_path / "persistent_cache",
    )


def test_resolve_account_identity_prefers_user_and_workspace_headers() -> None:
    identity = resolve_account_identity(
        headers={"x-user-id": "alice", "x-workspace-id": "workspace-1"},
        client_ip="127.0.0.1",
    )

    assert identity.account_id == "workspace:workspace-1:user:alice"
    assert identity.source == "workspace_user"
    assert identity.user_id == "alice"
    assert identity.workspace_id == "workspace-1"
    assert identity.anonymous is False


def test_resolve_account_identity_uses_api_token_fingerprint() -> None:
    identity = resolve_account_identity(
        headers={"authorization": "Bearer secret-token"},
        client_ip="10.0.0.2",
    )

    assert identity.account_id.startswith("token:")
    assert len(identity.api_token_fingerprint or "") == 16
    assert identity.source == "api_token"


def test_resolve_account_identity_ignores_user_headers_in_production_by_default(
    monkeypatch,
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "production")
    monkeypatch.setenv("API_AUTH_TOKEN", "demo-token")

    identity = resolve_account_identity(
        headers={"x-user-id": "alice", "x-workspace-id": "workspace-1"},
        client_ip="127.0.0.1",
    )

    assert identity.account_id == "anonymous-localhost"
    assert identity.source == "anonymous_localhost"
    assert identity.anonymous is True


def test_resolve_account_identity_trusts_user_headers_when_enabled(
    monkeypatch,
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "production")
    monkeypatch.setenv("API_AUTH_TOKEN", "demo-token")
    monkeypatch.setenv("TRUST_ACCOUNT_HEADERS", "1")

    identity = resolve_account_identity(
        headers={"x-user-id": "alice", "x-workspace-id": "workspace-1"},
        client_ip="127.0.0.1",
    )

    assert identity.account_id == "workspace:workspace-1:user:alice"
    assert identity.source == "workspace_user"
    assert identity.anonymous is False


def test_resolve_account_identity_ignores_trusted_headers_in_production_by_default(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "production")
    monkeypatch.setenv("API_AUTH_TOKEN", "demo-token")
    get_settings.cache_clear()
    settings = get_settings()

    identity = resolve_account_identity(
        headers={"x-user-id": "alice", "x-workspace-id": "workspace-1"},
        client_ip="10.0.0.2",
        settings=settings,
    )

    assert identity.source == "anonymous"
    assert identity.account_id == "anonymous:10.0.0.2"


def test_account_quota_repository_rolls_over_by_day(tmp_path: Path) -> None:
    repo = AccountQuotaRepository(lambda: tmp_path / "quota.sqlite")

    allowed_1, usage_1 = repo.reserve_daily_request_slot(
        "user:alice",
        limit=2,
        usage_date="2026-05-15",
    )
    allowed_2, usage_2 = repo.reserve_daily_request_slot(
        "user:alice",
        limit=2,
        usage_date="2026-05-15",
    )
    allowed_3, usage_3 = repo.reserve_daily_request_slot(
        "user:alice",
        limit=2,
        usage_date="2026-05-15",
    )
    allowed_next_day, usage_next_day = repo.reserve_daily_request_slot(
        "user:alice",
        limit=2,
        usage_date="2026-05-16",
    )

    assert allowed_1 is True
    assert usage_1.request_count == 1
    assert allowed_2 is True
    assert usage_2.request_count == 2
    assert allowed_3 is False
    assert usage_3.request_count == 2
    assert allowed_next_day is True
    assert usage_next_day.request_count == 1
    assert repo.get_daily_request_count("user:alice", usage_date="2026-05-15") == 2
    assert repo.get_daily_request_count("user:alice", usage_date="2026-05-16") == 1


def test_account_quota_service_blocks_concurrent_jobs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("ACCOUNT_MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("ACCOUNT_DAILY_REQUEST_LIMIT", "0")
    monkeypatch.setenv("ACCOUNT_MAX_HISTORY_SESSIONS", "0")
    get_settings.cache_clear()

    quota_repo = AccountQuotaRepository(lambda: tmp_path / "quota.sqlite")
    job_repo = JobRepository(lambda: tmp_path / "jobs.sqlite")
    session_repo = SessionRepository()
    service = AccountQuotaService(
        quota_repository=quota_repo,
        job_repository=job_repo,
        session_repository=session_repo,
    )

    job_repo.upsert_record(
        JobRecord(
            job_id="job-1",
            status="running",
            progress_value=20,
            progress_text="running",
            task_payload={"account_id": "user:alice"},
        )
    )

    violation = service.check_job_start_quota(
        resolve_account_identity(
            headers={"x-user-id": "alice"},
            client_ip="127.0.0.1",
        )
    )

    assert violation is not None
    assert violation.error_code == "ACCOUNT_MAX_CONCURRENT_JOBS_EXCEEDED"
    assert violation.limit == 1
    assert violation.current == 1


def test_account_quota_service_blocks_history_session_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("ACCOUNT_MAX_CONCURRENT_JOBS", "0")
    monkeypatch.setenv("ACCOUNT_DAILY_REQUEST_LIMIT", "0")
    monkeypatch.setenv("ACCOUNT_MAX_HISTORY_SESSIONS", "1")
    get_settings.cache_clear()

    quota_repo = AccountQuotaRepository(lambda: tmp_path / "quota.sqlite")
    job_repo = JobRepository(lambda: tmp_path / "jobs.sqlite")
    session_repo = SessionRepository()
    service = AccountQuotaService(
        quota_repository=quota_repo,
        job_repository=job_repo,
        session_repository=session_repo,
    )

    session_repo.upsert_job_session(
        content_context_id="ctx_12345",
        account_id="user:alice",
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

    violation = service.check_job_start_quota(
        resolve_account_identity(
            headers={"x-user-id": "alice"},
            client_ip="127.0.0.1",
        )
    )

    assert violation is not None
    assert violation.error_code == "ACCOUNT_MAX_HISTORY_SESSIONS_EXCEEDED"
    assert violation.limit == 1
    assert violation.current == 1
