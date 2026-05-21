"""Pipeline strategies for WriterAgent."""

from dataclasses import dataclass, field
import time
import re
from typing import Literal, Protocol

from app.services.article_generation_service import (
    ArticleSpec,
    ArticleValidationResult,
    measure_source_text_length,
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
    QualityIssue,
    QualityReport,
    build_revision_prompt,
    check_article_quality,
)
from app.services.skill_config_service import SkillConfig
from app.services.rewrite_stage_router import (
    THIN_LONGFORM_PROMPT_PROFILE,
)
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
    loop_state_snapshot: dict[str, object] = field(default_factory=dict)
    last_action: str = ""
    budget_usage: dict[str, object] = field(default_factory=dict)
    failure_stage: str | None = None
    next_recommended_action: str | None = None
    covered_facts_summary: tuple[str, ...] = ()


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
            precomputed_detail_coverage_issues=format_detail_coverage_issues(coverage),
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

        spec = resolve_article_spec(normalized_source, thin=True)
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

    def _build_length_guidance(self, source_text: str) -> str | None:
        output = getattr(self._skill_config, "output", None)
        ratio_min = getattr(output, "source_length_ratio_min", None)
        ratio_max = getattr(output, "source_length_ratio_max", None)
        if ratio_min is None and ratio_max is None:
            return None

        source_length = measure_source_text_length(source_text)
        if source_length <= 0:
            return None

        min_ratio = ratio_min if ratio_min is not None else 0.0
        max_ratio = ratio_max if ratio_max is not None else 1.0
        if max_ratio < min_ratio:
            min_ratio, max_ratio = max_ratio, min_ratio

        min_chars = max(1, round(source_length * min_ratio))
        max_chars = max(min_chars, round(source_length * max_ratio))
        suggested_sections = 5 if source_length >= 10000 else 4 if source_length >= 6000 else 3
        suggested_chars_per_section = max(1, round(((min_chars + max_chars) / 2) / suggested_sections))
        return (
            f"篇幅建议：总长度尽量控制在原文的 {int(ratio_min * 100)}%-{int(ratio_max * 100)}% "
            f"之间，当前原文约 {source_length} 字，建议输出约 {min_chars}-{max_chars} 字。"
            f"建议分 {suggested_sections} 段左右，每段约 {suggested_chars_per_section} 字。"
        )


