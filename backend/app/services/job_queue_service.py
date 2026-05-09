from __future__ import annotations

import logging
import json
import os
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from app.config import get_env_str, get_settings


logger = logging.getLogger(__name__)
JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]


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
    cancel_requested: bool = False
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


_JOB_RECORDS: dict[str, JobRecord] = {}
_JOB_RECORDS_LOCK = threading.RLock()
_JOB_EXECUTOR: ThreadPoolExecutor | None = None
_JOB_EXECUTOR_MAX_WORKERS: int | None = None
_JOB_EXECUTOR_LOCK = threading.Lock()
_JOB_DB_LOCK = threading.RLock()
_JOB_DB_INITIALIZED = False


def submit_background_job(
    target: Callable[[str], None],
    *,
    job_id: str | None = None,
) -> str:
    normalized_job_id = str(job_id or uuid4().hex).strip()
    record = JobRecord(job_id=normalized_job_id)
    with _JOB_RECORDS_LOCK:
        _JOB_RECORDS[normalized_job_id] = record
        _upsert_record_db(record)
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
        if record is not None:
            return _copy_record(record)

    db_record = _load_record_from_db(normalized_job_id)
    if db_record is None:
        return None
    with _JOB_RECORDS_LOCK:
        _JOB_RECORDS[normalized_job_id] = db_record
        return _copy_record(db_record)


def prune_job_records() -> None:
    with _JOB_RECORDS_LOCK:
        _prune_job_records_locked()
        _prune_records_db_locked()


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
        if record.status == "cancelled":
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
        _upsert_record_db(record)


def request_job_cancel(job_id: str) -> JobRecord | None:
    normalized_job_id = _normalize_job_id(job_id)
    if not normalized_job_id:
        return None

    with _JOB_RECORDS_LOCK:
        record = _JOB_RECORDS.get(normalized_job_id)
        if record is None:
            return None

        if record.status in {"done", "failed", "cancelled"}:
            return _copy_record(record)

        record.cancel_requested = True
        record.status = "cancelled"
        record.progress_value = 100
        record.progress_text = "任务已取消"
        record.error = "任务被用户取消。"
        record.error_code = "JOB_CANCELLED"
        record.retryable = False
        record.updated_at = _now_iso()
        _upsert_record_db(record)
        return _copy_record(record)


def is_job_cancel_requested(job_id: str) -> bool:
    normalized_job_id = _normalize_job_id(job_id)
    if not normalized_job_id:
        return False
    with _JOB_RECORDS_LOCK:
        record = _JOB_RECORDS.get(normalized_job_id)
        if record is None:
            return False
        return bool(record.cancel_requested or record.status == "cancelled")


def _run_background_job(job_id: str, target: Callable[[str], None]) -> None:
    try:
        if is_job_cancel_requested(job_id):
            return
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
    _prune_records_db_locked()


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
        cancel_requested=record.cancel_requested,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _normalize_job_id(job_id: str) -> str:
    return str(job_id or "").strip()


def _job_db_path() -> str:
    settings = get_settings()
    settings.job_queue_db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(settings.job_queue_db_path)


def _init_job_db() -> None:
    global _JOB_DB_INITIALIZED
    if _JOB_DB_INITIALIZED:
        return
    with _JOB_DB_LOCK:
        if _JOB_DB_INITIALIZED:
            return
        conn = sqlite3.connect(_job_db_path())
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_records (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    progress_value INTEGER NOT NULL,
                    progress_text TEXT NOT NULL,
                    stage TEXT NULL,
                    timeout_sec INTEGER NULL,
                    result_json TEXT NULL,
                    error TEXT NULL,
                    error_code TEXT NULL,
                    retryable INTEGER NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                UPDATE job_records
                SET status = 'failed',
                    progress_value = 100,
                    progress_text = '任务中断（服务重启）',
                    error = COALESCE(error, '任务在服务重启时中断。'),
                    error_code = COALESCE(error_code, 'JOB_INTERRUPTED_RESTART'),
                    retryable = 1,
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (_now_iso(),),
            )
            conn.commit()
        finally:
            conn.close()
        _JOB_DB_INITIALIZED = True


