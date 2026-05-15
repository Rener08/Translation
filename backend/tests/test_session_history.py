import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.content_context_service import create_content_context
from app.services.job_run_service import JobRunResult
from app.services import persistent_cache_service
from app.services.session_history_service import (
    append_chat_exchange,
    load_session_history,
    record_rewrite_result,
    upsert_job_session,
)
from app.services.transcription_service import TranscriptSegment, TranscriptionResult
from app.services.translation_service import TranslationSegment
from app.services.video_source_service import VideoSourceResult
from app.services.yt_dlp_service import VideoMetadata


client = TestClient(app)


def _wait_for_job_result(job_id: str, timeout_seconds: float = 5.0) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    last_body: dict[str, object] | None = None

    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        last_body = body
        if body.get("status") == "done":
            return body
        if body.get("status") == "failed":
            raise AssertionError(str(body.get("error") or "job failed"))
        time.sleep(0.05)

    raise AssertionError(
        f"job {job_id} did not finish within {timeout_seconds} seconds: {last_body}"
    )


def _use_tmp_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.services.persistent_cache_service.CACHE_ROOT_DIR",
        tmp_path / "persistent_cache",
    )


def _build_fake_job_result(content_context_id: str) -> JobRunResult:
    return JobRunResult(
        video=VideoMetadata(
            video_id="abc123xyz",
            title="Test video",
            duration_sec=12,
            uploader="Uploader",
            thumbnail="https://example.com/thumb.jpg",
            subtitles=["en"],
            automatic_captions=[],
        ),
        source_type="captions",
        transcript_en=TranscriptionResult(
            language="en",
            text="Hello everyone.\nWelcome back.",
            segments=[
                TranscriptSegment(
                    index=0,
                    start=0.0,
                    end=0.0,
                    text="Hello everyone.",
                ),
                TranscriptSegment(
                    index=1,
                    start=0.0,
                    end=0.0,
                    text="Welcome back.",
                ),
            ],
        ),
        translation_zh_segments=[
            TranslationSegment(
                index=0,
                start=0.0,
                end=0.0,
                source_text="Hello everyone.",
                translated_text="大家好。",
            ),
            TranslationSegment(
                index=1,
                start=0.0,
                end=0.0,
                source_text="Welcome back.",
                translated_text="欢迎回来。",
            ),
        ],
        content_context_id=content_context_id,
    )


