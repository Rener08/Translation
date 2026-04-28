from fastapi.testclient import TestClient

from app.main import app
from app.services.job_run_service import (
    JobRunResult,
    run_video_job,
    run_video_job_with_translation_config,
)
from app.services.translation_service import (
    TranslationSegment,
    TranslationProviderError,
)
from app.services.transcription_service import TranscriptSegment, TranscriptionResult
from app.services.video_source_service import VideoSourceResult
from app.services.yt_dlp_service import VideoMetadata


client = TestClient(app)


def test_run_video_job_uses_caption_source_without_transcription(monkeypatch) -> None:
    video_info = {"id": "abc123xyz", "title": "Test video"}

    def fake_extract(url: str) -> dict[str, object]:
        assert url == "https://www.youtube.com/watch?v=abc123xyz"
        return video_info  # type: ignore[return-value]

    def fake_build(payload: dict[str, object]) -> VideoMetadata:
        assert payload is video_info
        return VideoMetadata(
            video_id="abc123xyz",
            title="Test video",
            duration_sec=10,
            uploader="Uploader",
            thumbnail="https://example.com/thumb.jpg",
            subtitles=["en"],
            automatic_captions=[],
        )

    def fake_source(
        url: str,
        payload: dict[str, object],
        source_mode: str = "subtitle_first",
    ) -> VideoSourceResult:
        assert url == "https://www.youtube.com/watch?v=abc123xyz"
        assert payload is video_info
        assert source_mode == "subtitle_first"
        return VideoSourceResult(
            source_type="captions",
            language="en",
            text="Hello everyone.\nWelcome back.",
        )

    def fail_transcribe(audio_file_path: str) -> TranscriptionResult:
        raise AssertionError("Audio transcription should not run for captions.")

    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        assert segments == [
            {"index": 0, "start": 0.0, "end": 0.0, "text": "Hello everyone."},
            {"index": 1, "start": 0.0, "end": 0.0, "text": "Welcome back."},
        ]
        assert translation_config is None
        return [
            TranslationSegment(
                index=0,
                start=0.0,
                end=0.0,
                source_text="Hello everyone.",
                translated_text="\u5927\u5bb6\u597d\u3002",
            ),
            TranslationSegment(
                index=1,
                start=0.0,
                end=0.0,
                source_text="Welcome back.",
                translated_text="\u6b22\u8fce\u56de\u6765\u3002",
            ),
        ]

    monkeypatch.setattr("app.services.job_run_service.extract_video_info", fake_extract)
    monkeypatch.setattr("app.services.job_run_service.build_video_metadata", fake_build)
    monkeypatch.setattr(
        "app.services.job_run_service.fetch_video_source_from_info",
        fake_source,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.transcribe_audio_file", fail_transcribe
    )
    monkeypatch.setattr(
        "app.services.job_run_service._maybe_attach_speakers",
        lambda video, source, transcript: transcript,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.translate_segments_to_chinese",
        fake_translate,
    )

    result = run_video_job("https://www.youtube.com/watch?v=abc123xyz")

    assert result.video.title == "Test video"
    assert result.source_type == "captions"
    assert result.transcript_en.text == "Hello everyone.\nWelcome back."
    assert len(result.transcript_en.segments) == 2
    assert len(result.translation_zh_segments) == 2
    assert result.content_context_id


