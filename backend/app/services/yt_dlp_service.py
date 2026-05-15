import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path

from app.config import (
    ROOT_DIR,
    get_settings,
    get_yt_dlp_auth_args,
    get_yt_dlp_js_runtime_args,
    get_yt_dlp_proxy_args,
    get_yt_dlp_remote_components,
    get_yt_dlp_youtube_extractor_args,
)

logger = logging.getLogger(__name__)
VIDEO_INFO_CACHE_DIR = ROOT_DIR / "tmp" / "video_info_cache"
VIDEO_INFO_CACHE_TTL_SEC = 6 * 60 * 60


class YtDlpError(Exception):
    """Base error raised when yt-dlp inspection fails."""


class YtDlpNotInstalledError(YtDlpError):
    """Raised when yt-dlp is unavailable in the current Python environment."""


class VideoInspectError(YtDlpError):
    """Raised when yt-dlp cannot inspect a video URL."""


@dataclass(frozen=True)
class VideoChapter:
    start_time: float
    end_time: float | None
    title: str


@dataclass(frozen=True)
class VideoMetadata:
    video_id: str
    title: str
    duration_sec: int | None = None
    uploader: str | None = None
    uploader_id: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    thumbnail: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    chapters: list[VideoChapter] = field(default_factory=list)
    subtitles: list[str] = field(default_factory=list)
    automatic_captions: list[str] = field(default_factory=list)


def inspect_video_metadata(url: str) -> VideoMetadata:
    payload = extract_video_info(url)
    return build_video_metadata(payload)


def build_video_metadata(payload: dict[str, object]) -> VideoMetadata:
    if not isinstance(payload, dict):
        raise VideoInspectError("yt-dlp returned an unexpected metadata payload.")

    video_id = str(payload.get("id") or "").strip()
    title = str(payload.get("title") or "").strip()

    if not video_id or not title:
        raise VideoInspectError("yt-dlp returned incomplete video metadata.")

    return VideoMetadata(
        video_id=video_id,
        title=title,
        duration_sec=_as_int(payload.get("duration")),
        uploader=_as_optional_str(payload.get("uploader")),
        uploader_id=_as_optional_str(payload.get("uploader_id")),
        channel=_as_optional_str(payload.get("channel")),
        channel_id=_as_optional_str(payload.get("channel_id")),
        thumbnail=_as_optional_str(payload.get("thumbnail")),
        description=_as_optional_str(payload.get("description")),
        tags=_as_str_list(payload.get("tags")),
        categories=_as_str_list(payload.get("categories")),
        chapters=_as_chapters(payload.get("chapters")),
        subtitles=_language_keys(payload.get("subtitles")),
        automatic_captions=_language_keys(payload.get("automatic_captions")),
    )


def extract_video_info(url: str) -> dict[str, object]:
    cached_payload = _load_cached_video_info(url)
    if cached_payload is not None:
        logger.info("Using cached yt-dlp metadata for %s", url)
        return cached_payload

    logger.info("Inspecting video info with yt-dlp: %s", url)
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--dump-single-json",
        "--skip-download",
        "--ignore-no-formats-error",
        "--no-warnings",
        "--no-playlist",
        *get_yt_dlp_remote_components(),
        *get_yt_dlp_youtube_extractor_args(),
        *get_yt_dlp_js_runtime_args(),
        *get_yt_dlp_auth_args(),
        *get_yt_dlp_proxy_args(),
        url,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=float(get_settings().yt_dlp_timeout_sec),
        )
    except subprocess.TimeoutExpired as error:
        raise VideoInspectError(
            f"yt-dlp inspection timed out after {get_settings().yt_dlp_timeout_sec}s."
        ) from error

    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    combined_output = stderr or stdout

    if completed.returncode != 0:
        normalized_message = normalize_yt_dlp_error_message(combined_output)
        logger.error("yt-dlp video inspection failed: %s", normalized_message)
        if "No module named yt_dlp" in combined_output:
            raise YtDlpNotInstalledError(
                "yt-dlp is not installed. Install it with "
                "`python -m pip install yt-dlp`."
            )
        raise VideoInspectError(normalized_message)

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise VideoInspectError("yt-dlp returned invalid metadata JSON.") from error

    if not isinstance(payload, dict):
        raise VideoInspectError("yt-dlp returned an unexpected metadata payload.")

    _store_cached_video_info(url, payload)

    return payload


def _video_info_cache_path(url: str) -> Path:
    digest = sha1(url.encode("utf-8")).hexdigest()
    return VIDEO_INFO_CACHE_DIR / f"{digest}.json"


def _load_cached_video_info(url: str) -> dict[str, object] | None:
    cache_path = _video_info_cache_path(url)
    if not cache_path.exists():
        return None

    age_sec = time.time() - cache_path.stat().st_mtime
    if age_sec > VIDEO_INFO_CACHE_TTL_SEC:
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if isinstance(payload, dict):
        return payload
    return None


def _store_cached_video_info(url: str, payload: dict[str, object]) -> None:
    try:
        VIDEO_INFO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _video_info_cache_path(url).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Failed to persist yt-dlp metadata cache for %s", url)


def _language_keys(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(str(key) for key in value.keys())


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        parsed = _as_optional_str(item)
        if parsed:
            normalized.append(parsed)
    return normalized


def _as_chapters(value: object) -> list[VideoChapter]:
    if not isinstance(value, list):
        return []

    chapters: list[VideoChapter] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        title = _as_optional_str(item.get("title"))
        start_time = _as_float(item.get("start_time"))
        if title is None or start_time is None:
            continue

        chapters.append(
            VideoChapter(
                start_time=start_time,
                end_time=_as_float(item.get("end_time")),
                title=title,
            )
        )

    return chapters


def _as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    parsed = str(value).strip()
    return parsed or None


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def normalize_yt_dlp_error_message(raw_message: str) -> str:
    message = (raw_message or "").strip()
    lowered = message.lower()

    if "provided youtube account cookies are no longer valid" in lowered:
        return (
            "YouTube cookies are stale or no longer bound to the current session. "
            "Sign in to YouTube again in that browser profile, then retry "
            "YTDLP_COOKIES_FROM_BROWSER or export a fresh cookies.txt file."
        )

    if "could not copy chrome cookie database" in lowered:
        return (
            "yt-dlp could not read Chrome cookies. Close all Chrome processes first, "
            "or export a cookies.txt file and set YTDLP_COOKIES_FILE in .env."
        )

    if "failed to decrypt with dpapi" in lowered:
        return (
            "yt-dlp could not decrypt browser cookies on this Windows account. "
            "Use an exported cookies.txt file and set YTDLP_COOKIES_FILE in .env."
        )

    if "sign in to confirm you're not a bot" in lowered:
        return (
            "YouTube is asking for a signed-in browser session. Configure "
            "YTDLP_COOKIES_FILE with an exported cookies.txt file, or try "
            "YTDLP_COOKIES_FROM_BROWSER after fully closing the browser."
        )

    if (
        "n challenge solving failed" in lowered
        or "only images are available" in lowered
    ):
        return (
            "yt-dlp could not resolve the real YouTube media URLs. Update yt-dlp, "
            "make sure a JavaScript runtime such as Deno is installed, and enable the "
            "remote EJS challenge solver components."
        )

    return message or "yt-dlp failed to inspect the video."
