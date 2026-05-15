from __future__ import annotations

from datetime import datetime
import zipfile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.config import ROOT_DIR, get_settings
from app.services.youtube_access_service import inspect_youtube_access
from app.services.yt_dlp_cookie_service import (
    clear_yt_dlp_cookies_file,
    read_yt_dlp_cookies_snapshot,
    save_yt_dlp_cookies_file,
)
from app.youtube import (
    SystemExportLogsResponse,
    YouTubeAccessStatusRequest,
    YouTubeAccessStatusResponse,
)


router = APIRouter()


class SystemYtDlpCookiesResponse(BaseModel):
    ok: bool
    mode: str = "none"
    configured: bool = False
    active_for_yt_dlp: bool = False
    cookies_file: str
    exists: bool
    cookies_text: str = ""
    byte_count: int = 0


class SystemYtDlpCookiesUpdateRequest(BaseModel):
    cookies_text: str = Field(default="")

    @field_validator("cookies_text")
    @classmethod
    def validate_cookies_text(cls, value: str) -> str:
        return str(value or "")


@router.get("/api/system/export-logs", response_model=SystemExportLogsResponse)
async def export_logs() -> SystemExportLogsResponse:
    export_dir = ROOT_DIR / "tmp" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    archive_path = export_dir / f"translation-logs-{timestamp}.zip"
    settings = get_settings()
    source_files = [
        settings.backend_log_file,
        settings.frontend_log_file,
    ]

    included: list[str] = []
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in source_files:
            if not file_path.exists() or not file_path.is_file():
                continue
            zf.write(file_path, arcname=file_path.name)
            included.append(file_path.name)

    return SystemExportLogsResponse(
        ok=True,
        archive_path=str(archive_path),
        included_files=included,
    )


@router.get("/api/system/yt-dlp-cookies", response_model=SystemYtDlpCookiesResponse)
async def get_yt_dlp_cookies() -> SystemYtDlpCookiesResponse:
    snapshot = read_yt_dlp_cookies_snapshot()
    return SystemYtDlpCookiesResponse(
        ok=True,
        mode=snapshot.mode,
        configured=snapshot.configured,
        active_for_yt_dlp=snapshot.active_for_yt_dlp,
        cookies_file=snapshot.cookies_file,
        exists=snapshot.exists,
        cookies_text=snapshot.cookies_text,
        byte_count=snapshot.byte_count,
    )


@router.put("/api/system/yt-dlp-cookies", response_model=SystemYtDlpCookiesResponse)
async def save_yt_dlp_cookies(
    body: SystemYtDlpCookiesUpdateRequest,
) -> SystemYtDlpCookiesResponse:
    try:
        snapshot = save_yt_dlp_cookies_file(body.cookies_text)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return SystemYtDlpCookiesResponse(
        ok=True,
        mode=snapshot.mode,
        configured=snapshot.configured,
        active_for_yt_dlp=snapshot.active_for_yt_dlp,
        cookies_file=snapshot.cookies_file,
        exists=snapshot.exists,
        cookies_text=snapshot.cookies_text,
        byte_count=snapshot.byte_count,
    )


@router.delete("/api/system/yt-dlp-cookies", response_model=SystemYtDlpCookiesResponse)
async def clear_yt_dlp_cookies() -> SystemYtDlpCookiesResponse:
    snapshot = clear_yt_dlp_cookies_file()
    return SystemYtDlpCookiesResponse(
        ok=True,
        mode=snapshot.mode,
        configured=snapshot.configured,
        active_for_yt_dlp=snapshot.active_for_yt_dlp,
        cookies_file=snapshot.cookies_file,
        exists=snapshot.exists,
        cookies_text=snapshot.cookies_text,
        byte_count=snapshot.byte_count,
    )


@router.post(
    "/api/system/youtube-access-status",
    response_model=YouTubeAccessStatusResponse,
    response_model_exclude_none=True,
)
async def get_youtube_access_status(
    body: YouTubeAccessStatusRequest,
) -> YouTubeAccessStatusResponse:
    try:
        result = inspect_youtube_access(body.url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return YouTubeAccessStatusResponse(
        ok=result.ok,
        runtime_ok=result.runtime_ok,
        target_ok=result.target_ok,
        probe_url=result.probe_url,
        target_url=result.target_url,
        normalized_url=result.normalized_url,
        video_id=result.video_id,
        title=result.title,
        source_strategy=result.source_strategy,  # type: ignore[arg-type]
        cookies_configured=result.cookies_configured,
        cookies_file_exists=result.cookies_file_exists,
        cookies_active_for_yt_dlp=result.cookies_active_for_yt_dlp,
        cookie_mode=result.cookie_mode,
        error_code=result.error_code,
        retryable=result.retryable,
        message=result.message,
        recommended_action=result.recommended_action,
        subtitles=result.subtitles,
        automatic_captions=result.automatic_captions,
        checks=result.checks,
    )
