import html
import json
import logging
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import (
    ROOT_DIR,
    get_env_str,
    get_settings,
    get_yt_dlp_auth_args,
    get_yt_dlp_proxy_args,
    get_yt_dlp_youtube_extractor_args,
)
from app.services.job_cancel_context import get_cancel_event
from app.services.subprocess_utils import run_subprocess_killable


logger = logging.getLogger(__name__)
TMP_CAPTION_DIR = ROOT_DIR / "tmp" / "captions"
DEFAULT_CAPTION_HTTP_TIMEOUT_SECONDS = 5.0

TIMESTAMP_PATTERN = re.compile(
    r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{3})?\s+-->\s+(\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{3})?\s*$"
)
TAG_PATTERN = re.compile(r"<[^>]+>")


class CaptionServiceError(Exception):
    """Raised when caption extraction fails."""


class CaptionDownloadTimeoutError(CaptionServiceError):
    """Raised when yt-dlp exceeds the configured subtitle download timeout."""


@dataclass(frozen=True)
class CaptionResult:
    language: str
    text: str


def fetch_best_english_captions(
    video_info: dict[str, object],
    *,
    cancellation_checker=None,
    request_timeout_sec: float | None = None,
) -> CaptionResult | None:
    logger.info("Looking for English captions")

    subtitles = _as_caption_map(video_info.get("subtitles"))
    automatic_captions = _as_caption_map(video_info.get("automatic_captions"))

    selected = _pick_best_english_caption(subtitles)
    if selected is not None:
        logger.info("Using manual English subtitles: %s", selected[0])
        return _download_caption_text(
            video_info,
            selected,
            use_automatic_captions=False,
            cancellation_checker=cancellation_checker,
            request_timeout_sec=request_timeout_sec,
        )

    selected = _pick_best_english_caption(automatic_captions)
    if selected is not None:
        logger.info("Using automatic English captions: %s", selected[0])
        return _download_caption_text(
            video_info,
            selected,
            use_automatic_captions=True,
            cancellation_checker=cancellation_checker,
            request_timeout_sec=request_timeout_sec,
        )

    logger.info("No English captions available")
    return None


def _download_caption_text(
    video_info: dict[str, object],
    selected: tuple[str, list[dict[str, object]]],
    use_automatic_captions: bool,
    *,
    cancellation_checker=None,
    request_timeout_sec: float | None = None,
) -> CaptionResult:
    language, tracks = selected
    ext, url = _pick_caption_download_url(tracks)
    logger.info("Downloading caption track %s (%s)", language, ext)

    try:
        _raise_if_cancelled(cancellation_checker)
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=_get_caption_http_timeout_seconds(
                request_timeout_sec=request_timeout_sec,
            ),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 429 and _is_youtube_caption_url(url):
            _raise_if_cancelled(cancellation_checker)
            logger.warning(
                "Caption URL returned 429, retrying through yt-dlp for %s", language
            )
            return _download_caption_via_yt_dlp(
                video_info,
                language=language,
                preferred_ext=ext,
                use_automatic_captions=use_automatic_captions,
            )
        raise CaptionServiceError(f"Failed to download captions: {error}") from error
    except httpx.HTTPError as error:
        if _is_youtube_caption_url(url):
            _raise_if_cancelled(cancellation_checker)
            logger.warning(
                "Caption URL request failed (%s), retrying through yt-dlp for %s",
                error,
                language,
            )
            return _download_caption_via_yt_dlp(
                video_info,
                language=language,
                preferred_ext=ext,
                use_automatic_captions=use_automatic_captions,
            )
        raise CaptionServiceError(f"Failed to download captions: {error}") from error

    _raise_if_cancelled(cancellation_checker)
    decoded_text = response.content.decode("utf-8", errors="replace")
    text = _parse_caption_text(decoded_text, ext)
    if not text:
        raise CaptionServiceError("Downloaded captions were empty.")

    return CaptionResult(language=language, text=text)


