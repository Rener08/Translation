from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import os
import shutil
import subprocess
import zipfile

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from app.config import ROOT_DIR, _detect_available_yt_dlp_js_runtime, get_settings, resolve_yt_dlp_cookie_config
from app.services.rewrite_provider_service import RewriteProviderConfig, resolve_rewrite_config
from app.services.youtube_access_service import inspect_youtube_access
from app.services.translation_provider_client import TranslationProviderConfig, _resolve_translation_config
from app.services.yt_dlp_cookie_service import (
    clear_yt_dlp_cookies_file,
    read_yt_dlp_cookies_snapshot,
    save_yt_dlp_cookies_file,
)
from app.services.llm_provider_service import build_endpoint_url, normalize_ollama_base_url
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


class PreflightCheck(BaseModel):
    name: str
    label: str
    ok: bool
    detail: str


class PreflightResponse(BaseModel):
    checks: list[PreflightCheck]
    all_ok: bool


@router.get("/api/system/export-logs", response_model=SystemExportLogsResponse)
async def export_logs() -> SystemExportLogsResponse:
    export_dir = ROOT_DIR / "tmp" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
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
        result = await run_in_threadpool(inspect_youtube_access, body.url)
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


def _check_yt_dlp() -> PreflightCheck:
    try:
        path = shutil.which("yt-dlp")
        if path:
            try:
                result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=5)
                version = result.stdout.strip()
                detail = f"yt-dlp {version} 已安装" if version else "yt-dlp 已安装"
            except Exception:
                detail = "yt-dlp 已安装"
            return PreflightCheck(name="yt_dlp", label="yt-dlp 安装", ok=True, detail=detail)
        return PreflightCheck(name="yt_dlp", label="yt-dlp 安装", ok=False, detail="未找到 yt-dlp，请运行 pip install yt-dlp")
    except Exception as e:
        return PreflightCheck(name="yt_dlp", label="yt-dlp 安装", ok=False, detail=f"检查失败: {e}")


def _check_js_runtime() -> PreflightCheck:
    try:
        runtime = _detect_available_yt_dlp_js_runtime()
        if runtime:
            return PreflightCheck(name="js_runtime", label="JS Runtime", ok=True, detail=f"JS runtime: {runtime}")
        return PreflightCheck(name="js_runtime", label="JS Runtime", ok=False, detail="未找到 JS runtime（node/deno/bun），yt-dlp 可能无法处理部分视频")
    except Exception as e:
        return PreflightCheck(name="js_runtime", label="JS Runtime", ok=False, detail=f"检查失败: {e}")


def _check_ffmpeg() -> PreflightCheck:
    try:
        path = shutil.which("ffmpeg")
        ok = path is not None
        detail = "ffmpeg 已安装" if ok else "未找到 ffmpeg，音频处理可能失败"
        return PreflightCheck(name="ffmpeg", label="ffmpeg 安装", ok=ok, detail=detail)
    except Exception as e:
        return PreflightCheck(name="ffmpeg", label="ffmpeg 安装", ok=False, detail=f"检查失败: {e}")


def _check_tmp_dir() -> PreflightCheck:
    try:
        tmp_dir = ROOT_DIR / "tmp"
        tmp_dir.mkdir(exist_ok=True)
        ok = os.access(tmp_dir, os.W_OK)
        detail = f"{tmp_dir} 可写" if ok else f"{tmp_dir} 不可写，请检查目录权限"
        return PreflightCheck(name="tmp_writable", label="tmp 目录可写", ok=ok, detail=detail)
    except Exception as e:
        return PreflightCheck(name="tmp_writable", label="tmp 目录可写", ok=False, detail=f"检查失败: {e}")


def _check_yt_cookies() -> PreflightCheck:
    try:
        cookie_config = resolve_yt_dlp_cookie_config()
        if cookie_config.active_for_yt_dlp:
            return PreflightCheck(name="yt_cookies", label="YouTube Cookies", ok=True, detail=f"Cookies 已配置（{cookie_config.mode}）")
        if cookie_config.configured:
            return PreflightCheck(name="yt_cookies", label="YouTube Cookies", ok=False, detail=f"Cookies 已配置但无效（{cookie_config.mode}），请检查文件路径")
        return PreflightCheck(name="yt_cookies", label="YouTube Cookies", ok=True, detail="未配置 cookies（仅公开视频可用）")
    except Exception as e:
        return PreflightCheck(name="yt_cookies", label="YouTube Cookies", ok=False, detail=f"检查失败: {e}")


