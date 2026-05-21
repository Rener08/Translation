"""Stage-aware rewrite routing helpers."""

from __future__ import annotations

from app.config import get_env_str

THIN_LONGFORM_PROMPT_PROFILE = "thin_longform"
DEEPSEEK_CONTROL_MODEL = "deepseek-v4-flash"
DEEPSEEK_CONTENT_MODEL = "deepseek-v4-pro"

_CONTROL_STAGES = {
    "collect_evidence",
    "evidence_summary",
    "outline",
    "route",
    "validation",
    "validation_summary",
}
_CONTENT_STAGES = {
    "draft",
    "expand",
    "final",
    "patch",
    "repair",
    "re_ground",
    "revision",
}


def resolve_stage_model(
    raw_config: dict[str, object] | None,
    *,
    stage: str | None,
    prompt_profile: str = "default",
    provider: str | None = None,
) -> str | None:
    """Resolve an optional stage-specific model override.

    The router is intentionally narrow: it only activates for the thin longform
    profile and only changes DeepSeek model selection. Other providers keep their
    existing model untouched.
    """

    if prompt_profile != THIN_LONGFORM_PROMPT_PROFILE:
        return None

    normalized_provider = _normalize_provider(provider, raw_config)
    if normalized_provider != "deepseek":
        return None

    normalized_stage = str(stage or "").strip().lower()
    if not normalized_stage:
        return None

    config = dict(raw_config or {})
    model = _pick_stage_model(config.get("stage_models"), normalized_stage)
    if model:
        return model

    if normalized_stage in _CONTROL_STAGES:
        return _first_non_empty(
            str(config.get("control_model") or "").strip(),
            get_env_str("DEEPSEEK_REWRITE_CONTROL_MODEL"),
            DEEPSEEK_CONTROL_MODEL,
        )

    if normalized_stage in _CONTENT_STAGES:
        return _first_non_empty(
            str(config.get("content_model") or "").strip(),
            get_env_str("DEEPSEEK_REWRITE_CONTENT_MODEL"),
            DEEPSEEK_CONTENT_MODEL,
        )

    return None


def _normalize_provider(provider: str | None, raw_config: dict[str, object] | None) -> str:
    if provider and provider.strip():
        return provider.strip().lower()
    config = raw_config or {}
    return str(
        config.get("provider")
        or get_env_str("REWRITE_PROVIDER")
        or get_env_str("TRANSLATION_PROVIDER")
        or ""
    ).strip().lower()


def _pick_stage_model(stage_models: object, stage: str) -> str | None:
    if not isinstance(stage_models, dict):
        return None

    candidate = stage_models.get(stage)
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()

    if stage in _CONTROL_STAGES:
        candidate = stage_models.get("control") or stage_models.get("control_model")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    if stage in _CONTENT_STAGES:
        candidate = stage_models.get("content") or stage_models.get("content_model")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    candidate = stage_models.get("default")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


def _first_non_empty(*values: str) -> str | None:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return None
