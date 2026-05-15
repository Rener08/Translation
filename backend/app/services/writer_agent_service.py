"""WriterAgent: orchestrates content rewriting pipelines."""

from app.services.content_rewrite_service import (
    ContentRewriteInputError,
    ContentRewriteResult,
    DEFAULT_REWRITE_STYLE,
    RewriteStyle,
)
from app.services.pipelines import (
    ArticleDraft,
    ArticleLongformPipeline,
    FullPromptPipeline,
    MaterialPackage,
    PipelineStrategy,
    SpeechVerbatimPipeline,
    WriterRunReport,
)
from app.services.prompt_validation import validate_rewrite_prompt
from app.services.skill_config_service import SkillConfig, load_default_skill_config

# Re-export for backward compatibility
ARTICLE_LONGFORM_FIRST_PERSON_MARKERS: tuple[str, ...] = (
    "我想", "我会", "我认为", "我觉得", "我来", "我要", "我先", "我正在",
    "我们", "我们先", "我们会", "我们认为", "我们觉得", "咱们", "本人",
)
from app.services.pipelines import (  # noqa: F401
    _strip_quoted_spans,
)
from app.services.detail_ledger import (  # noqa: F401
    DETAIL_LEDGER_MAX_ITEMS,
    DetailLedger,
    DetailLedgerItem,
    build_detail_ledger,
    analyze_detail_coverage,
    format_detail_coverage_issues,
)


class WriterAgent:
    def run(
        self,
        *,
        material: MaterialPackage,
        reference_text: str | None = None,
        rewrite_focus: str | None = None,
        rewrite_style: RewriteStyle | None = None,
        rewrite_config: dict[str, object] | None = None,
        skill_config: SkillConfig | None = None,
        llm_call_fn=None,
    ) -> WriterRunReport:
        normalized_source = (material.source_text or "").strip()
        if not normalized_source:
            raise ValueError("material.source_text must not be empty.")

        normalized_style = rewrite_style or DEFAULT_REWRITE_STYLE
        config = skill_config or load_default_skill_config()

        # Validate rewrite_focus
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
                return self._execute_pipeline(
                    FullPromptPipeline(), material, normalized_focus, rewrite_config,
                )

        return self._execute_pipeline(
            self._select_strategy(normalized_style, skill_config=config, llm_call_fn=llm_call_fn),
            self._with_reference_text(material, reference_text),
            normalized_focus, rewrite_config,
        )

    def _select_strategy(
        self, style: RewriteStyle, *, skill_config: SkillConfig, llm_call_fn=None,
    ) -> PipelineStrategy:
        if style == "speech_verbatim":
            return SpeechVerbatimPipeline(skill_config, llm_call_fn=llm_call_fn)
        return ArticleLongformPipeline(skill_config)

    def _execute_pipeline(
        self,
        strategy: PipelineStrategy,
        material: MaterialPackage,
        rewrite_focus: str | None,
        rewrite_config: dict[str, object] | None,
    ) -> WriterRunReport:
        return strategy.execute(
            material=material,
            rewrite_focus=rewrite_focus,
            rewrite_config=rewrite_config,
        )

    @staticmethod
    def _with_reference_text(
        material: MaterialPackage,
        reference_text: str | None,
    ) -> MaterialPackage:
        normalized_reference = (reference_text or "").strip()
        if not normalized_reference:
            return material
        if normalized_reference == (material.reference_text or "").strip():
            return material
        return MaterialPackage(
            source_text=material.source_text,
            reference_text=normalized_reference,
            source_language=material.source_language,
            translation_language=material.translation_language,
        )


def run_writer_agent(
    *,
    source_text: str,
    reference_text: str | None = None,
    rewrite_focus: str | None = None,
    rewrite_style: RewriteStyle | None = None,
    rewrite_config: dict[str, object] | None = None,
    skill_config: SkillConfig | None = None,
) -> ContentRewriteResult:
    agent = WriterAgent()
    material = MaterialPackage(source_text=source_text, reference_text=(reference_text or "").strip())
    report = agent.run(
        material=material,
        reference_text=reference_text,
        rewrite_focus=rewrite_focus,
        rewrite_style=rewrite_style,
        rewrite_config=rewrite_config,
        skill_config=skill_config,
    )
    return ContentRewriteResult(
        rewritten_text=report.rewritten_text,
        provider=report.provider,
        model=report.model,
        quality_issues=report.quality_issues,
        detail_coverage_issues=report.detail_coverage_issues,
        writer_trace_id=report.writer_trace_id,
        writer_policy_version=report.writer_policy_version,
        writer_prompt_version=report.writer_prompt_version,
    )
