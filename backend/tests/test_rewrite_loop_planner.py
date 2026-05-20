from __future__ import annotations

from app.services.rewrite_loop_planner import decide_next_action
from app.services.rewrite_loop_state import (
    EvidenceBundle,
    LoopBudget,
    RewriteGoal,
    RewriteState,
    RewriteValidationBreakdown,
)
from app.services.rewrite_loop_validator import ValidationReport


def _state(
    *,
    draft: str = "",
    rounds_left: int = 2,
    evidence: bool = False,
    report: ValidationReport | None = None,
) -> RewriteState:
    evidence_bundle = (
        EvidenceBundle(
            required_fact_ids=("fact-1",),
            covered_fact_ids=("fact-1",) if evidence else (),
            missing_fact_ids=(),
            source_excerpt_hits=("excerpt",) if evidence else (),
            fact_snippets=("snippet",) if evidence else (),
            grounding_warnings=(),
        )
        if evidence
        else EvidenceBundle()
    )
    state = RewriteState(
        job_id="job-1",
        goal=RewriteGoal(
            rewrite_focus_raw="",
            rewrite_style="article_longform",
            skill_config_name="晚点",
            route_template_key="generic",
        ),
        draft=draft,
        rounds_left=rounds_left,
        budget=LoopBudget(),
        evidence_bundle=evidence_bundle,
    )
    if report is not None:
        breakdown = RewriteValidationBreakdown(
            grounding_failures=tuple(getattr(report, "grounding_failures", ())),
            writing_failures=tuple(getattr(report, "writing_failures", ())),
            hard_failures=tuple(getattr(report, "hard_failures", ())),
            soft_failures=tuple(getattr(report, "soft_failures", ())),
            detail_coverage_issues=tuple(getattr(report, "detail_coverage_issues", ())),
            metrics=dict(getattr(report, "metrics", {})),
            next_recommended_stage=getattr(report, "recommended_stage", "finalize") or "finalize",
        )
        state = state.with_validation_breakdown(breakdown)
    return state


def test_decide_next_action_collects_evidence_before_outline() -> None:
    action = decide_next_action(_state(draft=""), None)

    assert action.kind == "collect_evidence"
    assert action.metadata["next_recommended_action"] == "collect_evidence"


def test_decide_next_action_prefers_outline_with_evidence_but_no_draft() -> None:
    action = decide_next_action(_state(draft="", evidence=True), None)

    assert action.kind == "outline"
    assert action.metadata["next_recommended_action"] == "outline"


def test_decide_next_action_maps_validation_report_to_fixed_actions() -> None:
    grounding_report = ValidationReport(
        hard_failures=("hard issue",),
        soft_failures=(),
        grounding_failures=("hard issue",),
        recommended_stage="re_ground",
        next_recommended_action="patch",
    )
    expand_report = ValidationReport(
        hard_failures=(),
        soft_failures=("soft issue",),
        detail_coverage_issues=("missing detail",),
        writing_failures=("soft issue",),
        recommended_stage="expand",
        next_recommended_action="expand",
    )
    stop_report = ValidationReport(
        hard_failures=(),
        soft_failures=(),
        recommended_stage="finalize",
        next_recommended_action="stop",
    )

    grounding_action = decide_next_action(_state(draft="已有草稿", evidence=True, report=grounding_report), grounding_report)
    assert grounding_action.kind == "re_ground"
    assert grounding_action.metadata["next_recommended_action"] == "re_ground"

    expand_action = decide_next_action(_state(draft="已有草稿", evidence=True, report=expand_report), expand_report)
    assert expand_action.kind == "expand"
    assert expand_action.metadata["next_recommended_action"] == "expand"

    stop_action = decide_next_action(_state(draft="已有草稿", evidence=True, report=stop_report), stop_report)
    assert stop_action.kind == "stop"


def test_decide_next_action_stops_when_round_budget_is_empty() -> None:
    action = decide_next_action(_state(draft="已有草稿", rounds_left=0, evidence=True), None)

    assert action.kind == "stop"
    assert action.metadata["next_recommended_action"] == "stop"
