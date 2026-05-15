from __future__ import annotations

from pathlib import Path
import re
from uuid import uuid4

from fastapi import UploadFile

from app.config import ROOT_DIR, get_settings


UPLOAD_AUDIO_DIR = ROOT_DIR / "tmp" / "upload"
SAFE_FILE_STEM_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
ALLOWED_UPLOAD_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}


class UploadAudioError(ValueError):
    """Raised when an uploaded audio file cannot be accepted."""


def build_upload_title(filename: str) -> str:
    raw_name = Path(str(filename or "").strip()).stem.strip()
    if not raw_name:
        return "Uploaded audio"
    compact_name = re.sub(r"\s+", " ", raw_name).strip()
    return compact_name or "Uploaded audio"


async def save_uploaded_audio_file(file: UploadFile) -> tuple[str, str, str, int]:
    original_filename = Path(str(file.filename or "").strip()).name
    if not original_filename:
        raise UploadAudioError("Uploaded file must include a filename.")

    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_SUFFIXES))
        raise UploadAudioError(
            f"Unsupported upload file type '{suffix or '(none)'}'. Allowed types: {allowed}."
        )

    safe_stem = SAFE_FILE_STEM_PATTERN.sub("-", Path(original_filename).stem).strip("-._")
    if not safe_stem:
        safe_stem = "upload"

    UPLOAD_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    target_path = UPLOAD_AUDIO_DIR / f"{safe_stem}-{uuid4().hex[:12]}{suffix}"
    max_audio_bytes = get_settings().max_audio_bytes
    total_bytes = 0

    try:
        with target_path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if max_audio_bytes > 0 and total_bytes > max_audio_bytes:
                    raise UploadAudioError(
                        f"Uploaded file is {total_bytes} bytes, exceeding MAX_AUDIO_BYTES={max_audio_bytes}."
                    )
                handle.write(chunk)
    except Exception:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    relative_path = target_path.relative_to(ROOT_DIR).as_posix()
    return (
        relative_path,
        build_upload_title(original_filename),
        original_filename,
        total_bytes,
    )