def _db_connect() -> sqlite3.Connection:
    _init_job_db()
    conn = sqlite3.connect(_job_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _upsert_record_db(record: JobRecord) -> None:
    with _JOB_DB_LOCK:
        conn = _db_connect()
        try:
            conn.execute(
                """
                INSERT INTO job_records (
                    job_id, status, progress_value, progress_text, stage, timeout_sec,
                    result_json, error, error_code, retryable, cancel_requested,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status = excluded.status,
                    progress_value = excluded.progress_value,
                    progress_text = excluded.progress_text,
                    stage = excluded.stage,
                    timeout_sec = excluded.timeout_sec,
                    result_json = excluded.result_json,
                    error = excluded.error,
                    error_code = excluded.error_code,
                    retryable = excluded.retryable,
                    cancel_requested = excluded.cancel_requested,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    record.job_id,
                    record.status,
                    record.progress_value,
                    record.progress_text,
                    record.stage,
                    record.timeout_sec,
                    json.dumps(record.result, ensure_ascii=False, sort_keys=True)
                    if isinstance(record.result, dict)
                    else None,
                    record.error,
                    record.error_code,
                    None if record.retryable is None else int(bool(record.retryable)),
                    int(bool(record.cancel_requested)),
                    record.created_at,
                    record.updated_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def _load_record_from_db(job_id: str) -> JobRecord | None:
    with _JOB_DB_LOCK:
        conn = _db_connect()
        try:
            row = conn.execute(
                """
                SELECT job_id, status, progress_value, progress_text, stage, timeout_sec,
                       result_json, error, error_code, retryable, cancel_requested,
                       created_at, updated_at
                FROM job_records
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        finally:
            conn.close()
    if row is None:
        return None
    return _row_to_record(row)


def _prune_records_db_locked() -> None:
    ttl_hours = _get_job_record_ttl_hours()
    max_count = _get_job_record_max_count()
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()

    with _JOB_DB_LOCK:
        conn = _db_connect()
        try:
            conn.execute(
                """
                DELETE FROM job_records
                WHERE status IN ('done', 'failed', 'cancelled') AND updated_at < ?
                """,
                (stale_cutoff,),
            )
            count_row = conn.execute("SELECT COUNT(*) AS count FROM job_records").fetchone()
            total = int(count_row["count"] if count_row is not None else 0)
            if total > max_count:
                excess = total - max_count
                conn.execute(
                    """
                    DELETE FROM job_records
                    WHERE job_id IN (
                        SELECT job_id FROM job_records
                        WHERE status IN ('done', 'failed', 'cancelled')
                        ORDER BY updated_at ASC
                        LIMIT ?
                    )
                    """,
                    (excess,),
                )
            conn.commit()
        finally:
            conn.close()


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    raw_result = row["result_json"]
    parsed_result: dict[str, Any] | None = None
    if isinstance(raw_result, str) and raw_result.strip():
        try:
            payload = json.loads(raw_result)
            if isinstance(payload, dict):
                parsed_result = payload
        except json.JSONDecodeError:
            parsed_result = None
    return JobRecord(
        job_id=str(row["job_id"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        progress_value=int(row["progress_value"]),
        progress_text=str(row["progress_text"] or ""),
        stage=str(row["stage"]) if row["stage"] else None,  # type: ignore[arg-type]
        timeout_sec=int(row["timeout_sec"]) if row["timeout_sec"] is not None else None,
        result=parsed_result,
        error=str(row["error"]) if row["error"] is not None else None,
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
        retryable=None if row["retryable"] is None else bool(int(row["retryable"])),
        cancel_requested=bool(int(row["cancel_requested"] or 0)),
        created_at=str(row["created_at"] or _now_iso()),
        updated_at=str(row["updated_at"] or _now_iso()),
    )


def reset_job_queue_state_for_tests() -> None:
    global _JOB_DB_INITIALIZED
    with _JOB_RECORDS_LOCK:
        _JOB_RECORDS.clear()
    with _JOB_DB_LOCK:
        db_path = _job_db_path()
        if os.path.exists(db_path):
            os.remove(db_path)
    _JOB_DB_INITIALIZED = False
