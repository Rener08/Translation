from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services.content_chat_service import (
    ContentChatConfigurationError,
    ContentChatResult,
    answer_content_question,
)
from app.services.content_context_service import ContentContext


client = TestClient(app)


def _assert_error_response(
    response,
    *,
    status_code: int,
    error_code: str,
    retryable: bool,
    detail: str,
) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail", "error_code", "retryable", "request_id"}
    assert body["detail"] == detail
    assert body["error_code"] == error_code
    assert body["retryable"] is retryable
    assert body["request_id"] == response.headers["x-request-id"]


def test_answer_content_question_uses_ollama_with_history_and_prompt(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(*args, **kwargs):
        captured["url"] = args[0]
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={
                "message": {
                    "content": "这段视频主要在介绍如何使用 Claude Code 配合 NotebookLM。"
                }
            },
        )

    monkeypatch.setattr("app.services.content_chat_service.httpx.post", fake_post)

    result = answer_content_question(
        video_title="Demo video",
        transcript_en="Hello everyone. Today we talk about Claude Code.",
        translation_zh="大家好。今天我们来讲 Claude Code。",
        question="这段视频主要讲什么？",
        messages=[
            {"role": "user", "content": "先简单说下背景。"},
            {"role": "assistant", "content": "这是一个 AI 工具教程。"},
        ],
        chat_config={
            "provider": "ollama",
            "model": "qwen3.5:4b",
            "custom_prompt": "回答尽量简洁，先给结论。",
        },
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert "Authorization" not in captured["headers"]
    assert captured["json"]["model"] == "qwen3.5:4b"
    assert captured["json"]["think"] is False
    assert "Custom prompt" in captured["json"]["messages"][0]["content"]
    assert "Demo video" in captured["json"]["messages"][1]["content"]
    assert captured["json"]["messages"][2]["content"] == "先简单说下背景。"
    assert captured["json"]["messages"][3]["content"] == "这是一个 AI 工具教程。"
    assert captured["json"]["messages"][-1]["content"] == "这段视频主要讲什么？"
    assert result == ContentChatResult(
        answer="这段视频主要在介绍如何使用 Claude Code 配合 NotebookLM。",
        provider="ollama",
        model="qwen3.5:4b",
    )


def test_content_chat_endpoint_returns_answer(monkeypatch) -> None:
    def fake_answer_content_question(**kwargs) -> ContentChatResult:
        assert kwargs["video_title"] == "Demo video"
        assert kwargs["content_context_id"] is None
        assert kwargs["question"] == "请总结这条视频。"
        assert kwargs["messages"] == [
            {"role": "user", "content": "先说重点。"},
            {"role": "assistant", "content": "这是上一轮回答。"},
        ]
        assert kwargs["chat_config"] == {
            "provider": "ollama",
            "api_key": None,
            "base_url": None,
            "model": "qwen3.5:4b",
            "custom_prompt": "回答时先给要点。",
            "extra_headers": {},
        }
        return ContentChatResult(
            answer="这条视频重点介绍了 Claude Code 和 NotebookLM 的用法。",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.main.answer_content_question", fake_answer_content_question)

    response = client.post(
        "/api/content-chat",
        json={
            "video_title": "Demo video",
            "transcript_en": "Hello everyone.",
            "translation_zh": "大家好。",
            "question": "请总结这条视频。",
            "messages": [
                {"role": "user", "content": "先说重点。"},
                {"role": "assistant", "content": "这是上一轮回答。"},
            ],
            "chat_config": {
                "provider": "ollama",
                "model": "qwen3.5:4b",
                "custom_prompt": "回答时先给要点。",
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "provider": "ollama",
        "model": "qwen3.5:4b",
        "answer": "这条视频重点介绍了 Claude Code 和 NotebookLM 的用法。",
    }


def test_answer_content_question_uses_cached_context_when_id_is_provided(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_load(content_context_id: str) -> ContentContext | None:
        assert content_context_id == "ctx_demo"
        return ContentContext(
            content_context_id="ctx_demo",
            video_title="Demo video",
            transcript_en="Hello everyone. Today we talk about Claude Code.",
            translation_zh="大家好。今天我们来讲 Claude Code。",
        )

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={"message": {"content": "这是来自缓存上下文的回答。"}},
        )

    monkeypatch.setattr("app.services.content_chat_service.load_content_context", fake_load)
    monkeypatch.setattr("app.services.content_chat_service.httpx.post", fake_post)

    result = answer_content_question(
        content_context_id="ctx_demo",
        video_title=None,
        transcript_en=None,
        translation_zh=None,
        question="这段视频主要讲什么？",
        messages=[],
        chat_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert "Demo video" in captured["json"]["messages"][1]["content"]
    assert result.answer == "这是来自缓存上下文的回答。"


def test_content_chat_endpoint_accepts_content_context_id(monkeypatch) -> None:
    def fake_load(content_context_id: str, *, account_id: str | None = None) -> ContentContext | None:
        assert content_context_id == "ctx_demo"
        assert account_id == "user:alice"
        return ContentContext(
            content_context_id="ctx_demo",
            account_id="user:alice",
            video_title="Demo video",
            transcript_en="Hello everyone. Today we talk about Claude Code.",
            translation_zh="大家好。今天我们来讲 Claude Code。",
        )

    def fake_answer_content_question(**kwargs) -> ContentChatResult:
        assert kwargs["content_context_id"] is None
        assert kwargs["video_title"] == "Demo video"
        assert kwargs["transcript_en"] == "Hello everyone. Today we talk about Claude Code."
        assert kwargs["translation_zh"] == "大家好。今天我们来讲 Claude Code。"
        assert kwargs["question"] == "请总结这条视频。"
        return ContentChatResult(
            answer="这是缓存上下文版本的总结。",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.api.routers.content.load_content_context", fake_load)
    monkeypatch.setattr("app.main.answer_content_question", fake_answer_content_question)

    response = client.post(
        "/api/content-chat",
        headers={"x-user-id": "alice"},
        json={
            "content_context_id": "ctx_demo",
            "question": "请总结这条视频。",
            "chat_config": {"provider": "ollama", "model": "qwen3.5:4b"},
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "这是缓存上下文版本的总结。"


def test_content_chat_endpoint_rejects_cross_account_context(monkeypatch) -> None:
    def fake_load(content_context_id: str, *, account_id: str | None = None) -> ContentContext | None:
        assert content_context_id == "ctx_demo"
        assert account_id == "user:bob"
        return None

    monkeypatch.setattr("app.api.routers.content.load_content_context", fake_load)
    monkeypatch.setattr(
        "app.main.answer_content_question",
        lambda **kwargs: ContentChatResult(
            answer="不该返回。",
            provider="ollama",
            model="qwen3.5:4b",
        ),
    )

    response = client.post(
        "/api/content-chat",
        headers={"x-user-id": "bob"},
        json={
            "content_context_id": "ctx_demo",
            "question": "请总结这条视频。",
            "chat_config": {"provider": "ollama", "model": "qwen3.5:4b"},
        },
    )

    _assert_error_response(
        response,
        status_code=404,
        error_code="NOT_FOUND",
        retryable=False,
        detail="Content context not found.",
    )


def test_content_chat_endpoint_rejects_empty_question() -> None:
    response = client.post(
        "/api/content-chat",
        json={
            "transcript_en": "Hello everyone.",
            "translation_zh": "大家好。",
            "question": "   ",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail", "error_code", "retryable", "request_id"}
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["retryable"] is False
    assert body["request_id"] == response.headers["x-request-id"]
    assert isinstance(body["detail"], str)
    assert body["detail"]


def test_answer_content_question_rejects_non_local_ollama_base_url() -> None:
    try:
        answer_content_question(
            video_title="Demo video",
            transcript_en="Hello everyone.",
            translation_zh="大家好。",
            question="请总结这条视频。",
            chat_config={
                "provider": "ollama",
                "base_url": "http://192.168.1.10:11434",
                "model": "qwen3.5:4b",
            },
        )
    except ContentChatConfigurationError as error:
        assert "must point to localhost" in str(error)
    else:
        raise AssertionError("Expected configuration error")
