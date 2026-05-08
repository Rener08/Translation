from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services.content_rewrite_service import (
    ContentRewriteEmptyOutputError,
    ContentRewriteProviderError,
    ContentRewriteResult,
    RewriteReferences,
    _select_rewrite_template,
    rewrite_content,
)
from app.services.prompt_validation import validate_rewrite_prompt


client = TestClient(app)


def test_rewrite_content_uses_ollama_and_reference_materials(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.services.content_rewrite_service.load_rewrite_references",
        lambda: RewriteReferences(
            article_template="文章模板片段",
            content_methodology="内容方法论片段",
            style_examples="风格示例片段",
            skill_guide="写作规则片段",
            quality_pipeline="质量流程片段",
            category_templates={
                "01_big_company_war": "场景模板片段",
            },
            section_title_rules="标题规则片段",
        ),
    )

    def fake_post(*args, **kwargs):
        captured["url"] = args[0]
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={"message": {"content": "这是改写后的内容。"}},
        )

    monkeypatch.setattr("app.services.content_rewrite_service.httpx.post", fake_post)

    result = rewrite_content(
        source_text="原始内容第一句。原始内容第二句。",
        rewrite_focus="改成更有节奏感。",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert "Authorization" not in captured["headers"]
    assert captured["json"]["model"] == "qwen3.5:4b"
    assert captured["json"]["messages"][0]["role"] == "system"
    assert "中文内容改写助手" in captured["json"]["messages"][0]["content"]
    assert captured["json"]["messages"][1]["role"] == "system"
    assert "【场景模板】" in captured["json"]["messages"][1]["content"]
    assert "场景模板片段" in captured["json"]["messages"][1]["content"]
    assert "【通用一页模板】" in captured["json"]["messages"][1]["content"]
    assert "文章模板片段" in captured["json"]["messages"][1]["content"]
    assert "内容方法论片段" in captured["json"]["messages"][1]["content"]
    assert "风格示例片段" in captured["json"]["messages"][1]["content"]
    assert "写作规则片段" in captured["json"]["messages"][1]["content"]
    assert "标题规则片段" in captured["json"]["messages"][1]["content"]
    assert "质量流程片段" in captured["json"]["messages"][1]["content"]
    assert captured["json"]["messages"][2]["role"] == "user"
    assert "改写目标：改成更有节奏感。" in captured["json"]["messages"][2]["content"]
    assert "原始内容第一句。原始内容第二句。" in captured["json"]["messages"][2]["content"]
    assert result == ContentRewriteResult(
        rewritten_text="这是改写后的内容。",
        provider="ollama",
        model="qwen3.5:4b",
    )


def test_rewrite_content_injects_transcript_into_full_skill_prompt(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={"message": {"content": "这是技能改写后的内容。"}},
        )

    monkeypatch.setattr("app.services.content_rewrite_service.httpx.post", fake_post)

    result = rewrite_content(
        source_text="这是原始转录内容。",
        rewrite_focus="标题：测试技能\n正文：{{transcript}}\n结尾：保持克制。",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert captured["json"]["messages"][0]["content"] == "你是一个智能写作助手。请严格遵守用户的格式要求。"
    assert captured["json"]["messages"][1]["content"] == "标题：测试技能\n正文：这是原始转录内容。\n结尾：保持克制。"
    assert result == ContentRewriteResult(
        rewritten_text="这是技能改写后的内容。",
        provider="ollama",
        model="qwen3.5:4b",
    )


def test_content_rewrite_endpoint_returns_rewritten_text(monkeypatch) -> None:
    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        assert kwargs["source_text"] == "这里是需要改写的原文。"
        assert kwargs["rewrite_focus"] == "请改成更口语化。"
        assert kwargs["rewrite_config"] == {
            "provider": "deepseek",
            "api_key": None,
            "base_url": None,
            "model": "deepseek-chat",
            "extra_headers": {},
        }
        return ContentRewriteResult(
            rewritten_text="这是改写后的版本。",
            provider="deepseek",
            model="deepseek-chat",
        )

    monkeypatch.setattr("app.main.rewrite_content", fake_rewrite_content)

    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "请改成更口语化。",
            "translation_config": {
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "provider": "deepseek",
        "model": "deepseek-chat",
        "rewritten_text": "这是改写后的版本。",
        "quality_issues": [],
    }


def test_content_rewrite_endpoint_rejects_empty_source_text() -> None:
    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "   ",
            "rewrite_focus": "请改写。",
        },
    )

    assert response.status_code == 422


def test_content_rewrite_endpoint_rejects_blank_rewrite_focus() -> None:
    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "   ",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "改写提示为空。请重新选择写作风格，或移除空白 rewrite_focus 后重试。"
    }


