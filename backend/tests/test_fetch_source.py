import subprocess
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services.audio_download_service import (
    AudioDownloadError,
    AudioDownloadResult,
    download_audio,
)
from app.services.caption_service import (
    CaptionServiceError,
    CaptionResult,
    fetch_best_english_captions,
)
from app.services.video_source_service import VideoSourceResult, fetch_video_source


client = TestClient(app)


def test_fetch_best_english_captions_prefers_manual_subtitles(monkeypatch) -> None:
    def fake_get(url: str, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text='{"events":[{"segs":[{"utf8":"Hello world"}]}]}',
        )

    monkeypatch.setattr("app.services.caption_service.httpx.get", fake_get)

    result = fetch_best_english_captions(
        {
            "subtitles": {"en": [{"ext": "json3", "url": "https://example.com/sub"}]},
            "automatic_captions": {
                "en": [{"ext": "json3", "url": "https://example.com/auto"}]
            },
        }
    )

    assert result == CaptionResult(language="en", text="Hello world")


def test_fetch_best_english_captions_falls_back_to_automatic(monkeypatch) -> None:
    def fake_get(url: str, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text='{"events":[{"segs":[{"utf8":"Automatic caption"}]}]}',
        )

    monkeypatch.setattr("app.services.caption_service.httpx.get", fake_get)

    result = fetch_best_english_captions(
        {
            "subtitles": {"ja": [{"ext": "json3", "url": "https://example.com/ja"}]},
            "automatic_captions": {
                "en-US": [{"ext": "json3", "url": "https://example.com/en-us"}]
            },
        }
    )

    assert result == CaptionResult(language="en-US", text="Automatic caption")


def test_fetch_best_english_captions_returns_none_when_not_available() -> None:
    result = fetch_best_english_captions(
        {
            "subtitles": {"ja": [{"ext": "json3", "url": "https://example.com/ja"}]},
            "automatic_captions": {
                "fr": [{"ext": "json3", "url": "https://example.com/fr"}]
            },
        }
    )

    assert result is None


def test_fetch_best_english_captions_parses_xml_subtitles(monkeypatch) -> None:
    def fake_get(url: str, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text="<transcript><text>Hello</text><text>World</text></transcript>",
        )

    monkeypatch.setattr("app.services.caption_service.httpx.get", fake_get)

    result = fetch_best_english_captions(
        {
            "subtitles": {"en": [{"ext": "srv3", "url": "https://example.com/xml"}]},
            "automatic_captions": {},
        }
    )

    assert result == CaptionResult(language="en", text="Hello\nWorld")


def test_download_audio_returns_downloaded_file_path(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = tmp_path / "abc123xyz.m4a"
    audio_file.write_text("audio")
    captured_command: list[str] = []

    def fake_run(*args, **kwargs):
        captured_command.extend(args[0])
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=str(audio_file),
            stderr="",
        )

    monkeypatch.setattr("app.services.audio_download_service.subprocess.run", fake_run)

    result = download_audio("https://www.youtube.com/watch?v=abc123xyz", tmp_path)

    assert "--cookies-from-browser" not in captured_command
    assert "--remote-components" in captured_command
    assert "ejs:github" in captured_command
    assert "--concurrent-fragments" in captured_command
    assert captured_command[captured_command.index("--concurrent-fragments") + 1] == "3"
    assert "--extract-audio" not in captured_command
    assert "--audio-format" not in captured_command
    assert (
        captured_command[captured_command.index("--format") + 1]
        == "140/bestaudio[ext=m4a]/bestaudio"
    )
    assert captured_command.count("--print") == 1
    assert captured_command[captured_command.index("--print") + 1] == "filepath"
    assert "--no-simulate" in captured_command
    assert result.audio_file_path.endswith("abc123xyz.m4a")


def test_download_audio_clamps_concurrent_fragments_to_safe_max(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = tmp_path / "abc123xyz.m4a"
    audio_file.write_text("audio")
    captured_command: list[str] = []
    monkeypatch.setenv("YTDLP_CONCURRENT_FRAGMENTS", "16")

    def fake_run(*args, **kwargs):
        captured_command.extend(args[0])
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=str(audio_file),
            stderr="",
        )

    monkeypatch.setattr("app.services.audio_download_service.subprocess.run", fake_run)

    result = download_audio("https://www.youtube.com/watch?v=abc123xyz", tmp_path)

    assert captured_command[captured_command.index("--concurrent-fragments") + 1] == "4"
    assert result.audio_file_path.endswith("abc123xyz.m4a")


