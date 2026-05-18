from __future__ import annotations

import pytest

from app.services.rewrite_loop_action import LoopAction
from app.services.rewrite_loop_action import migrate_loop_action_snapshot
from app.services.rewrite_loop_state import (
    LoopBudget,
    LoopTraceStep,
    RewriteGoal,
    RewriteState,
    migrate_loop_budget_snapshot,
    migrate_loop_trace_step_snapshot,
    migrate_rewrite_goal_snapshot,
    migrate_rewrite_state_snapshot,
)


def test_rewrite_state_snapshot_roundtrip_preserves_core_fields() -> None:
    state = RewriteState(
        job_id="job-123",
        goal=RewriteGoal(
            rewrite_focus_raw="保留重点",
            rewrite_style="article_longform",
            skill_config_name="晚点",
            route_template_key="06_infra_cloud_model_platform",
            route_template_label="基础设施",
            route_reason="匹配基础设施题材",
        ),
        draft="第一段。\n\n第二段。",
        issues=("third_person", "detail_gap"),
        rounds_left=3,
        covered_facts=("fact-1", "fact-2"),
        style_constraints=("第三视角", "保留细节"),
        budget=LoopBudget(
            max_rounds=4,
            max_total_tokens=12_000,
            max_retries_per_action=2,
            max_patch_ratio_per_round=0.25,
            spent_tokens=321,
            action_retry_counts=(("patch", 1),),
        ),
        trace=(
            LoopTraceStep(
                action="draft",
                reason="需要初稿",
                prompt_preview="prompt preview",
                input_chars=128,
                output_chars=256,
                tokens_used=512,
                validation_summary="ok",
                metadata={"stage": "draft"},
            ),
        ),
        failure="",
    )

    snapshot = state.to_snapshot()
    rebuilt = RewriteState.from_snapshot(snapshot)

    assert rebuilt.job_id == "job-123"
    assert rebuilt.goal.route_template_key == "06_infra_cloud_model_platform"
    assert rebuilt.draft == "第一段。\n\n第二段。"
    assert rebuilt.issues == ("third_person", "detail_gap")
    assert rebuilt.rounds_left == 3
    assert rebuilt.covered_facts == ("fact-1", "fact-2")
    assert rebuilt.style_constraints == ("第三视角", "保留细节")
    assert rebuilt.budget.max_rounds == 4
    assert rebuilt.budget.spent_tokens == 321
    assert rebuilt.budget.retry_count("patch") == 1
    assert len(rebuilt.trace) == 1
    assert rebuilt.trace[0].action == "draft"
    assert rebuilt.failure is None


def test_rewrite_state_snapshot_migrates_legacy_keys_and_normalizes_values() -> None:
    legacy_snapshot = {
        "job_id": 42,
        "goal": {
            "rewrite_focus_raw": "  长文 ",
            "rewrite_style": " article_longform ",
            "skill_config_name": " latepost ",
            "route_template_key": " generic ",
            "route_template_label": " 基础设施 ",
            "route_reason": " reason ",
        },
        "draft_text": "  legacy draft  ",
        "issues": [" first ", "", None],
        "rounds_left": "2",
        "covered_facts": (" fact-a ", "fact-b", ""),
        "style_constraints": [" third person ", " detailed "],
        "budget": {
            "max_rounds": "8",
            "max_total_tokens": "9000",
            "max_retries_per_action": "3",
            "max_patch_ratio_per_round": "0.4",
            "spent_tokens": "50",
            "action_retry_counts": [("patch", 2), {"kind": "expand", "count": 1}],
        },
        "trace": [
            {
                "action": "outline",
                "reason": " need outline ",
                "prompt_preview": " preview ",
                "input_chars": "10",
                "output_chars": "20",
                "tokens_used": "30",
                "validation_summary": " ok ",
                "metadata": {"stage": "outline"},
            },
            None,
        ],
        "failure": " ",
    }

    rebuilt = RewriteState.from_snapshot(legacy_snapshot)

    assert rebuilt.job_id == "42"
    assert rebuilt.goal.rewrite_focus_raw == "长文"
    assert rebuilt.draft == "legacy draft"
    assert rebuilt.issues == ("first",)
    assert rebuilt.rounds_left == 2
    assert rebuilt.covered_facts == ("fact-a", "fact-b")
    assert rebuilt.style_constraints == ("third person", "detailed")
    assert rebuilt.budget.max_rounds == 8
    assert rebuilt.budget.max_total_tokens == 9000
    assert rebuilt.budget.max_retries_per_action == 3
    assert rebuilt.budget.max_patch_ratio_per_round == 0.4
    assert rebuilt.budget.spent_tokens == 50
    assert rebuilt.budget.retry_count("patch") == 2
    assert rebuilt.budget.retry_count("expand") == 1
    assert rebuilt.trace[0].action == "outline"
    assert rebuilt.failure is None


def test_loop_action_and_snapshot_helpers_reject_invalid_action_kind() -> None:
    with pytest.raises(ValueError, match="Unsupported loop action kind"):
        LoopAction(kind="summarize", reason="bad action")  # type: ignore[arg-type]

    assert migrate_loop_action_snapshot({"kind": "summarize"})["kind"] == "stop"
    assert migrate_rewrite_goal_snapshot(None)["route_template_key"] == ""
    assert migrate_loop_budget_snapshot(None)["max_rounds"] == 6
    assert migrate_loop_trace_step_snapshot(None)["action"] == "stop"
    assert migrate_rewrite_state_snapshot(None)["job_id"] == ""
