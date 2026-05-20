from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

LoopPhaseKind = Literal[
    "plan",
    "collect_evidence",
    "outline",
    "draft",
    "validate",
    "re_ground",
    "patch",
    "expand",
    "finalize",
    "fail",
]
LoopDecisionKind = LoopPhaseKind
LoopStepKind = Literal[
    "plan",
    "collect_evidence",
    "outline",
    "draft",
    "validate",
    "re_ground",
    "patch",
    "expand",
    "finalize",
    "fail",
    "stop",
]

ALLOWED_LOOP_PHASE_KINDS: tuple[LoopPhaseKind, ...] = (
    "plan",
    "collect_evidence",
    "outline",
    "draft",
    "validate",
    "re_ground",
    "patch",
    "expand",
    "finalize",
    "fail",
)
ALLOWED_LOOP_STEP_KINDS: tuple[LoopStepKind, ...] = (
    "plan",
    "collect_evidence",
    "outline",
    "draft",
    "validate",
    "re_ground",
    "patch",
    "expand",
    "finalize",
    "fail",
    "stop",
)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_text_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_text(item) for item in value if _normalize_text(item))
    normalized = _normalize_text(value)
    return (normalized,) if normalized else ()


def _normalize_unique_text_tuple(value: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_normalize_text_tuple(value)))


def _normalize_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, default)


def _normalize_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_mapping(value: Any) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _normalize_text_mapping(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        items = value.items()
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return {}

    normalized: dict[str, str] = {}
    for item in items:
        if isinstance(item, Mapping):
            key = item.get("id") or item.get("key") or item.get("name")
            text = item.get("text") or item.get("value") or item.get("snippet")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            key, text = item[0], item[1]
        else:
            continue
        normalized_key = _normalize_text(key)
        normalized_text = _normalize_text(text)
        if normalized_key and normalized_text:
            normalized[normalized_key] = normalized_text
    return normalized


def _normalize_step_kind(value: Any) -> LoopStepKind:
    normalized = _normalize_text(value)
    if normalized not in ALLOWED_LOOP_STEP_KINDS:
        raise ValueError(f"Unsupported loop action kind: {value!r}")
    return normalized  # type: ignore[return-value]


def _normalize_phase_kind(value: Any) -> LoopPhaseKind:
    normalized = _normalize_text(value)
    if normalized == "stop":
        return "finalize"
    if normalized not in ALLOWED_LOOP_PHASE_KINDS:
        raise ValueError(f"Unsupported loop phase kind: {value!r}")
    return normalized  # type: ignore[return-value]


def _migrate_step_kind(value: Any) -> LoopStepKind:
    try:
        return _normalize_step_kind(value)
    except ValueError:
        return "stop"


def _migrate_phase_kind(value: Any) -> LoopPhaseKind:
    try:
        return _normalize_phase_kind(value)
    except ValueError:
        return "plan"


def _normalize_action_kind(value: Any) -> LoopStepKind:
    return _normalize_step_kind(value)


def _migrate_action_kind(value: Any) -> LoopStepKind:
    return _migrate_step_kind(value)


def _normalize_action_retry_counts(value: Any) -> tuple[tuple[str, int], ...]:
    if isinstance(value, Mapping):
        items = value.items()
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return ()

    counts: dict[str, int] = {}
    for item in items:
        if isinstance(item, Mapping):
            kind = item.get("kind")
            count = item.get("count", 0)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            kind, count = item[0], item[1]
        else:
            continue
        normalized_kind = _normalize_text(kind)
        if normalized_kind not in ALLOWED_LOOP_STEP_KINDS:
            continue
        counts[normalized_kind] = max(0, counts.get(normalized_kind, 0) + _normalize_int(count))
    return tuple(sorted(counts.items()))


def _dedupe_text_items(items: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in _normalize_text_tuple(items) if item))


def _should_expand_from_metrics(metrics: Mapping[str, Any] | dict[str, object]) -> bool:
    metric_map = dict(metrics or {})
    length_ratio = _normalize_float(metric_map.get("length_ratio"), 0.0)
    output_chars = _normalize_int(metric_map.get("output_chars"), 0)
    source_chars = _normalize_int(metric_map.get("source_chars"), 0)
    if source_chars and output_chars and output_chars < max(1, round(source_chars * 0.55)):
        return True
    return 0.0 < length_ratio < 0.55