def test_download_audio_falls_back_to_output_directory_scan_when_stdout_is_na(
    monkeypatch, tmp_path: Path
) -> None:
    audio_file = tmp_path / "abc123xyz.m4a"
    audio_file.write_text("audio")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="NA\n",
            stderr="",
        )

    monkeypatch.setattr("app.services.audio_download_service.subprocess.run", fake_run)

    result = download_audio("https://www.youtube.com/watch?v=abc123xyz", tmp_path)

    assert result.audio_file_path.endswith("abc123xyz.m4a")


def test_download_audio_uses_browser_cookies(monkeypatch, tmp_path: Path) -> None:
    audio_file = tmp_path / "abc123xyz.m4a"
    audio_file.write_text("audio")
    captured_command: list[str] = []
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")

    def fake_run(*args, **kwargs):
        captured_command.extend(args[0])
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=str(audio_file),
            stderr="",
        )

    monkeypatch.setattr("app.services.audio_download_service.subprocess.run", fake_run)

    result = download_audio("https://www.youtube.com/watch?v=abc123xyz", tmp_path)

    assert "--cookies-from-browser" in captured_command
    assert "edge" in captured_command
    assert result.audio_file_path.endswith("abc123xyz.m4a")


def test_download_audio_normalizes_cookie_database_failure(
    monkeypatch, tmp_path: Path
) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="ERROR: Could not copy Chrome cookie database. See https://example.com",
        )

    monkeypatch.setattr("app.services.audio_download_service.subprocess.run", fake_run)

    try:
        download_audio("https://www.youtube.com/watch?v=abc123xyz", tmp_path)
    except AudioDownloadError as error:
        assert str(error) == (
            "yt-dlp could not read Chrome cookies. Close all Chrome processes first, "
            "or export a cookies.txt file and set YTDLP_COOKIES_FILE in .env."
        )
    else:
        raise AssertionError("Expected AudioDownloadError")


def test_fetch_video_source_prefers_captions_when_available(monkeypatch) -> None:
    def fake_extract(url: str) -> dict[str, object]:
        return {
            "subtitles": {"en": [{"ext": "json3", "url": "https://example.com/sub"}]},
            "automatic_captions": {},
        }

    def fake_captions(video_info: dict[str, object]) -> CaptionResult | None:
        assert video_info["subtitles"] == {
            "en": [{"ext": "json3", "url": "https://example.com/sub"}]
        }
        return CaptionResult(language="en", text="Caption text")

    def fail_download(url: str) -> AudioDownloadResult:
        raise AssertionError(
            "Audio download should not run when captions are available."
        )

    monkeypatch.setattr(
        "app.services.video_source_service.extract_video_info", fake_extract
    )
    monkeypatch.setattr(
        "app.services.video_source_service.fetch_best_english_captions", fake_captions
    )
    monkeypatch.setattr(
        "app.services.video_source_service.download_audio", fail_download
    )

    result = fetch_video_source("https://www.youtube.com/watch?v=abc123xyz")

    assert result == VideoSourceResult(
        source_type="captions",
        language="en",
        text="Caption text",
        audio_file_path=None,
    )


def test_fetch_video_source_falls_back_to_audio(monkeypatch) -> None:
    def fake_extract(url: str) -> dict[str, object]:
        return {"subtitles": {}, "automatic_captions": {}}

    def fake_download(url: str) -> AudioDownloadResult:
        return AudioDownloadResult(audio_file_path="tmp/abc123xyz.m4a")

    monkeypatch.setattr(
        "app.services.video_source_service.extract_video_info", fake_extract
    )
    monkeypatch.setattr(
        "app.services.video_source_service.fetch_best_english_captions",
        lambda video_info: None,
    )
    monkeypatch.setattr(
        "app.services.video_source_service.download_audio", fake_download
    )

    result = fetch_video_source("https://www.youtube.com/watch?v=abc123xyz")

    assert result == VideoSourceResult(
        source_type="audio",
        language=None,
        text=None,
        audio_file_path="tmp/abc123xyz.m4a",
    )