def _get_caption_http_timeout_seconds(
    *,
    request_timeout_sec: float | None = None,
) -> float:
    raw_value = get_env_str("CAPTION_HTTP_TIMEOUT")
    if not raw_value:
        timeout_sec = DEFAULT_CAPTION_HTTP_TIMEOUT_SECONDS
    else:
        try:
            parsed = float(raw_value)
        except ValueError:
            logger.warning(
                "Invalid CAPTION_HTTP_TIMEOUT=%r, falling back to %.1f",
                raw_value,
                DEFAULT_CAPTION_HTTP_TIMEOUT_SECONDS,
            )
            timeout_sec = DEFAULT_CAPTION_HTTP_TIMEOUT_SECONDS
        else:
            if parsed < 1.0:
                timeout_sec = 1.0
            elif parsed > 60.0:
                timeout_sec = 60.0
            else:
                timeout_sec = parsed

    if request_timeout_sec is not None:
        try:
            timeout_sec = min(timeout_sec, float(request_timeout_sec))
        except (TypeError, ValueError):
            pass

    return max(1.0, timeout_sec)


def _raise_if_cancelled(cancellation_checker) -> None:
    from app.services.job_run_models import JobCancelledError

    cancel_event = get_cancel_event()
    if cancellation_checker and cancellation_checker():
        raise JobCancelledError("Job was cancelled by user.")
    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelledError("Job was cancelled by user.")


