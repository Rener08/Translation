"""Pipeline strategies for WriterAgent."""

from dataclasses import dataclass
import re
from typing import Literal, Protocol

from app.services.article_generation_service import (
    ArticleSpec,
    ArticleValidationResult,
    resolve_article_spec,
    validate_generated_article,
)
from app.services.content_rewrite_service import (
    ContentRewriteInputError,
    ContentRewriteResult,
    RewriteStyle,
    rewrite_content,
)
from app.services.detail_ledger import (
    DetailLedger,
    build_detail_ledger,
    build_longform_topic_ledger,
    merge_detail_ledgers,
    analyze_detail_coverage_enhanced,
    build_detail_patch_prompt,
    build_detail_patch_ledger,
    format_detail_coverage_issues,
)
from app.services.detail_ledger_refiner import refine_detail_ledger_with_llm
from app.services.prompt_validation import validate_rewrite_prompt
from app.services.quality_check_service import (
    QualityReport,
    build_revision_prompt,
    check_article_quality,
)
from app.services.skill_config_service import SkillConfig
from app.services.writer_versions import (
    ARTICLE_LONGFORM_PROMPT_VERSION,
    FULL_PROMPT_PROMPT_VERSION,
    SPEECH_VERBATIM_PROMPT_VERSION,
    WRITER_POLICY_VERSION,
    new_writer_trace_id,
)


@dataclass(frozen=True)
class MaterialPackage:
    source_text: str
    reference_text: str = ""
    source_language: str = "en"
    translation_language: str = "zh-CN"

    def article_input_text(self) -> str:
        source = (self.source_text or "").strip()
        reference = (self.reference_text or "").strip()
        if not reference or reference == source:
            return source
        return (
            f"{source}\n\n【原始英文素材】\n{reference}"
        )


@dataclass(frozen=True)
class ArticleDraft:
    text: str
    outline: tuple[str, ...]
    spec: ArticleSpec
    validation: ArticleValidationResult
    revised_once: bool


@dataclass(frozen=True)
class WriterRunReport:
    rewritten_text: str
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    model: str
    quality_issues: tuple[str, ...]
    material: MaterialPackage
    draft: ArticleDraft
    rewrite_style: RewriteStyle
    detail_coverage_issues: tuple[str, ...] = ()
    writer_trace_id: str = ""
    writer_policy_version: str = ""
    writer_prompt_version: str = ""


class PipelineStrategy(Protocol):
    def execute(
        self,
        *,
        material: MaterialPackage,
        rewrite_focus: str | None,
        rewrite_config: dict[str, object] | None,
        cancellation_checker=None,
    ) -> WriterRunReport: ...


class FullPromptPipeline:
    """Pipeline for user-provided full prompts containing {{transcript}}."""

    def execute(
        self,
        *,
        material: MaterialPackage,
        rewrite_focus: str | None,
        rewrite_config: dict[str, object] | None,
        cancellation_checker=None,
    ) -> WriterRunReport:
        trace_id = new_writer_trace_id()
        focus = (rewrite_focus or "").strip()
        if callable(cancellation_checker) and cancellation_checker():
            raise ContentRewriteInputError("Rewrite cancelled.")
        result = rewrite_content(
            source_text=material.source_text,
            rewrite_focus=focus,
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
            cancellation_checker=cancellation_checker,
        )
        spec = resolve_article_spec(material.source_text)
        draft_validation = validate_generated_article(result.rewritten_text, spec)
        return WriterRunReport(
            rewritten_text=result.rewritten_text,
            provider=result.provider,
            model=result.model,
            quality_issues=tuple(result.quality_issues),
            material=material,
            draft=ArticleDraft(
                text=result.rewritten_text,
                outline=("full_prompt_passthrough",),
                spec=spec,
                validation=draft_validation,
                revised_once=False,
            ),
            rewrite_style="article_longform",
            writer_trace_id=trace_id,
            writer_policy_version=WRITER_POLICY_VERSION,
            writer_prompt_version=FULL_PROMPT_PROMPT_VERSION,
        )