def test_fetch_video_source_force_audio_skips_captions(monkeypatch) -> None:
    def fake_extract(url: str) -> dict[str, object]:
        return {
            "subtitles": {"en": [{"ext": "json3", "url": "https://example.com/sub"}]},
            "automatic_captions": {},
        }

    def fail_captions(video_info: dict[str, object]) -> CaptionResult | None:
        raise AssertionError(
            "Caption lookup should not run when force_audio is selected."
        )

    def fake_download(url: str) -> AudioDownloadResult:
        return AudioDownloadResult(audio_file_path="tmp/abc123xyz.m4a")

    monkeypatch.setattr(
        "app.services.video_source_service.extract_video_info", fake_extract
    )
    monkeypatch.setattr(
        "app.services.video_source_service.fetch_best_english_captions", fail_captions
    )
    monkeypatch.setattr(
        "app.services.video_source_service.download_audio", fake_download
    )

    result = fetch_video_source(
        "https://www.youtube.com/watch?v=abc123xyz",
        source_mode="force_audio",
    )

    assert result == VideoSourceResult(
        source_type="audio",
        language=None,
        text=None,
        audio_file_path="tmp/abc123xyz.m4a",
    )


def test_fetch_video_source_ignores_caption_errors_and_downloads_audio(
    monkeypatch,
) -> None:
    def fake_extract(url: str) -> dict[str, object]:
        return {"subtitles": {"en": [{}]}, "automatic_captions": {}}

    def fake_download(url: str) -> AudioDownloadResult:
        return AudioDownloadResult(audio_file_path="tmp/abc123xyz.m4a")

    monkeypatch.setattr(
        "app.services.video_source_service.extract_video_info", fake_extract
    )

    def fail_captions(video_info: dict[str, object]) -> CaptionResult | None:
        raise CaptionServiceError("caption failure")

    monkeypatch.setattr(
        "app.services.video_source_service.fetch_best_english_captions", fail_captions
    )
    monkeypatch.setattr(
        "app.services.video_source_service.download_audio", fake_download
    )

    result = fetch_video_source("https://www.youtube.com/watch?v=abc123xyz")

    assert result == VideoSourceResult(
        source_type="audio",
        language=None,
        text=None,
        audio_file_path="tmp/abc123xyz.m4a",
    )


def test_fetch_source_endpoint_returns_captions(monkeypatch) -> None:
    def fake_fetch(url: str, source_mode: str = "subtitle_first") -> VideoSourceResult:
        assert source_mode == "subtitle_first"
        return VideoSourceResult(
            source_type="captions",
            language="en",
            text="Caption text",
        )

    monkeypatch.setattr("app.main.fetch_video_source", fake_fetch)

    response = client.post(
        "/api/video/fetch-source",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "source_type": "captions",
        "language": "en",
        "text": "Caption text",
        "audio_file_path": None,
    }


def test_fetch_source_endpoint_returns_audio(monkeypatch) -> None:
    def fake_fetch(url: str, source_mode: str = "subtitle_first") -> VideoSourceResult:
        assert source_mode == "subtitle_first"
        return VideoSourceResult(
            source_type="audio",
            audio_file_path="tmp/abc123xyz.m4a",
        )

    monkeypatch.setattr("app.main.fetch_video_source", fake_fetch)

    response = client.post(
        "/api/video/fetch-source",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "source_type": "audio",
        "language": None,
        "text": None,
        "audio_file_path": "tmp/abc123xyz.m4a",
    }


def test_fetch_source_endpoint_forwards_source_mode(monkeypatch) -> None:
    def fake_fetch(url: str, source_mode: str) -> VideoSourceResult:
        assert url == "https://www.youtube.com/watch?v=abc123xyz"
        assert source_mode == "force_audio"
        return VideoSourceResult(
            source_type="audio",
            audio_file_path="tmp/abc123xyz.m4a",
        )

    monkeypatch.setattr("app.main.fetch_video_source", fake_fetch)

    response = client.post(
        "/api/video/fetch-source",
        json={
            "url": "https://www.youtube.com/watch?v=abc123xyz",
            "source_mode": "force_audio",
        },
    )

    assert response.status_code == 200
    assert response.json()["source_type"] == "audio"
