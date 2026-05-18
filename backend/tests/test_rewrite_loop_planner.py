from __future__ import annotations

from app.services.rewrite_loop_action import LoopAction
from app.services.rewrite_loop_planner import decide_next_action
from app.services.rewrite_loop_state import LoopBudget, RewriteGoal, RewriteState
from app.services.rewrite_loop_validator import ValidationReport


def _state(*, draft: str = "", rounds_left: int = 2) -> RewriteState:
    return RewriteState(
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
    )


def test_decide_next_action_prefers_outline_without_draft() -> None:
    action = decide_next_action(_state(draft=""), None)

    assert action.kind == "outline"
    assert action.metadata["next_recommended_action"] == "outline"


def test_decide_next_action_returns_draft_when_report_missing_and_draft_exists() -> None:
    action = decide_next_action(_state(draft="已有草稿"), None)

    assert action.kind == "draft"
    assert action.metadata["next_recommended_action"] == "draft"


def test_decide_next_action_maps_validation_report_to_fixed_actions() -> None:
    patch_report = ValidationReport(
        hard_failures=("hard issue",),
        soft_failures=(),
        next_recommended_action="patch",
    )
    expand_report = ValidationReport(
        hard_failures=(),
        soft_failures=("soft issue",),
        detail_coverage_issues=("missing detail",),
        next_recommended_action="expand",
    )
    stop_report = ValidationReport(
        hard_failures=(),
        soft_failures=(),
        next_recommended_action="stop",
    )

    assert decide_next_action(_state(draft="已有草稿"), patch_report).kind == "patch"

    expand_action = decide_next_action(_state(draft="已有草稿"), expand_report)
    assert expand_action.kind == "expand"
    assert expand_action.metadata["next_recommended_action"] == "expand"

    stop_action = decide_next_action(_state(draft="已有草稿"), stop_report)
    assert stop_action.kind == "stop"


def test_decide_next_action_stops_when_round_budget_is_empty() -> None:
    action = decide_next_action(_state(draft="已有草稿", rounds_left=0), None)

    assert action.kind == "stop"
    assert action.metadata["next_recommended_action"] == "stop"