class ArticleLongformPipeline:
    """Pipeline for article_longform style: outline → draft → validate → revise."""

    _MAX_REVISION_ROUNDS = 6

    def __init__(self, skill_config: SkillConfig):
        self._skill_config = skill_config

    def _resolve_length_bounds(self, source_text: str) -> tuple[int, int, int] | None:
        output = getattr(self._skill_config, "output", None)
        ratio_min = getattr(output, "source_length_ratio_min", None)
        ratio_max = getattr(output, "source_length_ratio_max", None)
        if ratio_min is None and ratio_max is None:
            return None

        source_length = measure_source_text_length(source_text)
        if source_length <= 0:
            return None

        min_ratio = ratio_min if ratio_min is not None else 0.0
        max_ratio = ratio_max if ratio_max is not None else 1.0
        if max_ratio < min_ratio:
            min_ratio, max_ratio = max_ratio, min_ratio

        min_chars = max(1, round(source_length * min_ratio))
        max_chars = max(min_chars, round(source_length * max_ratio))
        return source_length, min_chars, max_chars

    def _build_length_guidance(self, source_text: str) -> str | None:
        bounds = self._resolve_length_bounds(source_text)
        if bounds is None:
            return None
        source_length, min_chars, max_chars = bounds
        output = getattr(self._skill_config, "output", None)
        ratio_min = getattr(output, "source_length_ratio_min", 0.0) or 0.0
        ratio_max = getattr(output, "source_length_ratio_max", 1.0) or 1.0
        if ratio_max < ratio_min:
            ratio_min, ratio_max = ratio_max, ratio_min
        suggested_sections = 5 if source_length >= 10000 else 4 if source_length >= 6000 else 3
        suggested_chars_per_section = max(1, round(((min_chars + max_chars) / 2) / suggested_sections))
        return (
            f"篇幅建议：总长度尽量控制在原文的 {int(ratio_min * 100)}%-{int(ratio_max * 100)}% "
            f"之间，当前原文约 {source_length} 字，建议输出约 {min_chars}-{max_chars} 字。"
            f"建议分 {suggested_sections} 段左右，每段约 {suggested_chars_per_section} 字。"
        )

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
        spec = resolve_article_spec(normalized_source, thin=True)
        length_bounds = self._resolve_length_bounds(normalized_source)
        length_guidance = self._build_length_guidance(normalized_source)
        detail_ledger = build_detail_ledger(article_source)
        topic_ledger = build_longform_topic_ledger(article_source)
        longform_ledger = merge_detail_ledgers(detail_ledger, topic_ledger)
        stage_timings_ms: dict[str, int] = {}
        stage_models: dict[str, str] = {}
        stage_call_count = 0
        outline_used = False
        revision_used = False
        outline = ("按素材主线组织段落",)

        if callable(cancellation_checker) and cancellation_checker():
            raise ContentRewriteInputError("Rewrite cancelled.")
        if _should_run_thin_outline(normalized_source, longform_ledger):
            outline_started_at = time.monotonic()
            planning_result = rewrite_content(
                source_text=article_source,
                rewrite_focus=_build_outline_prompt(
                    spec=spec,
                    rewrite_focus=rewrite_focus,
                    length_guidance=length_guidance,
                    soft_length_mode=bool(length_guidance),
                    detail_ledger_text=longform_ledger.to_prompt_text(),
                ),
                rewrite_style="article_longform",
                rewrite_config=rewrite_config,
                skill_config=self._skill_config,
                cancellation_checker=cancellation_checker,
                rewrite_stage="outline",
                prompt_profile=THIN_LONGFORM_PROMPT_PROFILE,
            )
            stage_timings_ms["outline"] = int((time.monotonic() - outline_started_at) * 1000)
            stage_models["outline"] = planning_result.model
            stage_call_count += 1
            outline_used = True
            outline = _extract_outline(planning_result.rewritten_text)

        if callable(cancellation_checker) and cancellation_checker():
            raise ContentRewriteInputError("Rewrite cancelled.")
        draft_started_at = time.monotonic()
        draft_result = rewrite_content(
            source_text=article_source,
            rewrite_focus=_build_draft_prompt(
                spec=spec,
                rewrite_focus=rewrite_focus,
                outline=outline,
                length_guidance=length_guidance,
                soft_length_mode=bool(length_guidance),
                detail_ledger_text=longform_ledger.to_prompt_text(),
            ),
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
            skill_config=self._skill_config,
            cancellation_checker=cancellation_checker,
            rewrite_stage="draft",
            prompt_profile=THIN_LONGFORM_PROMPT_PROFILE,
        )
        stage_timings_ms["draft"] = int((time.monotonic() - draft_started_at) * 1000)
        stage_models["draft"] = draft_result.model
        stage_call_count += 1

        validation = validate_generated_article(draft_result.rewritten_text, spec)
        draft_coverage = analyze_detail_coverage_enhanced(longform_ledger, draft_result.rewritten_text)
        draft_coverage_issues = format_detail_coverage_issues(draft_coverage)
        style_issues = _validate_style_constraints(draft_result.rewritten_text, self._skill_config)
        soft_length_issues = _collect_length_ratio_issues(
            text=draft_result.rewritten_text,
            source_text=normalized_source,
            skill_config=self._skill_config,
        )

        final_result = draft_result
        revision_stage = "patch"
        revision_prompt = ""
        if (
            not validation.ok
            or draft_coverage_issues
            or style_issues
            or soft_length_issues
        ):
            revision_stage, revision_prompt = _build_thin_revision_prompt(
                previous_article=final_result.rewritten_text,
                spec=spec,
                validation=validation,
                detail_coverage_issues=draft_coverage_issues,
                style_issues=style_issues,
                soft_length_issues=soft_length_issues,
                length_guidance=length_guidance,
                source_length_bounds=length_bounds,
                source_text=normalized_source,
                detail_ledger=longform_ledger,
            )
            if callable(cancellation_checker) and cancellation_checker():
                raise ContentRewriteInputError("Rewrite cancelled.")
            revision_started_at = time.monotonic()
            final_result = rewrite_content(
                source_text=article_source,
                rewrite_focus=revision_prompt,
                rewrite_style="article_longform",
                rewrite_config=rewrite_config,
                skill_config=self._skill_config,
                cancellation_checker=cancellation_checker,
                skip_prompt_validation=True,
                rewrite_stage=revision_stage,
                prompt_profile=THIN_LONGFORM_PROMPT_PROFILE,
            )
            stage_timings_ms[revision_stage] = int((time.monotonic() - revision_started_at) * 1000)
            stage_models[revision_stage] = final_result.model
            stage_call_count += 1
            revision_used = True

        final_validation = validate_generated_article(final_result.rewritten_text, spec)
        final_coverage = analyze_detail_coverage_enhanced(longform_ledger, final_result.rewritten_text)
        detail_coverage_issues = format_detail_coverage_issues(final_coverage)
        final_quality_report = check_article_quality(
            final_result.rewritten_text,
            normalized_source,
            self._skill_config,
            longform_ledger,
            precomputed_detail_coverage_issues=detail_coverage_issues,
        )
        final_style_issues = _validate_style_constraints(final_result.rewritten_text, self._skill_config)
        final_soft_length_issues = _collect_length_ratio_issues(
            text=final_result.rewritten_text,
            source_text=normalized_source,
            skill_config=self._skill_config,
        )
        failure_stage = None
        if not final_validation.ok:
            failure_stage = "validation"
        elif detail_coverage_issues:
            failure_stage = "validation"
        elif final_style_issues:
            failure_stage = "validation"
        elif final_soft_length_issues:
            failure_stage = "validation"
        elif not final_quality_report.passed:
            failure_stage = "validation"

        next_recommended_action = "stop"
        if failure_stage is not None:
            if detail_coverage_issues or final_soft_length_issues:
                next_recommended_action = "expand"
            else:
                next_recommended_action = "patch"

        loop_snapshot = {
            "mode": "thin_longform",
            "outline_used": outline_used,
            "revision_used": revision_used,
            "stage_call_count": stage_call_count,
            "stage_timings_ms": stage_timings_ms,
            "stage_models": stage_models,
            "validation": {
                "passed": final_validation.ok,
                "total_chars": final_validation.total_chars,
                "section_count": final_validation.section_count,
                "issues": list(final_validation.issues),
            },
            "quality": {
                "passed": final_quality_report.passed,
                "issue_count": len(final_quality_report.issues),
                "layers_checked": final_quality_report.layers_checked,
                "layers_passed": final_quality_report.layers_passed,
            },
            "coverage": {
                "required_fact_count": len(longform_ledger.items),
                "missing_fact_count": len(final_coverage.missing_items),
                "issue_count": len(detail_coverage_issues),
            },
        }
        covered_facts = tuple(
            item.text for item in longform_ledger.items if item not in final_coverage.missing_items
        )

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
                validation=final_validation,
                revised_once=revision_used,
            ),
            rewrite_style="article_longform",
            detail_coverage_issues=detail_coverage_issues,
            writer_trace_id=trace_id,
            writer_policy_version=WRITER_POLICY_VERSION,
            writer_prompt_version=ARTICLE_LONGFORM_PROMPT_VERSION,
            loop_state_snapshot=loop_snapshot,
            last_action="revision" if revision_used else "draft",
            budget_usage={
                "stage_call_count": stage_call_count,
                "stage_timings_ms": stage_timings_ms,
                "stage_models": stage_models,
                "outline_used": outline_used,
                "revision_used": revision_used,
            },
            failure_stage=failure_stage,
            next_recommended_action=next_recommended_action,
            covered_facts_summary=covered_facts,
        )


