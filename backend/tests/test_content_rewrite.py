from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services.content_rewrite_service import (
    ContentRewriteResult,
    RewriteReferences,
    _select_rewrite_template,
    rewrite_content,
)


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
    assert "【场景模板】" in captured["json"]["messages"][1]["content"]
    assert "【通用一页模板】" in captured["json"]["messages"][1]["content"]
    assert "文章模板片段" in captured["json"]["messages"][1]["content"]
    assert "内容方法论片段" in captured["json"]["messages"][1]["content"]
    assert "风格示例片段" in captured["json"]["messages"][1]["content"]
    assert "写作规则片段" in captured["json"]["messages"][1]["content"]
    assert "原始内容第一句。原始内容第二句。" in captured["json"]["messages"][2]["content"]
    assert result == ContentRewriteResult(
        rewritten_text="这是改写后的内容。",
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