def migrate_rewrite_goal_snapshot(snapshot: Any) -> dict[str, object]:
    if isinstance(snapshot, RewriteGoal):
        return snapshot.to_snapshot()
    if not isinstance(snapshot, Mapping):
        return {
            "rewrite_focus_raw": "",
            "rewrite_style": "",
            "skill_config_name": "",
            "route_template_key": "",
            "route_template_label": "",
            "route_reason": "",
        }
    return {
        "rewrite_focus_raw": _normalize_text(snapshot.get("rewrite_focus_raw")),
        "rewrite_style": _normalize_text(snapshot.get("rewrite_style")),
        "skill_config_name": _normalize_text(snapshot.get("skill_config_name")),
        "route_template_key": _normalize_text(snapshot.get("route_template_key")),
        "route_template_label": _normalize_text(snapshot.get("route_template_label")),
        "route_reason": _normalize_text(snapshot.get("route_reason")),
    }


def migrate_loop_budget_snapshot(snapshot: Any) -> dict[str, object]:
    if isinstance(snapshot, LoopBudget):
        return snapshot.to_snapshot()
    if not isinstance(snapshot, Mapping):
        return {
            "max_rounds": 6,
            "max_total_tokens": 90_000,
            "max_retries_per_action": 2,
            "max_patch_ratio_per_round": 0.35,
            "spent_tokens": 0,
            "action_retry_counts": {},
        }
    return {
        "max_rounds": _normalize_int(snapshot.get("max_rounds"), 6) or 6,
        "max_total_tokens": _normalize_int(snapshot.get("max_total_tokens"), 90_000) or 90_000,
        "max_retries_per_action": _normalize_int(snapshot.get("max_retries_per_action"), 2) or 2,
        "max_patch_ratio_per_round": _normalize_float(snapshot.get("max_patch_ratio_per_round"), 0.35),
        "spent_tokens": _normalize_int(snapshot.get("spent_tokens"), 0),
        "action_retry_counts": dict(_normalize_action_retry_counts(snapshot.get("action_retry_counts"))),
    }


def migrate_loop_trace_step_snapshot(snapshot: Any) -> dict[str, object]:
    if isinstance(snapshot, LoopTraceStep):
        return snapshot.to_snapshot()
    if not isinstance(snapshot, Mapping):
        return {
            "action": "stop",
            "reason": "",
            "prompt_preview": "",
            "input_chars": 0,
            "output_chars": 0,
            "tokens_used": 0,
            "validation_summary": "",
            "metadata": {},
        }
    return {
        "action": _migrate_action_kind(snapshot.get("action", "stop")),
        "reason": _normalize_text(snapshot.get("reason")),
        "prompt_preview": _normalize_text(snapshot.get("prompt_preview")),
        "input_chars": _normalize_int(snapshot.get("input_chars"), 0),
        "output_chars": _normalize_int(snapshot.get("output_chars"), 0),
        "tokens_used": _normalize_int(snapshot.get("tokens_used"), 0),
        "validation_summary": _normalize_text(snapshot.get("validation_summary")),
        "metadata": _normalize_mapping(snapshot.get("metadata")),
    }


