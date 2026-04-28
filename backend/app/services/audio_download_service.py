import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import (
    ROOT_DIR,
    get_env_str,
    get_yt_dlp_auth_args,
    get_yt_dlp_proxy_args,
)
from app.services.yt_dlp_service import (
    YtDlpNotInstalledError,
    normalize_yt_dlp_error_message,
)


logger = logging.getLogger(__name__)
TMP_DIR = ROOT_DIR / "tmp"
REMOTE_COMPONENTS = "ejs:github"
FORMAT_FALLBACKS = [
    "140/bestaudio[ext=m4a]/bestaudio",
    "bestaudio[ext=m4a]/bestaudio/best",
    "bestaudio/best",
    "ba/b",
    "best",
]
DEFAULT_CONCURRENT_FRAGMENTS = 3
MAX_SAFE_CONCURRENT_FRAGMENTS = 4


class AudioDownloadError(Exception):
    """Raised when audio download fails."""


@dataclass(frozen=True)
class AudioDownloadResult:
    audio_file_path: str


def download_audio(url: str, target_dir: Path | None = None) -> AudioDownloadResult:
    output_dir = target_dir or TMP_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if _should_reuse_cached_audio():
        cached_path = _resolve_downloaded_file_path_from_output_dir(url, output_dir)
        if cached_path is not None and cached_path.exists():
            try:
                relative_path = cached_path.relative_to(ROOT_DIR).as_posix()
            except ValueError:
                relative_path = cached_path.as_posix()
            logger.info("Reusing cached audio file %s", relative_path)
            return AudioDownloadResult(audio_file_path=relative_path)

    output_template = str(output_dir / "%(id)s.%(ext)s")
    concurrent_fragments = _get_safe_concurrent_fragments()
    logger.info("Downloading Whisper-ready media to %s", output_dir)
    logger.info("Using yt-dlp native concurrent fragments: %s", concurrent_fragments)

    completed = None
    stdout = ""
    stderr = ""
    combined_output = ""

    for format_selector in FORMAT_FALLBACKS:
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-playlist",
            "--remote-components",
            REMOTE_COMPONENTS,
            "--concurrent-fragments",
            str(concurrent_fragments),
            *get_yt_dlp_auth_args(),
            *get_yt_dlp_proxy_args(),
            "--format",
            format_selector,
            "--output",
            output_template,
            "--no-simulate",
            "--print",
            "filepath",
            url,
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        combined_output = stderr or stdout

        if completed.returncode == 0:
            break

        normalized_message = normalize_yt_dlp_error_message(combined_output)
        if "No module named yt_dlp" in combined_output:
            raise YtDlpNotInstalledError(
                "yt-dlp is not installed. Install it with "
                "`python -m pip install yt-dlp`."
            )

        if "Requested format is not available" in normalized_message:
            logger.warning(
                "yt-dlp format %s unavailable, trying fallback", format_selector
            )
            continue

        logger.error("yt-dlp audio download failed: %s", normalized_message)
        raise AudioDownloadError(normalized_message)

    if completed is None or completed.returncode != 0:
        normalized_message = normalize_yt_dlp_error_message(combined_output)
        logger.error(
            "yt-dlp audio download failed after format fallbacks: %s",
            normalized_message,
        )
        raise AudioDownloadError(normalized_message)

    final_path = _resolve_downloaded_file_path(stdout)
    if final_path is None:
        final_path = _resolve_downloaded_file_path_from_output_dir(url, output_dir)
    if final_path is None or not final_path.exists():
        raise AudioDownloadError("yt-dlp did not produce an audio file in tmp.")

    try:
        relative_path = final_path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        relative_path = final_path.as_posix()
    logger.info("Audio downloaded to %s", relative_path)
    return AudioDownloadResult(audio_file_path=relative_path)


def _resolve_downloaded_file_path(stdout: str) -> Path | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        candidate = Path(line)
        if candidate.exists():
            return candidate.resolve()
    return None


def _resolve_downloaded_file_path_from_output_dir(
    url: str, output_dir: Path
) -> Path | None:
    video_id = _extract_video_id(url)
    if not video_id:
        return None

    for pattern in (f"{video_id}.m4a", f"{video_id}.*"):
        for candidate in sorted(output_dir.glob(pattern)):
            if candidate.is_file():
                return candidate.resolve()
    return None


def _extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    if hostname == "youtu.be":
        candidate = parsed.path.strip("/")
        return candidate or None

    if hostname.endswith("youtube.com"):
        query_value = parse_qs(parsed.query).get("v", [])
        if query_value:
            candidate = query_value[0].strip()
            return candidate or None

    return None


def _get_safe_concurrent_fragments() -> int:
    raw_value = get_env_str("YTDLP_CONCURRENT_FRAGMENTS")
    if not raw_value:
        return DEFAULT_CONCURRENT_FRAGMENTS

    try:
        parsed = int(raw_value)
    except ValueError:
        logger.warning(
            "Invalid YTDLP_CONCURRENT_FRAGMENTS=%r, falling back to %s",
            raw_value,
            DEFAULT_CONCURRENT_FRAGMENTS,
        )
        return DEFAULT_CONCURRENT_FRAGMENTS

    if parsed < 1:
        return 1
    if parsed > MAX_SAFE_CONCURRENT_FRAGMENTS:
        logger.warning(
            "Clamping YTDLP_CONCURRENT_FRAGMENTS from %s to safe max %s",
            parsed,
            MAX_SAFE_CONCURRENT_FRAGMENTS,
        )
        return MAX_SAFE_CONCURRENT_FRAGMENTS
    return parsed


def _should_reuse_cached_audio() -> bool:
    raw_value = get_env_str("YTDLP_REUSE_AUDIO_CACHE").lower()
    return raw_value in {"1", "true", "yes", "on"}
