from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import YtDlpCookieConfig, resolve_yt_dlp_cookie_config


@dataclass(frozen=True)
class YtDlpCookiesSnapshot:
    mode: str
    configured: bool
    active_for_yt_dlp: bool
    cookies_file: str
    exists: bool
    cookies_text: str
    byte_count: int


def _resolve_effective_cookie_file_path(config: YtDlpCookieConfig) -> Path | None:
    if config.mode in {"cookies_file", "default_cookies_file"}:
        return config.effective_path
    return None


def get_yt_dlp_cookies_file_path() -> Path | None:
    config = resolve_yt_dlp_cookie_config()
    return _resolve_effective_cookie_file_path(config)


def read_yt_dlp_cookies_snapshot() -> YtDlpCookiesSnapshot:
    config = resolve_yt_dlp_cookie_config()
    file_path = _resolve_effective_cookie_file_path(config)
    if file_path is None:
        return YtDlpCookiesSnapshot(
            mode=config.mode,
            configured=config.configured,
            active_for_yt_dlp=config.active_for_yt_dlp,
            cookies_file="",
            exists=False,
            cookies_text="",
            byte_count=0,
        )

    if not file_path.exists() or not file_path.is_file():
        return YtDlpCookiesSnapshot(
            mode=config.mode,
            configured=config.configured,
            active_for_yt_dlp=config.active_for_yt_dlp,
            cookies_file=file_path.as_posix(),
            exists=False,
            cookies_text="",
            byte_count=0,
        )

    try:
        cookies_text = file_path.read_text(encoding="utf-8")
    except OSError:
        cookies_text = ""

    return YtDlpCookiesSnapshot(
        mode=config.mode,
        configured=config.configured,
        active_for_yt_dlp=config.active_for_yt_dlp,
        cookies_file=file_path.as_posix(),
        exists=True,
        cookies_text=cookies_text,
        byte_count=len(cookies_text.encode("utf-8")),
    )


def save_yt_dlp_cookies_file(cookies_text: str) -> YtDlpCookiesSnapshot:
    normalized_text = str(cookies_text or "")
    config = resolve_yt_dlp_cookie_config()
    file_path = _resolve_effective_cookie_file_path(config)
    if file_path is None:
        raise ValueError(
            "YTDLP_COOKIES_FILE is not configured. Set an absolute file path before saving cookies."
        )
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if not normalized_text.strip():
        clear_yt_dlp_cookies_file()
        return read_yt_dlp_cookies_snapshot()

    file_path.write_text(normalized_text, encoding="utf-8")
    return read_yt_dlp_cookies_snapshot()


def clear_yt_dlp_cookies_file() -> YtDlpCookiesSnapshot:
    config = resolve_yt_dlp_cookie_config()
    file_path = _resolve_effective_cookie_file_path(config)
    if file_path is None:
        return read_yt_dlp_cookies_snapshot()
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        pass
    return read_yt_dlp_cookies_snapshot()
