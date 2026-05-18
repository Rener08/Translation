from dataclasses import dataclass, field
from typing import Literal

from app.services.llm_provider_service import clean_model_output_text
from app.services.prompt_validation import validate_rewrite_prompt
from app.services.rewrite_message_service import (
    ARTICLE_LONGFORM_DEFAULT_FOCUS,
    DEFAULT_REWRITE_FOCUS,
    build_rewrite_messages,
)
from app.services.rewrite_provider_service import (
    resolve_rewrite_config,
    rewrite_with_ollama,
    rewrite_with_openai_compatible,
)
from app.services.rewrite_template_service import (
    RewriteReferences,
    SelectedRewriteTemplate,
    load_rewrite_references,
    select_rewrite_template,
)
# Backward-compatible alias: tests import the old private name
_select_rewrite_template = select_rewrite_template
from app.services.rewrite_quality_service import analyze_rewrite_quality

# Re-export symbols for backward compatibility with existing imports
from app.services.rewrite_message_service import (  # noqa: F401
    SPEECH_VERBATIM_ASSISTANT_INSTRUCTIONS,
    ARTICLE_LONGFORM_ASSISTANT_INSTRUCTIONS,
)
from app.services.rewrite_template_service import (  # noqa: F401
    LASTPOST_TEMPLATE_SPECS,
    LastpostTemplateSpec,
    LASTPOST_DEFAULT_TEMPLATE_KEY,
)

RewriteStyle = Literal["speech_verbatim", "article_longform"]
DEFAULT_REWRITE_STYLE: RewriteStyle = "speech_verbatim"


class ContentRewriteError(Exception):
    """Base error for content rewrite failures."""


class ContentRewriteConfigurationError(ContentRewriteError):
    """Raised when rewrite configuration is missing or invalid."""


class ContentRewriteInputError(ContentRewriteError):
    """Raised when rewrite request input is invalid."""


class ContentRewriteProviderError(ContentRewriteError):
    """Raised when the upstream rewrite provider fails."""


class ContentRewriteEmptyOutputError(ContentRewriteProviderError):
    """Raised when the upstream provider returns an empty rewrite output."""


@dataclass(frozen=True)
class ContentRewriteResult:
    rewritten_text: str
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    model: str
    quality_issues: tuple[str, ...] = ()
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


def rewrite_content(
    *,
    source_text: str,
    rewrite_focus: str | None = None,
    rewrite_style: RewriteStyle | None = None,
    rewrite_config: dict[str, object] | None = None,
    detail_ledger: str | None = None,
    skill_config=None,
    cancellation_checker=None,
) -> ContentRewriteResult:
    normalized_source = str(source_text or "").strip()
    if not normalized_source:
        raise ContentRewriteConfigurationError("source_text must not be empty.")

    if rewrite_focus is None:
        normalized_focus = (
            ARTICLE_LONGFORM_DEFAULT_FOCUS
            if _normalize_rewrite_style(rewrite_style) == "article_longform"
            else DEFAULT_REWRITE_FOCUS
        )
    else:
        normalized_focus = str(rewrite_focus).strip()
        if not normalized_focus:
            raise ContentRewriteInputError(
                "改写提示为空。请重新选择写作风格，或移除空白 rewrite_focus 后重试。"
            )

    prompt_validation = validate_rewrite_prompt(normalized_focus)
    if not prompt_validation.is_valid:
        raise ContentRewriteInputError("；".join(prompt_validation.errors))

    normalized_style = _normalize_rewrite_style(rewrite_style)
    config = resolve_rewrite_config(rewrite_config)
    references = None
    if not prompt_validation.has_transcript_placeholder and normalized_style != "speech_verbatim":
        references = load_rewrite_references()
    messages = build_rewrite_messages(
        source_text=normalized_source,
        rewrite_focus=normalized_focus,
        rewrite_style=normalized_style,
        references=references,
        detail_ledger=detail_ledger,
        skill_config=skill_config,
    )

    if config.provider == "ollama":
        rewritten_text = rewrite_with_ollama(
            config,
            messages,
            rewrite_style=normalized_style,
            cancellation_checker=cancellation_checker,
        )
    else:
        rewritten_text = rewrite_with_openai_compatible(
            config,
            messages,
            rewrite_style=normalized_style,
            cancellation_checker=cancellation_checker,
        )

    cleaned = clean_model_output_text(rewritten_text).strip()
    if not cleaned:
        raise ContentRewriteEmptyOutputError(
            f"内容改写失败：{config.provider} 返回了空内容。请重试，或更换模型/提示词。"
        )
    quality_issues = tuple(analyze_rewrite_quality(cleaned))

    return ContentRewriteResult(
        rewritten_text=cleaned,
        provider=config.provider,
        model=config.model,
        quality_issues=quality_issues,
    )


def _normalize_rewrite_style(rewrite_style: RewriteStyle | None) -> RewriteStyle:
    if rewrite_style == "speech_verbatim":
        return "speech_verbatim"
    if rewrite_style == "article_longform":
        return "article_longform"
    return DEFAULT_REWRITE_STYLE