def test_run_video_job_transcribes_audio_source(monkeypatch) -> None:
    def fake_extract(url: str) -> dict[str, object]:
        return {"id": "abc123xyz", "title": "Test video"}

    def fake_build(payload: dict[str, object]) -> VideoMetadata:
        return VideoMetadata(
            video_id="abc123xyz",
            title="Test video",
            duration_sec=10,
            uploader="Uploader",
            thumbnail="https://example.com/thumb.jpg",
            subtitles=[],
            automatic_captions=[],
        )

    def fake_source(
        url: str,
        payload: dict[str, object],
        source_mode: str = "subtitle_first",
    ) -> VideoSourceResult:
        assert source_mode == "subtitle_first"
        return VideoSourceResult(
            source_type="audio",
            audio_file_path="tmp/sample.webm",
        )

    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        assert audio_file_path == "tmp/sample.webm"
        return TranscriptionResult(
            language="en",
            text="Hello everyone.",
            segments=[
                TranscriptSegment(
                    index=0,
                    start=0.0,
                    end=1.5,
                    text="Hello everyone.",
                )
            ],
        )

    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        assert segments == [
            {"index": 0, "start": 0.0, "end": 1.5, "text": "Hello everyone."}
        ]
        assert translation_config is None
        return [
            TranslationSegment(
                index=0,
                start=0.0,
                end=1.5,
                source_text="Hello everyone.",
                translated_text="\u5927\u5bb6\u597d\u3002",
            )
        ]

    monkeypatch.setattr("app.services.job_run_service.extract_video_info", fake_extract)
    monkeypatch.setattr("app.services.job_run_service.build_video_metadata", fake_build)
    monkeypatch.setattr(
        "app.services.job_run_service.fetch_video_source_from_info",
        fake_source,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.transcribe_audio_file",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.translate_segments_to_chinese",
        fake_translate,
    )

    result = run_video_job("https://www.youtube.com/watch?v=abc123xyz")

    assert result.source_type == "audio"
    assert result.transcript_en.text == "Hello everyone."
    assert result.transcript_en.segments[0].speaker is None
    assert (
        result.translation_zh_segments[0].translated_text == "\u5927\u5bb6\u597d\u3002"
    )
    assert result.content_context_id


def test_run_video_job_with_translation_config_forwards_force_audio_mode(
    monkeypatch,
) -> None:
    def fake_extract(url: str) -> dict[str, object]:
        return {"id": "abc123xyz", "title": "Test video"}

    def fake_build(payload: dict[str, object]) -> VideoMetadata:
        return VideoMetadata(
            video_id="abc123xyz",
            title="Test video",
            duration_sec=10,
            uploader="Uploader",
            thumbnail="https://example.com/thumb.jpg",
            subtitles=["en"],
            automatic_captions=[],
        )

    def fake_source(
        url: str,
        payload: dict[str, object],
        source_mode: str = "subtitle_first",
    ) -> VideoSourceResult:
        assert source_mode == "force_audio"
        return VideoSourceResult(
            source_type="audio",
            audio_file_path="tmp/sample.webm",
        )

    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        return TranscriptionResult(
            language="en",
            text="Audio transcript",
            segments=[
                TranscriptSegment(
                    index=0,
                    start=0.0,
                    end=1.0,
                    text="Audio transcript",
                )
            ],
        )

    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        return [
            TranslationSegment(
                index=0,
                start=0.0,
                end=1.0,
                source_text="Audio transcript",
                translated_text="\u97f3\u9891\u8f6c\u5f55",
            )
        ]

    monkeypatch.setattr("app.services.job_run_service.extract_video_info", fake_extract)
    monkeypatch.setattr("app.services.job_run_service.build_video_metadata", fake_build)
    monkeypatch.setattr(
        "app.services.job_run_service.fetch_video_source_from_info",
        fake_source,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.transcribe_audio_file",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.translate_segments_to_chinese",
        fake_translate,
    )

    result = run_video_job_with_translation_config(
        "https://www.youtube.com/watch?v=abc123xyz",
        source_mode="force_audio",
    )

    assert result.source_type == "audio"


def test_run_video_job_falls_back_to_single_segment_when_transcript_has_no_segments(
    monkeypatch,
) -> None:
    def fake_extract(url: str) -> dict[str, object]:
        return {"id": "abc123xyz", "title": "Test video"}

    def fake_build(payload: dict[str, object]) -> VideoMetadata:
        return VideoMetadata(
            video_id="abc123xyz",
            title="Test video",
            duration_sec=10,
            uploader="Uploader",
            thumbnail="https://example.com/thumb.jpg",
            subtitles=[],
            automatic_captions=[],
        )

    def fake_source(
        url: str,
        payload: dict[str, object],
        source_mode: str = "subtitle_first",
    ) -> VideoSourceResult:
        assert source_mode == "subtitle_first"
        return VideoSourceResult(
            source_type="audio",
            audio_file_path="tmp/sample.webm",
        )

    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        return TranscriptionResult(
            language="en",
            text="One full transcript block.",
            segments=[],
        )

    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        assert segments == [
            {
                "index": 0,
                "start": 0.0,
                "end": 0.0,
                "text": "One full transcript block.",
            }
        ]
        assert translation_config is None
        return [
            TranslationSegment(
                index=0,
                start=0.0,
                end=0.0,
                source_text="One full transcript block.",
                translated_text="\u4e00\u6574\u6bb5\u82f1\u6587\u8f6c\u5f55\u3002",
            )
        ]

    monkeypatch.setattr("app.services.job_run_service.extract_video_info", fake_extract)
    monkeypatch.setattr("app.services.job_run_service.build_video_metadata", fake_build)
    monkeypatch.setattr(
        "app.services.job_run_service.fetch_video_source_from_info",
        fake_source,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.transcribe_audio_file",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "app.services.job_run_service._maybe_attach_speakers",
        lambda video, source, transcript: transcript,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.translate_segments_to_chinese",
        fake_translate,
    )

    result = run_video_job("https://www.youtube.com/watch?v=abc123xyz")

    assert len(result.transcript_en.segments) == 1
    assert result.transcript_en.segments[0].text == "One full transcript block."