def migrate_rewrite_state_snapshot(snapshot: Any) -> dict[str, object]:
    if isinstance(snapshot, RewriteState):
        return snapshot.to_snapshot()
    if not isinstance(snapshot, Mapping):
        return {
            "job_id": "",
            "goal": migrate_rewrite_goal_snapshot(None),
            "stage": "plan",
            "draft": "",
            "draft_chars": 0,
            "issues": [],
            "rounds_left": 0,
            "covered_facts": [],
            "style_constraints": [],
            "evidence_bundle": migrate_evidence_bundle_snapshot(None),
            "validation_breakdown": migrate_validation_breakdown_snapshot(None),
            "budget": migrate_loop_budget_snapshot(None),
            "trace": [],
            "failure": None,
        }
    evidence_bundle_snapshot = snapshot.get("evidence_bundle")
    validation_breakdown_snapshot = snapshot.get("validation_breakdown") or snapshot.get("validation")
    covered_facts = list(_normalize_text_tuple(snapshot.get("covered_facts")))
    validation_breakdown = migrate_validation_breakdown_snapshot(validation_breakdown_snapshot)
    if not validation_breakdown_snapshot and snapshot.get("issues"):
        validation_breakdown["hard_failures"] = list(_normalize_text_tuple(snapshot.get("issues")))
    evidence_bundle = migrate_evidence_bundle_snapshot(evidence_bundle_snapshot)
    if not evidence_bundle_snapshot and covered_facts:
        evidence_bundle["covered_fact_ids"] = covered_facts
    return {
        "job_id": _normalize_text(snapshot.get("job_id")),
        "goal": migrate_rewrite_goal_snapshot(snapshot.get("goal")),
        "stage": _migrate_phase_kind(
            snapshot.get("stage")
            or snapshot.get("loop_stage")
            or snapshot.get("phase")
            or ("fail" if _normalize_text(snapshot.get("failure")) else None)
            or ("re_ground" if validation_breakdown["grounding_failures"] or validation_breakdown["detail_coverage_issues"] else None)
            or ("patch" if validation_breakdown["hard_failures"] else None)
            or ("expand" if validation_breakdown["writing_failures"] or validation_breakdown["soft_failures"] else None)
            or ("validate" if snapshot.get("draft") and snapshot.get("issues") else None)
            or ("draft" if snapshot.get("draft") else None)
            or ("collect_evidence" if evidence_bundle["source_excerpt_hits"] or evidence_bundle["covered_fact_ids"] else None)
            or "plan"
        ),
        "draft": _normalize_text(snapshot.get("draft") or snapshot.get("draft_text")),
        "draft_chars": _normalize_int(snapshot.get("draft_chars"), 0),
        "issues": list(_normalize_text_tuple(snapshot.get("issues"))),
        "rounds_left": _normalize_int(snapshot.get("rounds_left"), 0),
        "covered_facts": covered_facts,
        "style_constraints": list(_normalize_text_tuple(snapshot.get("style_constraints"))),
        "evidence_bundle": evidence_bundle,
        "validation_breakdown": validation_breakdown,
        "budget": migrate_loop_budget_snapshot(snapshot.get("budget")),
        "trace": [
            migrate_loop_trace_step_snapshot(item)
            for item in (snapshot.get("trace") or [])
            if item is not None
        ],
        "failure": _normalize_text(snapshot.get("failure")) or None,
    }


def migrate_evidence_bundle_snapshot(snapshot: Any) -> dict[str, object]:
    if isinstance(snapshot, EvidenceBundle):
        return snapshot.to_snapshot()
    if not isinstance(snapshot, Mapping):
        return {
            "source_excerpt_hits": [],
            "required_fact_ids": [],
            "covered_fact_ids": [],
            "missing_fact_ids": [],
            "fact_snippets": {},
            "grounding_warnings": [],
        }
    return {
        "source_excerpt_hits": list(
            _normalize_unique_text_tuple(
                snapshot.get("source_excerpt_hits")
                or snapshot.get("source_excerpt")
                or snapshot.get("excerpts")
                or snapshot.get("hits")
            )
        ),
        "required_fact_ids": list(
            _normalize_unique_text_tuple(snapshot.get("required_fact_ids") or snapshot.get("required_facts"))
        ),
        "covered_fact_ids": list(
            _normalize_unique_text_tuple(snapshot.get("covered_fact_ids") or snapshot.get("covered_facts"))
        ),
        "missing_fact_ids": list(
            _normalize_unique_text_tuple(snapshot.get("missing_fact_ids") or snapshot.get("missing_facts"))
        ),
        "fact_snippets": _normalize_text_mapping(
            snapshot.get("fact_snippets") or snapshot.get("snippets") or snapshot.get("fact_snippet_map")
        ),
        "grounding_warnings": list(
            _normalize_unique_text_tuple(snapshot.get("grounding_warnings") or snapshot.get("warnings"))
        ),
    }