def test_jobs_run_persists_session_history(monkeypatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    content_context_id = create_content_context(
        video_title="Test video",
        transcript_en="Hello everyone.\nWelcome back.",
        translation_zh="大家好。\n欢迎回来。",
    )

    def fake_run_video_job_with_translation_config(*args, **kwargs) -> JobRunResult:
        assert args[0] == "https://www.youtube.com/watch?v=abc123xyz"
        assert kwargs["source_mode"] == "subtitle_first"
        return _build_fake_job_result(content_context_id)

    monkeypatch.setattr(
        "app.main.run_video_job_with_translation_config",
        fake_run_video_job_with_translation_config,
    )

    response = client.post(
        "/api/jobs/run",
        json={
            "url": "https://www.youtube.com/watch?v=abc123xyz",
            "source_mode": "subtitle_first",
            "translation_config": {
                "provider": "deepseek",
                "api_key": "test-key",
                "model": "deepseek-chat",
            },
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "queued"
    assert body["job_id"]

    finished_job = _wait_for_job_result(str(body["job_id"]))
    assert finished_job["status"] == "done"
    assert finished_job["result"]["content_context_id"] == content_context_id

    history_list = client.get("/api/session-history")
    assert history_list.status_code == 200
    list_body = history_list.json()
    assert list_body["ok"] is True
    assert len(list_body["items"]) == 1
    assert list_body["items"][0]["content_context_id"] == content_context_id
    assert list_body["items"][0]["chat_turn_count"] == 0

    history_detail = client.get(f"/api/session-history/{content_context_id}")
    assert history_detail.status_code == 200
    detail_body = history_detail.json()
    assert detail_body["video_id"] == "abc123xyz"
    assert detail_body["video_url"] == "https://www.youtube.com/watch?v=abc123xyz"
    assert detail_body["video_title"] == "Test video"
    assert detail_body["video_duration_sec"] == 12
    assert detail_body["video_uploader"] == "Uploader"
    assert detail_body["video_thumbnail"] == "https://example.com/thumb.jpg"
    assert detail_body["source_mode"] == "subtitle_first"
    assert detail_body["source_type"] == "captions"
    assert detail_body["transcript_en_text"] == "Hello everyone.\nWelcome back."
    assert detail_body["translation_zh_text"] == ""
    assert detail_body["chat_turns"] == []


def test_content_rewrite_updates_session_history(monkeypatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    content_context_id = create_content_context(
        video_title="Test video",
        transcript_en="Hello everyone.\nWelcome back.",
        translation_zh="大家好。\n欢迎回来。",
    )

    def fake_run_writer_agent(**kwargs):
        assert kwargs["source_text"] == "大家好。\n欢迎回来。"
        assert kwargs["rewrite_focus"] == "请改成更口语化。"
        return type(
            "RewriteResult",
            (),
            {
                "rewritten_text": "这是改写后的版本。",
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
        )()

    monkeypatch.setattr("app.main.run_writer_agent", fake_run_writer_agent)

    response = client.post(
        "/api/content-rewrite",
        json={
            "content_context_id": content_context_id,
            "source_text": "大家好。\n欢迎回来。",
            "rewrite_focus": "请改成更口语化。",
            "translation_config": {
                "provider": "deepseek",
                "api_key": "test-key",
                "model": "deepseek-chat",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["rewritten_text"] == "这是改写后的版本。"

    history_detail = client.get(f"/api/session-history/{content_context_id}")
    assert history_detail.status_code == 200
    detail_body = history_detail.json()
    assert detail_body["rewrite_focus"] == "请改成更口语化。"
    assert detail_body["rewrite_source_text"] == "大家好。\n欢迎回来。"
    assert detail_body["rewritten_text"] == "这是改写后的版本。"
    assert detail_body["rewrite_quality_issues"] == []
    assert detail_body["rewrite_provider"] == "deepseek"
    assert detail_body["rewrite_model"] == "deepseek-chat"


def test_session_history_endpoints_filter_by_account_id(monkeypatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    content_context_id = create_content_context(
        video_title="Test video",
        transcript_en="Hello everyone.\nWelcome back.",
        translation_zh="大家好。\n欢迎回来。",
        account_id="user:alice",
    )

    upsert_job_session(
        content_context_id=content_context_id,
        account_id="user:alice",
        video_id="abc123xyz",
        video_url="https://www.youtube.com/watch?v=abc123xyz",
        video_title="Test video",
        source_mode="subtitle_first",
        source_type="captions",
        translation_provider="deepseek",
        translation_model="deepseek-chat",
        transcript_en_text="Hello everyone.\nWelcome back.",
        transcript_en_segments=[],
        translation_zh_text="大家好。\n欢迎回来。",
        translation_zh_segments=[],
    )

    list_response = client.get("/api/session-history", headers={"x-user-id": "alice"})
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert len(list_body["items"]) == 1
    assert list_body["items"][0]["content_context_id"] == content_context_id

    empty_list_response = client.get("/api/session-history", headers={"x-user-id": "bob"})
    assert empty_list_response.status_code == 200
    assert empty_list_response.json()["items"] == []

    alice_detail = client.get(
        f"/api/session-history/{content_context_id}",
        headers={"x-user-id": "alice"},
    )
    assert alice_detail.status_code == 200

    bob_detail = client.get(
        f"/api/session-history/{content_context_id}",
        headers={"x-user-id": "bob"},
    )
    assert bob_detail.status_code == 404


def test_content_chat_appends_turns_to_session_history(monkeypatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    content_context_id = create_content_context(
        video_title="Test video",
        transcript_en="Hello everyone.\nWelcome back.",
        translation_zh="大家好。\n欢迎回来。",
    )

    def fake_answer_content_question(**kwargs):
        assert kwargs["content_context_id"] is None
        assert kwargs["video_title"] == "Test video"
        return type(
            "ChatResult",
            (),
            {
                "answer": "这是回答。",
                "provider": "ollama",
                "model": "qwen3.5:4b",
            },
        )()

    monkeypatch.setattr("app.main.answer_content_question", fake_answer_content_question)

    response = client.post(
        "/api/content-chat",
        json={
            "content_context_id": content_context_id,
            "question": "这条视频的核心观点是什么？",
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "这是回答。"

    history_detail = client.get(f"/api/session-history/{content_context_id}")
    assert history_detail.status_code == 200
    detail_body = history_detail.json()
    assert len(detail_body["chat_turns"]) == 2
    assert detail_body["chat_turns"][0]["role"] == "user"
    assert detail_body["chat_turns"][0]["content"] == "这条视频的核心观点是什么？"
    assert detail_body["chat_turns"][1]["role"] == "assistant"
    assert detail_body["chat_turns"][1]["content"] == "这是回答。"


def test_session_history_writes_merge_atomically(monkeypatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    content_context_id = create_content_context(
        video_title="Test video",
        transcript_en="Hello everyone.\nWelcome back.",
        translation_zh="大家好。\n欢迎回来。",
    )

    upsert_job_session(
        content_context_id=content_context_id,
        video_id="abc123xyz",
        video_url="https://www.youtube.com/watch?v=abc123xyz",
        video_title="Test video",
        source_mode="subtitle_first",
        source_type="captions",
        translation_provider="deepseek",
        translation_model="deepseek-chat",
        transcript_en_text="Hello everyone.\nWelcome back.",
        transcript_en_segments=[],
        translation_zh_text="大家好。\n欢迎回来。",
        translation_zh_segments=[],
    )

    original_load = persistent_cache_service.load_json_cache
    original_store = persistent_cache_service.store_json_cache
    first_store_entered = threading.Event()
    release_first_store = threading.Event()
    second_load_seen = threading.Event()

    def load_wrapper(namespace: str, key: str):
        if (
            threading.current_thread().name == "chat-thread"
            and first_store_entered.is_set()
            and not release_first_store.is_set()
        ):
            second_load_seen.set()
        return original_load(namespace, key)

    def store_wrapper(namespace: str, key: str, payload: object):
        if threading.current_thread().name == "rewrite-thread":
            first_store_entered.set()
            assert release_first_store.wait(timeout=5)
        return original_store(namespace, key, payload)

    monkeypatch.setattr(
        "app.services.persistent_cache_service.load_json_cache",
        load_wrapper,
    )
    monkeypatch.setattr(
        "app.services.persistent_cache_service.store_json_cache",
        store_wrapper,
    )

    rewrite_thread = threading.Thread(
        target=record_rewrite_result,
        name="rewrite-thread",
        kwargs={
            "content_context_id": content_context_id,
            "rewrite_style": "speech_verbatim",
            "rewrite_focus": "请改成更口语化。",
            "rewrite_source_text": "大家好。\n欢迎回来。",
            "rewritten_text": "这是改写后的版本。",
            "rewrite_provider": "deepseek",
            "rewrite_model": "deepseek-chat",
            "writer_trace_id": "writer-trace-merge-test",
            "writer_policy_version": "policy-merge-test",
            "writer_prompt_version": "prompt-merge-test",
        },
    )
    chat_thread = threading.Thread(
        target=append_chat_exchange,
        name="chat-thread",
        kwargs={
            "content_context_id": content_context_id,
            "question": "这条视频的核心观点是什么？",
            "answer": "这是回答。",
        },
    )

    rewrite_thread.start()
    assert first_store_entered.wait(timeout=5)

    chat_thread.start()
    time.sleep(0.2)
    assert not second_load_seen.is_set()

    release_first_store.set()
    rewrite_thread.join(timeout=5)
    chat_thread.join(timeout=5)

    assert not rewrite_thread.is_alive()
    assert not chat_thread.is_alive()

    detail = load_session_history(content_context_id)
    assert detail is not None
    assert detail["rewrite_style"] == "speech_verbatim"
    assert detail["rewritten_text"] == "这是改写后的版本。"
    assert detail["rewrite_focus"] == "请改成更口语化。"
    assert detail["writer_trace_id"] == "writer-trace-merge-test"
    assert detail["writer_policy_version"] == "policy-merge-test"
    assert detail["writer_prompt_version"] == "prompt-merge-test"
    assert len(detail["chat_turns"]) == 2
    assert detail["chat_turns"][0]["role"] == "user"
    assert detail["chat_turns"][1]["role"] == "assistant"


def test_session_history_rejects_unsafe_context_id(monkeypatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    upsert_job_session(
        content_context_id="../../etc/passwd",
        video_id="vid",
        video_url="https://www.youtube.com/watch?v=abc123xyz",
        video_title="unsafe",
        source_mode="subtitle_first",
        source_type="captions",
        translation_provider="deepseek",
        translation_model="deepseek-chat",
        transcript_en_text="text",
        transcript_en_segments=[],
        translation_zh_text="文本",
        translation_zh_segments=[],
    )
    history_dir = persistent_cache_service.CACHE_ROOT_DIR / "session_history"
    assert not history_dir.exists() or not any(history_dir.glob("*.json"))
