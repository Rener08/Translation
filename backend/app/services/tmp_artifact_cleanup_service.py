import logging
from pathlib import Path

from app.config import ROOT_DIR, get_env_str


logger = logging.getLogger(__name__)
TMP_ROOT_DIR = ROOT_DIR / "tmp"
DEFAULT_TMP_ARTIFACT_TTL_HOURS = 24
MANAGED_ROOT_FILE_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}
MANAGED_SUBDIRS = (
    "captions",
    "video_info_cache",
)


def cleanup_stale_tmp_artifacts(
    *,
    tmp_root: Path | None = None,
    ttl_hours: float | None = None,
) -> dict[str, int]:
    root_dir = Path(tmp_root or TMP_ROOT_DIR)
    if not root_dir.exists():
        return {"removed": 0, "skipped": 0}

    ttl_seconds = _resolve_ttl_seconds(ttl_hours)
    cutoff_mtime = _cutoff_mtime(ttl_seconds)

    removed = 0
    skipped = 0

    for candidate in _iter_managed_tmp_artifacts(root_dir):
        try:
            if not candidate.exists() or not candidate.is_file():
                skipped += 1
                continue
            if candidate.stat().st_mtime >= cutoff_mtime:
                continue
            candidate.unlink()
            removed += 1
        except OSError:
            skipped += 1

    logger.info(
        "Tmp artifact cleanup finished: removed=%s skipped=%s root=%s",
        removed,
        skipped,
        root_dir,
    )
    return {"removed": removed, "skipped": skipped}


def _iter_managed_tmp_artifacts(root_dir: Path):
    for entry in root_dir.iterdir():
        if entry.is_file():
            if _should_manage_root_file(entry):
                yield entry
            continue

        if not entry.is_dir():
            continue

        if entry.name not in MANAGED_SUBDIRS:
            continue

        yield from entry.rglob("*")


def _should_manage_root_file(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".diarize.wav"):
        return True
    return path.suffix.lower() in MANAGED_ROOT_FILE_SUFFIXES


def _resolve_ttl_seconds(ttl_hours: float | None) -> float:
    if ttl_hours is not None:
        return max(0.0, float(ttl_hours) * 3600.0)

    raw_value = get_env_str("TMP_ARTIFACT_TTL_HOURS")
    if not raw_value:
        return float(DEFAULT_TMP_ARTIFACT_TTL_HOURS) * 3600.0

    try:
        parsed = float(raw_value)
    except ValueError:
        logger.warning(
            "Invalid TMP_ARTIFACT_TTL_HOURS=%r, falling back to %s",
            raw_value,
            DEFAULT_TMP_ARTIFACT_TTL_HOURS,
        )
        return float(DEFAULT_TMP_ARTIFACT_TTL_HOURS) * 3600.0

    if parsed < 0.0:
        return 0.0
    return parsed * 3600.0


def _cutoff_mtime(ttl_seconds: float) -> float:
    if ttl_seconds <= 0.0:
        return float("inf")

    import time

    return time.time() - ttl_seconds