def migrate_validation_breakdown_snapshot(snapshot: Any) -> dict[str, object]:
    if isinstance(snapshot, RewriteValidationBreakdown):
        return snapshot.to_snapshot()
    if not isinstance(snapshot, Mapping):
        return {
            "grounding_failures": [],
            "writing_failures": [],
            "hard_failures": [],
            "soft_failures": [],
            "detail_coverage_issues": [],
            "metrics": {},
            "next_recommended_stage": "finalize",
        }
    next_stage = snapshot.get("next_recommended_stage") or snapshot.get("next_recommended_action")
    return {
        "grounding_failures": list(
            _normalize_unique_text_tuple(snapshot.get("grounding_failures") or snapshot.get("grounding_issues"))
        ),
        "writing_failures": list(
            _normalize_unique_text_tuple(snapshot.get("writing_failures") or snapshot.get("writing_issues"))
        ),
        "hard_failures": list(_normalize_unique_text_tuple(snapshot.get("hard_failures"))),
        "soft_failures": list(_normalize_unique_text_tuple(snapshot.get("soft_failures"))),
        "detail_coverage_issues": list(
            _normalize_unique_text_tuple(snapshot.get("detail_coverage_issues") or snapshot.get("coverage_issues"))
        ),
        "metrics": _normalize_mapping(snapshot.get("metrics")),
        "next_recommended_stage": _migrate_phase_kind(next_stage),
    }


@dataclass(frozen=True)
class RewriteGoal:
    rewrite_focus_raw: str
    rewrite_style: str
    skill_config_name: str
    route_template_key: str
    route_template_label: str = ""
    route_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "rewrite_focus_raw", _normalize_text(self.rewrite_focus_raw))
        object.__setattr__(self, "rewrite_style", _normalize_text(self.rewrite_style))
        object.__setattr__(self, "skill_config_name", _normalize_text(self.skill_config_name))
        object.__setattr__(self, "route_template_key", _normalize_text(self.route_template_key))
        object.__setattr__(self, "route_template_label", _normalize_text(self.route_template_label))
        object.__setattr__(self, "route_reason", _normalize_text(self.route_reason))

    def to_snapshot(self) -> dict[str, object]:
        return {
            "rewrite_focus_raw": self.rewrite_focus_raw,
            "rewrite_style": self.rewrite_style,
            "skill_config_name": self.skill_config_name,
            "route_template_key": self.route_template_key,
            "route_template_label": self.route_template_label,
            "route_reason": self.route_reason,
        }

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> RewriteGoal:
        data = migrate_rewrite_goal_snapshot(snapshot)
        return cls(
            rewrite_focus_raw=data["rewrite_focus_raw"],
            rewrite_style=data["rewrite_style"],
            skill_config_name=data["skill_config_name"],
            route_template_key=data["route_template_key"],
            route_template_label=data["route_template_label"],
            route_reason=data["route_reason"],
        )


@dataclass(frozen=True)
class LoopBudget:
    max_rounds: int = 6
    max_total_tokens: int = 90_000
    max_retries_per_action: int = 2
    max_patch_ratio_per_round: float = 0.35
    spent_tokens: int = 0
    action_retry_counts: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_rounds", max(1, _normalize_int(self.max_rounds, 6)))
        object.__setattr__(self, "max_total_tokens", max(0, _normalize_int(self.max_total_tokens, 90_000)))
        object.__setattr__(self, "max_retries_per_action", max(0, _normalize_int(self.max_retries_per_action, 2)))
        object.__setattr__(self, "max_patch_ratio_per_round", max(0.0, _normalize_float(self.max_patch_ratio_per_round, 0.35)))
        object.__setattr__(self, "spent_tokens", max(0, _normalize_int(self.spent_tokens, 0)))
        object.__setattr__(self, "action_retry_counts", _normalize_action_retry_counts(self.action_retry_counts))

    def consume(self, token_cost: int = 0) -> LoopBudget:
        return replace(self, spent_tokens=max(0, self.spent_tokens + max(0, token_cost)))

    def increment_retry(self, action_kind: LoopStepKind) -> LoopBudget:
        normalized = _normalize_step_kind(action_kind)
        counts = dict(self.action_retry_counts)
        counts[normalized] = counts.get(normalized, 0) + 1
        return replace(self, action_retry_counts=tuple(sorted(counts.items())))

    def increment_retry_for_stage(self, stage: LoopPhaseKind) -> LoopBudget:
        normalized = _normalize_phase_kind(stage)
        counts = dict(self.action_retry_counts)
        counts[normalized] = counts.get(normalized, 0) + 1
        return replace(self, action_retry_counts=tuple(sorted(counts.items())))

    def retry_count(self, action_kind: LoopStepKind) -> int:
        return dict(self.action_retry_counts).get(_normalize_step_kind(action_kind), 0)

    def retry_count_for_stage(self, stage: LoopPhaseKind) -> int:
        return dict(self.action_retry_counts).get(_normalize_phase_kind(stage), 0)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "max_rounds": self.max_rounds,
            "max_total_tokens": self.max_total_tokens,
            "max_retries_per_action": self.max_retries_per_action,
            "max_patch_ratio_per_round": self.max_patch_ratio_per_round,
            "spent_tokens": self.spent_tokens,
            "action_retry_counts": dict(self.action_retry_counts),
        }

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> LoopBudget:
        data = migrate_loop_budget_snapshot(snapshot)
        return cls(
            max_rounds=data["max_rounds"],
            max_total_tokens=data["max_total_tokens"],
            max_retries_per_action=data["max_retries_per_action"],
            max_patch_ratio_per_round=data["max_patch_ratio_per_round"],
            spent_tokens=data["spent_tokens"],
            action_retry_counts=tuple(data["action_retry_counts"].items()),
        )


