import os
import time
from pathlib import Path

from app.services.tmp_artifact_cleanup_service import cleanup_stale_tmp_artifacts


def _write_file(path: Path, content: str = "x", age_seconds: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if age_seconds:
        stale_time = time.time() - age_seconds
        os.utime(path, (stale_time, stale_time))
    return path


def test_cleanup_stale_tmp_artifacts_removes_old_generated_files(tmp_path: Path) -> None:
    root = tmp_path / "tmp"
    stale_audio = _write_file(root / "video-1.m4a", age_seconds=3 * 3600)
    fresh_audio = _write_file(root / "video-2.webm", age_seconds=5 * 60)
    stale_caption = _write_file(root / "captions" / "video-1.en.vtt", age_seconds=3 * 3600)
    stale_video_info = _write_file(
        root / "video_info_cache" / "abc123.json",
        age_seconds=3 * 3600,
    )
    preserved_cache = _write_file(
        root / "persistent_cache" / "keep.json",
        age_seconds=3 * 3600,
    )

    result = cleanup_stale_tmp_artifacts(tmp_root=root, ttl_hours=1)

    assert result["removed"] == 3
    assert not stale_audio.exists()
    assert not stale_caption.exists()
    assert not stale_video_info.exists()
    assert fresh_audio.exists()
    assert preserved_cache.exists()
