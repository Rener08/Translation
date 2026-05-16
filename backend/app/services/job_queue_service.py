from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from app.config import get_env_str
from app.repositories.job_repository import (
    JobRecord,
    JobStatus,
    clone_job_record,
    default_job_repository,
)


logger = logging.getLogger(__name__)
JobTaskHandler = Callable[[str, dict[str, Any]], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_JOB_RECORDS: dict[str, JobRecord] = {}
_JOB_RECORDS_LOCK = threading.RLock()
_JOB_EXECUTOR: ThreadPoolExecutor | None = None
_JOB_EXECUTOR_MAX_WORKERS: int | None = None
_JOB_EXECUTOR_LOCK = threading.Lock()
_JOB_TASK_HANDLERS: dict[str, JobTaskHandler] = {}
_JOB_TASK_HANDLERS_LOCK = threading.RLock()
_JOB_DISPATCHER_THREAD: threading.Thread | None = None
_JOB_DISPATCHER_STOP_EVENT = threading.Event()
_JOB_DISPATCHER_WAKE_EVENT = threading.Event()
_JOB_DISPATCHER_LOCK = threading.Lock()
_JOB_ACTIVE_FUTURES: dict[str, Future[Any] | None] = {}
_JOB_ACTIVE_FUTURES_LOCK = threading.RLock()
_JOB_WORKER_ID = uuid4().hex


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
    stage: Literal["inspect", "fetch_source", "transcribe", "persist"] | None = None,
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
        if status in {"done", "failed", "cancelled"}:
            record.claimed_by = None
            record.claimed_at = None
            record.lease_expires_at = None
            record.last_heartbeat_at = None
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
        record.claimed_by = None
        record.claimed_at = None
        record.lease_expires_at = None
        record.last_heartbeat_at = None
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
        from app.services.job_run_service import JobCancelledError  # lazy import avoids circular dependency
        if isinstance(error, JobCancelledError):
            return
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

    lease_seconds = _get_job_queue_lease_seconds()
    claimed_records = _claim_dispatchable_jobs_db(
        task_types=task_types,
        limit=available,
        worker_id=_JOB_WORKER_ID,
        lease_seconds=lease_seconds,
    )
    if not claimed_records:
        return

    executor = _get_job_executor()
    for record in claimed_records:
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
            worker_id=_JOB_WORKER_ID,
            lease_seconds=lease_seconds,
        )
        _set_job_future(record.job_id, future)
        future.add_done_callback(lambda _f, job_id=record.job_id: _on_job_future_done(job_id))


def _run_registered_task_job(
    job_id: str,
    task_type: str,
    payload: dict[str, Any],
    *,
    worker_id: str,
    lease_seconds: int,
) -> None:
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_job_lease_heartbeat_loop,
        args=(job_id, worker_id, lease_seconds, heartbeat_stop),
        daemon=True,
        name=f"job-lease-heartbeat-{job_id}",
    )
    heartbeat_thread.start()
    with _JOB_TASK_HANDLERS_LOCK:
        handler = _JOB_TASK_HANDLERS.get(task_type)
    if handler is None:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)
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
    try:
        _run_background_job(job_id, lambda resolved_job_id: handler(resolved_job_id, payload))
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)


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


def _job_lease_heartbeat_loop(
    job_id: str,
    worker_id: str,
    lease_seconds: int,
    stop_event: threading.Event,
) -> None:
    interval = max(5, min(30, max(1, lease_seconds // 3)))
    while not stop_event.wait(timeout=interval):
        renewed = default_job_repository.renew_lease(
            job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        if not renewed:
            return


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


def _get_job_queue_lease_seconds() -> int:
    return _positive_int_env("JOB_QUEUE_LEASE_SECONDS", default=1800)


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
    return clone_job_record(record)


def _normalize_job_id(job_id: str) -> str:
    return str(job_id or "").strip()


def _init_job_db() -> None:
    default_job_repository.initialize()


def _upsert_record_db(record: JobRecord) -> None:
    default_job_repository.upsert_record(record)


def _load_record_from_db(job_id: str) -> JobRecord | None:
    return default_job_repository.load_record(job_id)


def _load_dispatchable_jobs_db(
    *,
    task_types: tuple[str, ...],
    limit: int,
) -> list[JobRecord]:
    return default_job_repository.load_dispatchable_records(
        task_types=task_types,
        limit=limit,
    )


def _claim_dispatchable_jobs_db(
    *,
    task_types: tuple[str, ...],
    limit: int,
    worker_id: str,
    lease_seconds: int,
) -> list[JobRecord]:
    return default_job_repository.claim_dispatchable_records(
        task_types=task_types,
        limit=limit,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )


def _prune_records_db_locked() -> None:
    default_job_repository.prune_records(
        ttl_hours=_get_job_record_ttl_hours(),
        max_count=_get_job_record_max_count(),
    )


def reset_job_queue_state_for_tests() -> None:
    global _JOB_DISPATCHER_THREAD
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
    default_job_repository.reset_for_tests()
