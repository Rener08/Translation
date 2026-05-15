from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time

import pytest

from app.config import get_settings
from app.repositories.job_repository import JobRecord, JobRepository


def _timestamp(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_job_repository_persists_and_loads_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("JOB_QUEUE_DB_PATH", str(tmp_path / "job_queue.sqlite"))
    get_settings.cache_clear()

    repo = JobRepository()
    repo.upsert_record(
        JobRecord(
            job_id="job-one",
            status="queued",
            progress_value=12,
            progress_text="已加入队列",
            task_type="video_job_v1",
            task_payload={"url": "https://example.com"},
        )
    )

    loaded = repo.load_record("job-one")
    assert loaded is not None
    assert loaded.job_id == "job-one"
    assert loaded.status == "queued"
    assert loaded.progress_value == 12
    assert loaded.task_type == "video_job_v1"
    assert loaded.task_payload == {"url": "https://example.com"}

    dispatchable = repo.load_dispatchable_records(
        task_types=("video_job_v1",),
        limit=10,
    )
    assert [record.job_id for record in dispatchable] == ["job-one"]


def test_job_repository_prunes_finished_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("JOB_QUEUE_DB_PATH", str(tmp_path / "job_queue.sqlite"))
    get_settings.cache_clear()

    repo = JobRepository()
    repo.upsert_record(
        JobRecord(
            job_id="old-done",
            status="done",
            progress_value=100,
            progress_text="完成",
            updated_at=_timestamp(48),
        )
    )
    repo.upsert_record(
        JobRecord(
            job_id="running",
            status="running",
            progress_text="处理中",
            updated_at=_timestamp(48),
        )
    )

    repo.prune_records(ttl_hours=24, max_count=200)

    assert repo.load_record("old-done") is None
    assert repo.load_record("running") is not None


def test_job_repository_claims_records_once_and_reclaims_after_lease_expiry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("JOB_QUEUE_DB_PATH", str(tmp_path / "job_queue.sqlite"))
    get_settings.cache_clear()

    repo = JobRepository()
    repo.upsert_record(
        JobRecord(
            job_id="job-one",
            status="queued",
            progress_value=0,
            progress_text="已加入队列",
            task_type="video_job_v1",
            task_payload={"account_id": "user:alice"},
        )
    )

    first_claim = repo.claim_dispatchable_records(
        task_types=("video_job_v1",),
        limit=1,
        worker_id="worker-a",
        lease_seconds=1,
    )
    assert [record.job_id for record in first_claim] == ["job-one"]
    assert first_claim[0].status == "running"
    assert first_claim[0].claimed_by == "worker-a"
    assert first_claim[0].attempt_count == 1

    second_claim = repo.claim_dispatchable_records(
        task_types=("video_job_v1",),
        limit=1,
        worker_id="worker-b",
        lease_seconds=1,
    )
    assert second_claim == []

    time.sleep(1.2)

    third_claim = repo.claim_dispatchable_records(
        task_types=("video_job_v1",),
        limit=1,
        worker_id="worker-b",
        lease_seconds=1,
    )
    assert [record.job_id for record in third_claim] == ["job-one"]
    assert third_claim[0].claimed_by == "worker-b"
    assert third_claim[0].attempt_count == 2

    loaded = repo.load_record("job-one")
    assert loaded is not None
    assert loaded.claimed_by == "worker-b"
    assert loaded.attempt_count == 2


def test_job_repository_renews_running_job_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("JOB_QUEUE_DB_PATH", str(tmp_path / "job_queue.sqlite"))
    get_settings.cache_clear()

    repo = JobRepository()
    repo.upsert_record(
        JobRecord(
            job_id="job-two",
            status="queued",
            progress_text="已加入队列",
            task_type="video_job_v1",
            task_payload={"account_id": "user:alice"},
        )
    )

    claimed = repo.claim_dispatchable_records(
        task_types=("video_job_v1",),
        limit=1,
        worker_id="worker-a",
        lease_seconds=1,
    )
    assert len(claimed) == 1

    renewed = repo.renew_lease("job-two", worker_id="worker-a", lease_seconds=2)
    assert renewed is True
