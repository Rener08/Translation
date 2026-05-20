from __future__ import annotations

from app.services.rewrite_loop_action import LoopAction
from app.services.rewrite_loop_state import RewriteState
from app.services.rewrite_loop_validator import ValidationReport


def decide_next_action(state: RewriteState, report: ValidationReport | None) -> LoopAction:
    if state.rounds_left <= 0:
        return _stop_action(reason="已达到剩余轮数上限。", next_stage="fail")

    if state.budget.spent_tokens >= state.budget.max_total_tokens:
        return _stop_action(reason="已达到总 token 预算上限。", next_stage="fail")

    policy_stage = _policy_stage_from_report(report)

    if not state.draft.strip():
        if report is not None and policy_stage:
            kind = _kind_for_stage(policy_stage, state)
            return _build_action(
                state=state,
                kind=kind,
                stage=policy_stage,
                reason=_reason_for_stage(policy_stage, report),
                report=report,
            )
        if state.evidence_bundle.is_empty:
            return _build_action(
                state=state,
                kind="collect_evidence",
                stage="collect_evidence",
                reason="当前还没有可用正文，也没有证据包，需要先收集证据。",
                report=report,
            )
        return _build_action(
            state=state,
            kind="outline",
            stage="outline",
            reason="当前还没有可用正文，需要先生成大纲。",
            report=report,
        )

    if report is None:
        stage = "collect_evidence" if state.evidence_bundle.is_empty else "draft"
        return _build_action(
            state=state,
            kind="collect_evidence" if stage == "collect_evidence" else "draft",
            stage=stage,
            reason=(
                "证据包不足，先收集证据再生成正文。"
                if stage == "collect_evidence"
                else "缺少验证结果，继续生成正文。"
            ),
            report=None,
        )

    if policy_stage:
        kind = _kind_for_stage(policy_stage, state)
        if _retry_limit_reached(state, kind):
            return _stop_action(
                reason=_retry_limit_reason(kind, state),
                next_stage="fail",
                report=report,
            )
        return _build_action(
            state=state,
            kind=kind,
            stage=policy_stage,
            reason=getattr(report, "recommendation_reason", "") or _reason_for_stage(policy_stage, report),
            report=report,
        )

    kind = _legacy_kind_from_report(report)
    if _retry_limit_reached(state, kind):
        return _stop_action(
            reason=_retry_limit_reason(kind, state),
            next_stage="fail",
            report=report,
        )

    stage = _legacy_stage_from_report(report)
    return _build_action(
        state=state,
        kind=kind,
        stage=stage,
        reason=_legacy_reason_from_report(report, stage),
        report=report,
    )


def _build_action(
    *,
    state: RewriteState,
    kind: str,
    stage: str,
    reason: str,
    report: ValidationReport | None,
) -> LoopAction:
    metadata: dict[str, object] = {
        "next_recommended_stage": _normalize_stage(stage) or "finalize",
        "next_recommended_action": kind,
        "current_stage": state.stage or "plan",
        "draft_chars": len(state.draft.strip()),
        "rounds_left": state.rounds_left,
        "remaining_budget": max(0, state.budget.max_total_tokens - state.budget.spent_tokens),
        "retry_count": state.budget.retry_count(kind),
        "retry_limit": state.budget.max_retries_per_action,
        "evidence_summary": state.evidence_summary,
    }
    if report is not None:
        metadata.update(
            {
                "grounding_failures": list(report.grounding_failures),
                "writing_failures": list(report.writing_failures),
                "soft_failures": list(report.soft_failures),
                "detail_coverage_issues": list(report.detail_coverage_issues),
                "recommendation_reason": getattr(report, "recommendation_reason", ""),
                "evidence_bundle": dict(report.evidence_bundle),
            }
        )
    return LoopAction(kind=kind, reason=reason, metadata=metadata)


def _stop_action(*, reason: str, next_stage: str, report: ValidationReport | None = None) -> LoopAction:
    metadata: dict[str, object] = {
        "next_recommended_stage": _normalize_stage(next_stage) or "fail",
        "next_recommended_action": "stop",
    }
    if report is not None:
        metadata.update(
            {
                "grounding_failures": list(report.grounding_failures),
                "writing_failures": list(report.writing_failures),
                "soft_failures": list(report.soft_failures),
                "detail_coverage_issues": list(report.detail_coverage_issues),
                "recommendation_reason": getattr(report, "recommendation_reason", ""),
            }
        )
    return LoopAction(kind="stop", reason=reason, metadata=metadata)


def _kind_for_stage(stage: str, state: RewriteState) -> str:
    normalized = _normalize_stage(stage)
    if normalized == "collect_evidence":
        return "collect_evidence"
    if normalized == "plan":
        return "collect_evidence" if state.evidence_bundle.is_empty else "outline"
    if normalized == "re_ground":
        return "re_ground"
    if normalized == "patch":
        return "patch"
    if normalized == "expand":
        return "expand"
    if normalized in {"finalize", "fail"}:
        return "stop"
    if normalized == "outline":
        return "outline"
    if normalized == "draft":
        return "draft"
    if normalized == "validate":
        return "draft"
    return _legacy_kind_from_stage(normalized)


