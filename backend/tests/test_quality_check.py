"""Tests for quality_check_service."""

import pytest

from app.services.quality_check_service import (
    QualityIssue,
    QualityReport,
    build_revision_prompt,
    check_article_quality,
)
from app.services.skill_config_service import SkillConfig, SkillOutputSpec, StyleConstraint


# ---------- fixtures ----------

def _make_kazek_config() -> SkillConfig:
    """卡兹克 config: first_person, empty perspective_markers."""
    return SkillConfig(
        style_name="卡兹克",
        perspective="first_person",
        output=SkillOutputSpec(
            min_chars=3000, target_chars=5000, max_chars=8000,
            min_sections=4, max_sections=8,
        ),
        constraints=(
            StyleConstraint("forbidden_word", "说白了", ""),
            StyleConstraint("forbidden_word", "本质上", ""),
            StyleConstraint("forbidden_punctuation", "：", "，"),
            StyleConstraint("forbidden_punctuation", "——", "，"),
        ),
        perspective_markers=(),
        template_routing_enabled=False,
        content_filters=("跳过广告和赞助内容",),
        quality_layers=(
            {"name": "L1 硬性规则", "checks": ["forbidden_words", "forbidden_punctuation", "no_fabrication", "output_length"]},
            {"name": "L2 风格一致性", "checks": ["rhythm_variety", "sentence_length_mix"]},
            {"name": "L3 内容深度", "checks": ["evidence_support", "detail_coverage"]},
            {"name": "L4 活人感", "checks": ["temperature", "colloquial_density"]},
        ),
    )


def _make_latepost_config() -> SkillConfig:
    """晚点 config: third_person, has perspective_markers."""
    return SkillConfig(
        style_name="晚点",
        perspective="third_person",
        output=SkillOutputSpec(
            min_chars=0, target_chars=0, max_chars=0,
            min_sections=3, max_sections=6,
            source_length_ratio_min=0.4,
            source_length_ratio_max=0.6,
        ),
        constraints=(
            StyleConstraint("forbidden_word", "说白了", ""),
            StyleConstraint("forbidden_word", "本质上", ""),
            StyleConstraint("forbidden_punctuation", "：", "，"),
            StyleConstraint("perspective_marker", "我认为", ""),
            StyleConstraint("perspective_marker", "我觉得", ""),
            StyleConstraint("perspective_marker", "我们先", ""),
            StyleConstraint("perspective_marker", "咱们", ""),
        ),
        perspective_markers=("我认为", "我觉得", "我们先", "咱们"),
        template_routing_enabled=True,
        content_filters=("跳过广告和赞助内容",),
        quality_layers=(
            {
                "name": "L1 硬约束",
                "checks": [
                    {"type": "perspective_consistent", "fix_hint": "请改成第三视角叙述，不要使用我/我们/咱们作为叙述主语"},
                    "no_fabrication",
                    "detail_coverage",
                ],
            },
            {"name": "L2 风格一致性", "checks": ["specific_subjects", "forbidden_words"]},
        ),
    )


# ---------- tests ----------

def test_forbidden_words_detected():
    cfg = _make_kazek_config()
    text = "这篇文章说白了就是讲技术的。"
    report = check_article_quality(text, "", cfg)
    assert not report.passed
    word_issues = [i for i in report.issues if i.check_type == "forbidden_word"]
    assert len(word_issues) == 1
    assert word_issues[0].matched == "说白了"


def test_forbidden_punctuation_detected():
    cfg = _make_kazek_config()
    text = "这是一个测试：看看标点" + "x" * 3000
    report = check_article_quality(text, "", cfg)
    punct_issues = [i for i in report.issues if i.check_type == "forbidden_punctuation"]
    assert len(punct_issues) >= 1
    assert punct_issues[0].matched == "："


def test_perspective_third_person():
    cfg = _make_latepost_config()
    text = "我认为这篇文章很好。" + "x" * 2500
    report = check_article_quality(text, "", cfg)
    persp_issues = [i for i in report.issues if i.check_type == "perspective"]
    assert len(persp_issues) == 1
    assert persp_issues[0].matched == "我认为"
    assert "第三视角" in persp_issues[0].fix_hint


def test_perspective_first_person_skipped():
    cfg = _make_kazek_config()
    text = "我认为这篇文章很好。" + "x" * 3500
    report = check_article_quality(text, "", cfg)
    persp_issues = [i for i in report.issues if i.check_type == "perspective"]
    assert len(persp_issues) == 0


def test_output_length_too_short():
    cfg = _make_kazek_config()
    text = "太短了"
    report = check_article_quality(text, "", cfg)
    length_issues = [i for i in report.issues if i.check_type == "output_length"]
    assert len(length_issues) == 1
    assert "低于" in length_issues[0].message


def test_output_length_ok():
    cfg = _make_kazek_config()
    text = "x" * 4000
    report = check_article_quality(text, "", cfg)
    length_issues = [i for i in report.issues if i.check_type == "output_length"]
    assert len(length_issues) == 0


def test_output_length_ratio_is_soft():
    cfg = SkillConfig(
        style_name="晚点",
        perspective="third_person",
        output=SkillOutputSpec(
            min_chars=0, target_chars=0, max_chars=0,
            min_sections=3, max_sections=6,
            source_length_ratio_min=0.4,
            source_length_ratio_max=0.6,
        ),
        constraints=(),
        perspective_markers=(),
        template_routing_enabled=True,
        content_filters=(),
        quality_layers=(),
    )
    source = "a" * 2000
    text = "b" * 500
    report = check_article_quality(text, source, cfg)
    ratio_issues = [i for i in report.issues if i.check_type == "output_length_ratio"]
    assert len(ratio_issues) == 1
    assert ratio_issues[0].severity == "soft"
    assert report.passed


def test_detail_coverage_missing():
    from app.services.detail_ledger import build_detail_ledger
    cfg = _make_latepost_config()
    source = "OpenAI released GPT-5 in 2025 with 42 billion parameters."
    text = "OpenAI released a new model recently." + "x" * 2500
    ledger = build_detail_ledger(source)
    report = check_article_quality(text, source, cfg, detail_ledger=ledger)
    coverage_issues = [i for i in report.issues if i.check_type == "detail_coverage"]
    # At least one detail should be detected as missing
    assert len(coverage_issues) >= 1


def test_clean_pass():
    cfg = _make_kazek_config()
    text = "这是一篇干净的测试文章。" * 400  # well over 3000 chars
    report = check_article_quality(text, "", cfg)
    assert report.passed
    assert report.layers_checked > 0
    assert report.layers_passed == report.layers_checked


def test_build_revision_prompt():
    issues = (
        QualityIssue("L1 硬性规则", "forbidden_word", 5, "说白了", "发现禁用词「说白了」", "请替换「说白了」"),
        QualityIssue("L1 硬约束", "perspective", 0, "我认为", "发现第一人称标记", "请改成第三视角叙述"),
    )
    report = QualityReport(passed=False, issues=issues, layers_checked=2, layers_passed=0)
    prompt = build_revision_prompt(report)
    assert "修订" in prompt
    assert "说白了" in prompt
    assert "第一人称标记" in prompt
    assert "只输出修订后的正文" in prompt


def test_multiple_issues():
    cfg = _make_latepost_config()
    text = "说白了，我认为这是一个好项目。" + "x" * 2000
    report = check_article_quality(text, "", cfg)
    assert not report.passed
    check_types = {i.check_type for i in report.issues}
    assert "forbidden_word" in check_types
    assert "perspective" in check_types