# --- helpers ---

_THIN_OUTLINE_SOURCE_LENGTH_THRESHOLD = 3600
_THIN_OUTLINE_DETAIL_THRESHOLD = 8


def _should_run_thin_outline(source_text: str, detail_ledger: DetailLedger) -> bool:
    return (
        measure_source_text_length(source_text) >= _THIN_OUTLINE_SOURCE_LENGTH_THRESHOLD
        or len(detail_ledger.items) >= _THIN_OUTLINE_DETAIL_THRESHOLD
    )


def _collect_length_ratio_issues(
    *,
    text: str,
    source_text: str,
    skill_config: SkillConfig,
) -> tuple[str, ...]:
    output = getattr(skill_config, "output", None)
    ratio_min = getattr(output, "source_length_ratio_min", None)
    ratio_max = getattr(output, "source_length_ratio_max", None)
    if ratio_min is None and ratio_max is None:
        return ()

    normalized_source = (source_text or "").strip()
    source_length = measure_source_text_length(normalized_source)
    if source_length <= 0:
        return ()

    min_ratio = ratio_min if ratio_min is not None else 0.0
    max_ratio = ratio_max if ratio_max is not None else 1.0
    if max_ratio < min_ratio:
        min_ratio, max_ratio = max_ratio, min_ratio

    min_chars = max(1, round(source_length * min_ratio))
    max_chars = max(min_chars, round(source_length * max_ratio))
    current_chars = measure_source_text_length(text)
    if min_chars <= current_chars <= max_chars:
        return ()

    return (
        f"输出字数 {current_chars} 建议控制在原文长度的 {int(min_ratio * 100)}%-{int(max_ratio * 100)}%（约 {min_chars}-{max_chars} 字）",
    )


