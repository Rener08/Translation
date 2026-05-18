from __future__ import annotations

from types import SimpleNamespace

from app.services.article_generation_service import ArticleValidationResult, resolve_article_spec
from app.services.detail_ledger import DetailLedger, DetailLedgerItem
from app.services.rewrite_loop_executor import (
    build_draft_prompt,
    build_expand_prompt,
    build_outline_prompt,
    build_patch_prompt,
    run_article_longform_loop,
)
from app.services.rewrite_loop_validator import ValidationReport
from app.services.skill_config_service import SkillConfig, SkillOutputSpec, StyleConstraint


def _skill_config() -> SkillConfig:
    return SkillConfig(
        style_name="",
        perspective="third_person",
        output=SkillOutputSpec(
            min_chars=10,
            target_chars=30,
            max_chars=200,
            min_sections=1,
            max_sections=4,
            source_length_ratio_min=None,
            source_length_ratio_max=None,
        ),
        constraints=(
            StyleConstraint(
                constraint_type="perspective_marker",
                pattern="我",
                fix_hint="请改成第三视角叙述",
            ),
        ),
        perspective_markers=("我",),
        template_routing_enabled=False,
        content_filters=(),
        quality_layers=(),
    )


def _material() -> MaterialPackage:
    class _Material:
        source_text = "OpenAI released a new model. It changes the product strategy."
        reference_text = ""

        @staticmethod
        def article_input_text() -> str:
            return _Material.source_text

    return _Material()


def test_run_article_longform_loop_falls_back_without_env_flag(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        return SimpleNamespace(
            rewritten_text="single-pass article",
            provider="openai",
            model="gpt-4",
            quality_issues=(),
        )

    monkeypatch.delenv("USE_AGENT_LOOP", raising=False)
    monkeypatch.setattr("app.services.rewrite_loop_executor.rewrite_content", fake_rewrite_content)

    report = run_article_longform_loop(
        material=_material(),
        rewrite_focus="保留重点",
        rewrite_style="article_longform",
        rewrite_config=None,
        skill_config=_skill_config(),
    )

    assert len(calls) == 1
    assert report.rewritten_text == "single-pass article"
    assert report.rewrite_style == "article_longform"
    assert report.next_recommended_action == "stop"


def test_run_article_longform_loop_uses_loop_when_enabled(monkeypatch) -> None:
    calls: list[str] = []
    results = iter(
        [
            SimpleNamespace(
                rewritten_text="1. 先出大纲\n2. 再写正文",
                provider="openai",
                model="gpt-4",
                quality_issues=(),
            ),
            SimpleNamespace(
                rewritten_text="第一段。\n\n第二段。",
                provider="openai",
                model="gpt-4",
                quality_issues=(),
            ),
        ]
    )

    def fake_rewrite_content(**kwargs):
        calls.append(str(kwargs.get("rewrite_focus", "")))
        return next(results)

    passed_report = ValidationReport(
        hard_failures=(),
        soft_failures=(),
        detail_coverage_issues=(),
        next_recommended_action="stop",
        article_validation=ArticleValidationResult(
            ok=True,
            total_chars=20,
            section_count=2,
            section_chars=(10, 10),
            issues=(),
        ),
    )

    monkeypatch.setenv("USE_AGENT_LOOP", "true")
    monkeypatch.setattr("app.services.rewrite_loop_executor.rewrite_content", fake_rewrite_content)
    monkeypatch.setattr(
        "app.services.rewrite_loop_executor.validate_longform_rewrite",
        lambda **kwargs: passed_report,
    )
    monkeypatch.setattr(
        "app.services.rewrite_loop_executor.analyze_detail_coverage_enhanced",
        lambda ledger, text: SimpleNamespace(missing_items=()),
    )

    report = run_article_longform_loop(
        material=_material(),
        rewrite_focus="保留重点",
        rewrite_style="article_longform",
        rewrite_config=None,
        skill_config=_skill_config(),
    )

    assert len(calls) == 2
    assert "写作规划" in calls[0]
    assert "初稿" in calls[1]
    assert report.rewritten_text == "第一段。\n\n第二段。"
    assert report.next_recommended_action == "stop"


def test_prompt_builders_include_required_sections() -> None:
    spec = resolve_article_spec("short source text")
    ledger = DetailLedger(items=(DetailLedgerItem(kind="事实", text="must keep"),))
    validation = ValidationReport(
        hard_failures=("hard issue",),
        soft_failures=("soft issue",),
        detail_coverage_issues=("事实 must keep",),
        next_recommended_action="patch",
        article_validation=ArticleValidationResult(
            ok=False,
            total_chars=10,
            section_count=1,
            section_chars=(10,),
            issues=("bad section",),
        ),
    )

    outline_prompt = build_outline_prompt(
        rewrite_focus="保留重点",
        length_guidance="length guidance",
        spec=spec,
        detail_ledger_text=ledger.to_prompt_text(),
        template_label="模板A",
        template_reason="因为题材",
        template_body="模板摘要",
    )
    draft_prompt = build_draft_prompt(
        rewrite_focus="保留重点",
        outline=("第一点", "第二点"),
        spec=spec,
        length_guidance="length guidance",
        detail_ledger_text=ledger.to_prompt_text(),
        template_label="模板A",
        template_reason="因为题材",
    )
    expand_prompt = build_expand_prompt(
        previous_article="已有正文",
        source_text="source text",
        detail_ledger=ledger,
        length_guidance="length guidance",
        spec=spec,
        validation=validation,
    )
    patch_prompt = build_patch_prompt(
        previous_article="已有正文",
        validation=validation,
        detail_ledger=ledger,
        source_text="source text",
        length_guidance="length guidance",
    )

    assert "写作规划" in outline_prompt
    assert "模板摘要" in outline_prompt
    assert "初稿" in draft_prompt
    assert "第一点" in draft_prompt
    assert "扩写式重写" in expand_prompt
    assert "hard issue" not in expand_prompt
    assert "hard issue" in patch_prompt
    assert "must keep" in patch_prompt
