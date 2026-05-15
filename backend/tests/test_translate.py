import json
import re
import threading
import time
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services.translation_service import (
    _build_translation_chunks,
    _translation_cache_key,
    clean_translated_chinese_text,
    _segment_to_chunk_item,
    _translation_output_token_budget,
    TranslationSegment,
    TranslationChunkItem,
    TranslationProviderConfig,
    TranslationConfigurationError,
    TranslationProviderError,
    translate_segments_to_chinese,
)


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


def _extract_prompt_indices(content: str) -> list[int]:
    return [
        int(value)
        for value in re.findall(r"^index:\s+(\d+)\s*$", content, re.MULTILINE)
    ]


def test_clean_translated_chinese_text_removes_stage_directions_fillers_and_ads() -> (
    None
):
    value = """
    [音乐]
    嗯。
    这个，今天我们来聊 AI。
    掌声
    欢迎订阅我们的频道
    然后，我们先看第一件事。
    """

    assert (
        clean_translated_chinese_text(value) == "今天我们来聊 AI。\n我们先看第一件事。"
    )


def test_clean_translated_chinese_text_deduplicates_repeated_lines() -> None:
    value = "大家好。\n大家好。\n[掌声]\n这是正文。\n这是正文。"

    assert clean_translated_chinese_text(value) == "大家好。\n这是正文。"


def test_clean_translated_chinese_text_collapses_repeated_filler_tokens() -> None:
    value = "那个，那个网红景点肯定，肯定挤爆了，就，就光排队了。我，我其实还没想好。"

    assert (
        clean_translated_chinese_text(value)
        == "那个网红景点肯定，肯定挤爆了，就光排队了。我其实还没想好。"
    )


def test_clean_translated_chinese_text_removes_inline_pause_tokens() -> None:
    value = "甲：呃……我们今天开始。乙：啊？那就继续。嗯……其实已经很清楚了。"

    assert (
        clean_translated_chinese_text(value)
        == "甲：我们今天开始。乙：那就继续。其实已经很清楚了。"
    )


def test_clean_translated_chinese_text_removes_common_stage_direction_variants() -> None:
    value = "[音乐]\n【掌声】\n(laughter)\n正文。"

    assert clean_translated_chinese_text(value) == "正文。"


def test_translation_cache_key_ignores_extra_header_order() -> None:
    segments = [
        {"index": 0, "start": 0.0, "end": 1.2, "text": "Hello there."},
    ]
    config_a = TranslationProviderConfig(
        provider="deepseek",
        api_key="demo-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        extra_headers={"X-Trace-Id": "1", "X-Session-Id": "2"},
    )
    config_b = TranslationProviderConfig(
        provider="deepseek",
        api_key="demo-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        extra_headers={"X-Session-Id": "2", "X-Trace-Id": "1"},
    )

    assert _translation_cache_key(segments, config_a) == _translation_cache_key(
        segments,
        config_b,
    )


def test_translation_output_token_budget_scales_and_clamps() -> None:
    small_chunk = [
        TranslationChunkItem(index=0, start=0.0, end=1.0, source_text="one two three"),
        TranslationChunkItem(index=1, start=1.0, end=2.0, source_text="four five"),
    ]
    huge_chunk = [
        TranslationChunkItem(index=i, start=float(i), end=float(i + 1), source_text="word " * 200)
        for i in range(20)
    ]

    assert _translation_output_token_budget(small_chunk) == 500
    assert _translation_output_token_budget(huge_chunk) == 1800


