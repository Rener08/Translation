"""Pipeline strategies for WriterAgent."""

from dataclasses import dataclass
import re
from typing import Literal, Protocol

from app.services.article_generation_service import (
    ArticleSpec,
    ArticleValidationResult,
    build_article_rewrite_prompt,
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
    analyze_detail_coverage_enhanced,
    build_detail_patch_prompt,
    build_detail_patch_ledger,
    format_detail_coverage_issues,
)
from app.services.detail_ledger_refiner import refine_detail_ledger_with_llm
from app.services.prompt_validation import validate_rewrite_prompt
from app.services.writer_versions import (
    ARTICLE_LONGFORM_PROMPT_VERSION,
    FULL_PROMPT_PROMPT_VERSION,
    SPEECH_VERBATIM_PROMPT_VERSION,
    WRITER_POLICY_VERSION,
    new_writer_trace_id,
)


ARTICLE_LONGFORM_FIRST_PERSON_MARKERS: tuple[str, ...] = (
    "我想", "我会", "我认为", "我觉得", "我来", "我要", "我先", "我正在",
    "我们", "我们先", "我们会", "我们认为", "我们觉得", "咱们", "本人",
)


@dataclass(frozen=True)
class MaterialPackage:
    source_text: str
    source_language: str = "en"
    translation_language: str = "zh-CN"


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
    ) -> WriterRunReport: ...


class FullPromptPipeline:
    """Pipeline for user-provided full prompts containing {{transcript}}."""

    def execute(
        self,
        *,
        material: MaterialPackage,
        rewrite_focus: str | None,
        rewrite_config: dict[str, object] | None,
    ) -> WriterRunReport:
        trace_id = new_writer_trace_id()
        focus = (rewrite_focus or "").strip()
        result = rewrite_content(
            source_text=material.source_text,
            rewrite_focus=focus,
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
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

    def __init__(self, llm_call_fn=None):
        self._llm_call_fn = llm_call_fn

    def execute(
        self,
        *,
        material: MaterialPackage,
        rewrite_focus: str | None,
        rewrite_config: dict[str, object] | None,
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

        direct_result = rewrite_content(
            source_text=normalized_source,
            rewrite_focus=rewrite_focus,
            rewrite_style="speech_verbatim",
            rewrite_config=rewrite_config,
            detail_ledger=detail_ledger.to_prompt_text(),
        )

        coverage = analyze_detail_coverage_enhanced(detail_ledger, direct_result.rewritten_text)
        final_result = direct_result
        patched_once = False

        if coverage.missing_items:
            patched_once = True
            patch_result = rewrite_content(
                source_text=normalized_source,
                rewrite_focus=build_detail_patch_prompt(coverage.missing_items),
                rewrite_style="speech_verbatim",
                rewrite_config=rewrite_config,
                detail_ledger=build_detail_patch_ledger(coverage.missing_items),
            )
            final_result = patch_result
            coverage = analyze_detail_coverage_enhanced(
                detail_ledger, final_result.rewritten_text,
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


class ArticleLongformPipeline:
    """Pipeline for article_longform style: outline → draft → validate → revise."""

    def execute(
        self,
        *,
        material: MaterialPackage,
        rewrite_focus: str | None,
        rewrite_config: dict[str, object] | None,
    ) -> WriterRunReport:
        trace_id = new_writer_trace_id()
        normalized_source = material.source_text
        spec = resolve_article_spec(normalized_source)

        planning_result = rewrite_content(
            source_text=normalized_source,
            rewrite_focus=_build_outline_prompt(spec=spec, rewrite_focus=rewrite_focus),
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
        )
        outline = _extract_outline(planning_result.rewritten_text)

        draft_result = rewrite_content(
            source_text=normalized_source,
            rewrite_focus=_build_draft_prompt(
                spec=spec, rewrite_focus=rewrite_focus, outline=outline,
            ),
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
        )
        validation = validate_generated_article(draft_result.rewritten_text, spec)
        style_issues = _detect_article_longform_style_issues(draft_result.rewritten_text)
        final_result = draft_result
        revised_once = False

        if not validation.ok or style_issues:
            revised_once = True
            revise_prompt = build_article_rewrite_prompt(
                previous_article=draft_result.rewritten_text,
                spec=spec,
                validation=validation,
                style_issues=style_issues,
            )
            final_result = rewrite_content(
                source_text=normalized_source,
                rewrite_focus=revise_prompt,
                rewrite_style="article_longform",
                rewrite_config=rewrite_config,
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


def _detect_article_longform_style_issues(text: str) -> tuple[str, ...]:
    normalized_text = _strip_quoted_spans(text)
    if not normalized_text.strip():
        return ()
    if any(marker in normalized_text for marker in ARTICLE_LONGFORM_FIRST_PERSON_MARKERS):
        return (
            "文章仍包含第一人称自述，请改成第三视角叙述，不要使用我/我们/咱们作为叙述主语。",
        )
    return ()


def _build_outline_prompt(*, spec: ArticleSpec, rewrite_focus: str | None) -> str:
    focus_text = (rewrite_focus or "科技深度中文文章").strip()
    return (
        "请基于原始素材先给出写作规划。\n\n"
        f"写作目标：{focus_text}\n"
        f"目标字数：{spec.target_total_chars}（允许 {spec.min_total_chars}-{spec.max_total_chars}）\n"
        f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）\n\n"
        "只输出一个简短大纲，每行一个要点。"
    )


def _build_draft_prompt(
    *, spec: ArticleSpec, rewrite_focus: str | None, outline: tuple[str, ...],
) -> str:
    focus_text = (rewrite_focus or "保留原意并提升中文可读性").strip()
    outline_text = "\n".join(f"- {line}" for line in outline) if outline else "- 按素材主线组织段落"
    return (
        "请按以下要求输出中文文章初稿。\n\n"
        f"写作目标：{focus_text}\n"
        f"总字数：{spec.min_total_chars}-{spec.max_total_chars}（目标 {spec.target_total_chars}）\n"
        f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）\n"
        f"每段字数：{spec.min_chars_per_section}-{spec.max_chars_per_section}（建议 {spec.target_chars_per_section}）\n\n"
        "大纲：\n"
        f"{outline_text}\n\n"
        "要求：不编造事实，段落之间空行，只输出正文。"
    )


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
