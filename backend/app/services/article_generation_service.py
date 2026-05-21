from dataclasses import dataclass
import re


VISIBLE_TEXT_PATTERN = re.compile(r"\S")


@dataclass(frozen=True)
class ArticleSpec:
    source_length: int
    target_total_chars: int
    min_total_chars: int
    max_total_chars: int
    min_sections: int
    max_sections: int
    recommended_sections: int
    target_chars_per_section: int
    min_chars_per_section: int
    max_chars_per_section: int


@dataclass(frozen=True)
class ArticleValidationResult:
    ok: bool
    total_chars: int
    section_count: int
    section_chars: tuple[int, ...]
    issues: tuple[str, ...]


def resolve_article_spec(source_text: str, *, thin: bool = False) -> ArticleSpec:
    source_length = measure_source_text_length(source_text)

    if thin:
        return _build_thin_article_spec(source_length)

    if source_length <= 3000:
        return _build_article_spec(
            source_length=source_length,
            target_total_chars=1500,
            min_total_chars=1200,
            max_total_chars=1800,
            min_sections=2,
            max_sections=3,
            recommended_sections=3 if source_length >= 1800 else 2,
        )

    if source_length <= 10000:
        return _build_article_spec(
            source_length=source_length,
            target_total_chars=5000,
            min_total_chars=4200,
            max_total_chars=5800,
            min_sections=3,
            max_sections=4,
            recommended_sections=4 if source_length >= 6500 else 3,
        )

    return _build_article_spec(
        source_length=source_length,
        target_total_chars=8000,
        min_total_chars=7000,
        max_total_chars=9000,
        min_sections=5,
        max_sections=5,
        recommended_sections=5,
    )


def measure_source_text_length(value: str) -> int:
    return len(VISIBLE_TEXT_PATTERN.findall(value or ""))


def build_article_generation_prompt(
    *,
    source_text: str,
    cleaned_translation_zh: str,
    spec: ArticleSpec,
) -> str:
    source = (source_text or "").strip()
    cleaned = (cleaned_translation_zh or "").strip()

    return (
        "你是一位科技深度写作编辑助手。请基于提供的文本生成第三视角中文科技文章。\n\n"
        "硬性要求（必须满足）：\n"
        f"1) 总字数目标：{spec.target_total_chars} 字，允许范围 {spec.min_total_chars}-{spec.max_total_chars}。\n"
        f"2) 段落数量：{spec.min_sections}-{spec.max_sections} 段，推荐 {spec.recommended_sections} 段。\n"
        f"3) 每段字数：建议约 {spec.target_chars_per_section} 字，允许范围 {spec.min_chars_per_section}-{spec.max_chars_per_section}。\n"
        "4) 禁止凭空补充事实；若原文信息不足，请明确说明而不要编造。\n"
        "5) 默认使用第三视角叙述，除原文直接引用外，不使用“我 / 我们 / 咱们 / 本人”等第一人称自述。\n"
        "6) 删除口水词、舞台提示、广告语，保持正式科技写作风格。\n"
        "7) 只输出正文，不要输出解释和分析过程。\n\n"
        "结构要求：\n"
        "- 以段落为单位输出，段落之间用空行分隔。\n"
        "- 每段围绕一个明确子主题，逻辑递进。\n\n"
        "可用素材（英文转录）：\n"
        f"{source}\n\n"
        "可用素材（清洗后的中文）：\n"
        f"{cleaned}\n"
    )


def validate_generated_article(
    article_text: str, spec: ArticleSpec
) -> ArticleValidationResult:
    article = (article_text or "").strip()
    if not article:
        return ArticleValidationResult(
            ok=False,
            total_chars=0,
            section_count=0,
            section_chars=(),
            issues=("Article is empty.",),
        )

    sections = _split_article_sections(article)
    section_chars = tuple(measure_source_text_length(section) for section in sections)
    total_chars = sum(section_chars)

    issues: list[str] = []

    if total_chars < spec.min_total_chars or total_chars > spec.max_total_chars:
        issues.append(
            f"Total chars {total_chars} outside allowed range {spec.min_total_chars}-{spec.max_total_chars}."
        )

    if len(sections) < spec.min_sections or len(sections) > spec.max_sections:
        issues.append(
            f"Section count {len(sections)} outside allowed range {spec.min_sections}-{spec.max_sections}."
        )

    for index, chars in enumerate(section_chars, start=1):
        if chars < spec.min_chars_per_section or chars > spec.max_chars_per_section:
            issues.append(
                f"Section {index} chars {chars} outside allowed range {spec.min_chars_per_section}-{spec.max_chars_per_section}."
            )

    return ArticleValidationResult(
        ok=not issues,
        total_chars=total_chars,
        section_count=len(sections),
        section_chars=section_chars,
        issues=tuple(issues),
    )