def test_run_video_job_forwards_translation_config(monkeypatch) -> None:
    def fake_extract(url: str) -> dict[str, object]:
        return {"id": "abc123xyz", "title": "Test video"}

    def fake_build(payload: dict[str, object]) -> VideoMetadata:
        return VideoMetadata(
            video_id="abc123xyz",
            title="Test video",
            duration_sec=10,
            uploader="Uploader",
            thumbnail="https://example.com/thumb.jpg",
            subtitles=["en"],
            automatic_captions=[],
        )

    def fake_source(
        url: str,
        payload: dict[str, object],
        source_mode: str = "subtitle_first",
    ) -> VideoSourceResult:
        assert source_mode == "subtitle_first"
        return VideoSourceResult(
            source_type="captions",
            language="en",
            text="Hello everyone.",
        )

    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        assert translation_config == {
            "provider": "deepseek",
            "api_key": "deepseek-demo-key",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "extra_headers": {"X-Test-Header": "demo"},
        }
        return [
            TranslationSegment(
                index=0,
                start=0.0,
                end=0.0,
                source_text="Hello everyone.",
                translated_text="\u5927\u5bb6\u597d\u3002",
            )
        ]

    monkeypatch.setattr("app.services.job_run_service.extract_video_info", fake_extract)
    monkeypatch.setattr("app.services.job_run_service.build_video_metadata", fake_build)
    monkeypatch.setattr(
        "app.services.job_run_service.fetch_video_source_from_info",
        fake_source,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.translate_segments_to_chinese",
        fake_translate,
    )
    monkeypatch.setattr(
        "app.services.job_run_service._maybe_attach_speakers",
        lambda video, source, transcript: transcript,
    )

    result = run_video_job_with_translation_config(
        "https://www.youtube.com/watch?v=abc123xyz",
        translation_config={
            "provider": "deepseek",
            "api_key": "deepseek-demo-key",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "extra_headers": {"X-Test-Header": "demo"},
        },
    )

    assert (
        result.translation_zh_segments[0].translated_text == "\u5927\u5bb6\u597d\u3002"
    )


def test_run_video_job_can_attach_speakers_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("JOB_RUN_ATTACH_SPEAKERS", "true")

    def fake_extract(url: str) -> dict[str, object]:
        return {"id": "abc123xyz", "title": "Test video"}

    def fake_build(payload: dict[str, object]) -> VideoMetadata:
        return VideoMetadata(
            video_id="abc123xyz",
            title="Test video",
            duration_sec=10,
            uploader="Uploader",
            thumbnail="https://example.com/thumb.jpg",
            subtitles=[],
            automatic_captions=[],
        )

    def fake_source(
        url: str,
        payload: dict[str, object],
        source_mode: str = "subtitle_first",
    ) -> VideoSourceResult:
        assert source_mode == "subtitle_first"
        return VideoSourceResult(
            source_type="audio",
            audio_file_path="tmp/sample.webm",
        )

    def fake_transcribe(audio_file_path: str) -> TranscriptionResult:
        return TranscriptionResult(
            language="en",
            text="Hello everyone.",
            segments=[
                TranscriptSegment(
                    index=0,
                    start=0.0,
                    end=1.5,
                    text="Hello everyone.",
                )
            ],
        )

    def fake_attach(video, source, transcript):
        return TranscriptionResult(
            language=transcript.language,
            text=transcript.text,
            segments=[
                TranscriptSegment(
                    index=0,
                    start=0.0,
                    end=1.5,
                    text="Hello everyone.",
                    speaker="Felix LeClair",
                )
            ],
        )

    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        return [
            TranslationSegment(
                index=0,
                start=0.0,
                end=1.5,
                source_text="Hello everyone.",
                translated_text="\u5927\u5bb6\u597d\u3002",
            )
        ]

    monkeypatch.setattr("app.services.job_run_service.extract_video_info", fake_extract)
    monkeypatch.setattr("app.services.job_run_service.build_video_metadata", fake_build)
    monkeypatch.setattr(
        "app.services.job_run_service.fetch_video_source_from_info",
        fake_source,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.transcribe_audio_file",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "app.services.job_run_service._maybe_attach_speakers",
        fake_attach,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.translate_segments_to_chinese",
        fake_translate,
    )

    result = run_video_job("https://www.youtube.com/watch?v=abc123xyz")

    assert result.transcript_en.segments[0].speaker == "Felix LeClair"


