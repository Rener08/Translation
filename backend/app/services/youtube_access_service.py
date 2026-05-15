from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tempfile

from app.api.error_mapping import ErrorClassification, classify_service_error
from app.config import ROOT_DIR, resolve_yt_dlp_cookie_config
from app.services.audio_download_service import download_audio
from app.services.caption_service import CaptionServiceError, fetch_best_english_captions
from app.services.yt_dlp_service import build_video_metadata, extract_video_info
from app.youtube import parse_youtube_url


PUBLIC_PROBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@dataclass(frozen=True)
class YouTubeAccessStatusResult:
    ok: bool
    runtime_ok: bool
    target_ok: bool
    probe_url: str
    target_url: str | None = None
    normalized_url: str | None = None
    video_id: str | None = None
    title: str | None = None
    source_strategy: str = "unknown"
    cookies_configured: bool = False
    cookies_file_exists: bool = False
    cookies_active_for_yt_dlp: bool = False
    cookie_mode: str = "none"
    error_code: str | None = None
    retryable: bool | None = None
    message: str = ""
    recommended_action: str = ""
    subtitles: list[str] = field(default_factory=list)
    automatic_captions: list[str] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)


def inspect_youtube_access(target_url: str | None = None) -> YouTubeAccessStatusResult:
    cookie_config = resolve_yt_dlp_cookie_config()
    base_result = YouTubeAccessStatusResult(
        ok=False,
        runtime_ok=False,
        target_ok=False,
        probe_url=PUBLIC_PROBE_URL,
        target_url=target_url,
        cookies_configured=cookie_config.configured,
        cookies_file_exists=bool(
            cookie_config.effective_path and cookie_config.effective_path.exists()
        ),
        cookies_active_for_yt_dlp=cookie_config.active_for_yt_dlp,
        cookie_mode=cookie_config.mode,
        checks={
            "yt_dlp_cookies": _cookie_check_label(cookie_config),
        },
    )

    try:
        extract_video_info(PUBLIC_PROBE_URL)
    except Exception as error:
        return _apply_classification(
            base_result,
            classify_service_error(error),
            runtime_ok=False,
            target_ok=False,
            checks={
                **base_result.checks,
                "public_probe_inspect": "failed",
            },
        )

    runtime_ready = base_result.checks | {"public_probe_inspect": "ok"}
    if not target_url:
        return YouTubeAccessStatusResult(
            **{
                **base_result.__dict__,
                "ok": True,
                "runtime_ok": True,
                "target_ok": True,
                "checks": runtime_ready,
                "message": "当前环境可访问 YouTube 元数据接口。",
                "recommended_action": "",
            }
        )

    try:
        parsed = parse_youtube_url(target_url)
    except Exception as error:
        return _apply_classification(
            YouTubeAccessStatusResult(
                **{
                    **base_result.__dict__,
                    "runtime_ok": True,
                    "checks": runtime_ready | {"target_url": "invalid"},
                }
            ),
            classify_service_error(error),
            runtime_ok=True,
            target_ok=False,
            checks=runtime_ready | {"target_url": "invalid"},
        )

    try:
        video_info = extract_video_info(parsed.normalized_url)
        metadata = build_video_metadata(video_info)
    except Exception as error:
        return _apply_classification(
            YouTubeAccessStatusResult(
                **{
                    **base_result.__dict__,
                    "runtime_ok": True,
                    "target_url": target_url,
                    "normalized_url": parsed.normalized_url,
                    "video_id": parsed.video_id,
                    "checks": runtime_ready | {"target_inspect": "failed"},
                }
            ),
            classify_service_error(error),
            runtime_ok=True,
            target_ok=False,
            checks=runtime_ready | {"target_inspect": "failed"},
        )

    current = YouTubeAccessStatusResult(
        **{
            **base_result.__dict__,
            "runtime_ok": True,
            "target_url": target_url,
            "normalized_url": parsed.normalized_url,
            "video_id": metadata.video_id,
            "title": metadata.title,
            "subtitles": metadata.subtitles,
            "automatic_captions": metadata.automatic_captions,
            "checks": runtime_ready | {"target_inspect": "ok"},
        }
    )

    try:
        caption_result = fetch_best_english_captions(video_info)
    except CaptionServiceError as error:
        caption_result = None
        current = YouTubeAccessStatusResult(
            **{
                **current.__dict__,
                "checks": {
                    **current.checks,
                    "target_captions": f"failed:{classify_service_error(error).error_code}",
                },
            }
        )
    else:
        if caption_result is not None:
            return YouTubeAccessStatusResult(
                **{
                    **current.__dict__,
                    "ok": True,
                    "target_ok": True,
                    "source_strategy": "captions",
                    "message": "该视频可直接走字幕路径。",
                    "recommended_action": "",
                    "checks": {
                        **current.checks,
                        "target_captions": "ok",
                        "target_audio_probe": "skipped",
                    },
                }
            )
        current = YouTubeAccessStatusResult(
            **{
                **current.__dict__,
                "checks": {
                    **current.checks,
                    "target_captions": "missing",
                },
            }
        )

    try:
        with tempfile.TemporaryDirectory(
            dir=(ROOT_DIR / "tmp").as_posix(),
            prefix="yt-access-",
        ) as temp_dir:
            result = download_audio(parsed.normalized_url, Path(temp_dir))
            _cleanup_probe_file(result.audio_file_path)
    except Exception as error:
        return _apply_classification(
            current,
            classify_service_error(error),
            runtime_ok=True,
            target_ok=False,
            checks={
                **current.checks,
                "target_audio_probe": "failed",
            },
        )

    return YouTubeAccessStatusResult(
        **{
            **current.__dict__,
            "ok": True,
            "target_ok": True,
            "source_strategy": "audio",
            "message": "该视频没有可用英文字幕，但音频下载链路可用。",
            "recommended_action": "",
            "checks": {
                **current.checks,
                "target_audio_probe": "ok",
            },
        }
    )