def build_article_rewrite_prompt(
    *,
    previous_article: str,
    spec: ArticleSpec,
    validation: ArticleValidationResult,
    style_issues: tuple[str, ...] = (),
) -> str:
    problems = (
        "\n".join(f"- {issue}" for issue in validation.issues)
        if validation.issues
        else "- 无长度或结构问题"
    )
    style_problem_lines = "\n".join(f"- {issue}" for issue in style_issues)
    style_problem_block = (
        f"\n\n当前风格问题：\n{style_problem_lines}" if style_problem_lines else ""
    )
    return (
        "请重写下面的科技文章，只修正结构、长度和第三视角问题，不要添加原文没有的新事实。\n\n"
        "当前不合规问题：\n"
        f"{problems}{style_problem_block}\n\n"
        "重写目标：\n"
        f"- 总字数 {spec.min_total_chars}-{spec.max_total_chars}（目标 {spec.target_total_chars}）\n"
        f"- 段落数 {spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）\n"
        f"- 每段 {spec.min_chars_per_section}-{spec.max_chars_per_section} 字（建议 {spec.target_chars_per_section}）\n\n"
        "请保持第三视角叙述，除原文直接引用外，不要再使用我/我们/咱们/本人作为叙述主语。\n"
        "请仅输出重写后的正文（段落间空行分隔）。\n\n"
        "原输出：\n"
        f"{previous_article.strip()}\n"
    )


def _split_article_sections(article_text: str) -> list[str]:
    normalized = article_text.replace("\r\n", "\n").replace("\r", "\n")
    chunks = [
        chunk.strip() for chunk in re.split(r"\n\s*\n", normalized) if chunk.strip()
    ]
    if chunks:
        return chunks
    return [line.strip() for line in normalized.split("\n") if line.strip()]


def _build_article_spec(
    *,
    source_length: int,
    target_total_chars: int,
    min_total_chars: int,
    max_total_chars: int,
    min_sections: int,
    max_sections: int,
    recommended_sections: int,
) -> ArticleSpec:
    target_chars_per_section = max(1, round(target_total_chars / recommended_sections))
    min_chars_per_section = max(1, round(min_total_chars / max_sections))
    max_chars_per_section = max(1, round(max_total_chars / min_sections))

    return ArticleSpec(
        source_length=source_length,
        target_total_chars=target_total_chars,
        min_total_chars=min_total_chars,
        max_total_chars=max_total_chars,
        min_sections=min_sections,
        max_sections=max_sections,
        recommended_sections=recommended_sections,
        target_chars_per_section=target_chars_per_section,
        min_chars_per_section=min_chars_per_section,
        max_chars_per_section=max_chars_per_section,
    )


def _build_thin_article_spec(source_length: int) -> ArticleSpec:
    target_total_chars = max(1, round(source_length * 0.5))
    min_total_chars = max(1, round(source_length * 0.4))
    max_total_chars = max(min_total_chars, round(source_length * 0.6))

    if source_length < 1800:
        min_sections = 2
        max_sections = 3
        recommended_sections = 2
    elif source_length <= 6500:
        min_sections = 3
        max_sections = 4
        recommended_sections = 3
    else:
        min_sections = 4
        max_sections = 5
        recommended_sections = 4 if source_length <= 12000 else 5

    return _build_article_spec(
        source_length=source_length,
        target_total_chars=target_total_chars,
        min_total_chars=min_total_chars,
        max_total_chars=max_total_chars,
        min_sections=min_sections,
        max_sections=max_sections,
        recommended_sections=recommended_sections,
    )