def test_run_video_job_merges_caption_lines_before_translation(monkeypatch) -> None:
    def fake_extract(url: str) -> dict[str, object]:
        return {"id": "abc123xyz", "title": "Test video"}

    def fake_build(payload: dict[str, object]) -> VideoMetadata:
        return VideoMetadata(
            video_id="abc123xyz",
            title="Test video",
            subtitles=["en"],
            automatic_captions=[],
        )

    def fake_source(
        url: str,
        payload: dict[str, object],
        source_mode: str = "subtitle_first",
    ) -> VideoSourceResult:
        return VideoSourceResult(
            source_type="captions",
            language="en",
            text="OpenAI was founded on December 11,\n2015 in San Francisco.\nIt later launched GPT.",
        )

    captured_segments: list[dict[str, object]] = []

    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        captured_segments.extend(segments)
        return [
            TranslationSegment(
                index=index,
                start=float(index),
                end=float(index),
                source_text=str(segment["text"]),
                translated_text=f"翻译 {index}",
            )
            for index, segment in enumerate(segments)
        ]

    monkeypatch.setattr("app.services.job_run_service.extract_video_info", fake_extract)
    monkeypatch.setattr("app.services.job_run_service.build_video_metadata", fake_build)
    monkeypatch.setattr(
        "app.services.job_run_service.fetch_video_source_from_info",
        fake_source,
    )
    monkeypatch.setattr(
        "app.services.job_run_service._maybe_attach_speakers",
        lambda video, source, transcript: transcript,
    )
    monkeypatch.setattr(
        "app.services.job_run_service.translate_segments_to_chinese",
        fake_translate,
    )

    result = run_video_job("https://www.youtube.com/watch?v=abc123xyz")

    assert [segment["text"] for segment in captured_segments] == [
        "OpenAI was founded on December 11, 2015 in San Francisco.",
        "It later launched GPT.",
    ]
    assert len(result.transcript_en.segments) == 2


def test_jobs_run_endpoint_returns_final_result(monkeypatch) -> None:
    def fake_run(
        url: str,
        source_mode: str = "subtitle_first",
        translation_config: dict[str, object] | None = None,
    ) -> JobRunResult:
        assert url == "https://www.youtube.com/watch?v=abc123xyz"
        assert source_mode == "subtitle_first"
        assert translation_config is None
        return JobRunResult(
            video=VideoMetadata(
                video_id="abc123xyz",
                title="Test video",
                duration_sec=10,
                uploader="Uploader",
                thumbnail="https://example.com/thumb.jpg",
                subtitles=["en"],
                automatic_captions=[],
            ),
            source_type="captions",
            transcript_en=TranscriptionResult(
                language="en",
                text="Hello everyone.",
                segments=[
                    TranscriptSegment(
                        index=0,
                        start=0.0,
                        end=0.0,
                        text="Hello everyone.",
                        speaker="Felix LeClair",
                    )
                ],
            ),
            translation_zh_segments=[
                TranslationSegment(
                    index=0,
                    start=0.0,
                    end=0.0,
                    source_text="Hello everyone.",
                    translated_text="\u5927\u5bb6\u597d\u3002",
                )
            ],
            content_context_id="ctx_demo",
        )

    monkeypatch.setattr("app.main.run_video_job_with_translation_config", fake_run)

    response = client.post(
        "/api/jobs/run",
        json={"url": "https://youtu.be/abc123xyz?t=12"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "video": {
            "video_id": "abc123xyz",
            "title": "Test video",
            "thumbnail": "https://example.com/thumb.jpg",
            "duration_sec": 10,
            "uploader": "Uploader",
        },
        "source_type": "captions",
        "transcript_en": {
            "text": "Hello everyone.",
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 0.0,
                    "text": "Hello everyone.",
                    "speaker": "Felix LeClair",
                }
            ],
        },
        "translation_zh": {
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 0.0,
                    "source_text": "Hello everyone.",
                    "translated_text": "\u5927\u5bb6\u597d\u3002",
                }
            ]
        },
        "content_context_id": "ctx_demo",
    }