@dataclass(frozen=True)
class LoopTraceStep:
    action: LoopStepKind
    reason: str
    prompt_preview: str = ""
    input_chars: int = 0
    output_chars: int = 0
    tokens_used: int = 0
    validation_summary: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _normalize_step_kind(self.action))
        object.__setattr__(self, "reason", _normalize_text(self.reason))
        object.__setattr__(self, "prompt_preview", _normalize_text(self.prompt_preview))
        object.__setattr__(self, "input_chars", _normalize_int(self.input_chars, 0))
        object.__setattr__(self, "output_chars", _normalize_int(self.output_chars, 0))
        object.__setattr__(self, "tokens_used", _normalize_int(self.tokens_used, 0))
        object.__setattr__(self, "validation_summary", _normalize_text(self.validation_summary))
        object.__setattr__(self, "metadata", _normalize_mapping(self.metadata))

    def to_snapshot(self) -> dict[str, object]:
        return {
            "action": self.action,
            "reason": self.reason,
            "prompt_preview": self.prompt_preview,
            "input_chars": self.input_chars,
            "output_chars": self.output_chars,
            "tokens_used": self.tokens_used,
            "validation_summary": self.validation_summary,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> LoopTraceStep:
        data = migrate_loop_trace_step_snapshot(snapshot)
        return cls(
            action=data["action"],
            reason=data["reason"],
            prompt_preview=data["prompt_preview"],
            input_chars=data["input_chars"],
            output_chars=data["output_chars"],
            tokens_used=data["tokens_used"],
            validation_summary=data["validation_summary"],
            metadata=data["metadata"],
        )


@dataclass(frozen=True)
class EvidenceBundle:
    source_excerpt_hits: tuple[str, ...] = ()
    required_fact_ids: tuple[str, ...] = ()
    covered_fact_ids: tuple[str, ...] = ()
    missing_fact_ids: tuple[str, ...] = ()
    fact_snippets: dict[str, str] = field(default_factory=dict)
    grounding_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_excerpt_hits", _dedupe_text_items(self.source_excerpt_hits))
        object.__setattr__(self, "required_fact_ids", _dedupe_text_items(self.required_fact_ids))
        object.__setattr__(self, "covered_fact_ids", _dedupe_text_items(self.covered_fact_ids))
        object.__setattr__(self, "missing_fact_ids", _dedupe_text_items(self.missing_fact_ids))
        object.__setattr__(self, "fact_snippets", _normalize_text_mapping(self.fact_snippets))
        object.__setattr__(self, "grounding_warnings", _dedupe_text_items(self.grounding_warnings))

    @property
    def is_empty(self) -> bool:
        return not (
            self.source_excerpt_hits
            or self.covered_fact_ids
            or self.missing_fact_ids
            or self.fact_snippets
            or self.grounding_warnings
        )

    @property
    def has_grounding_gaps(self) -> bool:
        return bool(self.missing_fact_ids or self.grounding_warnings)

    @property
    def coverage_ratio(self) -> float:
        if not self.required_fact_ids:
            return 1.0
        return round(len(self.covered_fact_ids) / len(self.required_fact_ids), 4)

    def summarize(self) -> str:
        parts: list[str] = []
        if self.required_fact_ids:
            parts.append(f"facts {len(self.covered_fact_ids)}/{len(self.required_fact_ids)}")
        elif self.covered_fact_ids:
            parts.append(f"covered {len(self.covered_fact_ids)}")
        if self.source_excerpt_hits:
            parts.append(f"excerpts {len(self.source_excerpt_hits)}")
        if self.missing_fact_ids:
            parts.append(f"missing {len(self.missing_fact_ids)}")
        if self.grounding_warnings:
            parts.append(f"warnings {len(self.grounding_warnings)}")
        return "; ".join(parts) if parts else "empty"

    def to_snapshot(self) -> dict[str, object]:
        return {
            "source_excerpt_hits": list(self.source_excerpt_hits),
            "required_fact_ids": list(self.required_fact_ids),
            "covered_fact_ids": list(self.covered_fact_ids),
            "missing_fact_ids": list(self.missing_fact_ids),
            "fact_snippets": dict(self.fact_snippets),
            "grounding_warnings": list(self.grounding_warnings),
        }

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> EvidenceBundle:
        data = migrate_evidence_bundle_snapshot(snapshot)
        return cls(
            source_excerpt_hits=tuple(data["source_excerpt_hits"]),
            required_fact_ids=tuple(data["required_fact_ids"]),
            covered_fact_ids=tuple(data["covered_fact_ids"]),
            missing_fact_ids=tuple(data["missing_fact_ids"]),
            fact_snippets=dict(data["fact_snippets"]),
            grounding_warnings=tuple(data["grounding_warnings"]),
        )


@dataclass(frozen=True)
class RewriteValidationBreakdown:
    grounding_failures: tuple[str, ...] = ()
    writing_failures: tuple[str, ...] = ()
    hard_failures: tuple[str, ...] = ()
    soft_failures: tuple[str, ...] = ()
    detail_coverage_issues: tuple[str, ...] = ()
    metrics: dict[str, object] = field(default_factory=dict)
    next_recommended_stage: LoopPhaseKind = "finalize"

    def __post_init__(self) -> None:
        object.__setattr__(self, "grounding_failures", _dedupe_text_items(self.grounding_failures))
        object.__setattr__(self, "writing_failures", _dedupe_text_items(self.writing_failures))
        object.__setattr__(self, "hard_failures", _dedupe_text_items(self.hard_failures))
        object.__setattr__(self, "soft_failures", _dedupe_text_items(self.soft_failures))
        object.__setattr__(self, "detail_coverage_issues", _dedupe_text_items(self.detail_coverage_issues))
        object.__setattr__(self, "metrics", _normalize_mapping(self.metrics))
        object.__setattr__(self, "next_recommended_stage", _normalize_phase_kind(self.next_recommended_stage))

    @property
    def combined_failures(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item
                for item in (
                    *self.grounding_failures,
                    *self.writing_failures,
                    *self.hard_failures,
                    *self.soft_failures,
                    *self.detail_coverage_issues,
                )
                if item
            )
        )

    @property
    def has_grounding_failures(self) -> bool:
        return bool(self.grounding_failures or self.detail_coverage_issues)

    @property
    def has_writing_failures(self) -> bool:
        return bool(self.writing_failures or self.soft_failures or self.hard_failures)

    @property
    def passed(self) -> bool:
        return not self.combined_failures

    @property
    def recommended_stage(self) -> LoopPhaseKind:
        if self.has_grounding_failures:
            return "re_ground"
        if self.hard_failures:
            return "patch"
        if self.writing_failures or self.soft_failures:
            return "expand" if _should_expand_from_metrics(self.metrics) else "patch"
        if self.passed:
            return self.next_recommended_stage
        return self.next_recommended_stage

    def summarize(self) -> str:
        parts: list[str] = []
        if self.grounding_failures:
            parts.append(f"grounding {len(self.grounding_failures)}")
        if self.writing_failures:
            parts.append(f"writing {len(self.writing_failures)}")
        if self.hard_failures:
            parts.append(f"hard {len(self.hard_failures)}")
        if self.soft_failures:
            parts.append(f"soft {len(self.soft_failures)}")
        if self.detail_coverage_issues:
            parts.append(f"coverage {len(self.detail_coverage_issues)}")
        return "; ".join(parts) if parts else "passed"

    def to_snapshot(self) -> dict[str, object]:
        return {
            "grounding_failures": list(self.grounding_failures),
            "writing_failures": list(self.writing_failures),
            "hard_failures": list(self.hard_failures),
            "soft_failures": list(self.soft_failures),
            "detail_coverage_issues": list(self.detail_coverage_issues),
            "metrics": dict(self.metrics),
            "next_recommended_stage": self.next_recommended_stage,
            "passed": self.passed,
        }

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> RewriteValidationBreakdown:
        data = migrate_validation_breakdown_snapshot(snapshot)
        return cls(
            grounding_failures=tuple(data["grounding_failures"]),
            writing_failures=tuple(data["writing_failures"]),
            hard_failures=tuple(data["hard_failures"]),
            soft_failures=tuple(data["soft_failures"]),
            detail_coverage_issues=tuple(data["detail_coverage_issues"]),
            metrics=dict(data["metrics"]),
            next_recommended_stage=data["next_recommended_stage"],
        )


