from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from app.services.rewrite_loop_action import LoopActionKind
from app.services.rewrite_loop_action import ALLOWED_LOOP_ACTION_KINDS


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_text_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_text(item) for item in value if _normalize_text(item))
    normalized = _normalize_text(value)
    return (normalized,) if normalized else ()


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


def _normalize_action_kind(value: Any) -> LoopActionKind:
    normalized = _normalize_text(value)
    if normalized not in ALLOWED_LOOP_ACTION_KINDS:
        raise ValueError(f"Unsupported loop action kind: {value!r}")
    return normalized  # type: ignore[return-value]


def _migrate_action_kind(value: Any) -> LoopActionKind:
    try:
        return _normalize_action_kind(value)
    except ValueError:
        return "stop"


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
        if normalized_kind not in ALLOWED_LOOP_ACTION_KINDS:
            continue
        counts[normalized_kind] = max(0, counts.get(normalized_kind, 0) + _normalize_int(count))
    return tuple(sorted(counts.items()))


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
            "draft": "",
            "draft_chars": 0,
            "issues": [],
            "rounds_left": 0,
            "covered_facts": [],
            "style_constraints": [],
            "budget": migrate_loop_budget_snapshot(None),
            "trace": [],
            "failure": None,
        }
    return {
        "job_id": _normalize_text(snapshot.get("job_id")),
        "goal": migrate_rewrite_goal_snapshot(snapshot.get("goal")),
        "draft": _normalize_text(snapshot.get("draft") or snapshot.get("draft_text")),
        "draft_chars": _normalize_int(snapshot.get("draft_chars"), 0),
        "issues": list(_normalize_text_tuple(snapshot.get("issues"))),
        "rounds_left": _normalize_int(snapshot.get("rounds_left"), 0),
        "covered_facts": list(_normalize_text_tuple(snapshot.get("covered_facts"))),
        "style_constraints": list(_normalize_text_tuple(snapshot.get("style_constraints"))),
        "budget": migrate_loop_budget_snapshot(snapshot.get("budget")),
        "trace": [
            migrate_loop_trace_step_snapshot(item)
            for item in (snapshot.get("trace") or [])
            if item is not None
        ],
        "failure": _normalize_text(snapshot.get("failure")) or None,
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

    def increment_retry(self, action_kind: LoopActionKind) -> LoopBudget:
        normalized = _normalize_action_kind(action_kind)
        counts = dict(self.action_retry_counts)
        counts[normalized] = counts.get(normalized, 0) + 1
        return replace(self, action_retry_counts=tuple(sorted(counts.items())))

    def retry_count(self, action_kind: LoopActionKind) -> int:
        return dict(self.action_retry_counts).get(_normalize_action_kind(action_kind), 0)

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
    action: LoopActionKind
    reason: str
    prompt_preview: str = ""
    input_chars: int = 0
    output_chars: int = 0
    tokens_used: int = 0
    validation_summary: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _normalize_action_kind(self.action))
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
class RewriteState:
    job_id: str
    goal: RewriteGoal
    draft: str = ""
    issues: tuple[str, ...] = ()
    rounds_left: int = 0
    covered_facts: tuple[str, ...] = ()
    style_constraints: tuple[str, ...] = ()
    budget: LoopBudget = field(default_factory=LoopBudget)
    trace: tuple[LoopTraceStep, ...] = ()
    failure: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _normalize_text(self.job_id))
        if not isinstance(self.goal, RewriteGoal):
            object.__setattr__(self, "goal", RewriteGoal.from_snapshot(self.goal))
        object.__setattr__(self, "draft", _normalize_text(self.draft))
        object.__setattr__(self, "issues", _normalize_text_tuple(self.issues))
        object.__setattr__(self, "rounds_left", max(0, _normalize_int(self.rounds_left, 0)))
        object.__setattr__(self, "covered_facts", _normalize_text_tuple(self.covered_facts))
        object.__setattr__(self, "style_constraints", _normalize_text_tuple(self.style_constraints))
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

    def with_issues(self, issues: tuple[str, ...]) -> RewriteState:
        return replace(self, issues=tuple(issues))

    def with_failure(self, failure: str | None) -> RewriteState:
        return replace(self, failure=(failure or None))

    def consume_round(self) -> RewriteState:
        return replace(self, rounds_left=max(0, self.rounds_left - 1))

    def consume_budget(self, token_cost: int = 0) -> RewriteState:
        return replace(self, budget=self.budget.consume(token_cost))

    def increment_retry(self, action_kind: LoopActionKind) -> RewriteState:
        return replace(self, budget=self.budget.increment_retry(action_kind))

    def append_trace(self, step: LoopTraceStep) -> RewriteState:
        return replace(self, trace=self.trace + (step,))

    def to_snapshot(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "goal": self.goal.to_snapshot(),
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

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> RewriteState:
        data = migrate_rewrite_state_snapshot(snapshot)
        return cls(
            job_id=data["job_id"],
            goal=RewriteGoal.from_snapshot(data["goal"]),
            draft=data["draft"],
            issues=tuple(data["issues"]),
            rounds_left=data["rounds_left"],
            covered_facts=tuple(data["covered_facts"]),
            style_constraints=tuple(data["style_constraints"]),
            budget=LoopBudget.from_snapshot(data["budget"]),
            trace=tuple(LoopTraceStep.from_snapshot(item) for item in data["trace"]),
            failure=data["failure"],
        )
