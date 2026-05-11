from app.services.article_generation_service import (
    ArticleSpec,
    ArticleValidationResult,
    build_article_generation_prompt,
    build_article_rewrite_prompt,
    measure_source_text_length,
    resolve_article_spec,
    validate_generated_article,
)


def test_measure_source_text_length_ignores_whitespace() -> None:
    assert measure_source_text_length(" 你好\n世界 ") == 4


def test_resolve_article_spec_for_short_source() -> None:
    result = resolve_article_spec("a" * 2800)

    assert result == ArticleSpec(
        source_length=2800,
        target_total_chars=1500,
        min_total_chars=1200,
        max_total_chars=1800,
        min_sections=2,
        max_sections=3,
        recommended_sections=3,
        target_chars_per_section=500,
        min_chars_per_section=400,
        max_chars_per_section=900,
    )


def test_resolve_article_spec_for_medium_source() -> None:
    result = resolve_article_spec("a" * 5000)

    assert result == ArticleSpec(
        source_length=5000,
        target_total_chars=5000,
        min_total_chars=4200,
        max_total_chars=5800,
        min_sections=3,
        max_sections=4,
        recommended_sections=3,
        target_chars_per_section=1667,
        min_chars_per_section=1050,
        max_chars_per_section=1933,
    )


def test_resolve_article_spec_for_large_source() -> None:
    result = resolve_article_spec("a" * 12000)

    assert result == ArticleSpec(
        source_length=12000,
        target_total_chars=8000,
        min_total_chars=7000,
        max_total_chars=9000,
        min_sections=5,
        max_sections=5,
        recommended_sections=5,
        target_chars_per_section=1600,
        min_chars_per_section=1400,
        max_chars_per_section=1800,
    )


def test_build_article_generation_prompt_includes_spec_constraints() -> None:
    spec = resolve_article_spec("a" * 3200)

    prompt = build_article_generation_prompt(
        source_text="English source text.",
        cleaned_translation_zh="清洗后的中文内容。",
        spec=spec,
    )

    assert "总字数目标：5000 字" in prompt
    assert "段落数量：3-4 段" in prompt
    assert "每段字数：建议约 1667 字" in prompt
    assert "第三视角中文科技文章" in prompt
    assert "不使用“我 / 我们 / 咱们 / 本人”等第一人称自述" in prompt
    assert "English source text." in prompt
    assert "清洗后的中文内容。" in prompt


def test_validate_generated_article_returns_ok_when_within_budget() -> None:
    spec = resolve_article_spec("a" * 2000)
    article = (
        "第一段" + "甲" * 450 + "\n\n第二段" + "乙" * 460 + "\n\n第三段" + "丙" * 455
    )

    result = validate_generated_article(article, spec)

    assert result.ok is True
    assert result.section_count == 3
    assert result.total_chars >= spec.min_total_chars
    assert result.total_chars <= spec.max_total_chars
    assert len(result.issues) == 0


def test_validate_generated_article_reports_structure_and_length_issues() -> None:
    spec = resolve_article_spec("a" * 2000)
    article = "太短了。\n\n第二段也很短。"

    result = validate_generated_article(article, spec)

    assert result.ok is False
    assert result.section_count == 2
    assert any("Total chars" in issue for issue in result.issues)
    assert any("Section 1 chars" in issue for issue in result.issues)
    assert any("Section 2 chars" in issue for issue in result.issues)


def test_build_article_rewrite_prompt_includes_validation_issues() -> None:
    spec = resolve_article_spec("a" * 2000)
    validation = ArticleValidationResult(
        ok=False,
        total_chars=500,
        section_count=1,
        section_chars=(500,),
        issues=(
            "Total chars 500 outside allowed range 1200-1800.",
            "Section count 1 outside allowed range 2-3.",
        ),
    )

    prompt = build_article_rewrite_prompt(
        previous_article="原文很短。",
        spec=spec,
        validation=validation,
    )

    assert "当前不合规问题" in prompt
    assert "Total chars 500 outside allowed range 1200-1800." in prompt
    assert "Section count 1 outside allowed range 2-3." in prompt
    assert "原文很短。" in prompt


def test_build_article_rewrite_prompt_includes_style_issues() -> None:
    spec = resolve_article_spec("a" * 2000)
    validation = ArticleValidationResult(
        ok=True,
        total_chars=1500,
        section_count=3,
        section_chars=(500, 500, 500),
        issues=(),
    )

    prompt = build_article_rewrite_prompt(
        previous_article="我认为这件事很重要。",
        spec=spec,
        validation=validation,
        style_issues=(
            "文章仍包含第一人称自述，请改成第三视角叙述，不要使用我/我们/咱们作为叙述主语。",
        ),
    )

    assert "第三视角问题" in prompt
    assert "第一人称自述" in prompt
    assert "我认为这件事很重要。" in prompt
