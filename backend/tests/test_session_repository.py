from __future__ import annotations

from pathlib import Path

from app.repositories.session_repository import SessionRepository
from app.services import persistent_cache_service


def _use_tmp_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.services.persistent_cache_service.CACHE_ROOT_DIR",
        tmp_path / "persistent_cache",
    )


def test_session_repository_persists_and_lists_history(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)

    repo = SessionRepository()
    content_context_id = "ctx_12345"
    repo.upsert_job_session(
        content_context_id=content_context_id,
        video_id="abc123xyz",
        video_url="https://www.youtube.com/watch?v=abc123xyz",
        video_title="Test video",
        source_mode="subtitle_first",
        source_type="captions",
        translation_provider="deepseek",
        translation_model="deepseek-chat",
        translation_base_url="https://api.deepseek.com",
        transcript_en_text="Hello everyone.\nWelcome back.",
        transcript_en_segments=[],
        translation_zh_text="大家好。\n欢迎回来。",
        translation_zh_segments=[],
    )
    repo.record_rewrite_result(
        content_context_id=content_context_id,
        rewrite_style="speech_verbatim",
        rewrite_focus="请改成更口语化。",
        rewrite_source_text="大家好。\n欢迎回来。",
        rewritten_text="这是改写后的版本。",
        rewrite_provider="deepseek",
        rewrite_model="deepseek-chat",
        translation_base_url="https://api.deepseek.com",
        skill_config_name="kazix",
    )
    repo.append_chat_exchange(
        content_context_id=content_context_id,
        question="这条视频的核心观点是什么？",
        answer="这是回答。",
    )

    detail = repo.load_session_history(content_context_id)
    assert detail is not None
    assert detail["video_id"] == "abc123xyz"
    assert detail["translation_base_url"] == "https://api.deepseek.com"
    assert detail["rewrite_style"] == "speech_verbatim"
    assert detail["skill_config_name"] == "kazix"
    assert detail["rewrite_base_url"] == "https://api.deepseek.com"
    assert detail["rewritten_text"] == "这是改写后的版本。"
    assert len(detail["chat_turns"]) == 2

    summaries = repo.list_session_history()
    assert len(summaries) == 1
    assert summaries[0]["content_context_id"] == content_context_id
    assert summaries[0]["has_rewrite"] is True
    assert summaries[0]["chat_turn_count"] == 2


def test_session_repository_rejects_unsafe_context_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)

    repo = SessionRepository()
    repo.upsert_job_session(
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


def test_session_repository_records_rewrite_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)

    repo = SessionRepository()
    content_context_id = "ctx_failure"
    repo.upsert_job_session(
        content_context_id=content_context_id,
        video_id="abc123xyz",
        video_url="https://www.youtube.com/watch?v=abc123xyz",
        video_title="Test video",
        source_mode="subtitle_first",
        source_type="captions",
        translation_provider="deepseek",
        translation_model="deepseek-chat",
        translation_base_url="https://api.deepseek.com",
        transcript_en_text="Hello everyone.\nWelcome back.",
        transcript_en_segments=[],
        translation_zh_text="大家好。\n欢迎回来。",
        translation_zh_segments=[],
    )
    repo.record_rewrite_failure(
        content_context_id=content_context_id,
        rewrite_style="speech_verbatim",
        rewrite_focus="请改成更口语化。",
        rewrite_source_text="大家好。\n欢迎回来。",
        rewrite_provider="deepseek",
        rewrite_model="deepseek-chat",
        translation_base_url="https://api.deepseek.com",
        skill_config_name="kazix",
        rewrite_failure_error_code="UPSTREAM_ERROR",
        rewrite_failure_message="内容改写失败：上游模型服务返回错误。",
        rewrite_failure_retryable=True,
        rewrite_failure_details=[
            "写作风格：speech_verbatim",
            "技能配置：kazix",
        ],
    )

    detail = repo.load_session_history(content_context_id)
    assert detail is not None
    assert detail["translation_base_url"] == "https://api.deepseek.com"
    assert detail["rewrite_base_url"] == "https://api.deepseek.com"
    assert detail["skill_config_name"] == "kazix"
    assert detail["rewrite_failure_error_code"] == "UPSTREAM_ERROR"
    assert detail["rewrite_failure_message"] == "内容改写失败：上游模型服务返回错误。"
    assert detail["rewrite_failure_retryable"] is True
    assert detail["rewrite_failure_details"] == [
        "写作风格：speech_verbatim",
        "技能配置：kazix",
    ]