def test_translate_segments_to_chinese_translates_each_segment(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TRANSLATION_PROVIDER", "openai")
    calls: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        payload = kwargs["json"]
        input_items = payload.get("input") if isinstance(payload, dict) else None
        content = ""
        if isinstance(input_items, list) and input_items:
            first_item = input_items[0]
            if isinstance(first_item, dict):
                content = str(first_item.get("content") or "")

        translations = []
        if "index: 0" in content:
            translations.append(
                {"index": 0, "translated_text": "\u5927\u5bb6\u597d\u3002"}
            )
        if "index: 1" in content:
            translations.append(
                {"index": 1, "translated_text": "\u6b22\u8fce\u56de\u6765\u3002"}
            )

        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            json={"output_text": json.dumps({"translations": translations})},
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    result = translate_segments_to_chinese(
        [
            {
                "index": 0,
                "start": 0.0,
                "end": 1.5,
                "text": "Hello everyone.",
            },
            {
                "index": 1,
                "start": 1.5,
                "end": 3.0,
                "text": "Welcome back.",
            },
        ],
        translation_config={"provider": "openai"},
    )

    assert len(calls) == 1
    assert result == [
        TranslationSegment(
            index=0,
            start=0.0,
            end=1.5,
            source_text="Hello everyone.",
            translated_text="\u5927\u5bb6\u597d\u3002",
        ),
        TranslationSegment(
            index=1,
            start=1.5,
            end=3.0,
            source_text="Welcome back.",
            translated_text="\u6b22\u8fce\u56de\u6765\u3002",
        ),
    ]


def test_translate_segments_to_chinese_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("TRANSLATION_PROVIDER", "openai")

    try:
        translate_segments_to_chinese(
            [{"index": 0, "start": 0.0, "end": 1.0, "text": "Hello"}],
            translation_config={"provider": "openai"},
        )
    except TranslationConfigurationError as error:
        assert "OPENAI_API_KEY is not set" in str(error)
    else:
        raise AssertionError("Expected TranslationConfigurationError")


def test_translate_segments_to_chinese_rejects_non_local_ollama_base_url() -> None:
    try:
        translate_segments_to_chinese(
            [{"index": 0, "start": 0.0, "end": 1.0, "text": "Hello"}],
            translation_config={
                "provider": "ollama",
                "base_url": "http://192.168.1.10:11434",
                "model": "qwen3.5:4b",
            },
        )
    except TranslationConfigurationError as error:
        assert "must point to localhost" in str(error)
    else:
        raise AssertionError("Expected TranslationConfigurationError")


def test_translate_segments_to_chinese_surfaces_openai_errors(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TRANSLATION_PROVIDER", "openai")

    def fake_post(*args, **kwargs):
        return httpx.Response(
            400,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            json={"error": {"message": "Structured output validation failed."}},
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    try:
        translate_segments_to_chinese(
            [{"index": 0, "start": 0.0, "end": 1.0, "text": "Hello"}],
            translation_config={"provider": "openai"},
        )
    except TranslationProviderError as error:
        assert str(error) == "Structured output validation failed."
    else:
        raise AssertionError("Expected TranslationProviderError")


def test_translate_segments_to_chinese_supports_deepseek(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    calls: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        calls.append(
            {
                "url": args[0],
                "headers": kwargs["headers"],
                "json": kwargs["json"],
            }
        )
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "translations": [
                                        {
                                            "index": 0,
                                            "translated_text": "\u5927\u5bb6\u597d\u3002",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    result = translate_segments_to_chinese(
        [{"index": 0, "start": 0.0, "end": 1.0, "text": "Hello everyone."}],
        translation_config={"provider": "deepseek"},
    )

    assert calls[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer deepseek-test-key"
    assert calls[0]["json"]["model"] == "deepseek-chat"
    assert result[0].translated_text == "\u5927\u5bb6\u597d\u3002"


def test_translate_segments_to_chinese_uses_persistent_cache(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "translations": [
                                        {
                                            "index": 0,
                                            "translated_text": "\u5927\u5bb6\u597d\u3002",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    segments = [{"index": 0, "start": 0.0, "end": 1.0, "text": "Hello everyone."}]
    first = translate_segments_to_chinese(
        segments,
        translation_config={"provider": "deepseek"},
    )
    second = translate_segments_to_chinese(
        segments,
        translation_config={"provider": "deepseek"},
    )

    assert calls == 1
    assert first[0].translated_text == second[0].translated_text


def test_translate_segments_to_chinese_retries_empty_deepseek_translation(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    calls: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        payload = dict(kwargs["json"])
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(
                200,
                request=httpx.Request(
                    "POST", "https://api.deepseek.com/chat/completions"
                ),
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "translations": [
                                            {"index": 8, "translated_text": ""}
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                },
            )

        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "translations": [
                                        {
                                            "index": 8,
                                            "translated_text": "\u5927\u5bb6\u597d\u3002",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    result = translate_segments_to_chinese(
        [{"index": 8, "start": 0.0, "end": 1.0, "text": "Hello everyone."}],
        translation_config={"provider": "deepseek"},
    )

    assert len(calls) == 2
    assert (
        "Previous attempt returned unusable output"
        in calls[1]["messages"][1]["content"]
    )
    assert result[0].translated_text == "\u5927\u5bb6\u597d\u3002"


def test_translate_segments_to_chinese_retries_only_missing_indices(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    prompts: list[str] = []

    def fake_post(*args, **kwargs):
        payload = kwargs["json"]
        messages = payload.get("messages") if isinstance(payload, dict) else None
        content = ""
        if isinstance(messages, list) and len(messages) > 1:
            user_message = messages[1]
            if isinstance(user_message, dict):
                content = str(user_message.get("content") or "")
        prompts.append(content)

        indices = _extract_prompt_indices(content)
        if len(prompts) == 1:
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "translations": [
                                        {
                                            "index": 0,
                                            "translated_text": "\u7ffb\u8bd1 0",
                                        },
                                        {
                                            "index": 2,
                                            "translated_text": "\u7ffb\u8bd1 2",
                                        },
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
        else:
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "translations": [
                                        {
                                            "index": indices[0],
                                            "translated_text": f"\u7ffb\u8bd1 {indices[0]}",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
            json=body,
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    result = translate_segments_to_chinese(
        [
            {"index": 0, "start": 0.0, "end": 1.0, "text": "Hello everyone."},
            {"index": 1, "start": 1.0, "end": 2.0, "text": "Welcome back."},
            {"index": 2, "start": 2.0, "end": 3.0, "text": "Let's begin."},
        ],
        translation_config={"provider": "deepseek", "chunk_concurrency": 1},
    )

    assert len(prompts) == 2
    assert _extract_prompt_indices(prompts[0]) == [0, 1, 2]
    assert _extract_prompt_indices(prompts[1]) == [1]
    assert "context_index: 0" in prompts[1]
    assert [item.translated_text for item in result] == [
        "\u7ffb\u8bd1 0",
        "\u7ffb\u8bd1 1",
        "\u7ffb\u8bd1 2",
    ]


def test_translate_segments_to_chinese_supports_lmstudio_model_discovery(
    monkeypatch,
) -> None:
    captured_get: dict[str, Any] = {}
    captured_post: dict[str, Any] = {}

    def fake_get(*args, **kwargs):
        captured_get["url"] = args[0]
        captured_get["headers"] = kwargs["headers"]
        return httpx.Response(
            200,
            request=httpx.Request("GET", "http://127.0.0.1:1234/v1/models"),
            json={
                "data": [
                    {
                        "id": "qwen3.5-4b",
                        "object": "model",
                    }
                ]
            },
        )

    def fake_post(*args, **kwargs):
        captured_post["url"] = args[0]
        captured_post["headers"] = kwargs["headers"]
        captured_post["json"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<think>internal reasoning</think>\n"
                                '{"translations":[{"index":0,"translated_text":"\u5927\u5bb6\u597d\u3002"}]}'
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("app.services.translation_service.httpx.get", fake_get)
    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    result = translate_segments_to_chinese(
        [{"index": 0, "start": 0.0, "end": 1.0, "text": "Hello everyone."}],
        translation_config={"provider": "lmstudio"},
    )

    assert captured_get["url"] == "http://127.0.0.1:1234/v1/models"
    assert "Authorization" not in captured_post["headers"]
    assert captured_post["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert captured_post["json"]["model"] == "qwen3.5-4b"
    assert result[0].translated_text == "\u5927\u5bb6\u597d\u3002"


def test_translate_segments_to_chinese_supports_ollama_plain_text_response(
    monkeypatch,
) -> None:
    captured_post: dict[str, Any] = {}

    def fake_post(*args, **kwargs):
        captured_post["url"] = args[0]
        captured_post["headers"] = kwargs["headers"]
        captured_post["json"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={
                "message": {
                    "content": '{"translations":[{"index":0,"translated_text":"\u5927\u5bb6\u597d\u3002"}]}',
                }
            },
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    result = translate_segments_to_chinese(
        [{"index": 0, "start": 0.0, "end": 1.0, "text": "Hello everyone."}],
        translation_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert captured_post["url"] == "http://127.0.0.1:11434/api/chat"
    assert "Authorization" not in captured_post["headers"]
    assert captured_post["json"]["model"] == "qwen3.5:4b"
    assert captured_post["json"]["think"] is False
    assert result[0].translated_text == "\u5927\u5bb6\u597d\u3002"


def test_translate_segments_to_chinese_translates_chunks_with_bounded_concurrency(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TRANSLATION_PROVIDER", "openai")
    monkeypatch.setenv("TRANSLATION_CHUNK_CONCURRENCY", "2")
    active_requests = 0
    max_inflight = 0
    state_lock = threading.Lock()

    def fake_post(*args, **kwargs):
        nonlocal active_requests, max_inflight
        payload = kwargs["json"]
        input_items = payload.get("input") if isinstance(payload, dict) else None
        content = ""
        if isinstance(input_items, list) and input_items:
            first_item = input_items[0]
            if isinstance(first_item, dict):
                content = str(first_item.get("content") or "")

        translations = [
            {"index": index, "translated_text": f"\u7ffb\u8bd1 {index}"}
            for index in _extract_prompt_indices(content)
        ]

        with state_lock:
            active_requests += 1
            max_inflight = max(max_inflight, active_requests)

        time.sleep(0.05)

        with state_lock:
            active_requests -= 1

        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            json={"output_text": json.dumps({"translations": translations})},
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    segments = [
        {
            "index": index,
            "start": float(index),
            "end": float(index) + 0.5,
            "text": f"Segment {index} one two three four five.",
        }
        for index in range(90)
    ]

    result = translate_segments_to_chinese(
        segments,
        translation_config={"provider": "openai"},
    )

    assert max_inflight >= 2
    assert [item.index for item in result] == list(range(90))
    assert result[89].translated_text == "\u7ffb\u8bd1 89"


def test_translate_segments_to_chinese_falls_back_to_serial_after_parallel_failure(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TRANSLATION_PROVIDER", "openai")
    monkeypatch.setenv("TRANSLATION_CHUNK_CONCURRENCY", "2")
    active_requests = 0
    state_lock = threading.Lock()
    attempts_by_chunk: dict[int, int] = {}

    def fake_post(*args, **kwargs):
        nonlocal active_requests
        payload = kwargs["json"]
        input_items = payload.get("input") if isinstance(payload, dict) else None
        content = ""
        if isinstance(input_items, list) and input_items:
            first_item = input_items[0]
            if isinstance(first_item, dict):
                content = str(first_item.get("content") or "")

        indices = _extract_prompt_indices(content)
        chunk_start = indices[0]
        with state_lock:
            active_requests += 1
            attempts_by_chunk[chunk_start] = attempts_by_chunk.get(chunk_start, 0) + 1
            concurrent_request = active_requests > 1

        time.sleep(0.03)

        with state_lock:
            active_requests -= 1

        if concurrent_request and attempts_by_chunk[chunk_start] == 1:
            translations = [{"index": chunk_start, "translated_text": ""}]
        else:
            translations = [
                {"index": index, "translated_text": f"\u7ffb\u8bd1 {index}"}
                for index in indices
            ]

        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            json={"output_text": json.dumps({"translations": translations})},
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    segments = [
        {
            "index": index,
            "start": float(index),
            "end": float(index) + 0.5,
            "text": f"Segment {index} one two three four five.",
        }
        for index in range(76)
    ]

    result = translate_segments_to_chinese(
        segments,
        translation_config={"provider": "openai"},
    )

    assert [item.index for item in result] == list(range(76))
    assert max(attempts_by_chunk.values()) >= 2


def test_translate_segments_to_chinese_handles_parallel_content_errors_locally(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TRANSLATION_PROVIDER", "openai")
    monkeypatch.setenv("TRANSLATION_CHUNK_CONCURRENCY", "2")
    attempts_by_indices: dict[tuple[int, ...], int] = {}

    def fake_post(*args, **kwargs):
        payload = kwargs["json"]
        input_items = payload.get("input") if isinstance(payload, dict) else None
        content = ""
        if isinstance(input_items, list) and input_items:
            first_item = input_items[0]
            if isinstance(first_item, dict):
                content = str(first_item.get("content") or "")

        indices = tuple(_extract_prompt_indices(content))
        attempts_by_indices[indices] = attempts_by_indices.get(indices, 0) + 1

        if indices and indices[0] == 0 and len(indices) > 1 and attempts_by_indices[indices] == 1:
            translations = [{"index": indices[0], "translated_text": f"\u7ffb\u8bd1 {indices[0]}"}]
        else:
            translations = [
                {"index": index, "translated_text": f"\u7ffb\u8bd1 {index}"}
                for index in indices
            ]

        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            json={"output_text": json.dumps({"translations": translations})},
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    segments = [
        {
            "index": index,
            "start": float(index),
            "end": float(index) + 0.5,
            "text": f"Segment {index} one two three four five.",
        }
        for index in range(76)
    ]

    result = translate_segments_to_chinese(
        segments,
        translation_config={"provider": "openai"},
    )

    assert [item.index for item in result] == list(range(76))
    assert any(
        indices and max(indices) < 40 and 0 not in indices
        for indices in attempts_by_indices
    )


def test_translate_segments_to_chinese_reduces_concurrency_after_backpressure(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TRANSLATION_PROVIDER", "openai")
    monkeypatch.setenv("TRANSLATION_CHUNK_CONCURRENCY", "4")
    monkeypatch.setattr("app.services.translation_service.time.sleep", lambda *_: None)
    active_requests = 0
    state_lock = threading.Lock()
    max_inflight = 0
    overlap_event = threading.Event()

    def fake_post(*args, **kwargs):
        nonlocal active_requests, max_inflight
        payload = kwargs["json"]
        input_items = payload.get("input") if isinstance(payload, dict) else None
        content = ""
        if isinstance(input_items, list) and input_items:
            first_item = input_items[0]
            if isinstance(first_item, dict):
                content = str(first_item.get("content") or "")

        indices = _extract_prompt_indices(content)

        with state_lock:
            active_requests += 1
            max_inflight = max(max_inflight, active_requests)
            concurrent_request = active_requests > 1
            if concurrent_request:
                overlap_event.set()

        if not concurrent_request:
            overlap_event.wait(0.05)

        with state_lock:
            active_requests -= 1

        if concurrent_request:
            return httpx.Response(
                429,
                request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
                json={"error": {"message": "Rate limit exceeded."}},
            )

        translations = [
            {"index": index, "translated_text": f"\u7ffb\u8bd1 {index}"}
            for index in indices
        ]
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            json={"output_text": json.dumps({"translations": translations})},
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    segments = [
        {
            "index": index,
            "start": float(index),
            "end": float(index) + 0.5,
            "text": f"Segment {index} one two three four five.",
        }
        for index in range(90)
    ]

    result = translate_segments_to_chinese(
        segments,
        translation_config={"provider": "openai"},
    )

    assert max_inflight >= 2
    assert [item.index for item in result] == list(range(90))
    assert result[0].translated_text == "\u7ffb\u8bd1 0"


def test_translate_segments_to_chinese_stops_after_bounded_backpressure_retries(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TRANSLATION_PROVIDER", "openai")
    monkeypatch.setenv("TRANSLATION_CHUNK_CONCURRENCY", "4")
    monkeypatch.setattr("app.services.translation_service.time.sleep", lambda *_: None)
    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            json={"error": {"message": "Rate limit exceeded."}},
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    segments = [
        {
            "index": index,
            "start": float(index),
            "end": float(index) + 0.5,
            "text": f"Segment {index} one two three four five.",
        }
        for index in range(76)
    ]

    try:
        translate_segments_to_chinese(
            segments,
            translation_config={"provider": "openai"},
        )
    except TranslationProviderError as error:
        assert "Rate limit exceeded" in str(error)
    else:
        raise AssertionError("Expected TranslationProviderError")

    assert call_count < 100
    assert call_count >= 3


def test_build_translation_chunks_prefers_word_budget_over_old_eight_segment_limit() -> (
    None
):
    items = [
        _segment_to_chunk_item(
            {
                "index": index,
                "start": float(index),
                "end": float(index) + 0.5,
                "text": "one two three.",
            }
        )
        for index in range(12)
    ]

    chunks = _build_translation_chunks(items)

    assert len(chunks) == 1
    assert len(chunks[0]) == 12


def test_translate_segments_to_chinese_splits_failed_chunk_and_recovers(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("TRANSLATION_PROVIDER", "deepseek")
    monkeypatch.setenv("TRANSLATION_CHUNK_CONCURRENCY", "1")

    def fake_post(*args, **kwargs):
        payload = kwargs["json"]
        messages = payload.get("messages") if isinstance(payload, dict) else None
        content = ""
        if isinstance(messages, list) and len(messages) > 1:
            user_message = messages[1]
            if isinstance(user_message, dict):
                content = str(user_message.get("content") or "")

        indices = _extract_prompt_indices(content)
        if len(indices) > 1:
            body = {"choices": [{"message": {"content": "not valid json"}}]}
        else:
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "translations": [
                                        {
                                            "index": indices[0],
                                            "translated_text": f"\u7ffb\u8bd1 {indices[0]}",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
            json=body,
        )

    monkeypatch.setattr("app.services.translation_service.httpx.post", fake_post)

    segments = [
        {
            "index": index,
            "start": float(index),
            "end": float(index) + 0.5,
            "text": f"Segment {index} one two three four five.",
        }
        for index in range(3)
    ]

    result = translate_segments_to_chinese(
        segments,
        translation_config={"provider": "deepseek"},
    )

    assert [item.index for item in result] == [0, 1, 2]
    assert result[2].translated_text == "\u7ffb\u8bd1 2"


def test_translate_endpoint_returns_aligned_translations(monkeypatch) -> None:
    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        assert segments == [
            {
                "index": 0,
                "start": 0.0,
                "end": 5.2,
                "text": "Hello everyone...",
            }
        ]
        assert translation_config is None
        return [
            TranslationSegment(
                index=0,
                start=0.0,
                end=5.2,
                source_text="Hello everyone...",
                translated_text="\u5927\u5bb6\u597d\u2026\u2026",
            )
        ]

    monkeypatch.setattr("app.main.translate_segments_to_chinese", fake_translate)

    response = client.post(
        "/api/translate",
        json={
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 5.2,
                    "text": "Hello everyone...",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "translations": [
            {
                "index": 0,
                "start": 0.0,
                "end": 5.2,
                "source_text": "Hello everyone...",
                "translated_text": "\u5927\u5bb6\u597d\u2026\u2026",
            }
        ],
    }


def test_translate_endpoint_accepts_lmstudio_provider(monkeypatch) -> None:
    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        assert translation_config == {
            "provider": "lmstudio",
            "api_key": None,
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "qwen3.5-4b",
            "extra_headers": {},
        }
        return [
            TranslationSegment(
                index=0,
                start=0.0,
                end=5.2,
                source_text="Hello everyone...",
                translated_text="\u5927\u5bb6\u597d\u2026\u2026",
            )
        ]

    monkeypatch.setattr("app.main.translate_segments_to_chinese", fake_translate)

    response = client.post(
        "/api/translate",
        json={
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 5.2,
                    "text": "Hello everyone...",
                }
            ],
            "translation_config": {
                "provider": "lmstudio",
                "base_url": "http://127.0.0.1:1234/v1",
                "model": "qwen3.5-4b",
            },
        },
    )

    assert response.status_code == 200


def test_translate_endpoint_returns_configuration_error(monkeypatch) -> None:
    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        raise TranslationConfigurationError(
            "OPENAI_API_KEY is not set. Add it to your environment or .env file."
        )

    monkeypatch.setattr("app.main.translate_segments_to_chinese", fake_translate)

    response = client.post(
        "/api/translate",
        json={
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 5.2,
                    "text": "Hello everyone...",
                }
            ]
        },
    )

    _assert_error_response(
        response,
        status_code=500,
        error_code="CONFIGURATION_ERROR",
        retryable=False,
        detail="OPENAI_API_KEY is not set. Add it to your environment or .env file.",
    )


def test_translate_endpoint_returns_openai_error(monkeypatch) -> None:
    def fake_translate(
        segments: list[dict[str, object]],
        translation_config: dict[str, object] | None = None,
    ) -> list[TranslationSegment]:
        raise TranslationProviderError("Upstream translation failed.")

    monkeypatch.setattr("app.main.translate_segments_to_chinese", fake_translate)

    response = client.post(
        "/api/translate",
        json={
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 5.2,
                    "text": "Hello everyone...",
                }
            ]
        },
    )

    _assert_error_response(
        response,
        status_code=502,
        error_code="UPSTREAM_ERROR",
        retryable=True,
        detail="Upstream translation failed.",
    )


def test_translate_endpoint_forwards_translation_config(monkeypatch) -> None:
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
                end=5.2,
                source_text="Hello everyone...",
                translated_text="\u5927\u5bb6\u597d\u2026\u2026",
            )
        ]

    monkeypatch.setattr("app.main.translate_segments_to_chinese", fake_translate)

    response = client.post(
        "/api/translate",
        json={
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 5.2,
                    "text": "Hello everyone...",
                }
            ],
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


def test_translate_endpoint_rejects_empty_segment_text() -> None:
    response = client.post(
        "/api/translate",
        json={
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 5.2,
                    "text": "   ",
                }
            ]
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


def test_translate_endpoint_rejects_empty_segment_list() -> None:
    response = client.post("/api/translate", json={"segments": []})

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail", "error_code", "retryable", "request_id"}
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["retryable"] is False
    assert body["request_id"] == response.headers["x-request-id"]
    assert isinstance(body["detail"], str)
    assert body["detail"]
