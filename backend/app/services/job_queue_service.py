from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from app.config import get_env_str


logger = logging.getLogger(__name__)
JobStatus = Literal["queued", "running", "done", "failed"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus = "queued"
    progress_value: int = 0
    progress_text: str = "已加入队列"
    stage: Literal["inspect", "fetch_source", "transcribe", "translate", "persist"] | None = None
    timeout_sec: int | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


_JOB_RECORDS: dict[str, JobRecord] = {}
_JOB_RECORDS_LOCK = threading.RLock()
_JOB_EXECUTOR: ThreadPoolExecutor | None = None
_JOB_EXECUTOR_MAX_WORKERS: int | None = None
_JOB_EXECUTOR_LOCK = threading.Lock()


def submit_background_job(
    target: Callable[[str], None],
    *,
    job_id: str | None = None,
) -> str:
    normalized_job_id = str(job_id or uuid4().hex).strip()
    record = JobRecord(job_id=normalized_job_id)
    with _JOB_RECORDS_LOCK:
        _JOB_RECORDS[normalized_job_id] = record
        _prune_job_records_locked()

    _get_job_executor().submit(_run_background_job, normalized_job_id, target)
    return normalized_job_id


def get_job_record(job_id: str) -> JobRecord | None:
    normalized_job_id = _normalize_job_id(job_id)
    if not normalized_job_id:
        return None

    with _JOB_RECORDS_LOCK:
        _prune_job_records_locked()
        record = _JOB_RECORDS.get(normalized_job_id)
        if record is None:
            return None
        return _copy_record(record)


def prune_job_records() -> None:
    with _JOB_RECORDS_LOCK:
        _prune_job_records_locked()


def update_job_progress(
    job_id: str,
    *,
    status: JobStatus | None = None,
    progress_value: int | None = None,
    progress_text: str | None = None,
    stage: Literal["inspect", "fetch_source", "transcribe", "translate", "persist"] | None = None,
    timeout_sec: int | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    error_code: str | None = None,
    retryable: bool | None = None,
) -> None:
    normalized_job_id = _normalize_job_id(job_id)
    if not normalized_job_id:
        return

    with _JOB_RECORDS_LOCK:
        record = _JOB_RECORDS.get(normalized_job_id)
        if record is None:
            return

        if status is not None:
            record.status = status
        if progress_value is not None:
            record.progress_value = max(0, min(100, int(progress_value)))
        if progress_text is not None:
            record.progress_text = str(progress_text).strip()
        if stage is not None:
            record.stage = stage
        if timeout_sec is not None:
            record.timeout_sec = max(0, int(timeout_sec))
        if result is not None:
            record.result = dict(result)
        if error is not None:
            record.error = str(error).strip() or None
        if error_code is not None:
            record.error_code = str(error_code).strip() or None
        if retryable is not None:
            record.retryable = bool(retryable)
        record.updated_at = _now_iso()


def _run_background_job(job_id: str, target: Callable[[str], None]) -> None:
    try:
        update_job_progress(
            job_id,
            status="running",
            progress_value=5,
            progress_text="正在处理",
        )
        target(job_id)
    except Exception as error:  # pragma: no cover - defensive
        logger.exception("Job %s failed unexpectedly", job_id)
        update_job_progress(
            job_id,
            status="failed",
            progress_value=100,
            progress_text="处理失败",
            error=str(error),
        )


def _get_job_executor() -> ThreadPoolExecutor:
    max_workers = _get_job_queue_max_workers()
    global _JOB_EXECUTOR, _JOB_EXECUTOR_MAX_WORKERS

    with _JOB_EXECUTOR_LOCK:
        if _JOB_EXECUTOR is None or _JOB_EXECUTOR_MAX_WORKERS != max_workers:
            previous_executor = _JOB_EXECUTOR
            _JOB_EXECUTOR = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="job-queue",
            )
            _JOB_EXECUTOR_MAX_WORKERS = max_workers
            if previous_executor is not None:
                previous_executor.shutdown(wait=False, cancel_futures=False)

        assert _JOB_EXECUTOR is not None
        return _JOB_EXECUTOR


def _get_job_queue_max_workers() -> int:
    return _clamp_int_env("JOB_QUEUE_MAX_WORKERS", default=1, minimum=1, maximum=4)


def _get_job_record_ttl_hours() -> int:
    return _positive_int_env("JOB_RECORD_TTL_HOURS", default=24)


def _get_job_record_max_count() -> int:
    return _positive_int_env("JOB_RECORD_MAX_COUNT", default=200)


def _positive_int_env(name: str, default: int) -> int:
    raw_value = get_env_str(name)
    if not raw_value:
        return default

    try:
        parsed = int(raw_value)
    except ValueError:
        return default

    if parsed <= 0:
        return default
    return parsed


def _clamp_int_env(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw_value = get_env_str(name)
    if not raw_value:
        return default

    try:
        parsed = int(raw_value)
    except ValueError:
        return default

    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _prune_job_records_locked() -> None:
    ttl_hours = _get_job_record_ttl_hours()
    max_count = _get_job_record_max_count()
    now = datetime.now(timezone.utc)
    finished_records: list[tuple[str, datetime]] = []

    for job_id, record in list(_JOB_RECORDS.items()):
        if record.status in ("queued", "running"):
            continue
        finished_records.append((job_id, _parse_record_timestamp(record.updated_at)))

    stale_cutoff = now - timedelta(hours=ttl_hours)
    for job_id, updated_at in finished_records:
        if updated_at < stale_cutoff:
            _JOB_RECORDS.pop(job_id, None)

    if len(_JOB_RECORDS) <= max_count:
        return

    remaining_finished = sorted(
        (
            (job_id, updated_at)
            for job_id, updated_at in finished_records
            if job_id in _JOB_RECORDS
        ),
        key=lambda item: item[1],
    )
    excess = len(_JOB_RECORDS) - max_count
    for job_id, _ in remaining_finished[:excess]:
        _JOB_RECORDS.pop(job_id, None)


def _parse_record_timestamp(value: str) -> datetime:
    normalized_value = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized_value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _copy_record(record: JobRecord) -> JobRecord:
    return JobRecord(
        job_id=record.job_id,
        status=record.status,
        progress_value=record.progress_value,
        progress_text=record.progress_text,
        stage=record.stage,
        timeout_sec=record.timeout_sec,
        result=dict(record.result) if isinstance(record.result, dict) else None,
        error=record.error,
        error_code=record.error_code,
        retryable=record.retryable,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _normalize_job_id(job_id: str) -> str:
    return str(job_id or "").strip()