def test_content_rewrite_endpoint_rejects_invalid_placeholder_usage() -> None:
    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "标题：测试\n正文：{{ transcript }}",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "改写模板包含不支持的占位符：{{ transcript }}。当前仅支持 {{transcript}}。"
    }


def test_content_rewrite_endpoint_rejects_full_prompt_without_transcript_placeholder() -> None:
    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "请根据以下视频内容写一篇公众号文章。\n\n视频内容：",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "该写作风格看起来是完整 Prompt，但缺少 {{transcript}}。请补上占位符，或删掉完整 prompt 结构后作为风格提示使用。"
    }


def test_content_rewrite_endpoint_surfaces_provider_failure(monkeypatch) -> None:
    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        raise ContentRewriteProviderError("deepseek rewrite request failed: timed out")

    monkeypatch.setattr("app.main.rewrite_content", fake_rewrite_content)

    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "请改成更口语化。",
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "内容改写失败：上游模型服务返回错误。deepseek rewrite request failed: timed out"
    }


def test_content_rewrite_endpoint_surfaces_empty_rewrite_output(monkeypatch) -> None:
    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        raise ContentRewriteEmptyOutputError(
            "内容改写失败：deepseek 返回了空内容。请重试，或更换模型/提示词。"
        )

    monkeypatch.setattr("app.main.rewrite_content", fake_rewrite_content)

    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "请改成更口语化。",
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "内容改写失败：deepseek 返回了空内容。请重试，或更换模型/提示词。"
    }


def test_select_rewrite_template_routes_transcript_first() -> None:
    references = RewriteReferences(
        article_template="一页版模板",
        content_methodology="方法论",
        style_examples="示例",
        skill_guide="规则",
        category_templates={
            "09_interview_transcript_sync": "逐字稿模板",
            "03_product_review": "评测模板",
            "01_big_company_war": "公司战役模板",
        },
        section_title_rules="标题规则",
    )

    selected = _select_rewrite_template(
        source_text="00:12 主持人：先问一个问题。\n00:33 嘉宾：我们先从组织调整说起。",
        rewrite_focus="整理成晚点风格中文稿。",
        references=references,
    )

    assert selected.key == "09_interview_transcript_sync"
    assert selected.body == "逐字稿模板"


def test_select_rewrite_template_routes_product_review_by_keywords() -> None:
    references = RewriteReferences(
        article_template="一页版模板",
        content_methodology="方法论",
        style_examples="示例",
        skill_guide="规则",
        category_templates={
            "03_product_review": "评测模板",
            "01_big_company_war": "公司战役模板",
        },
        section_title_rules="标题规则",
    )

    selected = _select_rewrite_template(
        source_text="我们实测了这个 Agent 的三个真实任务，记录了失败点、纠错过程和可用性边界。",
        rewrite_focus="改写成有晚点味的稿子。",
        references=references,
    )

    assert selected.key == "03_product_review"
    assert selected.body == "评测模板"


def test_validate_rewrite_prompt_classifies_modes() -> None:
    full_prompt = validate_rewrite_prompt(
        "请根据以下内容写文章。\n\n视频内容：\n{{transcript}}"
    )
    hint_prompt = validate_rewrite_prompt("请改写为更短、更有节奏感的中文文章。")
    broken_prompt = validate_rewrite_prompt("请根据以下内容写文章。\n\n视频内容：")

    assert full_prompt.mode == "full_prompt"
    assert full_prompt.is_valid is True
    assert hint_prompt.mode == "style_hint"
    assert hint_prompt.is_valid is True
    assert broken_prompt.mode == "style_hint"
    assert broken_prompt.is_valid is False
    assert any("缺少 {{transcript}}" in error for error in broken_prompt.errors)


def test_rewrite_content_attaches_quality_issues(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.content_rewrite_service.load_rewrite_references",
        lambda: RewriteReferences(
            article_template="文章模板片段",
            content_methodology="内容方法论片段",
            style_examples="风格示例片段",
            skill_guide="写作规则片段",
            quality_pipeline="质量流程片段",
            category_templates={"01_big_company_war": "场景模板片段"},
            section_title_rules="标题规则片段",
        ),
    )

    def fake_post(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={
                "message": {
                    "content": "# 标题\n\n# 标题\n\n作为AI，我只能说这些。"
                }
            },
        )

    monkeypatch.setattr("app.services.content_rewrite_service.httpx.post", fake_post)

    result = rewrite_content(
        source_text="原始内容。",
        rewrite_focus="请改写为更顺畅的中文文章。",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert result.quality_issues
    assert any("重复段落" in issue or "重复" in issue for issue in result.quality_issues)
