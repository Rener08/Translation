import logging
from dataclasses import dataclass
from typing import Literal

from app.services.audio_download_service import AudioDownloadResult, download_audio
from app.services.caption_service import (
    CaptionServiceError,
    fetch_best_english_captions,
)
from app.services.yt_dlp_service import extract_video_info


logger = logging.getLogger(__name__)

SOURCE_MODE_SUBTITLE_FIRST = "subtitle_first"
SOURCE_MODE_FORCE_AUDIO = "force_audio"
SourceMode = Literal["subtitle_first", "force_audio"]


@dataclass(frozen=True)
class VideoSourceResult:
    source_type: Literal["captions", "audio"]
    language: str | None = None
    text: str | None = None
    audio_file_path: str | None = None


def fetch_video_source(
    url: str,
    source_mode: SourceMode = SOURCE_MODE_SUBTITLE_FIRST,
) -> VideoSourceResult:
    logger.info("Fetching source for %s", url)
    video_info = extract_video_info(url)
    return fetch_video_source_from_info(url, video_info, source_mode=source_mode)


def fetch_video_source_from_info(
    url: str,
    video_info: dict[str, object],
    source_mode: SourceMode = SOURCE_MODE_SUBTITLE_FIRST,
) -> VideoSourceResult:
    if source_mode == SOURCE_MODE_FORCE_AUDIO:
        logger.info("Source mode force_audio selected for %s; downloading audio", url)
        audio_result = download_audio(url)
        return _audio_result_to_source(audio_result)

    try:
        caption_result = fetch_best_english_captions(video_info)
    except CaptionServiceError as error:
        logger.warning(
            "Caption fetch failed for %s, falling back to audio: %s", url, error
        )
        caption_result = None

    if caption_result is not None:
        logger.info("Using English captions for %s", url)
        return VideoSourceResult(
            source_type="captions",
            language=caption_result.language,
            text=caption_result.text,
        )

    logger.info("No usable English captions for %s; downloading audio for Whisper", url)
    audio_result = download_audio(url)
    return _audio_result_to_source(audio_result)


def _audio_result_to_source(result: AudioDownloadResult) -> VideoSourceResult:
    return VideoSourceResult(
        source_type="audio",
        audio_file_path=result.audio_file_path,
    )
