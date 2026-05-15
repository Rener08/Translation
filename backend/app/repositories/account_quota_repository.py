from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from app.config import get_settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _usage_date_from_value(value: str | date | None = None) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return datetime.now(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class AccountDailyRequestUsage:
    account_id: str
    usage_date: str
    request_count: int
    updated_at: str


class AccountQuotaRepository:
    def __init__(self, db_path_getter: Callable[[], Path] | None = None) -> None:
        self._db_path_getter = db_path_getter or self._default_db_path
        self._db_lock = threading.RLock()
        self._initialized_db_path: Path | None = None

    def reserve_daily_request_slot(
        self,
        account_id: str,
        *,
        limit: int,
        usage_date: str | date | None = None,
    ) -> tuple[bool, AccountDailyRequestUsage]:
        normalized_account_id = str(account_id or "").strip()
        if not normalized_account_id or limit <= 0:
            return True, AccountDailyRequestUsage(
                account_id=normalized_account_id,
                usage_date=_usage_date_from_value(usage_date),
                request_count=0,
                updated_at=_now_iso(),
            )

        normalized_usage_date = _usage_date_from_value(usage_date)
        with self._db_lock:
            conn = self._db_connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                current = self._get_daily_request_count_locked(
                    conn,
                    account_id=normalized_account_id,
                    usage_date=normalized_usage_date,
                )
                if current >= limit:
                    conn.rollback()
                    return False, AccountDailyRequestUsage(
                        account_id=normalized_account_id,
                        usage_date=normalized_usage_date,
                        request_count=current,
                        updated_at=_now_iso(),
                    )

                updated_at = _now_iso()
                conn.execute(
                    """
                    INSERT INTO account_daily_request_usage (
                        account_id, usage_date, request_count, updated_at
                    ) VALUES (?, ?, 1, ?)
                    ON CONFLICT(account_id, usage_date) DO UPDATE SET
                        request_count = request_count + 1,
                        updated_at = excluded.updated_at
                    """,
                    (
                        normalized_account_id,
                        normalized_usage_date,
                        updated_at,
                    ),
                )
                conn.commit()
                return True, AccountDailyRequestUsage(
                    account_id=normalized_account_id,
                    usage_date=normalized_usage_date,
                    request_count=current + 1,
                    updated_at=updated_at,
                )
            finally:
                conn.close()

    def get_daily_request_count(
        self,
        account_id: str,
        *,
        usage_date: str | date | None = None,
    ) -> int:
        normalized_account_id = str(account_id or "").strip()
        if not normalized_account_id:
            return 0

        normalized_usage_date = _usage_date_from_value(usage_date)
        with self._db_lock:
            conn = self._db_connect()
            try:
                return self._get_daily_request_count_locked(
                    conn,
                    account_id=normalized_account_id,
                    usage_date=normalized_usage_date,
                )
            finally:
                conn.close()

    def reset_for_tests(self) -> None:
        with self._db_lock:
            self._initialized_db_path = None
            db_path = self._db_path()
            if db_path.exists():
                db_path.unlink()

    def initialize(self) -> None:
        with self._db_lock:
            db_path = self._db_path()
            if self._initialized_db_path == db_path:
                return

            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS account_daily_request_usage (
                        account_id TEXT NOT NULL,
                        usage_date TEXT NOT NULL,
                        request_count INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (account_id, usage_date)
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()
            self._initialized_db_path = db_path

    def _get_daily_request_count_locked(
        self,
        conn: sqlite3.Connection,
        *,
        account_id: str,
        usage_date: str,
    ) -> int:
        row = conn.execute(
            """
            SELECT request_count
            FROM account_daily_request_usage
            WHERE account_id = ? AND usage_date = ?
            """,
            (account_id, usage_date),
        ).fetchone()
        if row is None:
            return 0
        return int(row["request_count"] or 0)

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
        return get_settings().account_quota_db_path


default_account_quota_repository = AccountQuotaRepository()
