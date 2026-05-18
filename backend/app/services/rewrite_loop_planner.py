from __future__ import annotations

from app.services.rewrite_loop_action import LoopAction
from app.services.rewrite_loop_state import RewriteState
from app.services.rewrite_loop_validator import ValidationReport


def decide_next_action(state: RewriteState, report: ValidationReport | None) -> LoopAction:
    if state.rounds_left <= 0:
        return LoopAction(
            kind="stop",
            reason="已达到剩余轮数上限。",
            metadata={"next_recommended_action": "stop"},
        )

    if not state.draft.strip():
        return LoopAction(
            kind="outline",
            reason="当前还没有可用正文，需要先生成大纲。",
            metadata={"next_recommended_action": "outline"},
        )

    if report is None:
        return LoopAction(
            kind="draft",
            reason="缺少验证结果，继续生成正文。",
            metadata={"next_recommended_action": "draft"},
        )

    recommended = _normalize_action_kind(report.next_recommended_action)

    if report.hard_failures:
        return LoopAction(
            kind="patch",
            reason="存在硬性问题，需要局部修订。",
            metadata={
                "next_recommended_action": "patch",
                "hard_failures": list(report.hard_failures),
            },
        )

    if report.detail_coverage_issues or report.soft_failures:
        return LoopAction(
            kind="expand",
            reason="细节或篇幅仍不足，需要扩写补强。",
            metadata={
                "next_recommended_action": recommended or "expand",
                "detail_coverage_issues": list(report.detail_coverage_issues),
                "soft_failures": list(report.soft_failures),
            },
        )

    return LoopAction(
        kind="stop",
        reason="验证已通过，可以收束。",
        metadata={"next_recommended_action": "stop"},
    )


def _normalize_action_kind(value: str | None) -> str:
    if value in {"outline", "draft", "expand", "patch", "stop"}:
        return value
    return ""
