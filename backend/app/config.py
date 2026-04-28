import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_YTDLP_COOKIES_FILE = ROOT_DIR / "youtube-cookies.txt"

load_dotenv(ROOT_DIR / ".env")


def get_env_str(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def get_yt_dlp_auth_args() -> list[str]:
    cookies_file = get_env_str("YTDLP_COOKIES_FILE")
    if cookies_file:
        return ["--cookies", cookies_file]

    if DEFAULT_YTDLP_COOKIES_FILE.exists():
        return ["--cookies", str(DEFAULT_YTDLP_COOKIES_FILE)]

    cookies_from_browser = get_env_str("YTDLP_COOKIES_FROM_BROWSER")
    if cookies_from_browser:
        return ["--cookies-from-browser", cookies_from_browser]

    return []


def get_yt_dlp_proxy_args() -> list[str]:
    proxy = get_env_str("YTDLP_PROXY")
    if proxy:
        return ["--proxy", proxy]
    return []


def get_http_proxy_from_env() -> str:
    return (
        get_env_str("HTTP_PROXY")
        or get_env_str("http_proxy")
        or get_env_str("HTTPS_PROXY")
        or get_env_str("https_proxy")
    )
