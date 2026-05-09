from __future__ import annotations

import logging
import json
import os
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from app.config import get_env_str, get_settings


logger = logging.getLogger(__name__)
JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]
JobTaskHandler = Callable[[str, dict[str, Any]], None]


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
    task_type: str | None = None
    task_payload: dict[str, Any] | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


_JOB_RECORDS: dict[str, JobRecord] = {}
_JOB_RECORDS_LOCK = threading.RLock()
_JOB_EXECUTOR: ThreadPoolExecutor | None = None
_JOB_EXECUTOR_MAX_WORKERS: int | None = None
_JOB_EXECUTOR_LOCK = threading.Lock()
_JOB_DB_LOCK = threading.RLock()
_JOB_DB_INITIALIZED = False
_JOB_TASK_HANDLERS: dict[str, JobTaskHandler] = {}
_JOB_TASK_HANDLERS_LOCK = threading.RLock()
_JOB_DISPATCHER_THREAD: threading.Thread | None = None
_JOB_DISPATCHER_STOP_EVENT = threading.Event()
_JOB_DISPATCHER_WAKE_EVENT = threading.Event()
_JOB_DISPATCHER_LOCK = threading.Lock()
_JOB_ACTIVE_FUTURES: dict[str, Future[Any] | None] = {}
_JOB_ACTIVE_FUTURES_LOCK = threading.RLock()


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


def register_job_task_handler(task_type: str, handler: JobTaskHandler) -> None:
    normalized_task_type = str(task_type or "").strip()
    if not normalized_task_type:
        raise ValueError("task_type is required.")

    with _JOB_TASK_HANDLERS_LOCK:
        _JOB_TASK_HANDLERS[normalized_task_type] = handler
    _start_dispatcher_if_needed()
    _JOB_DISPATCHER_WAKE_EVENT.set()


def submit_persistent_job(
    task_type: str,
    task_payload: dict[str, Any],
    *,
    job_id: str | None = None,
) -> str:
    normalized_job_id = str(job_id or uuid4().hex).strip()
    normalized_task_type = str(task_type or "").strip()
    if not normalized_task_type:
        raise ValueError("task_type is required.")
    if not isinstance(task_payload, dict):
        raise ValueError("task_payload must be a dict.")

    record = JobRecord(
        job_id=normalized_job_id,
        task_type=normalized_task_type,
        task_payload=dict(task_payload),
    )
    with _JOB_RECORDS_LOCK:
        _JOB_RECORDS[normalized_job_id] = record
        _upsert_record_db(record)
        _prune_job_records_locked()
    _start_dispatcher_if_needed()
    _JOB_DISPATCHER_WAKE_EVENT.set()
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
            loaded = _load_record_from_db(normalized_job_id)
            if loaded is None:
                return
            _JOB_RECORDS[normalized_job_id] = loaded
            record = loaded
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
            loaded = _load_record_from_db(normalized_job_id)
            if loaded is None:
                return None
            _JOB_RECORDS[normalized_job_id] = loaded
            record = loaded

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
            loaded = _load_record_from_db(normalized_job_id)
            if loaded is None:
                return False
            _JOB_RECORDS[normalized_job_id] = loaded
            record = loaded
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


def _start_dispatcher_if_needed() -> None:
    global _JOB_DISPATCHER_THREAD
    with _JOB_DISPATCHER_LOCK:
        thread = _JOB_DISPATCHER_THREAD
        if thread is not None and thread.is_alive():
            return
        _JOB_DISPATCHER_STOP_EVENT.clear()
        _JOB_DISPATCHER_WAKE_EVENT.clear()
        _JOB_DISPATCHER_THREAD = threading.Thread(
            target=_persistent_dispatcher_loop,
            name="job-persistent-dispatcher",
            daemon=True,
        )
        _JOB_DISPATCHER_THREAD.start()


def _persistent_dispatcher_loop() -> None:
    while not _JOB_DISPATCHER_STOP_EVENT.is_set():
        try:
            _dispatch_queued_persistent_jobs()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Persistent job dispatcher loop failed.")
        _JOB_DISPATCHER_WAKE_EVENT.wait(timeout=0.5)
        _JOB_DISPATCHER_WAKE_EVENT.clear()


def _dispatch_queued_persistent_jobs() -> None:
    with _JOB_TASK_HANDLERS_LOCK:
        task_types = tuple(_JOB_TASK_HANDLERS.keys())
    if not task_types:
        return

    available = _available_worker_slots()
    if available <= 0:
        return

    queued_records = _load_dispatchable_jobs_db(task_types=task_types, limit=available)
    if not queued_records:
        return

    executor = _get_job_executor()
    for record in queued_records:
        if record.cancel_requested or record.status != "queued":
            continue
        if not record.task_type:
            continue
        payload = dict(record.task_payload or {})
        with _JOB_RECORDS_LOCK:
            _JOB_RECORDS[record.job_id] = record
        if not _mark_job_future_active(record.job_id):
            continue
        future = executor.submit(
            _run_registered_task_job,
            record.job_id,
            record.task_type,
            payload,
        )
        _set_job_future(record.job_id, future)
        future.add_done_callback(lambda _f, job_id=record.job_id: _on_job_future_done(job_id))


def _run_registered_task_job(job_id: str, task_type: str, payload: dict[str, Any]) -> None:
    with _JOB_TASK_HANDLERS_LOCK:
        handler = _JOB_TASK_HANDLERS.get(task_type)
    if handler is None:
        update_job_progress(
            job_id,
            status="failed",
            progress_value=100,
            progress_text="处理失败",
            error=f"No handler registered for task type: {task_type}",
            error_code="JOB_HANDLER_NOT_FOUND",
            retryable=False,
        )
        return
    _run_background_job(job_id, lambda resolved_job_id: handler(resolved_job_id, payload))


