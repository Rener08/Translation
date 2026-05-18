from __future__ import annotations

from types import SimpleNamespace

from app.services.article_generation_service import ArticleValidationResult
from app.services.detail_ledger import DetailLedger, DetailLedgerItem
from app.services.quality_check_service import QualityIssue, QualityReport
from app.services.rewrite_loop_validator import validate_longform_rewrite
from app.services.skill_config_service import SkillConfig, SkillOutputSpec, StyleConstraint


def _skill_config() -> SkillConfig:
    return SkillConfig(
        style_name="晚点",
        perspective="third_person",
        output=SkillOutputSpec(
            min_chars=10,
            target_chars=30,
            max_chars=200,
            min_sections=1,
            max_sections=4,
            source_length_ratio_min=0.4,
            source_length_ratio_max=0.6,
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
        quality_layers=(
            {"checks": [{"type": "perspective_consistent"}, {"type": "detail_coverage"}]},
        ),
    )


def test_validate_longform_rewrite_classifies_hard_soft_and_detail(monkeypatch) -> None:
    ledger = DetailLedger(items=(DetailLedgerItem(kind="事实", text="missing detail"),))

    monkeypatch.setattr(
        "app.services.rewrite_loop_validator.validate_generated_article",
        lambda text, spec: ArticleValidationResult(
            ok=True,
            total_chars=120,
            section_count=2,
            section_chars=(60, 60),
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "app.services.rewrite_loop_validator.check_article_quality",
        lambda text, source_text, skill_config, detail_ledger: QualityReport(
            passed=False,
            issues=(
                QualityIssue(
                    layer="L1 硬约束",
                    check_type="perspective",
                    position=0,
                    matched="我",
                    message="发现第一人称标记「我」，当前配置为第三人称",
                    fix_hint="请改成第三视角叙述",
                    severity="hard",
                ),
                QualityIssue(
                    layer="L2 篇幅建议",
                    check_type="output_length_ratio",
                    position=-1,
                    matched="120",
                    message="输出字数 120 建议控制在原文长度的 40%-60%",
                    fix_hint="请按原文篇幅比例适当压缩或扩展。",
                    severity="soft",
                ),
                QualityIssue(
                    layer="L1 硬约束",
                    check_type="detail_coverage",
                    position=-1,
                    matched="missing detail",
                    message="缺失关键细节：事实 missing detail",
                    fix_hint="请将「missing detail」补回正文",
                    severity="hard",
                ),
            ),
            layers_checked=1,
            layers_passed=0,
        ),
    )
    monkeypatch.setattr(
        "app.services.rewrite_loop_validator.analyze_detail_coverage_enhanced",
        lambda detail_ledger, rewritten_text: SimpleNamespace(
            missing_items=(DetailLedgerItem(kind="事实", text="missing detail"),)
        ),
    )

    report = validate_longform_rewrite(
        text="我在这里写一段。\n\n第二段。",
        source_text="source material",
        skill_config=_skill_config(),
        detail_ledger=ledger,
    )

    assert report.hard_failures == ('发现第一人称标记「我」，当前配置为第三人称',)
    assert report.soft_failures == ('输出字数 120 建议控制在原文长度的 40%-60%',)
    assert report.detail_coverage_issues == ('事实 missing detail',)
    assert report.next_recommended_action == "patch"
    assert report.passed is False


def test_validate_longform_rewrite_expands_for_only_detail_gaps(monkeypatch) -> None:
    ledger = DetailLedger(items=(DetailLedgerItem(kind="事实", text="another missing detail"),))

    monkeypatch.setattr(
        "app.services.rewrite_loop_validator.validate_generated_article",
        lambda text, spec: ArticleValidationResult(
            ok=True,
            total_chars=140,
            section_count=2,
            section_chars=(70, 70),
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "app.services.rewrite_loop_validator.check_article_quality",
        lambda text, source_text, skill_config, detail_ledger: QualityReport(
            passed=True,
            issues=(),
            layers_checked=1,
            layers_passed=1,
        ),
    )
    monkeypatch.setattr(
        "app.services.rewrite_loop_validator.analyze_detail_coverage_enhanced",
        lambda detail_ledger, rewritten_text: SimpleNamespace(
            missing_items=(DetailLedgerItem(kind="事实", text="another missing detail"),)
        ),
    )

    report = validate_longform_rewrite(
        text="第一段。\n\n第二段。",
        source_text="source material",
        skill_config=_skill_config(),
        detail_ledger=ledger,
    )

    assert report.hard_failures == ()
    assert report.soft_failures == ()
    assert report.detail_coverage_issues == ('事实 another missing detail',)
    assert report.next_recommended_action == "expand"
    assert report.passed is False