def _check_job_queue_db() -> PreflightCheck:
    try:
        db_path = get_settings().job_queue_db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            os.utime(db_path, None)
        detail = f"{db_path} 可用"
        return PreflightCheck(name="job_queue_db", label="job_queue_db", ok=True, detail=detail)
    except Exception as e:
        return PreflightCheck(name="job_queue_db", label="job_queue_db", ok=False, detail=f"检查失败: {e}")


def _check_yaml_available() -> PreflightCheck:
    try:
        yaml_spec = importlib.util.find_spec("yaml")
        ok = yaml_spec is not None
        detail = "yaml 可用" if ok else "缺少 PyYAML"
        return PreflightCheck(name="yaml_available", label="YAML", ok=ok, detail=detail)
    except Exception as e:
        return PreflightCheck(name="yaml_available", label="YAML", ok=False, detail=f"检查失败: {e}")


def _check_provider_ready(
    *,
    name: str,
    label: str,
    config: TranslationProviderConfig | RewriteProviderConfig,
) -> PreflightCheck:
    try:
        models = _probe_provider_models(
            provider=config.provider,
            base_url=config.base_url,
            api_key=config.api_key,
            extra_headers=config.extra_headers,
        )
        if config.model not in models:
            discovered = ", ".join(models[:4]) or "无"
            return PreflightCheck(
                name=name,
                label=label,
                ok=False,
                detail=f"{config.provider} 已连通，但模型 `{config.model}` 未出现在可发现列表中（{discovered}）",
            )
        return PreflightCheck(
            name=name,
            label=label,
            ok=True,
            detail=f"{config.provider} · {config.model} 可用（{config.base_url}）",
        )
    except Exception as e:
        return PreflightCheck(
            name=name,
            label=label,
            ok=False,
            detail=f"{config.provider} 检查失败: {e}",
        )


def _check_translation_provider() -> PreflightCheck:
    try:
        config = _resolve_translation_config(None)
    except Exception as e:
        return PreflightCheck(name="translation_provider", label="翻译 provider", ok=False, detail=f"配置失败: {e}")
    return _check_provider_ready(
        name="translation_provider",
        label="翻译 provider",
        config=config,
    )


def _check_rewrite_provider() -> PreflightCheck:
    try:
        config = resolve_rewrite_config(None)
    except Exception as e:
        return PreflightCheck(name="rewrite_provider", label="写作 provider", ok=False, detail=f"配置失败: {e}")
    return _check_provider_ready(
        name="rewrite_provider",
        label="写作 provider",
        config=config,
    )


def _probe_provider_models(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    extra_headers: dict[str, str],
) -> list[str]:
    endpoint_url = _provider_models_endpoint(provider, base_url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(extra_headers)

    try:
        response = httpx.get(endpoint_url, headers=headers, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise RuntimeError(f"无法访问 {endpoint_url}: {error}") from error

    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError(f"{endpoint_url} 返回了无效 JSON") from error

    models: list[str] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id") or "").strip()
                if model_id and model_id not in models:
                    models.append(model_id)

        provider_models = payload.get("models")
        if isinstance(provider_models, list):
            for item in provider_models:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("model") or item.get("name") or "").strip()
                if model_id and model_id not in models:
                    models.append(model_id)

    if not models:
        raise RuntimeError(f"{endpoint_url} 未返回可用模型列表")
    return models


def _provider_models_endpoint(provider: str, base_url: str) -> str:
    if provider == "ollama":
        return build_endpoint_url(normalize_ollama_base_url(base_url), "/api/tags")
    return build_endpoint_url(base_url, "/models")


def _run_all_preflight_checks() -> list[PreflightCheck]:
    return [
        _check_job_queue_db(),
        _check_yaml_available(),
        _check_yt_dlp(),
        _check_js_runtime(),
        _check_ffmpeg(),
        _check_tmp_dir(),
        _check_yt_cookies(),
        _check_translation_provider(),
        _check_rewrite_provider(),
    ]


@router.get("/api/system/preflight", response_model=PreflightResponse)
async def get_preflight() -> PreflightResponse:
    checks = await run_in_threadpool(_run_all_preflight_checks)
    return PreflightResponse(checks=checks, all_ok=all(c.ok for c in checks))