@dataclass(frozen=True)
class RewriteState:
    job_id: str
    goal: RewriteGoal
    stage: LoopPhaseKind = "plan"
    draft: str = ""
    issues: tuple[str, ...] = ()
    rounds_left: int = 0
    covered_facts: tuple[str, ...] = ()
    style_constraints: tuple[str, ...] = ()
    evidence_bundle: EvidenceBundle = field(default_factory=EvidenceBundle)
    validation_breakdown: RewriteValidationBreakdown = field(default_factory=RewriteValidationBreakdown)
    budget: LoopBudget = field(default_factory=LoopBudget)
    trace: tuple[LoopTraceStep, ...] = ()
    failure: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _normalize_text(self.job_id))
        if not isinstance(self.goal, RewriteGoal):
            object.__setattr__(self, "goal", RewriteGoal.from_snapshot(self.goal))
        object.__setattr__(self, "stage", _normalize_phase_kind(self.stage))
        object.__setattr__(self, "draft", _normalize_text(self.draft))
        object.__setattr__(self, "issues", _normalize_text_tuple(self.issues))
        object.__setattr__(self, "rounds_left", max(0, _normalize_int(self.rounds_left, 0)))
        object.__setattr__(self, "covered_facts", _normalize_text_tuple(self.covered_facts))
        object.__setattr__(self, "style_constraints", _normalize_text_tuple(self.style_constraints))
        if not isinstance(self.evidence_bundle, EvidenceBundle):
            object.__setattr__(self, "evidence_bundle", EvidenceBundle.from_snapshot(self.evidence_bundle))
        if not isinstance(self.validation_breakdown, RewriteValidationBreakdown):
            object.__setattr__(
                self,
                "validation_breakdown",
                RewriteValidationBreakdown.from_snapshot(self.validation_breakdown),
            )
        if self.issues and self.validation_breakdown.passed and not self.validation_breakdown.combined_failures:
            object.__setattr__(
                self,
                "validation_breakdown",
                replace(self.validation_breakdown, hard_failures=self.issues),
            )
        if not isinstance(self.budget, LoopBudget):
            object.__setattr__(self, "budget", LoopBudget.from_snapshot(self.budget))
        object.__setattr__(
            self,
            "trace",
            tuple(step if isinstance(step, LoopTraceStep) else LoopTraceStep.from_snapshot(step) for step in self.trace),
        )
        object.__setattr__(self, "failure", _normalize_text(self.failure) or None)

    def with_draft(self, draft: str) -> RewriteState:
        return replace(self, draft=(draft or "").strip())

    def with_stage(self, stage: LoopPhaseKind) -> RewriteState:
        return replace(self, stage=_normalize_phase_kind(stage))

    def with_evidence_bundle(self, evidence_bundle: EvidenceBundle | Mapping[str, Any]) -> RewriteState:
        bundle = evidence_bundle if isinstance(evidence_bundle, EvidenceBundle) else EvidenceBundle.from_snapshot(evidence_bundle)
        return replace(self, evidence_bundle=bundle)

    def with_validation_breakdown(
        self, validation_breakdown: RewriteValidationBreakdown | Mapping[str, Any]
    ) -> RewriteState:
        breakdown = (
            validation_breakdown
            if isinstance(validation_breakdown, RewriteValidationBreakdown)
            else RewriteValidationBreakdown.from_snapshot(validation_breakdown)
        )
        issues = breakdown.combined_failures or self.issues
        return replace(self, validation_breakdown=breakdown, issues=issues)

    def with_issues(self, issues: tuple[str, ...]) -> RewriteState:
        normalized_issues = _normalize_text_tuple(issues)
        breakdown = self.validation_breakdown
        if normalized_issues and breakdown.passed and not breakdown.combined_failures:
            breakdown = replace(breakdown, hard_failures=normalized_issues)
        return replace(self, issues=normalized_issues, validation_breakdown=breakdown)

    def with_failure(self, failure: str | None) -> RewriteState:
        return replace(self, failure=(failure or None))

    def consume_round(self) -> RewriteState:
        return replace(self, rounds_left=max(0, self.rounds_left - 1))

    def consume_budget(self, token_cost: int = 0) -> RewriteState:
        return replace(self, budget=self.budget.consume(token_cost))

    def increment_retry(self, action_kind: LoopStepKind) -> RewriteState:
        return replace(self, budget=self.budget.increment_retry(action_kind))

    def increment_retry_for_stage(self, stage: LoopPhaseKind) -> RewriteState:
        return replace(self, budget=self.budget.increment_retry_for_stage(stage))

    def append_trace(self, step: LoopTraceStep) -> RewriteState:
        return replace(self, trace=self.trace + (step,))

    @property
    def validation_issues(self) -> tuple[str, ...]:
        return self.validation_breakdown.combined_failures or self.issues

    @property
    def evidence_summary(self) -> str:
        return self.evidence_bundle.summarize()

    @property
    def validation_summary(self) -> str:
        if self.validation_breakdown.combined_failures:
            return self.validation_breakdown.summarize()
        if self.issues:
            return "; ".join(self.issues[:2])
        return "passed"

    @property
    def recommended_stage(self) -> LoopPhaseKind:
        if self.failure:
            return "fail"
        if self.stage == "plan" and not self.draft and self.evidence_bundle.is_empty:
            return "collect_evidence"
        if not self.draft:
            return "collect_evidence" if self.evidence_bundle.is_empty else "outline"
        if self.validation_breakdown.grounding_failures:
            return "re_ground"
        if self.validation_breakdown.detail_coverage_issues:
            return "expand"
        if self.validation_breakdown.hard_failures:
            return "patch"
        if self.validation_breakdown.writing_failures or self.validation_breakdown.soft_failures:
            return "expand" if _should_expand_from_metrics(self.validation_breakdown.metrics) else "patch"
        return self.validation_breakdown.next_recommended_stage or "finalize"

    @property
    def can_finalize(self) -> bool:
        return not self.failure and not self.validation_issues and not self.evidence_bundle.has_grounding_gaps

    def to_snapshot(self) -> dict[str, object]:
        snapshot = {
            "job_id": self.job_id,
            "goal": self.goal.to_snapshot(),
            "stage": self.stage,
            "draft": self.draft,
            "draft_chars": len(self.draft),
            "issues": list(self.issues),
            "rounds_left": self.rounds_left,
            "covered_facts": list(self.covered_facts),
            "style_constraints": list(self.style_constraints),
            "budget": self.budget.to_snapshot(),
            "trace": [step.to_snapshot() for step in self.trace],
            "failure": self.failure,
        }
        if not self.evidence_bundle.is_empty:
            snapshot["evidence_bundle"] = self.evidence_bundle.to_snapshot()
        if not self.validation_breakdown.passed or self.validation_breakdown.next_recommended_stage != "finalize":
            snapshot["validation_breakdown"] = self.validation_breakdown.to_snapshot()
        return snapshot

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> RewriteState:
        data = migrate_rewrite_state_snapshot(snapshot)
        return cls(
            job_id=data["job_id"],
            goal=RewriteGoal.from_snapshot(data["goal"]),
            stage=data["stage"],
            draft=data["draft"],
            issues=tuple(data["issues"]),
            rounds_left=data["rounds_left"],
            covered_facts=tuple(data["covered_facts"]),
            style_constraints=tuple(data["style_constraints"]),
            evidence_bundle=EvidenceBundle.from_snapshot(data["evidence_bundle"]),
            validation_breakdown=RewriteValidationBreakdown.from_snapshot(data["validation_breakdown"]),
            budget=LoopBudget.from_snapshot(data["budget"]),
            trace=tuple(LoopTraceStep.from_snapshot(item) for item in data["trace"]),
            failure=data["failure"],
        )
