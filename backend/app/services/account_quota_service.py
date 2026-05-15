from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from fastapi import Request

from app.config import AppSettings, get_settings
from app.repositories.account_quota_repository import (
    AccountDailyRequestUsage,
    default_account_quota_repository,
)
from app.repositories.job_repository import default_job_repository
from app.repositories.session_repository import default_session_repository


@dataclass(frozen=True)
class AccountIdentity:
    account_id: str
    source: str
    user_id: str | None = None
    workspace_id: str | None = None
    api_token_fingerprint: str | None = None
    client_ip: str | None = None
    anonymous: bool = False


@dataclass(frozen=True)
class AccountQuotaLimits:
    daily_request_limit: int
    max_concurrent_jobs: int
    max_history_sessions: int


@dataclass(frozen=True)
class AccountQuotaViolation:
    quota_name: str
    account_id: str
    limit: int
    current: int
    error_code: str
    detail: str
    retryable: bool = True


class AccountQuotaService:
    def __init__(
        self,
        *,
        quota_repository=default_account_quota_repository,
        job_repository=default_job_repository,
        session_repository=default_session_repository,
    ) -> None:
        self._quota_repository = quota_repository
        self._job_repository = job_repository
        self._session_repository = session_repository

    def get_limits(self, settings: AppSettings | None = None) -> AccountQuotaLimits:
        resolved_settings = settings or get_settings()
        return AccountQuotaLimits(
            daily_request_limit=max(0, int(resolved_settings.account_daily_request_limit)),
            max_concurrent_jobs=max(0, int(resolved_settings.account_max_concurrent_jobs)),
            max_history_sessions=max(0, int(resolved_settings.account_max_history_sessions)),
        )

    def resolve_identity(
        self,
        *,
        headers: Mapping[str, Any],
        client_ip: str | None,
        settings: AppSettings | None = None,
    ) -> AccountIdentity:
        return resolve_account_identity(
            headers=headers,
            client_ip=client_ip,
            settings=settings,
        )

    def resolve_identity_from_request(
        self,
        request: Request,
        *,
        settings: AppSettings | None = None,
    ) -> AccountIdentity:
        existing_identity = getattr(request.state, "account_identity", None)
        if isinstance(existing_identity, AccountIdentity):
            return existing_identity

        identity = resolve_account_identity_from_request(request, settings=settings)
        request.state.account_identity = identity
        return identity

    def consume_daily_request(
        self,
        identity: AccountIdentity,
        *,
        settings: AppSettings | None = None,
        usage_date: str | date | None = None,
    ) -> AccountQuotaViolation | None:
        limits = self.get_limits(settings)
        if limits.daily_request_limit <= 0:
            return None

        allowed, usage = self._quota_repository.reserve_daily_request_slot(
            identity.account_id,
            limit=limits.daily_request_limit,
            usage_date=usage_date,
        )
        if allowed:
            return None
        return _build_daily_request_violation(identity, limits.daily_request_limit, usage)

    def check_job_start_quota(
        self,
        identity: AccountIdentity,
        *,
        settings: AppSettings | None = None,
    ) -> AccountQuotaViolation | None:
        limits = self.get_limits(settings)

        if limits.max_concurrent_jobs > 0:
            current_jobs = self._job_repository.count_active_jobs_for_account(identity.account_id)
            if current_jobs >= limits.max_concurrent_jobs:
                return AccountQuotaViolation(
                    quota_name="max_concurrent_jobs",
                    account_id=identity.account_id,
                    limit=limits.max_concurrent_jobs,
                    current=current_jobs,
                    error_code="ACCOUNT_MAX_CONCURRENT_JOBS_EXCEEDED",
                    detail="该账号的并发任务数已达上限。",
                )

        if limits.max_history_sessions > 0:
            current_sessions = self._session_repository.count_sessions_for_account(
                identity.account_id
            )
            if current_sessions >= limits.max_history_sessions:
                return AccountQuotaViolation(
                    quota_name="max_history_sessions",
                    account_id=identity.account_id,
                    limit=limits.max_history_sessions,
                    current=current_sessions,
                    error_code="ACCOUNT_MAX_HISTORY_SESSIONS_EXCEEDED",
                    detail="该账号的历史会话数已达上限。",
                )

        return None

    def reset_for_tests(self) -> None:
        self._quota_repository.reset_for_tests()


