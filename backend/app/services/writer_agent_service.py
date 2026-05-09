from dataclasses import dataclass
from typing import Literal

from app.services.article_generation_service import (
    ArticleSpec,
    ArticleValidationResult,
    build_article_rewrite_prompt,
    resolve_article_spec,
    validate_generated_article,
)
from app.services.content_rewrite_service import ContentRewriteResult, rewrite_content
from app.services.content_rewrite_service import ContentRewriteInputError
from app.services.prompt_validation import validate_rewrite_prompt


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


class WriterAgent:
    def run(
        self,
        *,
        material: MaterialPackage,
        rewrite_focus: str | None = None,
        rewrite_config: dict[str, object] | None = None,
    ) -> WriterRunReport:
        normalized_source = (material.source_text or "").strip()
        if not normalized_source:
            raise ValueError("material.source_text must not be empty.")

        normalized_focus = None
        if rewrite_focus is not None:
            normalized_focus = rewrite_focus.strip()
            if not normalized_focus:
                raise ContentRewriteInputError(
                    "改写提示为空。请重新选择写作风格，或移除空白 rewrite_focus 后重试。"
                )
            validation = validate_rewrite_prompt(normalized_focus)
            if not validation.is_valid:
                raise ContentRewriteInputError("；".join(validation.errors))
            if validation.has_transcript_placeholder:
                direct_result = rewrite_content(
                    source_text=normalized_source,
                    rewrite_focus=normalized_focus,
                    rewrite_config=rewrite_config,
                )
                spec = resolve_article_spec(normalized_source)
                draft_validation = validate_generated_article(direct_result.rewritten_text, spec)
                return WriterRunReport(
                    rewritten_text=direct_result.rewritten_text,
                    provider=direct_result.provider,
                    model=direct_result.model,
                    quality_issues=tuple(direct_result.quality_issues),
                    material=material,
                    draft=ArticleDraft(
                        text=direct_result.rewritten_text,
                        outline=("full_prompt_passthrough",),
                        spec=spec,
                        validation=draft_validation,
                        revised_once=False,
                    ),
                )

        spec = resolve_article_spec(normalized_source)
        planning_result = rewrite_content(
            source_text=normalized_source,
            rewrite_focus=_build_outline_prompt(spec=spec, rewrite_focus=normalized_focus),
            rewrite_config=rewrite_config,
        )
        outline = _extract_outline(planning_result.rewritten_text)

        draft_result = rewrite_content(
            source_text=normalized_source,
            rewrite_focus=_build_draft_prompt(
                spec=spec,
                rewrite_focus=normalized_focus,
                outline=outline,
            ),
            rewrite_config=rewrite_config,
        )
        validation = validate_generated_article(draft_result.rewritten_text, spec)
        final_result = draft_result
        revised_once = False

        if not validation.ok:
            revised_once = True
            revise_prompt = build_article_rewrite_prompt(
                previous_article=draft_result.rewritten_text,
                spec=spec,
                validation=validation,
            )
            final_result = rewrite_content(
                source_text=normalized_source,
                rewrite_focus=revise_prompt,
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
        )


def run_writer_agent(
    *,
    source_text: str,
    rewrite_focus: str | None = None,
    rewrite_config: dict[str, object] | None = None,
) -> ContentRewriteResult:
    agent = WriterAgent()
    material = MaterialPackage(source_text=source_text)
    report = agent.run(
        material=material,
        rewrite_focus=rewrite_focus,
        rewrite_config=rewrite_config,
    )
    return ContentRewriteResult(
        rewritten_text=report.rewritten_text,
        provider=report.provider,
        model=report.model,
        quality_issues=report.quality_issues,
    )


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
    *,
    spec: ArticleSpec,
    rewrite_focus: str | None,
    outline: tuple[str, ...],
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