def test_jobs_run_endpoint_rejects_invalid_url() -> None:
    response = client.post(
        "/api/jobs/run",
        json={"url": "https://example.com/not-youtube"},
    )

    assert response.status_code == 400


def test_jobs_run_endpoint_returns_upstream_error(monkeypatch) -> None:
    def fake_run(
        url: str,
        source_mode: str = "subtitle_first",
        translation_config: dict[str, object] | None = None,
    ) -> JobRunResult:
        assert source_mode == "subtitle_first"
        raise TranslationProviderError("Upstream translation failed.")

    monkeypatch.setattr("app.main.run_video_job_with_translation_config", fake_run)

    response = client.post(
        "/api/jobs/run",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Upstream translation failed."}


def test_jobs_run_endpoint_forwards_translation_config(monkeypatch) -> None:
    def fake_run(
        url: str,
        source_mode: str = "subtitle_first",
        translation_config: dict[str, object] | None = None,
    ) -> JobRunResult:
        assert source_mode == "subtitle_first"
        assert translation_config == {
            "provider": "deepseek",
            "api_key": "deepseek-demo-key",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "extra_headers": {"X-Test-Header": "demo"},
        }
        return JobRunResult(
            video=VideoMetadata(
                video_id="abc123xyz",
                title="Test video",
                duration_sec=10,
                uploader="Uploader",
                thumbnail="https://example.com/thumb.jpg",
                subtitles=["en"],
                automatic_captions=[],
            ),
            source_type="captions",
            transcript_en=TranscriptionResult(
                language="en",
                text="Hello everyone.",
                segments=[
                    TranscriptSegment(
                        index=0,
                        start=0.0,
                        end=0.0,
                        text="Hello everyone.",
                        speaker="Felix LeClair",
                    )
                ],
            ),
            translation_zh_segments=[
                TranslationSegment(
                    index=0,
                    start=0.0,
                    end=0.0,
                    source_text="Hello everyone.",
                    translated_text="\u5927\u5bb6\u597d\u3002",
                )
            ],
            content_context_id="ctx_demo",
        )

    monkeypatch.setattr("app.main.run_video_job_with_translation_config", fake_run)

    response = client.post(
        "/api/jobs/run",
        json={
            "url": "https://www.youtube.com/watch?v=abc123xyz",
            "translation_config": {
                "provider": "deepseek",
                "api_key": "deepseek-demo-key",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-chat",
                "extra_headers": {"X-Test-Header": "demo"},
            },
        },
    )

    assert response.status_code == 200


def test_jobs_run_endpoint_forwards_source_mode(monkeypatch) -> None:
    def fake_run(
        url: str,
        source_mode: str = "subtitle_first",
        translation_config: dict[str, object] | None = None,
    ) -> JobRunResult:
        assert url == "https://www.youtube.com/watch?v=abc123xyz"
        assert source_mode == "force_audio"
        assert translation_config is None
        return JobRunResult(
            video=VideoMetadata(
                video_id="abc123xyz",
                title="Test video",
                duration_sec=10,
                uploader="Uploader",
                thumbnail="https://example.com/thumb.jpg",
                subtitles=[],
                automatic_captions=[],
            ),
            source_type="audio",
            transcript_en=TranscriptionResult(
                language="en",
                text="Audio transcript",
                segments=[
                    TranscriptSegment(
                        index=0,
                        start=0.0,
                        end=1.0,
                        text="Audio transcript",
                    )
                ],
            ),
            translation_zh_segments=[
                TranslationSegment(
                    index=0,
                    start=0.0,
                    end=1.0,
                    source_text="Audio transcript",
                    translated_text="音频转录",
                )
            ],
            content_context_id="ctx_demo",
        )

    monkeypatch.setattr("app.main.run_video_job_with_translation_config", fake_run)

    response = client.post(
        "/api/jobs/run",
        json={
            "url": "https://www.youtube.com/watch?v=abc123xyz",
            "source_mode": "force_audio",
        },
    )

    assert response.status_code == 200
    assert response.json()["source_type"] == "audio"