def _build_thin_revision_prompt(
    *,
    previous_article: str,
    spec: ArticleSpec,
    validation: ArticleValidationResult,
    detail_coverage_issues: tuple[str, ...],
    style_issues: tuple[str, ...],
    soft_length_issues: tuple[str, ...],
    length_guidance: str | None,
    source_length_bounds: tuple[int, int, int] | None,
    source_text: str,
    detail_ledger: DetailLedger,
) -> tuple[str, str]:
    if detail_coverage_issues:
        lines = [
            "请先回查证据，再重写当前稿件。",
            "",
            "当前问题：",
        ]
        if not validation.ok:
            lines.append("结构问题：")
            lines.extend(f"- {issue}" for issue in validation.issues)
        if detail_coverage_issues:
            lines.append("缺失细节：")
            lines.extend(f"- {issue}" for issue in detail_coverage_issues)
        if style_issues:
            lines.append("风格问题：")
            lines.extend(f"- {issue}" for issue in style_issues)
        if soft_length_issues:
            lines.append("篇幅问题：")
            lines.extend(f"- {issue}" for issue in soft_length_issues)
        if length_guidance:
            lines.extend(["", f"篇幅标准：{length_guidance}"])
        if source_length_bounds is not None:
            source_length, min_chars, max_chars = source_length_bounds
            current_chars = measure_source_text_length(previous_article)
            deficit = max(0, min_chars - current_chars)
            lines.append(
                f"当前稿件约 {current_chars} 字，原文约 {source_length} 字，目标区间 {min_chars}-{max_chars} 字，当前至少还需要补足约 {deficit} 字。"
            )
        lines.extend(
            [
                "- 先修正事实锚点和信息顺序，再输出修订后的正文。",
                "- 报道主语优先使用事件、变化、机制、平台和边界，不要让人物发言顺序主导段落顺序。",
                "- 如果仍然像翻译稿或逐字稿，请重新组织段落结构，而不是只改几个句子。",
                "",
                "原始素材：",
                source_text.strip(),
                "",
                "当前完整草稿：",
                previous_article.strip(),
                "",
                f"必须保留的关键细节：\n{detail_ledger.to_prompt_text()}",
            ]
        )
        return "re_ground", "\n".join(lines)

    if soft_length_issues:
        issue_lines = "\n".join(f"- {issue}" for issue in soft_length_issues)
        source_length = measure_source_text_length(source_text)
        current_chars = measure_source_text_length(previous_article)
        deficit = 0
        if source_length_bounds is not None:
            source_length, min_chars, max_chars = source_length_bounds
            deficit = max(0, min_chars - current_chars)
            length_line = (
                f"当前稿件约 {current_chars} 字，原文约 {source_length} 字，目标区间 {min_chars}-{max_chars} 字，当前至少还需要补足约 {deficit} 字。"
            )
        else:
            min_chars = max_chars = 0
            length_line = f"当前稿件约 {current_chars} 字，原文约 {source_length} 字。"
        lines = [
            "请基于下面这版内容进行一次扩写式重写，目标是补足篇幅和报道层次，不要只做局部润色。",
            f"篇幅标准：{length_guidance or f'总长度尽量达到 {spec.min_total_chars}-{spec.max_total_chars} 字。'}",
            length_line,
            "- 这不是摘要压缩任务，而是扩写任务；如果当前稿子偏短，请补出机制、代价、边界、对比和下一步判断。",
            "- 叙事主语优先使用事件、变化、系统、平台和产业链，不要沿着演讲顺序逐条复述。",
            "- 继续保持报道视角，不要把人物发言顺序当成段落顺序。",
            "- 每一段都要有明确的事实锚点或机制锚点，避免空泛判断。",
            "- 如果仍然像逐字稿，先重组结构，再补充细节。",
            f"当前软性问题：\n{issue_lines}",
            "",
            "待扩写文本：",
            previous_article.strip(),
            "",
            f"必须保留的关键细节：\n{detail_ledger.to_prompt_text()}",
        ]
        return "expand", "\n".join(lines)

    lines = [
        "请修订下面这版文章，只改有问题的部分，保留其余内容。",
        "",
    ]
    if not validation.ok:
        lines.append("当前结构问题：")
        lines.extend(f"- {issue}" for issue in validation.issues)
    if style_issues:
        lines.append("当前风格问题：")
        lines.extend(f"- {issue}" for issue in style_issues)
    if length_guidance:
        lines.extend(["", f"篇幅标准：{length_guidance}"])
    if source_length_bounds is not None:
        source_length, min_chars, max_chars = source_length_bounds
        current_chars = measure_source_text_length(previous_article)
        deficit = max(0, min_chars - current_chars)
        lines.append(
            f"当前稿件约 {current_chars} 字，原文约 {source_length} 字，目标区间 {min_chars}-{max_chars} 字，当前至少还需要补足约 {deficit} 字。"
        )
    if soft_length_issues:
        lines.append("当前篇幅提示：")
        lines.extend(f"- {issue}" for issue in soft_length_issues)
    lines.extend(
        [
            "",
            "处理原则：仅返回修订后的正文，不要解释。",
            "",
            "原始素材：",
            source_text.strip(),
            "",
            "当前完整草稿：",
            previous_article.strip(),
            "",
            f"必须保留的关键细节：\n{detail_ledger.to_prompt_text()}",
        ]
    )
    return "patch", "\n".join(lines)

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
    parts = ["请修订下面这版文章，只改有问题的部分，保留其余内容。", ""]
    if not validation.ok:
        for issue in validation.issues:
            parts.append(f"- 结构问题：{issue}")
    for issue in style_issues:
        parts.append(f"- 风格问题：{issue}")
    for item in missing_details[:6]:
        parts.append(f"- 缺失细节：{item.kind} {item.text}")
    parts.extend(["", "处理原则：仅返回修订后的正文，不要解释。"])
    return "\n".join(parts)