def resolve_account_identity(
    *,
    headers: Mapping[str, Any],
    client_ip: str | None,
    settings: AppSettings | None = None,
) -> AccountIdentity:
    resolved_settings = settings or get_settings()
    trust_account_headers = bool(resolved_settings.trust_account_headers)
    user_id = _normalize_identity_part(headers.get("x-user-id")) if trust_account_headers else ""
    workspace_id = (
        _normalize_identity_part(headers.get("x-workspace-id")) if trust_account_headers else ""
    )
    token = _extract_api_token(headers)

    if user_id and workspace_id:
        return AccountIdentity(
            account_id=f"workspace:{workspace_id}:user:{user_id}",
            source="workspace_user",
            user_id=user_id,
            workspace_id=workspace_id,
            client_ip=_normalize_identity_part(client_ip),
        )
    if user_id:
        return AccountIdentity(
            account_id=f"user:{user_id}",
            source="user",
            user_id=user_id,
            client_ip=_normalize_identity_part(client_ip),
        )
    if workspace_id:
        return AccountIdentity(
            account_id=f"workspace:{workspace_id}",
            source="workspace",
            workspace_id=workspace_id,
            client_ip=_normalize_identity_part(client_ip),
        )
    if token:
        fingerprint = _fingerprint_token(token)
        return AccountIdentity(
            account_id=f"token:{fingerprint}",
            source="api_token",
            api_token_fingerprint=fingerprint,
            client_ip=_normalize_identity_part(client_ip),
        )

    normalized_ip = _normalize_identity_part(client_ip)
    anonymous_local = _is_localhost_client_ip(normalized_ip)
    account_id = "anonymous-localhost" if anonymous_local else f"anonymous:{normalized_ip or 'unknown'}"
    return AccountIdentity(
        account_id=account_id,
        source="anonymous_localhost" if anonymous_local else "anonymous",
        client_ip=normalized_ip,
        anonymous=True,
    )


def resolve_account_identity_from_request(
    request: Request,
    *,
    settings: AppSettings | None = None,
) -> AccountIdentity:
    client_ip = request.client.host if request.client else None
    return resolve_account_identity(
        headers=request.headers,
        client_ip=client_ip,
        settings=settings or get_settings(),
    )


def get_account_quota_limits(settings: AppSettings | None = None) -> AccountQuotaLimits:
    return AccountQuotaService().get_limits(settings)


def _build_daily_request_violation(
    identity: AccountIdentity,
    limit: int,
    usage: AccountDailyRequestUsage,
) -> AccountQuotaViolation:
    return AccountQuotaViolation(
        quota_name="daily_request_limit",
        account_id=identity.account_id,
        limit=limit,
        current=usage.request_count,
        error_code="ACCOUNT_DAILY_REQUEST_LIMIT_EXCEEDED",
        detail="该账号今日写入请求数已达上限。",
    )


def _extract_api_token(headers: Mapping[str, Any]) -> str:
    authorization = str(headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return str(headers.get("x-api-token") or "").strip()


def _fingerprint_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _normalize_identity_part(value: object | None) -> str:
    return str(value or "").strip()


def _is_localhost_client_ip(client_ip: str | None) -> bool:
    normalized = _normalize_identity_part(client_ip)
    if not normalized:
        return True
    return normalized in {"127.0.0.1", "::1", "localhost"} or normalized.startswith("127.")


default_account_quota_service = AccountQuotaService()