def _set_job_future(job_id: str, future: Future[Any]) -> None:
    with _JOB_ACTIVE_FUTURES_LOCK:
        _JOB_ACTIVE_FUTURES[job_id] = future


def _mark_job_future_active(job_id: str) -> bool:
    with _JOB_ACTIVE_FUTURES_LOCK:
        existing = _JOB_ACTIVE_FUTURES.get(job_id)
        if existing is None and job_id in _JOB_ACTIVE_FUTURES:
            return False
        if isinstance(existing, Future) and not existing.done():
            return False
        _JOB_ACTIVE_FUTURES[job_id] = None
        return True


def _on_job_future_done(job_id: str) -> None:
    with _JOB_ACTIVE_FUTURES_LOCK:
        _JOB_ACTIVE_FUTURES.pop(job_id, None)
    _JOB_DISPATCHER_WAKE_EVENT.set()


def _available_worker_slots() -> int:
    max_workers = _get_job_queue_max_workers()
    with _JOB_ACTIVE_FUTURES_LOCK:
        stale_job_ids = [
            job_id
            for job_id, future in _JOB_ACTIVE_FUTURES.items()
            if isinstance(future, Future) and future.done()
        ]
        for job_id in stale_job_ids:
            _JOB_ACTIVE_FUTURES.pop(job_id, None)
        active_count = len(_JOB_ACTIVE_FUTURES)
    remaining = max_workers - active_count
    if remaining < 0:
        return 0
    return remaining


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
        task_type=record.task_type,
        task_payload=dict(record.task_payload)
        if isinstance(record.task_payload, dict)
        else None,
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
                    task_type TEXT NULL,
                    task_payload_json TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            _ensure_job_records_column(conn, "task_type", "TEXT NULL")
            _ensure_job_records_column(conn, "task_payload_json", "TEXT NULL")
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
                WHERE status = 'running'
                """,
                (_now_iso(),),
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
                WHERE status = 'queued' AND (task_type IS NULL OR TRIM(task_type) = '')
                """,
                (_now_iso(),),
            )
            conn.commit()
        finally:
            conn.close()
        _JOB_DB_INITIALIZED = True


def _ensure_job_records_column(
    conn: sqlite3.Connection,
    column_name: str,
    ddl_suffix: str,
) -> None:
    try:
        conn.execute(
            f"ALTER TABLE job_records ADD COLUMN {column_name} {ddl_suffix}"  # noqa: S608
        )
    except sqlite3.OperationalError:
        # Column already exists.
        return


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
                    task_type, task_payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    task_type = excluded.task_type,
                    task_payload_json = excluded.task_payload_json,
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
                    record.task_type,
                    json.dumps(record.task_payload, ensure_ascii=False, sort_keys=True)
                    if isinstance(record.task_payload, dict)
                    else None,
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
                       task_type, task_payload_json,
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


def _load_dispatchable_jobs_db(
    *,
    task_types: tuple[str, ...],
    limit: int,
) -> list[JobRecord]:
    if not task_types or limit <= 0:
        return []

    placeholders = ", ".join("?" for _ in task_types)
    with _JOB_DB_LOCK:
        conn = _db_connect()
        try:
            rows = conn.execute(
                f"""
                SELECT job_id, status, progress_value, progress_text, stage, timeout_sec,
                       result_json, error, error_code, retryable, cancel_requested,
                       task_type, task_payload_json,
                       created_at, updated_at
                FROM job_records
                WHERE status = 'queued'
                  AND cancel_requested = 0
                  AND task_type IN ({placeholders})
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (*task_types, int(limit)),
            ).fetchall()
        finally:
            conn.close()
    return [_row_to_record(row) for row in rows]


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
    raw_task_payload = row["task_payload_json"]
    parsed_task_payload: dict[str, Any] | None = None
    if isinstance(raw_task_payload, str) and raw_task_payload.strip():
        try:
            payload = json.loads(raw_task_payload)
            if isinstance(payload, dict):
                parsed_task_payload = payload
        except json.JSONDecodeError:
            parsed_task_payload = None
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
        task_type=str(row["task_type"]) if row["task_type"] is not None else None,
        task_payload=parsed_task_payload,
        created_at=str(row["created_at"] or _now_iso()),
        updated_at=str(row["updated_at"] or _now_iso()),
    )


def reset_job_queue_state_for_tests() -> None:
    global _JOB_DB_INITIALIZED, _JOB_DISPATCHER_THREAD
    _JOB_DISPATCHER_STOP_EVENT.set()
    _JOB_DISPATCHER_WAKE_EVENT.set()
    dispatcher = _JOB_DISPATCHER_THREAD
    if dispatcher is not None and dispatcher.is_alive():
        dispatcher.join(timeout=1)
    _JOB_DISPATCHER_THREAD = None
    _JOB_DISPATCHER_STOP_EVENT.clear()
    _JOB_DISPATCHER_WAKE_EVENT.clear()
    with _JOB_ACTIVE_FUTURES_LOCK:
        _JOB_ACTIVE_FUTURES.clear()
    with _JOB_RECORDS_LOCK:
        _JOB_RECORDS.clear()
    with _JOB_DB_LOCK:
        db_path = _job_db_path()
        if os.path.exists(db_path):
            os.remove(db_path)
    _JOB_DB_INITIALIZED = False