def _build_article_longform_revision_prompt(
    *,
    previous_article: str,
    spec: ArticleSpec,
    validation: ArticleValidationResult,
    quality_report: QualityReport,
    length_guidance: str | None = None,
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
        + (f"篇幅标准：{length_guidance}\n" if length_guidance else "")
        + "补充原则：\n"
        "- 直接把全文重写成第三视角文章，不要保留问答式、逐字稿式或时间块同步式表达。\n"
        "- 如果原文是访谈或播客，把对话内容融合成连续叙事，而不是拆成主持人/嘉宾轮流发言。\n"
        "- 除原文直接引语外，不要再出现我/我们/咱们/本人作为叙述主语。\n"
        "- 报道主语优先使用事件、变化、机制、平台和边界，不要让人物发言顺序主导段落顺序。\n"
        "- 如果仍然像翻译稿，请重新组织段落结构，而不是只改几个句子。"
    )


def _build_article_longform_length_expansion_prompt(
    *,
    previous_article: str,
    spec: ArticleSpec,
    soft_length_issues: tuple[QualityIssue, ...],
    length_guidance: str | None = None,
    source_length_bounds: tuple[int, int, int] | None = None,
) -> str:
    issue_lines = "\n".join(f"- {issue.message}" for issue in soft_length_issues)
    current_chars = measure_source_text_length(previous_article)
    target_line = ""
    if source_length_bounds is not None:
        source_length, min_chars, max_chars = source_length_bounds
        deficit = max(0, min_chars - current_chars)
        target_line = (
            f"当前稿件约 {current_chars} 字，原文约 {source_length} 字，"
            f"目标区间 {min_chars}-{max_chars} 字，"
            f"当前至少还需要补足约 {deficit} 字。"
        )
    guidance_line = (
        f"篇幅标准：{length_guidance}"
        if length_guidance
        else f"篇幅标准：总长度尽量达到 {spec.min_total_chars}-{spec.max_total_chars} 字。"
    )
    prompt_parts = [
        "\n\n请基于下面这版内容进行一次扩写式重写，目标是补足篇幅和报道层次，不要只做局部润色。",
        guidance_line,
    ]
    if target_line:
        prompt_parts.append(target_line)
    prompt_parts.extend(
        [
            "- 这不是摘要压缩任务，而是扩写任务；如果当前稿子偏短，请补出机制、代价、边界、对比和下一步判断。",
            "- 叙事主语优先使用事件、变化、系统、平台和产业链，不要沿着演讲顺序逐条复述。",
            "- 继续保持报道视角，不要把人物发言顺序当成段落顺序。",
            "- 每一段都要有明确的事实锚点或机制锚点，避免空泛判断。",
            "- 如果仍然像逐字稿，先重组结构，再补充细节。",
            f"当前软长度提示：\n{issue_lines}",
            "待扩写文本：",
            previous_article.strip(),
        ]
    )
    return "\n".join(prompt_parts) + "\n"


