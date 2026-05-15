from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from app.config import get_settings


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
    task_type: str | None = None
    task_payload: dict[str, Any] | None = None
    claimed_by: str | None = None
    claimed_at: str | None = None
    lease_expires_at: str | None = None
    last_heartbeat_at: str | None = None
    attempt_count: int = 0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


def clone_job_record(record: JobRecord) -> JobRecord:
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
        claimed_by=record.claimed_by,
        claimed_at=record.claimed_at,
        lease_expires_at=record.lease_expires_at,
        last_heartbeat_at=record.last_heartbeat_at,
        attempt_count=record.attempt_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class JobRepository:
    def __init__(self, db_path_getter: Callable[[], Path] | None = None) -> None:
        self._db_path_getter = db_path_getter or self._default_db_path
        self._db_lock = threading.RLock()
        self._initialized_db_path: Path | None = None

    def upsert_record(self, record: JobRecord) -> None:
        with self._db_lock:
            conn = self._db_connect()
            try:
                conn.execute(
                    """
                    INSERT INTO job_records (
                        job_id, status, progress_value, progress_text, stage, timeout_sec,
                        result_json, error, error_code, retryable, cancel_requested,
                        task_type, task_payload_json,
                        claimed_by, claimed_at, lease_expires_at, last_heartbeat_at,
                        attempt_count,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        claimed_by = excluded.claimed_by,
                        claimed_at = excluded.claimed_at,
                        lease_expires_at = excluded.lease_expires_at,
                        last_heartbeat_at = excluded.last_heartbeat_at,
                        attempt_count = excluded.attempt_count,
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
                        record.claimed_by,
                        record.claimed_at,
                        record.lease_expires_at,
                        record.last_heartbeat_at,
                        int(record.attempt_count),
                        record.created_at,
                        record.updated_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def load_record(self, job_id: str) -> JobRecord | None:
        normalized_job_id = _normalize_job_id(job_id)
        if not normalized_job_id:
            return None

        with self._db_lock:
            conn = self._db_connect()
            try:
                row = conn.execute(
                    """
                    SELECT job_id, status, progress_value, progress_text, stage, timeout_sec,
                           result_json, error, error_code, retryable, cancel_requested,
                           task_type, task_payload_json,
                           claimed_by, claimed_at, lease_expires_at, last_heartbeat_at,
                           attempt_count,
                           created_at, updated_at
                    FROM job_records
                    WHERE job_id = ?
                    """,
                    (normalized_job_id,),
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            return None
        return _row_to_record(row)

    def load_dispatchable_records(
        self,
        *,
        task_types: tuple[str, ...],
        limit: int,
    ) -> list[JobRecord]:
        if not task_types or limit <= 0:
            return []

        placeholders = ", ".join("?" for _ in task_types)
        with self._db_lock:
            conn = self._db_connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT job_id, status, progress_value, progress_text, stage, timeout_sec,
                           result_json, error, error_code, retryable, cancel_requested,
                           task_type, task_payload_json,
                           claimed_by, claimed_at, lease_expires_at, last_heartbeat_at,
                           attempt_count,
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

    def list_records(self, *, statuses: tuple[str, ...] | None = None) -> list[JobRecord]:
        with self._db_lock:
            conn = self._db_connect()
            try:
                if statuses:
                    placeholders = ", ".join("?" for _ in statuses)
                    rows = conn.execute(
                        f"""
                        SELECT job_id, status, progress_value, progress_text, stage, timeout_sec,
                               result_json, error, error_code, retryable, cancel_requested,
                               task_type, task_payload_json,
                               claimed_by, claimed_at, lease_expires_at, last_heartbeat_at,
                               attempt_count,
                               created_at, updated_at
                        FROM job_records
                        WHERE status IN ({placeholders})
                        ORDER BY created_at ASC
                        """,
                        statuses,
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT job_id, status, progress_value, progress_text, stage, timeout_sec,
                               result_json, error, error_code, retryable, cancel_requested,
                               task_type, task_payload_json,
                               claimed_by, claimed_at, lease_expires_at, last_heartbeat_at,
                               attempt_count,
                               created_at, updated_at
                        FROM job_records
                        ORDER BY created_at ASC
                        """
                    ).fetchall()
            finally:
                conn.close()
        return [_row_to_record(row) for row in rows]

    def claim_dispatchable_records(
        self,
        *,
        task_types: tuple[str, ...],
        limit: int,
        worker_id: str,
        lease_seconds: int,
    ) -> list[JobRecord]:
        normalized_worker_id = _normalize_text(worker_id)
        if not task_types or limit <= 0 or not normalized_worker_id:
            return []

        normalized_limit = int(limit)
        if normalized_limit <= 0:
            return []

        lease_seconds = max(1, int(lease_seconds))
        claim_time = _now_iso()
        lease_expires_at = _iso_after_seconds(lease_seconds)
        placeholders = ", ".join("?" for _ in task_types)

        with self._db_lock:
            conn = self._db_connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    f"""
                    SELECT job_id, status, progress_value, progress_text, stage, timeout_sec,
                           result_json, error, error_code, retryable, cancel_requested,
                           task_type, task_payload_json,
                           claimed_by, claimed_at, lease_expires_at, last_heartbeat_at,
                           attempt_count,
                           created_at, updated_at
                    FROM job_records
                    WHERE cancel_requested = 0
                      AND task_type IN ({placeholders})
                      AND (
                        status = 'queued'
                        OR (
                            status = 'running'
                            AND lease_expires_at IS NOT NULL
                            AND lease_expires_at <= ?
                        )
                      )
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (*task_types, claim_time, normalized_limit),
                ).fetchall()

                claimed_records: list[JobRecord] = []
                for row in rows:
                    job_id = str(row["job_id"])
                    attempt_count = int(row["attempt_count"] or 0) + 1
                    cursor = conn.execute(
                        f"""
                        UPDATE job_records
                        SET status = 'running',
                            claimed_by = ?,
                            claimed_at = ?,
                            lease_expires_at = ?,
                            last_heartbeat_at = ?,
                            attempt_count = ?,
                            updated_at = ?
                        WHERE job_id = ?
                          AND cancel_requested = 0
                          AND task_type IN ({placeholders})
                          AND (
                            status = 'queued'
                            OR (
                                status = 'running'
                                AND lease_expires_at IS NOT NULL
                                AND lease_expires_at <= ?
                            )
                          )
                        """,
                        (
                            normalized_worker_id,
                            claim_time,
                            lease_expires_at,
                            claim_time,
                            attempt_count,
                            claim_time,
                            job_id,
                            *task_types,
                            claim_time,
                        ),
                    )
                    if cursor.rowcount <= 0:
                        continue
                    claimed_record = _row_to_record(row)
                    claimed_record.status = "running"
                    claimed_record.claimed_by = normalized_worker_id
                    claimed_record.claimed_at = claim_time
                    claimed_record.lease_expires_at = lease_expires_at
                    claimed_record.last_heartbeat_at = claim_time
                    claimed_record.attempt_count = attempt_count
                    claimed_record.updated_at = claim_time
                    claimed_records.append(claimed_record)
                conn.commit()
                return claimed_records
            finally:
                conn.close()

    def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        normalized_job_id = _normalize_job_id(job_id)
        normalized_worker_id = _normalize_text(worker_id)
        if not normalized_job_id or not normalized_worker_id:
            return False

        lease_seconds = max(1, int(lease_seconds))
        now = _now_iso()
        lease_expires_at = _iso_after_seconds(lease_seconds)

        with self._db_lock:
            conn = self._db_connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    """
                    UPDATE job_records
                    SET lease_expires_at = ?,
                        last_heartbeat_at = ?,
                        updated_at = ?
                    WHERE job_id = ?
                      AND status = 'running'
                      AND claimed_by = ?
                    """,
                    (
                        lease_expires_at,
                        now,
                        now,
                        normalized_job_id,
                        normalized_worker_id,
                    ),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def count_active_jobs_for_account(self, account_id: str) -> int:
        normalized_account_id = _normalize_account_id(account_id)
        if not normalized_account_id:
            return 0

        records = self.list_records(statuses=("queued", "running"))
        return sum(
            1
            for record in records
            if _task_payload_account_id(record.task_payload) == normalized_account_id
        )

    def prune_records(self, *, ttl_hours: int, max_count: int) -> None:
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()
        with self._db_lock:
            conn = self._db_connect()
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

    def initialize(self) -> None:
        with self._db_lock:
            db_path = self._db_path()
            if self._initialized_db_path == db_path and self._job_records_table_exists(db_path):
                return

            conn = sqlite3.connect(str(db_path))
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
                        claimed_by TEXT NULL,
                        claimed_at TEXT NULL,
                        lease_expires_at TEXT NULL,
                        last_heartbeat_at TEXT NULL,
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                self._ensure_job_records_column(conn, "task_type", "TEXT NULL")
                self._ensure_job_records_column(conn, "task_payload_json", "TEXT NULL")
                self._ensure_job_records_column(conn, "claimed_by", "TEXT NULL")
                self._ensure_job_records_column(conn, "claimed_at", "TEXT NULL")
                self._ensure_job_records_column(conn, "lease_expires_at", "TEXT NULL")
                self._ensure_job_records_column(conn, "last_heartbeat_at", "TEXT NULL")
                self._ensure_job_records_column(conn, "attempt_count", "INTEGER NOT NULL DEFAULT 0")
                conn.execute(
                    """
                    UPDATE job_records
                    SET status = 'failed',
                        progress_value = 100,
                        progress_text = '任务中断（服务重启）',
                        error = COALESCE(error, '任务在服务重启时中断。'),
                        error_code = COALESCE(error_code, 'JOB_INTERRUPTED_RESTART'),
                        retryable = 1,
                        claimed_by = NULL,
                        claimed_at = NULL,
                        lease_expires_at = NULL,
                        last_heartbeat_at = NULL,
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
                        claimed_by = NULL,
                        claimed_at = NULL,
                        lease_expires_at = NULL,
                        last_heartbeat_at = NULL,
                        updated_at = ?
                    WHERE status = 'queued' AND (task_type IS NULL OR TRIM(task_type) = '')
                    """,
                    (_now_iso(),),
                )
                conn.commit()
            finally:
                conn.close()
            self._initialized_db_path = db_path

    def reset_for_tests(self) -> None:
        with self._db_lock:
            self._initialized_db_path = None
            db_path = self._db_path()
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except PermissionError:
                    return

    def _db_connect(self) -> sqlite3.Connection:
        self.initialize()
        conn = sqlite3.connect(str(self._db_path()))
        conn.row_factory = sqlite3.Row
        return conn

    def _db_path(self) -> Path:
        db_path = self._db_path_getter()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_path

    def _default_db_path(self) -> Path:
        return get_settings().job_queue_db_path

    def _ensure_job_records_column(
        self,
        conn: sqlite3.Connection,
        column_name: str,
        ddl_suffix: str,
    ) -> None:
        try:
            conn.execute(
                f"ALTER TABLE job_records ADD COLUMN {column_name} {ddl_suffix}"  # noqa: S608
            )
        except sqlite3.OperationalError:
            return

    def _job_records_table_exists(self, db_path: Path) -> bool:
        if not db_path.exists():
            return False

        try:
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'job_records'
                    """
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.OperationalError:
            return False

        return row is not None


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
        claimed_by=str(row["claimed_by"]) if row["claimed_by"] is not None else None,
        claimed_at=str(row["claimed_at"]) if row["claimed_at"] is not None else None,
        lease_expires_at=(
            str(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None
        ),
        last_heartbeat_at=(
            str(row["last_heartbeat_at"]) if row["last_heartbeat_at"] is not None else None
        ),
        attempt_count=int(row["attempt_count"]) if row["attempt_count"] is not None else 0,
        created_at=str(row["created_at"] or _now_iso()),
        updated_at=str(row["updated_at"] or _now_iso()),
    )


def _normalize_job_id(job_id: str) -> str:
    return str(job_id or "").strip()


def _normalize_text(value: object | None) -> str:
    return str(value or "").strip()


def _normalize_account_id(account_id: str) -> str:
    return str(account_id or "").strip()


def _task_payload_account_id(task_payload: dict[str, Any] | None) -> str:
    if not isinstance(task_payload, dict):
        return ""
    return _normalize_account_id(task_payload.get("account_id"))


def _iso_after_seconds(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(seconds)))).isoformat()


default_job_repository = JobRepository()
