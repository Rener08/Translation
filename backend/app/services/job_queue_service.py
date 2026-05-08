from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


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
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


_JOB_RECORDS: dict[str, JobRecord] = {}
_JOB_RECORDS_LOCK = threading.RLock()


def submit_background_job(
    target: Callable[[str], None],
    *,
    job_id: str | None = None,
) -> str:
    normalized_job_id = str(job_id or uuid4().hex).strip()
    record = JobRecord(job_id=normalized_job_id)
    with _JOB_RECORDS_LOCK:
        _JOB_RECORDS[normalized_job_id] = record

    thread = threading.Thread(
        target=_run_background_job,
        args=(normalized_job_id, target),
        daemon=True,
        name=f"job-{normalized_job_id[:8]}",
    )
    thread.start()
    return normalized_job_id


def get_job_record(job_id: str) -> JobRecord | None:
    normalized_job_id = _normalize_job_id(job_id)
    if not normalized_job_id:
        return None

    with _JOB_RECORDS_LOCK:
        record = _JOB_RECORDS.get(normalized_job_id)
        if record is None:
            return None
        return _copy_record(record)


def update_job_progress(
    job_id: str,
    *,
    status: JobStatus | None = None,
    progress_value: int | None = None,
    progress_text: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
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
        if result is not None:
            record.result = dict(result)
        if error is not None:
            record.error = str(error).strip() or None
        record.updated_at = _now_iso()


def _run_background_job(job_id: str, target: Callable[[str], None]) -> None:
    try:
        update_job_progress(job_id, status="running", progress_value=5, progress_text="正在处理")
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


def _copy_record(record: JobRecord) -> JobRecord:
    return JobRecord(
        job_id=record.job_id,
        status=record.status,
        progress_value=record.progress_value,
        progress_text=record.progress_text,
        result=dict(record.result) if isinstance(record.result, dict) else None,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _normalize_job_id(job_id: str) -> str:
    return str(job_id or "").strip()
