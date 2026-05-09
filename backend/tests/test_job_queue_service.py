from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.services import job_queue_service
from app.services.job_queue_service import JobRecord, JobStatus


@pytest.fixture(autouse=True)
def isolate_job_queue_state() -> None:
    executor = job_queue_service._JOB_EXECUTOR
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    job_queue_service._JOB_EXECUTOR = None
    job_queue_service._JOB_EXECUTOR_MAX_WORKERS = None
    with job_queue_service._JOB_RECORDS_LOCK:
        job_queue_service._JOB_RECORDS.clear()
    job_queue_service.reset_job_queue_state_for_tests()

    yield

    executor = job_queue_service._JOB_EXECUTOR
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    job_queue_service._JOB_EXECUTOR = None
    job_queue_service._JOB_EXECUTOR_MAX_WORKERS = None
    with job_queue_service._JOB_RECORDS_LOCK:
        job_queue_service._JOB_RECORDS.clear()
    job_queue_service.reset_job_queue_state_for_tests()


def _timestamp(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _make_record(job_id: str, status: JobStatus, hours_ago: float) -> JobRecord:
    timestamp = _timestamp(hours_ago)
    return JobRecord(
        job_id=job_id,
        status=status,
        progress_value=100 if status in {"done", "failed", "cancelled"} else 0,
        progress_text=status,
        result={"job_id": job_id} if status == "done" else None,
        error="boom" if status == "failed" else None,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _wait_for_record_status(job_id: str, expected_status: str, timeout: float = 2.0) -> JobRecord:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = job_queue_service.get_job_record(job_id)
        if record is not None and record.status == expected_status:
            return record
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach status {expected_status}.")


def test_job_queue_max_workers_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_QUEUE_MAX_WORKERS", "0")
    assert job_queue_service._get_job_queue_max_workers() == 1

    monkeypatch.setenv("JOB_QUEUE_MAX_WORKERS", "9")
    assert job_queue_service._get_job_queue_max_workers() == 4


def test_prune_job_records_removes_old_finished_records_but_keeps_active_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JOB_RECORD_TTL_HOURS", "24")
    monkeypatch.setenv("JOB_RECORD_MAX_COUNT", "200")

    with job_queue_service._JOB_RECORDS_LOCK:
        job_queue_service._JOB_RECORDS.update(
            {
                "old-done": _make_record("old-done", "done", 30),
                "old-failed": _make_record("old-failed", "failed", 36),
                "recent-done": _make_record("recent-done", "done", 2),
                "queued": _make_record("queued", "queued", 40),
                "running": _make_record("running", "running", 40),
            }
        )

    job_queue_service.prune_job_records()

    with job_queue_service._JOB_RECORDS_LOCK:
        assert set(job_queue_service._JOB_RECORDS) == {"recent-done", "queued", "running"}


def test_prune_job_records_enforces_max_count_using_only_finished_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JOB_RECORD_TTL_HOURS", "24")
    monkeypatch.setenv("JOB_RECORD_MAX_COUNT", "3")

    with job_queue_service._JOB_RECORDS_LOCK:
        job_queue_service._JOB_RECORDS.update(
            {
                "queued": _make_record("queued", "queued", 50),
                "running": _make_record("running", "running", 50),
                "finished-1": _make_record("finished-1", "done", 4),
                "finished-2": _make_record("finished-2", "failed", 3),
                "finished-3": _make_record("finished-3", "done", 2),
                "finished-4": _make_record("finished-4", "done", 1),
            }
        )

    job_queue_service.prune_job_records()

    with job_queue_service._JOB_RECORDS_LOCK:
        assert set(job_queue_service._JOB_RECORDS) == {
            "queued",
            "running",
            "finished-4",
        }


def test_submit_background_job_honors_global_worker_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JOB_QUEUE_MAX_WORKERS", "1")

    call_order: list[str] = []
    call_order_lock = threading.Lock()
    first_release = threading.Event()
    second_release = threading.Event()
    first_started = threading.Event()
    second_started = threading.Event()

    def target(job_id: str) -> None:
        with call_order_lock:
            call_order.append(job_id)
            order = len(call_order)

        if order == 1:
            first_started.set()
            assert first_release.wait(timeout=2)
        elif order == 2:
            second_started.set()
            assert second_release.wait(timeout=2)
        else:
            raise AssertionError(f"Unexpected job order: {order}")

        job_queue_service.update_job_progress(
            job_id,
            status="done",
            progress_value=100,
            progress_text="完成",
            result={"job_id": job_id},
        )

    first_job_id = job_queue_service.submit_background_job(target, job_id="job-one")
    assert first_job_id == "job-one"
    assert first_started.wait(timeout=2)

    first_record = job_queue_service.get_job_record(first_job_id)
    assert first_record is not None
    assert first_record.status == "running"

    second_job_id = job_queue_service.submit_background_job(target, job_id="job-two")
    assert second_job_id == "job-two"

    time.sleep(0.2)
    second_record = job_queue_service.get_job_record(second_job_id)
    assert second_record is not None
    assert second_record.status == "queued"
    assert not second_started.is_set()

    first_release.set()
    second_running_record = _wait_for_record_status(second_job_id, "running")
    assert second_running_record.progress_value >= 5

    second_release.set()
    assert _wait_for_record_status(first_job_id, "done").result == {"job_id": "job-one"}
    assert _wait_for_record_status(second_job_id, "done").result == {"job_id": "job-two"}


def test_request_job_cancel_marks_job_cancelled() -> None:
    started = threading.Event()
    release = threading.Event()

    def target(job_id: str) -> None:
        started.set()
        assert release.wait(timeout=2)
        job_queue_service.update_job_progress(
            job_id,
            status="done",
            progress_value=100,
            progress_text="完成",
        )

    job_id = job_queue_service.submit_background_job(target, job_id="cancel-me")
    assert started.wait(timeout=2)

    cancelled = job_queue_service.request_job_cancel(job_id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.cancel_requested is True
    assert job_queue_service.is_job_cancel_requested(job_id) is True

    release.set()
    final = _wait_for_record_status(job_id, "cancelled")
    assert final.error_code == "JOB_CANCELLED"