def _legacy_kind_from_stage(stage: str) -> str:
    if stage == "plan":
        return "collect_evidence"
    if stage == "collect_evidence":
        return "collect_evidence"
    if stage == "outline":
        return "outline"
    if stage in {"draft", "validate"}:
        return "draft"
    if stage in {"re_ground", "patch"}:
        return "patch"
    if stage == "expand":
        return "expand"
    return "stop"


def _legacy_kind_from_report(report: ValidationReport) -> str:
    if report.grounding_failures:
        return "patch"
    if report.detail_coverage_issues:
        return "expand"
    if report.soft_failures:
        return "expand" if _should_expand_from_report(report) else "patch"
    if report.hard_failures:
        return "patch"
    return "stop"


def _legacy_stage_from_report(report: ValidationReport) -> str:
    if report.grounding_failures:
        return "re_ground"
    if report.detail_coverage_issues:
        return "expand"
    if report.hard_failures:
        return "patch"
    if report.soft_failures:
        return "expand" if _should_expand_from_report(report) else "patch"
    return "finalize"


def _legacy_reason_from_report(report: ValidationReport, stage: str) -> str:
    if report.grounding_failures and stage == "re_ground":
        return "存在 grounding 问题，需要回查证据。"
    if report.hard_failures and stage == "patch":
        return "存在硬性问题，需要局部修订。"
    if report.detail_coverage_issues:
        return "细节仍有缺口，需要扩写补强。"
    if report.soft_failures:
        return "存在软性问题，需要继续优化。"
    return "验证已通过，可以收束。"


def _policy_stage_from_report(report: ValidationReport | None) -> str:
    if report is None:
        return ""

    explicit_stage = _normalize_stage(getattr(report, "recommended_stage", ""))
    if explicit_stage:
        return explicit_stage

    if report.grounding_failures:
        return "re_ground"
    if report.detail_coverage_issues:
        return "expand"
    if report.writing_failures:
        return "expand" if _should_expand_from_report(report) else "patch"
    if report.soft_failures:
        return "expand" if _should_expand_from_report(report) else "patch"
    if report.hard_failures:
        return "patch"
    if getattr(report, "passed", False):
        return "finalize"
    return ""


def _should_expand_from_report(report: ValidationReport) -> bool:
    metrics = dict(getattr(report, "metrics", {}) or {})
    if _should_expand_from_metrics(metrics):
        return True

    evidence_bundle = dict(getattr(report, "evidence_bundle", {}) or {})
    length_ratio = float(evidence_bundle.get("length_ratio", 0.0) or 0.0)
    output_chars = int(evidence_bundle.get("output_chars", 0) or 0)
    source_chars = int(evidence_bundle.get("source_chars", 0) or 0)
    if source_chars and output_chars and output_chars < max(1, round(source_chars * 0.55)):
        return True
    return 0.0 < length_ratio < 0.55


def _retry_limit_reached(state: RewriteState, kind: str) -> bool:
    if kind not in {"re_ground", "patch", "expand"}:
        return False
    return state.budget.retry_count(kind) >= state.budget.max_retries_per_action


def _retry_limit_reason(kind: str, state: RewriteState) -> str:
    return (
        f"{kind} 已达到单动作重试上限 {state.budget.max_retries_per_action}，"
        "为避免重复循环，先停止并交回。"
    )


def _should_expand_from_metrics(metrics: dict[str, object]) -> bool:
    length_ratio = float(metrics.get("length_ratio", 0.0) or 0.0)
    output_chars = int(metrics.get("output_chars", 0) or 0)
    source_chars = int(metrics.get("source_chars", 0) or 0)
    if source_chars and output_chars and output_chars < max(1, round(source_chars * 0.55)):
        return True
    return 0.0 < length_ratio < 0.55


def _reason_for_stage(stage: str, report: ValidationReport | None = None) -> str:
    normalized = _normalize_stage(stage)
    if normalized == "collect_evidence":
        return "证据包不足，先收集证据再继续。"
    if normalized == "re_ground":
        return "存在 grounding 问题，需要回查证据。"
    if normalized == "patch":
        return "存在写作或结构问题，需要局部修订。"
    if normalized == "expand":
        return "篇幅或层次仍不足，需要扩写补强。"
    if normalized == "finalize":
        return "验证通过，可以收束。"
    if normalized == "fail":
        return "当前草稿无法在现有约束下继续推进。"
    if report is not None and getattr(report, "recommendation_reason", ""):
        return report.recommendation_reason
    return "继续推进当前草稿。"


def _normalize_stage(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized in {
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
    }:
        return normalized
    return ""