def _download_caption_via_yt_dlp(
    video_info: dict[str, object],
    *,
    language: str,
    preferred_ext: str,
    use_automatic_captions: bool,
) -> CaptionResult:
    video_url = _video_url_from_info(video_info)
    video_id = str(video_info.get("id") or "caption")

    TMP_CAPTION_DIR.mkdir(parents=True, exist_ok=True)
    output_template = str(TMP_CAPTION_DIR / f"{video_id}")
    timeout_sec = get_settings().yt_dlp_timeout_sec
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--skip-download",
        "--ignore-no-formats-error",
        "--no-warnings",
        "--no-playlist",
        *get_yt_dlp_youtube_extractor_args(),
        *get_yt_dlp_auth_args(),
        *get_yt_dlp_proxy_args(),
        *( ["--write-auto-subs"] if use_automatic_captions else ["--write-subs"] ),
        "--sub-langs",
        language,
        "--sub-format",
        preferred_ext,
        "--output",
        output_template,
        video_url,
    ]

    try:
        completed = run_subprocess_killable(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            subprocess_timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as error:
        logger.error(
            "yt-dlp caption download timed out after %ss for %s",
            timeout_sec,
            video_url,
        )
        raise CaptionDownloadTimeoutError(
            f"yt-dlp subtitle download timed out after {timeout_sec}s."
        ) from error

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        message = stderr or stdout or "yt-dlp subtitle download failed."
        raise CaptionServiceError(message)

    subtitle_file = _find_downloaded_subtitle_file(video_id, language, preferred_ext)
    if subtitle_file is None:
        raise CaptionServiceError("yt-dlp did not produce a subtitle file.")

    raw_text = subtitle_file.read_text(encoding="utf-8", errors="replace")
    text = _parse_caption_text(raw_text, preferred_ext)
    if not text:
        raise CaptionServiceError("Downloaded captions were empty.")

    return CaptionResult(language=language, text=text)


def _pick_best_english_caption(
    captions: dict[str, list[dict[str, object]]]
) -> tuple[str, list[dict[str, object]]] | None:
    english_languages = sorted(
        (
            language
            for language in captions.keys()
            if _is_english_language(language)
        ),
        key=_english_language_priority,
    )

    if not english_languages:
        return None

    best_language = english_languages[0]
    return best_language, captions[best_language]


def _pick_caption_download_url(tracks: list[dict[str, object]]) -> tuple[str, str]:
    preferred_extensions = ["json3", "vtt", "srt", "ttml", "srv3", "srv2", "srv1"]
    track_by_extension = {
        str(track.get("ext")): str(track.get("url"))
        for track in tracks
        if track.get("ext") and track.get("url")
    }

    for ext in preferred_extensions:
        url = track_by_extension.get(ext)
        if url:
            return ext, url

    raise CaptionServiceError("Could not find a downloadable caption format.")


def _find_downloaded_subtitle_file(
    video_id: str,
    language: str,
    preferred_ext: str,
) -> Path | None:
    candidates = [
        TMP_CAPTION_DIR / f"{video_id}.{language}.{preferred_ext}",
        TMP_CAPTION_DIR / f"{video_id}.{preferred_ext}",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    for candidate in TMP_CAPTION_DIR.glob(f"{video_id}*.{preferred_ext}"):
        if candidate.is_file():
            return candidate

    return None


def _parse_caption_text(raw_text: str, ext: str) -> str:
    if ext == "json3":
        return _parse_json3_text(raw_text)
    if ext in {"ttml", "srv1", "srv2", "srv3"}:
        return _parse_xml_caption_text(raw_text)
    return _parse_plain_caption_text(raw_text)


def _parse_json3_text(raw_text: str) -> str:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise CaptionServiceError("Caption JSON could not be parsed.") from error

    events = payload.get("events")
    if not isinstance(events, list):
        raise CaptionServiceError("Caption JSON did not include subtitle events.")

    lines: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        segments = event.get("segs")
        if not isinstance(segments, list):
            continue
        line = "".join(
            str(segment.get("utf8", ""))
            for segment in segments
            if isinstance(segment, dict)
        )
        normalized = _normalize_caption_line(line)
        if normalized:
            lines.append(normalized)

    return _dedupe_adjacent_lines(lines)


def _parse_xml_caption_text(raw_text: str) -> str:
    try:
        root = ET.fromstring(raw_text)
    except ET.ParseError as error:
        raise CaptionServiceError("Caption XML could not be parsed.") from error

    caption_elements = [
        element
        for element in root.iter()
        if _element_name(element) in {"text", "p"}
    ]
    elements_to_parse = caption_elements or list(root.iter())

    lines: list[str] = []
    for element in elements_to_parse:
        normalized = _normalize_caption_line("".join(element.itertext()))
        if normalized:
            lines.append(normalized)

    return _dedupe_adjacent_lines(lines)


def _parse_plain_caption_text(raw_text: str) -> str:
    lines: list[str] = []
    for raw_line in raw_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == "WEBVTT":
            continue
        if stripped.isdigit():
            continue
        if TIMESTAMP_PATTERN.match(stripped):
            continue
        normalized = _normalize_caption_line(stripped)
        if normalized:
            lines.append(normalized)

    return _dedupe_adjacent_lines(lines)


def _normalize_caption_line(value: str) -> str:
    without_tags = TAG_PATTERN.sub("", value)
    normalized = html.unescape(without_tags).replace("\n", " ").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _dedupe_adjacent_lines(lines: list[str]) -> str:
    deduped: list[str] = []
    for line in lines:
        if deduped and deduped[-1] == line:
            continue
        deduped.append(line)
    return "\n".join(deduped).strip()


def _as_caption_map(value: object) -> dict[str, list[dict[str, object]]]:
    if not isinstance(value, dict):
        return {}

    parsed: dict[str, list[dict[str, object]]] = {}
    for language, tracks in value.items():
        if not isinstance(language, str) or not isinstance(tracks, list):
            continue
        parsed[language] = [
            track
            for track in tracks
            if isinstance(track, dict)
        ]
    return parsed


def _is_english_language(language: str) -> bool:
    lowered = language.lower()
    return lowered == "en" or lowered.startswith("en-") or lowered.startswith("en_")


def _english_language_priority(language: str) -> tuple[int, str]:
    lowered = language.lower()
    if lowered == "en":
        return (0, lowered)
    if lowered.startswith("en-"):
        return (1, lowered)
    if lowered.startswith("en_"):
        return (2, lowered)
    return (3, lowered)


def _element_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", maxsplit=1)[-1].lower()


def _video_url_from_info(video_info: dict[str, object]) -> str:
    for key in ("webpage_url", "original_url", "url"):
        value = video_info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    video_id = str(video_info.get("id") or "").strip()
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    raise CaptionServiceError("Could not determine video URL for caption download.")


def _is_youtube_caption_url(url: str) -> bool:
    return "youtube.com/api/timedtext" in url
