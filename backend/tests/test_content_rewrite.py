from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services.content_context_service import ContentContext, create_content_context
from app.services.content_rewrite_service import (
    ContentRewriteEmptyOutputError,
    ContentRewriteConfigurationError,
    ContentRewriteProviderError,
    ContentRewriteResult,
    RewriteReferences,
    _select_rewrite_template,
    rewrite_content,
)
from app.services.prompt_validation import validate_rewrite_prompt


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

    monkeypatch.setattr("app.services.rewrite_provider_service.httpx.post", fake_post)

    result = rewrite_content(
        source_text="原始内容第一句。原始内容第二句。",
        rewrite_focus="改成更有节奏感。",
        rewrite_style="article_longform",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert "Authorization" not in captured["headers"]
    assert captured["json"]["model"] == "qwen3.5:4b"
    assert captured["json"]["messages"][0]["role"] == "system"
    assert "中文文章改写助手" in captured["json"]["messages"][0]["content"]
    assert captured["json"]["messages"][1]["role"] == "system"
    assert "【场景模板】" in captured["json"]["messages"][1]["content"]
    assert "场景模板片段" not in captured["json"]["messages"][1]["content"]
    assert "【通用一页模板】" not in captured["json"]["messages"][1]["content"]
    assert "文章模板片段" in captured["json"]["messages"][1]["content"]
    assert "内容方法论片段" in captured["json"]["messages"][1]["content"]
    assert "风格示例片段" in captured["json"]["messages"][1]["content"]
    assert "写作规则片段" in captured["json"]["messages"][1]["content"]
    assert "标题规则片段" in captured["json"]["messages"][1]["content"]
    assert "质量流程片段" in captured["json"]["messages"][1]["content"]
    assert captured["json"]["messages"][2]["role"] == "user"
    assert "改写目标：改成更有节奏感。" in captured["json"]["messages"][2]["content"]
    assert "第三视角成文" in captured["json"]["messages"][2]["content"]
    assert "不使用我/我们/咱们/本人作为叙述主语" in captured["json"]["messages"][2]["content"]
    assert "原始内容第一句。原始内容第二句。" in captured["json"]["messages"][2]["content"]
    assert result == ContentRewriteResult(
        rewritten_text="这是改写后的内容。",
        provider="ollama",
        model="qwen3.5:4b",
    )


def test_rewrite_content_defaults_to_speech_verbatim_without_references(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={"message": {"content": "这是口吻整理后的内容。"}},
        )

    monkeypatch.setattr("app.services.rewrite_provider_service.httpx.post", fake_post)

    result = rewrite_content(
        source_text="原始内容第一句。原始内容第二句。",
        rewrite_focus="保留原作者说话节奏。",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert captured["json"]["messages"][0]["role"] == "system"
    assert "口吻整理助手" in captured["json"]["messages"][0]["content"]
    assert len(captured["json"]["messages"]) == 2
    assert "晚点题材路由" not in captured["json"]["messages"][0]["content"]
    assert "【参考来源】" not in captured["json"]["messages"][1]["content"]
    assert "不要总结化" in captured["json"]["messages"][1]["content"]
    assert result == ContentRewriteResult(
        rewritten_text="这是口吻整理后的内容。",
        provider="ollama",
        model="qwen3.5:4b",
    )


def test_rewrite_content_reports_language_mismatch_for_english_output(
    monkeypatch,
) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={"message": {"content": "This is an English rewrite with no Chinese main body."}},
        )

    monkeypatch.setattr("app.services.rewrite_provider_service.httpx.post", fake_post)

    result = rewrite_content(
        source_text="Original source text.",
        rewrite_focus="Please keep it concise.",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert any("简体中文" in issue for issue in result.quality_issues)


def test_rewrite_content_speech_verbatim_includes_detail_ledger(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={"message": {"content": "这是口吻整理后的内容。"}},
        )

    monkeypatch.setattr("app.services.rewrite_provider_service.httpx.post", fake_post)

    result = rewrite_content(
        source_text="原始内容第一句。原始内容第二句。",
        rewrite_focus="保留原作者说话节奏。",
        detail_ledger="- 数字: 3\n- 专有名词: NASA",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert captured["json"]["messages"][0]["role"] == "system"
    assert len(captured["json"]["messages"]) == 2
    assert "【细节清单（优先保留）】" in captured["json"]["messages"][1]["content"]
    assert "- 数字: 3" in captured["json"]["messages"][1]["content"]
    assert "- 专有名词: NASA" in captured["json"]["messages"][1]["content"]
    assert result == ContentRewriteResult(
        rewritten_text="这是口吻整理后的内容。",
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

    monkeypatch.setattr("app.services.rewrite_provider_service.httpx.post", fake_post)

    result = rewrite_content(
        source_text="这是原始转录内容。",
        rewrite_focus="标题：测试技能\n正文：{{transcript}}\n结尾：保持克制。",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert captured["json"]["messages"][0]["content"] == "你是一个智能写作助手。请严格遵守用户的格式要求。"
    assert (
        captured["json"]["messages"][1]["content"]
        == "标题：测试技能\n正文：\n\n[转录内容开始]\n这是原始转录内容。\n[转录内容结束]\n\n\n结尾：保持克制。"
    )
    assert result == ContentRewriteResult(
        rewritten_text="这是技能改写后的内容。",
        provider="ollama",
        model="qwen3.5:4b",
    )


def test_content_rewrite_endpoint_returns_rewritten_text(monkeypatch) -> None:
    def fake_run_writer_agent(**kwargs) -> ContentRewriteResult:
        assert kwargs["source_text"] == "这里是需要改写的原文。"
        assert kwargs["reference_text"] is None
        assert kwargs["rewrite_focus"] == "请改成更口语化。"
        assert kwargs["rewrite_style"] == "speech_verbatim"
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

    monkeypatch.setattr("app.main.run_writer_agent", fake_run_writer_agent)

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
        "detail_coverage_issues": [],
    }


def test_content_rewrite_endpoint_loads_reference_text_from_context(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_load_content_context(
        content_context_id: str,
        *,
        account_id: str | None = None,
    ) -> ContentContext | None:
        assert content_context_id == "ctx-reference"
        assert account_id == "user:alice"
        return ContentContext(
            content_context_id="ctx-reference",
            account_id="user:alice",
            video_title="Demo video",
            transcript_en="Original English transcript.",
            translation_zh="中文译文。",
        )

    def fake_run_writer_agent(**kwargs) -> ContentRewriteResult:
        captured.update(kwargs)
        return ContentRewriteResult(
            rewritten_text="这是改写后的版本。",
            provider="deepseek",
            model="deepseek-chat",
        )

    monkeypatch.setattr("app.api.routers.content.load_content_context", fake_load_content_context)
    monkeypatch.setattr("app.main.run_writer_agent", fake_run_writer_agent)

    response = client.post(
        "/api/content-rewrite",
        headers={"x-user-id": "alice"},
        json={
            "content_context_id": "ctx-reference",
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "请改成更口语化。",
            "translation_config": {
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
        },
    )

    assert response.status_code == 200
    assert captured["reference_text"] == "Original English transcript."
    assert response.json()["rewritten_text"] == "这是改写后的版本。"


def test_content_rewrite_endpoint_rejects_cross_account_context(monkeypatch) -> None:
    def fake_load_content_context(
        content_context_id: str,
        *,
        account_id: str | None = None,
    ) -> ContentContext | None:
        assert content_context_id == "ctx-reference"
        assert account_id == "user:bob"
        return None

    monkeypatch.setattr("app.api.routers.content.load_content_context", fake_load_content_context)
    monkeypatch.setattr(
        "app.main.run_writer_agent",
        lambda **kwargs: ContentRewriteResult(
            rewritten_text="不该返回。",
            provider="deepseek",
            model="deepseek-chat",
        ),
    )

    response = client.post(
        "/api/content-rewrite",
        headers={"x-user-id": "bob"},
        json={
            "content_context_id": "ctx-reference",
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "请改成更口语化。",
            "translation_config": {
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
        },
    )

    _assert_error_response(
        response,
        status_code=404,
        error_code="NOT_FOUND",
        retryable=False,
        detail="Content context not found.",
    )


def test_rewrite_content_rejects_non_local_ollama_base_url() -> None:
    try:
        rewrite_content(
            source_text="原始内容第一句。原始内容第二句。",
            rewrite_focus="保留原作者说话节奏。",
            rewrite_config={
                "provider": "ollama",
                "base_url": "http://192.168.1.10:11434",
                "model": "qwen3.5:4b",
            },
        )
    except ContentRewriteConfigurationError as error:
        assert "must point to localhost" in str(error)
    else:
        raise AssertionError("Expected configuration error")


def test_content_rewrite_endpoint_returns_detail_coverage_issues(monkeypatch) -> None:
    captured: dict[str, object] = {}
    content_context_id = create_content_context(
        video_title="Test video",
        transcript_en="Hello everyone.\nWelcome back.",
        translation_zh="大家好。\n欢迎回来。",
        account_id="user:alice",
    )

    def fake_load_content_context(
        content_context_id: str,
        *,
        account_id: str | None = None,
    ) -> ContentContext | None:
        assert content_context_id == content_context_id
        assert account_id == "user:alice"
        return ContentContext(
            content_context_id=content_context_id,
            account_id="user:alice",
            video_title="Test video",
            transcript_en="Hello everyone.\nWelcome back.",
            translation_zh="大家好。\n欢迎回来。",
        )

    def fake_run_writer_agent(**kwargs) -> ContentRewriteResult:
        return ContentRewriteResult(
            rewritten_text="改写后的正文。",
            provider="deepseek",
            model="deepseek-chat",
            quality_issues=("段落重复",),
            detail_coverage_issues=("缺失细节：数字 3", "缺失细节：专有名词 NASA"),
        )

    def fake_record_rewrite_result(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("app.api.routers.content.load_content_context", fake_load_content_context)
    monkeypatch.setattr("app.main.run_writer_agent", fake_run_writer_agent)
    monkeypatch.setattr(
        "app.api.routers.content.record_rewrite_result",
        fake_record_rewrite_result,
    )

    response = client.post(
        "/api/content-rewrite",
        headers={"x-user-id": "alice"},
        json={
            "source_text": "原文",
            "rewrite_focus": "改写",
            "content_context_id": content_context_id,
            "translation_config": {
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["detail_coverage_issues"] == [
        "缺失细节：数字 3",
        "缺失细节：专有名词 NASA",
    ]
    assert body["quality_issues"] == ["段落重复"]
    assert captured["rewrite_style"] == "speech_verbatim"
    assert captured["rewrite_detail_coverage_issues"] == [
        "缺失细节：数字 3",
        "缺失细节：专有名词 NASA",
    ]
    assert captured["writer_trace_id"] == ""
    assert captured["writer_policy_version"] == ""
    assert captured["writer_prompt_version"] == ""
    assert captured["rewrite_quality_issues"] == ["段落重复"]


def test_content_rewrite_endpoint_rejects_empty_source_text() -> None:
    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "   ",
            "rewrite_focus": "请改写。",
        },
    )

    _assert_error_response(
        response,
        status_code=422,
        error_code="VALIDATION_ERROR",
        retryable=False,
        detail="source_text: Value error, source_text must not be empty.",
    )


def test_content_rewrite_endpoint_rejects_blank_rewrite_focus() -> None:
    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "   ",
        },
    )

    _assert_error_response(
        response,
        status_code=400,
        error_code="REWRITE_INPUT_INVALID",
        retryable=False,
        detail="改写提示为空。请重新选择写作风格，或移除空白 rewrite_focus 后重试。",
    )


def test_content_rewrite_endpoint_rejects_invalid_placeholder_usage() -> None:
    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "标题：测试\n正文：{{ transcript }}",
        },
    )

    _assert_error_response(
        response,
        status_code=400,
        error_code="REWRITE_INPUT_INVALID",
        retryable=False,
        detail="改写模板包含不支持的占位符：{{ transcript }}。当前仅支持 {{transcript}}。",
    )


def test_content_rewrite_endpoint_rejects_full_prompt_without_transcript_placeholder() -> None:
    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "请根据以下视频内容写一篇公众号文章。\n\n视频内容：",
        },
    )

    _assert_error_response(
        response,
        status_code=400,
        error_code="REWRITE_INPUT_INVALID",
        retryable=False,
        detail="该写作风格看起来是完整 Prompt，但缺少 {{transcript}}。请补上占位符，或删掉完整 prompt 结构后作为风格提示使用。",
    )


def test_content_rewrite_endpoint_surfaces_provider_failure(monkeypatch) -> None:
    def fake_run_writer_agent(**kwargs) -> ContentRewriteResult:
        raise ContentRewriteProviderError("deepseek rewrite request failed: timed out")

    monkeypatch.setattr("app.main.run_writer_agent", fake_run_writer_agent)

    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "请改成更口语化。",
        },
    )

    _assert_error_response(
        response,
        status_code=502,
        error_code="UPSTREAM_ERROR",
        retryable=True,
        detail="内容改写失败：上游模型服务返回错误。deepseek rewrite request failed: timed out",
    )


def test_content_rewrite_endpoint_surfaces_empty_rewrite_output(monkeypatch) -> None:
    def fake_run_writer_agent(**kwargs) -> ContentRewriteResult:
        raise ContentRewriteEmptyOutputError(
            "内容改写失败：deepseek 返回了空内容。请重试，或更换模型/提示词。"
        )

    monkeypatch.setattr("app.main.run_writer_agent", fake_run_writer_agent)

    response = client.post(
        "/api/content-rewrite",
        json={
            "source_text": "这里是需要改写的原文。",
            "rewrite_focus": "请改成更口语化。",
        },
    )

    _assert_error_response(
        response,
        status_code=502,
        error_code="REWRITE_EMPTY",
        retryable=True,
        detail="内容改写失败：deepseek 返回了空内容。请重试，或更换模型/提示词。",
    )


def test_select_rewrite_template_routes_transcript_first_to_transcript_template() -> None:
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


def test_select_rewrite_template_routes_explicit_transcript_sync_request() -> None:
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
        rewrite_focus="请整理成逐字稿/同步稿。",
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


def test_select_rewrite_template_uses_generic_fallback_for_unknown_material() -> None:
    references = RewriteReferences(
        article_template="一页版模板",
        content_methodology="方法论",
        style_examples="示例",
        skill_guide="规则",
        category_templates={
            "09_interview_transcript_sync": "逐字稿模板",
            "03_product_review": "评测模板",
            "06_infra_cloud_model_platform": "平台模板",
            "01_big_company_war": "公司战役模板",
        },
        section_title_rules="标题规则",
    )

    selected = _select_rewrite_template(
        source_text="这是一个没有明显题材信号的普通素材。",
        rewrite_focus="整理成中文稿。",
        references=references,
    )

    assert selected.key == "generic"
    assert selected.label == "通用素材报道稿"
    assert selected.body == "一页版模板"


def test_select_rewrite_template_routes_strategic_fallback_by_explicit_signals() -> None:
    references = RewriteReferences(
        article_template="一页版模板",
        content_methodology="方法论",
        style_examples="示例",
        skill_guide="规则",
        category_templates={
            "01_big_company_war": "公司战役模板",
        },
        section_title_rules="标题规则",
    )

    selected = _select_rewrite_template(
        source_text="这场竞争和入口之争正在推动资源重排。",
        rewrite_focus="改写成晚点风格。",
        references=references,
    )

    assert selected.key == "01_big_company_war"
    assert selected.body == "公司战役模板"


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

    monkeypatch.setattr("app.services.rewrite_provider_service.httpx.post", fake_post)

    result = rewrite_content(
        source_text="原始内容。",
        rewrite_focus="请改写为更顺畅的中文文章。",
        rewrite_style="article_longform",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert result.quality_issues
    assert any("重复段落" in issue or "重复" in issue for issue in result.quality_issues)