def _apply_classification(
    result: YouTubeAccessStatusResult,
    classification: ErrorClassification,
    *,
    runtime_ok: bool,
    target_ok: bool,
    checks: dict[str, str],
) -> YouTubeAccessStatusResult:
    recommended_action = _recommended_action_for_error_code(classification.error_code)
    return YouTubeAccessStatusResult(
        **{
            **result.__dict__,
            "ok": runtime_ok and target_ok,
            "runtime_ok": runtime_ok,
            "target_ok": target_ok,
            "error_code": classification.error_code,
            "retryable": classification.retryable,
            "message": classification.detail,
            "recommended_action": recommended_action,
            "checks": checks,
        }
    )


def _recommended_action_for_error_code(error_code: str) -> str:
    if error_code == "YTDLP_NOT_INSTALLED":
        return "请先安装 yt-dlp，再重试。"
    if error_code == "COOKIE_STALE":
        return "请重新导出并保存最新的 cookies.txt。"
    if error_code in {"COOKIE_REQUIRED", "YOUTUBE_BOT_CHECK"}:
        return "请更新 cookies.txt；如果仍失败，建议改走本地音频上传。"
    if error_code == "YOUTUBE_429":
        return "请稍后重试，或切换网络后再试。"
    if error_code in {"VIDEO_UNAVAILABLE", "VIDEO_PRIVATE", "VIDEO_REGION_BLOCKED"}:
        return "请确认视频在当前网络和账号下可访问；必要时改走本地音频上传。"
    if error_code.endswith("_TIMEOUT") or error_code == "YTDLP_TIMEOUT":
        return "请稍后重试；如果问题持续，优先检查 cookies 和网络状态。"
    if error_code == "YOUTUBE_URL_INVALID":
        return "请改用标准的 YouTube 视频链接。"
    return "请检查 YouTube 访问状态、cookies 配置，或改走本地音频上传。"


def _cookie_check_label(cookie_config) -> str:
    if not cookie_config.configured:
        return "unconfigured"
    if cookie_config.mode == "browser":
        return "browser"
    if cookie_config.mode == "cookie_header":
        return "cookie_header"
    if cookie_config.active_for_yt_dlp:
        return "ok"
    return "configured_but_inactive"


def _cleanup_probe_file(audio_file_path: str) -> None:
    candidate = Path(audio_file_path)
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    if candidate.exists() and candidate.is_file():
        try:
            candidate.unlink()
        except OSError:
            pass