class SpeechVerbatimPipeline:
    """Pipeline for speech_verbatim style: DetailLedger → draft → coverage → patch."""

    def __init__(self, skill_config: SkillConfig, llm_call_fn=None):
        self._skill_config = skill_config
        self._llm_call_fn = llm_call_fn

    def execute(
        self,
        *,
        material: MaterialPackage,
        rewrite_focus: str | None,
        rewrite_config: dict[str, object] | None,
        cancellation_checker=None,
    ) -> WriterRunReport:
        trace_id = new_writer_trace_id()
        normalized_source = material.source_text
        coarse_ledger = build_detail_ledger(normalized_source)

        if self._llm_call_fn and coarse_ledger.items:
            refined = refine_detail_ledger_with_llm(
                source_text=normalized_source,
                coarse_ledger=coarse_ledger,
                llm_call_fn=self._llm_call_fn,
            )
            detail_ledger = refined.to_detail_ledger()
        else:
            detail_ledger = coarse_ledger

        if callable(cancellation_checker) and cancellation_checker():
            raise ContentRewriteInputError("Rewrite cancelled.")
        direct_result = rewrite_content(
            source_text=normalized_source,
            rewrite_focus=rewrite_focus,
            rewrite_style="speech_verbatim",
            rewrite_config=rewrite_config,
            detail_ledger=detail_ledger.to_prompt_text(),
            cancellation_checker=cancellation_checker,
        )

        coverage = analyze_detail_coverage_enhanced(detail_ledger, direct_result.rewritten_text)
        final_result = direct_result
        patched_once = False

        if coverage.missing_items and not _is_english_text(normalized_source):
            patched_once = True
            if callable(cancellation_checker) and cancellation_checker():
                raise ContentRewriteInputError("Rewrite cancelled.")
            patch_result = rewrite_content(
                source_text=direct_result.rewritten_text,
                rewrite_focus=build_detail_patch_prompt(
                    coverage.missing_items,
                    original_source=normalized_source,
                    previous_draft=direct_result.rewritten_text,
                ),
                rewrite_style="speech_verbatim",
                rewrite_config=rewrite_config,
                detail_ledger=build_detail_patch_ledger(coverage.missing_items),
                cancellation_checker=cancellation_checker,
            )
            if self._patch_output_is_safe(direct_result.rewritten_text, patch_result.rewritten_text):
                final_result = patch_result
                coverage = analyze_detail_coverage_enhanced(
                    detail_ledger, final_result.rewritten_text,
                )

        # Quality check after coverage patch
        quality_report = check_article_quality(
            final_result.rewritten_text,
            normalized_source,
            self._skill_config,
            detail_ledger,
        )
        if not quality_report.passed:
            revise_prompt = build_revision_prompt(quality_report)
            if callable(cancellation_checker) and cancellation_checker():
                raise ContentRewriteInputError("Rewrite cancelled.")
            final_result = rewrite_content(
                source_text=normalized_source,
                rewrite_focus=revise_prompt,
                rewrite_style="speech_verbatim",
                rewrite_config=rewrite_config,
                detail_ledger=detail_ledger.to_prompt_text(),
                skill_config=self._skill_config,
                cancellation_checker=cancellation_checker,
            )

        spec = resolve_article_spec(normalized_source)
        validation = _build_soft_validation(final_result.rewritten_text)
        return WriterRunReport(
            rewritten_text=final_result.rewritten_text,
            provider=final_result.provider,
            model=final_result.model,
            quality_issues=tuple(final_result.quality_issues),
            material=material,
            draft=ArticleDraft(
                text=final_result.rewritten_text,
                outline=("speech_verbatim",),
                spec=spec,
                validation=validation,
                revised_once=patched_once,
            ),
            rewrite_style="speech_verbatim",
            detail_coverage_issues=format_detail_coverage_issues(coverage),
            writer_trace_id=trace_id,
            writer_policy_version=WRITER_POLICY_VERSION,
            writer_prompt_version=SPEECH_VERBATIM_PROMPT_VERSION,
        )

    @staticmethod
    def _paragraph_count(text: str) -> int:
        normalized_text = (text or "").strip()
        if not normalized_text:
            return 0
        paragraphs = [
            block.strip()
            for block in re.split(r"\n\s*\n+", normalized_text)
            if block.strip()
        ]
        return len(paragraphs) if paragraphs else 1

    @classmethod
    def _patch_output_is_safe(cls, previous: str, patched: str) -> bool:
        previous_text = (previous or "").strip()
        patched_text = (patched or "").strip()
        if not previous_text or not patched_text:
            return bool(patched_text)
        if len(patched_text) < len(previous_text) * 0.7:
            return False
        previous_paragraphs = cls._paragraph_count(previous_text)
        patched_paragraphs = cls._paragraph_count(patched_text)
        if patched_paragraphs < max(1, previous_paragraphs // 2):
            return False
        return True


class ArticleLongformPipeline:
    """Pipeline for article_longform style: outline → draft → validate → revise."""

    def __init__(self, skill_config: SkillConfig):
        self._skill_config = skill_config

    def execute(
        self,
        *,
        material: MaterialPackage,
        rewrite_focus: str | None,
        rewrite_config: dict[str, object] | None,
        cancellation_checker=None,
    ) -> WriterRunReport:
        trace_id = new_writer_trace_id()
        normalized_source = material.source_text
        article_source = material.article_input_text()
        spec = resolve_article_spec(normalized_source)
        detail_ledger = build_detail_ledger(article_source)
        topic_ledger = build_longform_topic_ledger(article_source)
        longform_ledger = merge_detail_ledgers(detail_ledger, topic_ledger)

        if callable(cancellation_checker) and cancellation_checker():
            raise ContentRewriteInputError("Rewrite cancelled.")
        planning_result = rewrite_content(
            source_text=article_source,
            rewrite_focus=_build_outline_prompt(
                spec=spec, rewrite_focus=rewrite_focus,
                detail_ledger_text=longform_ledger.to_prompt_text(),
            ),
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
            skill_config=self._skill_config,
            cancellation_checker=cancellation_checker,
        )
        outline = _extract_outline(planning_result.rewritten_text)

        if callable(cancellation_checker) and cancellation_checker():
            raise ContentRewriteInputError("Rewrite cancelled.")
        draft_result = rewrite_content(
            source_text=article_source,
            rewrite_focus=_build_draft_prompt(
                spec=spec, rewrite_focus=rewrite_focus, outline=outline,
                detail_ledger_text=longform_ledger.to_prompt_text(),
            ),
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
            skill_config=self._skill_config,
            cancellation_checker=cancellation_checker,
        )
        validation = validate_generated_article(draft_result.rewritten_text, spec)
        quality_report = check_article_quality(
            draft_result.rewritten_text,
            normalized_source,
            self._skill_config,
            longform_ledger,
        )
        final_result = draft_result
        revised_once = False

        if not quality_report.passed:
            revised_once = True
            revise_prompt = _build_article_longform_revision_prompt(
                previous_article=draft_result.rewritten_text,
                spec=spec,
                validation=validation,
                quality_report=quality_report,
            )
            if callable(cancellation_checker) and cancellation_checker():
                raise ContentRewriteInputError("Rewrite cancelled.")
            final_result = rewrite_content(
                source_text=draft_result.rewritten_text,
                rewrite_focus=revise_prompt,
                rewrite_style="article_longform",
                rewrite_config=rewrite_config,
                skill_config=self._skill_config,
                cancellation_checker=cancellation_checker,
            )
            validation = validate_generated_article(final_result.rewritten_text, spec)
            post_quality_report = check_article_quality(
                final_result.rewritten_text,
                normalized_source,
                self._skill_config,
                longform_ledger,
            )
            if not post_quality_report.passed:
                second_revise_prompt = _build_article_longform_revision_prompt(
                    previous_article=final_result.rewritten_text,
                    spec=spec,
                    validation=validation,
                    quality_report=post_quality_report,
                )
                if callable(cancellation_checker) and cancellation_checker():
                    raise ContentRewriteInputError("Rewrite cancelled.")
                final_result = rewrite_content(
                    source_text=final_result.rewritten_text,
                    rewrite_focus=second_revise_prompt,
                    rewrite_style="article_longform",
                    rewrite_config=rewrite_config,
                    skill_config=self._skill_config,
                    cancellation_checker=cancellation_checker,
                )
                validation = validate_generated_article(final_result.rewritten_text, spec)

        return WriterRunReport(
            rewritten_text=final_result.rewritten_text,
            provider=final_result.provider,
            model=final_result.model,
            quality_issues=tuple(final_result.quality_issues),
            material=material,
            draft=ArticleDraft(
                text=final_result.rewritten_text,
                outline=outline,
                spec=spec,
                validation=validation,
                revised_once=revised_once,
            ),
            rewrite_style="article_longform",
            writer_trace_id=trace_id,
            writer_policy_version=WRITER_POLICY_VERSION,
            writer_prompt_version=ARTICLE_LONGFORM_PROMPT_VERSION,
        )


# --- helpers ---

def _build_soft_validation(text: str) -> ArticleValidationResult:
    normalized_text = (text or "").strip()
    if not normalized_text:
        return ArticleValidationResult(
            ok=False, total_chars=0, section_count=0,
            section_chars=(), issues=("Article is empty.",),
        )

    sections = tuple(
        s.strip() for s in normalized_text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
        if s.strip()
    )
    if not sections:
        sections = (normalized_text,)

    section_chars = tuple(len(s) for s in sections)
    return ArticleValidationResult(
        ok=True, total_chars=sum(section_chars),
        section_count=len(sections), section_chars=section_chars, issues=(),
    )


def _validate_style_constraints(text: str, skill_config: SkillConfig) -> tuple[str, ...]:
    normalized_text = _strip_quoted_spans(text)
    if not normalized_text.strip():
        return ()
    issues: list[str] = []
    for c in skill_config.constraints:
        if c.constraint_type == "forbidden_word" and c.enabled and c.pattern in normalized_text:
            issues.append(f"发现禁用词「{c.pattern}」，{c.fix_hint or '请替换'}")
    if skill_config.perspective == "third_person":
        for marker in skill_config.perspective_markers:
            if marker in normalized_text:
                fix = next(
                    (c.fix_hint for c in skill_config.constraints
                     if c.constraint_type == "perspective_marker" and c.pattern == marker and c.fix_hint),
                    "请改成第三视角叙述",
                )
                issues.append(f"发现第一人称标记「{marker}」，{fix}")
                break
    return tuple(issues)


def _build_comprehensive_revise_prompt(
    *, previous_article: str, spec: ArticleSpec, validation: ArticleValidationResult,
    style_issues: tuple[str, ...], missing_details: tuple,
) -> str:
    parts = ["请修订以下问题，只改有问题的部分，保留其余内容。", ""]
    if not validation.ok:
        for issue in validation.issues:
            parts.append(f"- 结构问题：{issue}")
    for issue in style_issues:
        parts.append(f"- 风格问题：{issue}")
    for item in missing_details[:6]:
        parts.append(f"- 缺失细节：{item.kind} {item.text}")
    parts.extend(["", "要求：只输出修订后的正文，不要解释。"])
    return "\n".join(parts)


def _build_article_longform_revision_prompt(
    *,
    previous_article: str,
    spec: ArticleSpec,
    validation: ArticleValidationResult,
    quality_report: QualityReport,
) -> str:
    style_issues = tuple(issue.message for issue in quality_report.issues)
    prompt = _build_comprehensive_revise_prompt(
        previous_article=previous_article,
        spec=spec,
        validation=validation,
        style_issues=style_issues,
        missing_details=(),
    )
    return (
        prompt
        + "\n\n"
        "额外要求：\n"
        "- 直接把全文重写成第三视角文章，不要保留问答式、逐字稿式或时间块同步式表达。\n"
        "- 如果原文是访谈或播客，把对话内容融合成连续叙事，而不是拆成主持人/嘉宾轮流发言。\n"
        "- 除原文直接引语外，不要再出现我/我们/咱们/本人作为叙述主语。\n"
        "- 如果仍然像翻译稿，请重新组织段落结构，而不是只改几个句子。"
    )


def _build_outline_prompt(
    *, spec: ArticleSpec, rewrite_focus: str | None, detail_ledger_text: str | None = None,
) -> str:
    focus_text = (rewrite_focus or "科技深度中文文章").strip()
    prompt = (
        "请基于原始素材先给出写作规划。\n\n"
        f"写作目标：{focus_text}\n"
        f"目标字数：{spec.target_total_chars}（允许 {spec.min_total_chars}-{spec.max_total_chars}）\n"
        f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）\n\n"
        "只输出一个简短大纲，每行一个要点。"
    )
    if detail_ledger_text:
        prompt += f"\n\n必须保留的关键细节：\n{detail_ledger_text}"
    return prompt


def _build_draft_prompt(
    *, spec: ArticleSpec, rewrite_focus: str | None, outline: tuple[str, ...],
    detail_ledger_text: str | None = None,
) -> str:
    focus_text = (rewrite_focus or "保留原意并提升中文可读性").strip()
    outline_text = "\n".join(f"- {line}" for line in outline) if outline else "- 按素材主线组织段落"
    prompt = (
        "请按以下要求输出中文文章初稿。\n\n"
        f"写作目标：{focus_text}\n"
        f"总字数：{spec.min_total_chars}-{spec.max_total_chars}（目标 {spec.target_total_chars}）\n"
        f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）\n"
        f"每段字数：{spec.min_chars_per_section}-{spec.max_chars_per_section}（建议 {spec.target_chars_per_section}）\n\n"
        "大纲：\n"
        f"{outline_text}\n\n"
        "要求：不编造事实，段落之间空行，只输出正文。"
    )
    if detail_ledger_text:
        prompt += f"\n\n必须保留的关键细节：\n{detail_ledger_text}"
    return prompt


def _extract_outline(text: str) -> tuple[str, ...]:
    lines = [line.strip(" -\t") for line in (text or "").splitlines()]
    cleaned = tuple(line for line in lines if line)
    if cleaned:
        return cleaned[:8]
    return ("按素材主线组织段落",)


def _strip_quoted_spans(text: str) -> str:
    normalized = text or ""
    normalized = re.sub(r'"[^"]*"', " ", normalized)
    normalized = re.sub(r"“[^”]*”", " ", normalized)
    normalized = re.sub(r"『[^』]*』", " ", normalized)
    normalized = re.sub(r"「[^」]*」", " ", normalized)
    return normalized


def _is_english_text(text: str) -> bool:
    if not text:
        return False
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return ascii_count / len(text) > 0.8