def _build_outline_prompt(
    *, spec: ArticleSpec, rewrite_focus: str | None, detail_ledger_text: str | None = None,
    length_guidance: str | None = None,
    soft_length_mode: bool = False,
) -> str:
    focus_text = (rewrite_focus or "科技深度中文文章").strip()
    prompt_lines = [
        "请基于原始素材先给出写作规划。",
        "",
        f"写作目标：{focus_text}",
        "写作视角：报道视角，围绕变化、机制和边界组织，不要按人物发言顺序列提纲。",
    ]
    if soft_length_mode:
        prompt_lines.append(
            f"篇幅要求：{length_guidance or '总长度尽量控制在原文的 40%-60% 之间。'}"
        )
    else:
        prompt_lines.append(
            f"目标字数：{spec.target_total_chars}（允许 {spec.min_total_chars}-{spec.max_total_chars}）"
        )
    prompt_lines.extend(
        [
            f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）",
            "",
            "只输出一个简短大纲，每行一个要点。",
        ]
    )
    prompt = "\n".join(prompt_lines)
    if length_guidance and not soft_length_mode:
        prompt += f"\n\n{length_guidance}"
    if detail_ledger_text:
        prompt += f"\n\n必须保留的关键细节：\n{detail_ledger_text}"
    return prompt


def _build_draft_prompt(
    *, spec: ArticleSpec, rewrite_focus: str | None, outline: tuple[str, ...],
    detail_ledger_text: str | None = None,
    length_guidance: str | None = None,
    soft_length_mode: bool = False,
) -> str:
    focus_text = (rewrite_focus or "保留原意并提升中文可读性").strip()
    outline_text = "\n".join(f"- {line}" for line in outline) if outline else "- 按素材主线组织段落"
    prompt_lines = [
        "请按以下要求输出中文文章初稿。",
        "",
        f"写作目标：{focus_text}",
        "视角要求：第三视角报道写法，人物只作为信息来源，不要让发言顺序主导段落顺序。",
    ]
    if soft_length_mode:
        prompt_lines.append(
            f"篇幅要求：{length_guidance or '总长度尽量控制在原文的 40%-60% 之间。'}"
        )
    else:
        prompt_lines.extend(
            [
                f"总字数：{spec.min_total_chars}-{spec.max_total_chars}（目标 {spec.target_total_chars}）",
                f"每段字数：{spec.min_chars_per_section}-{spec.max_chars_per_section}（建议 {spec.target_chars_per_section}）",
            ]
        )
    prompt_lines.extend(
        [
            f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）",
            "",
            "大纲：",
            outline_text,
            "",
            "要求：不编造事实，段落之间空行，只输出正文。",
        ]
    )
    prompt = "\n".join(prompt_lines)
    if length_guidance and not soft_length_mode:
        prompt += f"\n\n{length_guidance}"
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
