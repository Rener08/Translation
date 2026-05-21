from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.article_generation_service import (
    ArticleValidationResult,
    measure_source_text_length,
    validate_generated_article,
)
from app.services.detail_ledger import DetailLedger, analyze_detail_coverage_enhanced
from app.services.quality_check_service import check_article_quality
from app.services.rewrite_loop_action import LoopActionKind
from app.services.skill_config_service import SkillConfig


@dataclass(frozen=True)
class ValidationReport:
    hard_failures: tuple[str, ...]
    soft_failures: tuple[str, ...]
    grounding_failures: tuple[str, ...] = ()
    writing_failures: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    next_recommended_action: LoopActionKind = "stop"
    recommended_stage: str = ""
    recommendation_reason: str = ""
    detail_coverage_issues: tuple[str, ...] = ()
    evidence_bundle: dict[str, Any] = field(default_factory=dict)
    article_validation: ArticleValidationResult | None = None

    @property
    def passed(self) -> bool:
        return (
            not self.hard_failures
            and not self.grounding_failures
            and not self.writing_failures
            and not self.soft_failures
            and not self.detail_coverage_issues
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "hard_failures": list(self.hard_failures),
            "soft_failures": list(self.soft_failures),
            "grounding_failures": list(self.grounding_failures),
            "writing_failures": list(self.writing_failures),
            "metrics": dict(self.metrics),
            "next_recommended_action": self.next_recommended_action,
            "recommended_stage": self.recommended_stage,
            "recommendation_reason": self.recommendation_reason,
            "detail_coverage_issues": list(self.detail_coverage_issues),
            "evidence_bundle": dict(self.evidence_bundle),
            "passed": self.passed,
        }


def validate_longform_rewrite(
    *,
    text: str,
    source_text: str,
    skill_config: SkillConfig,
    detail_ledger: DetailLedger | None = None,
) -> ValidationReport:
    normalized_text = (text or "").strip()
    normalized_source = (source_text or "").strip()
    grounding_failures: list[str] = []
    writing_failures: list[str] = []
    detail_coverage_signals: list[str] = []
    soft_failures: list[str] = []
    evidence_bundle, detail_coverage_issues = _build_evidence_bundle(
        detail_ledger,
        normalized_text,
    )

    article_validation = validate_generated_article(
        normalized_text,
        _resolve_article_spec(normalized_source),
    )
    if not article_validation.ok:
        writing_failures.extend(article_validation.issues)

    quality_report = check_article_quality(
        normalized_text,
        normalized_source,
        skill_config,
        detail_ledger,
        precomputed_detail_coverage_issues=detail_coverage_issues,
    )
    for issue in quality_report.issues:
        if issue.check_type == "detail_coverage":
            detail_coverage_signals.append(issue.message)
            continue
        if issue.severity == "hard":
            if _is_grounding_issue(issue):
                grounding_failures.append(issue.message)
            else:
                writing_failures.append(issue.message)
        else:
            soft_failures.append(issue.message)

    detail_coverage_issues = _dedupe_preserving_order(
        [*detail_coverage_issues, *detail_coverage_signals]
    )

    soft_failures.extend(_detect_readability_soft_signals(normalized_text))

    hard_failures = _dedupe_preserving_order([*grounding_failures, *writing_failures])
    grounding_failures = _dedupe_preserving_order(grounding_failures)
    writing_failures = _dedupe_preserving_order(writing_failures)
    detail_coverage_issues = _dedupe_preserving_order(list(detail_coverage_issues))
    soft_failures = _dedupe_preserving_order(soft_failures)

    recommended_stage = _recommend_stage(
        grounding_failures=grounding_failures,
        writing_failures=writing_failures,
        soft_failures=soft_failures,
        detail_coverage_issues=detail_coverage_issues,
        evidence_bundle=evidence_bundle,
    )
    metrics = {
        "source_chars": measure_source_text_length(normalized_source),
        "output_chars": measure_source_text_length(normalized_text),
        "section_count": article_validation.section_count,
        "section_chars": list(article_validation.section_chars),
        "hard_issue_count": len(hard_failures),
        "soft_issue_count": len(soft_failures),
        "detail_coverage_issue_count": len(detail_coverage_issues),
        "grounding_issue_count": len(grounding_failures),
        "writing_issue_count": len(writing_failures),
        "evidence_available": bool(evidence_bundle.get("available")),
        "required_fact_count": int(evidence_bundle.get("required_fact_count", 0) or 0),
        "covered_fact_count": int(evidence_bundle.get("covered_fact_count", 0) or 0),
        "missing_fact_count": int(evidence_bundle.get("missing_fact_count", 0) or 0),
        "coverage_rate": float(evidence_bundle.get("coverage_rate", 0.0) or 0.0),
    }
    source_chars = int(metrics["source_chars"] or 0)
    output_chars = int(metrics["output_chars"] or 0)
    metrics["length_ratio"] = round(output_chars / source_chars, 4) if source_chars else 0.0
    evidence_bundle["source_chars"] = source_chars
    evidence_bundle["output_chars"] = output_chars
    evidence_bundle["length_ratio"] = metrics["length_ratio"]

    next_action = _recommend_action(
        grounding_failures=grounding_failures,
        writing_failures=writing_failures,
        soft_failures=tuple(soft_failures),
        detail_coverage_issues=detail_coverage_issues,
        recommended_stage=recommended_stage,
    )

    return ValidationReport(
        hard_failures=hard_failures,
        soft_failures=soft_failures,
        grounding_failures=grounding_failures,
        writing_failures=writing_failures,
        metrics=metrics,
        next_recommended_action=next_action,
        recommended_stage=recommended_stage,
        recommendation_reason=_recommendation_reason(
            recommended_stage=recommended_stage,
            grounding_failures=grounding_failures,
            writing_failures=writing_failures,
            soft_failures=soft_failures,
            evidence_bundle=evidence_bundle,
        ),
        detail_coverage_issues=detail_coverage_issues,
        evidence_bundle=evidence_bundle,
        article_validation=article_validation,
    )


def _recommend_action(
    *,
    grounding_failures: tuple[str, ...],
    writing_failures: tuple[str, ...],
    soft_failures: tuple[str, ...],
    detail_coverage_issues: tuple[str, ...],
    recommended_stage: str,
) -> LoopActionKind:
    if recommended_stage == "collect_evidence":
        return "outline"
    if recommended_stage == "re_ground":
        return "patch"
    if recommended_stage == "patch":
        return "patch"
    if recommended_stage == "expand":
        return "expand"
    if recommended_stage in {"finalize", "fail"}:
        return "stop"
    if grounding_failures:
        return "patch"
    if writing_failures:
        return "patch"
    if detail_coverage_issues:
        return "expand"
    if soft_failures:
        return "expand"
    return "stop"


def _recommend_stage(
    *,
    grounding_failures: tuple[str, ...],
    writing_failures: tuple[str, ...],
    soft_failures: tuple[str, ...],
    detail_coverage_issues: tuple[str, ...],
    evidence_bundle: dict[str, Any],
) -> str:
    evidence_available = bool(evidence_bundle.get("available"))
    if not evidence_available and (
        grounding_failures or writing_failures or soft_failures or detail_coverage_issues
    ):
        return "collect_evidence"
    if grounding_failures:
        return "re_ground" if evidence_available else "collect_evidence"
    if writing_failures:
        if _should_expand_for_writing(writing_failures, evidence_bundle, soft_failures):
            return "expand"
        return "patch"
    if detail_coverage_issues:
        return "expand"
    if soft_failures:
        return "expand" if _should_expand_for_soft_signals(soft_failures, evidence_bundle) else "patch"
    return "finalize"


def _recommendation_reason(
    *,
    recommended_stage: str,
    grounding_failures: tuple[str, ...],
    writing_failures: tuple[str, ...],
    soft_failures: tuple[str, ...],
    evidence_bundle: dict[str, Any],
) -> str:
    if recommended_stage == "collect_evidence":
        return "证据包缺失或不可用，先补齐证据再判断修订方向。"
    if recommended_stage == "re_ground":
        return "存在 grounding 问题，需要回查证据并重新对齐原文。"
    if recommended_stage == "patch":
        return "主要问题集中在写作表达或结构，优先局部修订。"
    if recommended_stage == "expand":
        return "篇幅、层次或软性写作问题仍在，优先扩写补强。"
    if recommended_stage == "finalize":
        return "验证通过。"
    if recommended_stage == "fail":
        return "当前草稿无法在现有约束下继续推进。"
    if grounding_failures:
        return f"存在 {len(grounding_failures)} 个 grounding 问题。"
    if writing_failures:
        return f"存在 {len(writing_failures)} 个 writing 问题。"
    if soft_failures:
        return f"存在 {len(soft_failures)} 个软性问题。"
    if not evidence_bundle.get("available"):
        return "证据包不可用。"
    return "验证通过。"


def _should_expand_for_writing(
    writing_failures: tuple[str, ...],
    evidence_bundle: dict[str, Any],
    soft_failures: tuple[str, ...],
) -> bool:
    if _should_expand_for_soft_signals(soft_failures, evidence_bundle):
        return True
    if not writing_failures:
        return False
    length_ratio = float(evidence_bundle.get("length_ratio", 0.0) or 0.0)
    if 0.0 < length_ratio < 0.55:
        return True
    if any("Total chars" in issue or "Section" in issue for issue in writing_failures):
        return True
    return False


def _ledger_item_id(kind: str, text: str) -> str:
    return f"{kind}:{' '.join((text or '').split())}"


def _should_expand_for_soft_signals(
    soft_failures: tuple[str, ...],
    evidence_bundle: dict[str, Any],
) -> bool:
    if not soft_failures:
        return False
    for issue in soft_failures:
        normalized = (issue or "").lower()
        if any(marker in normalized for marker in ("字数", "length", "篇幅")):
            return True
    length_ratio = float(evidence_bundle.get("length_ratio", 0.0) or 0.0)
    output_chars = int(evidence_bundle.get("output_chars", 0) or 0)
    source_chars = int(evidence_bundle.get("source_chars", 0) or 0)
    if source_chars and output_chars and output_chars < max(1, round(source_chars * 0.55)):
        return True
    return 0.0 < length_ratio < 0.55


def _is_grounding_issue(issue) -> bool:
    check_type = getattr(issue, "check_type", "")
    if check_type in {
        "detail_coverage",
        "no_fabrication",
        "evidence_support",
        "judgment_follows_fact",
        "mechanism_explained",
        "cost_and_boundary",
        "specific_subjects",
    }:
        return True

    message = (getattr(issue, "message", "") or "").lower()
    grounding_markers = ("事实", "证据", "原文", "细节", "依据", "引用", "证明")
    return any(marker in message for marker in grounding_markers)


def _build_evidence_bundle(
    detail_ledger: DetailLedger | None,
    rewritten_text: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if detail_ledger is None or not detail_ledger.items:
        return {
            "available": False,
            "required_fact_ids": (),
            "covered_fact_ids": (),
            "missing_fact_ids": (),
            "source_excerpt_hits": (),
            "fact_snippets": {},
            "grounding_warnings": ("证据包不可用。",),
            "required_fact_texts": (),
            "covered_fact_texts": (),
            "missing_fact_texts": (),
            "required_fact_count": 0,
            "covered_fact_count": 0,
            "missing_fact_count": 0,
            "coverage_rate": 0.0,
        }, ()

    coverage = analyze_detail_coverage_enhanced(detail_ledger, rewritten_text)
    required_items = tuple(detail_ledger.items)
    missing_items = tuple(coverage.missing_items)
    covered_items = tuple(item for item in required_items if item not in missing_items)

    required_fact_ids = tuple(_ledger_item_id(item.kind, item.text) for item in required_items)
    covered_fact_ids = tuple(_ledger_item_id(item.kind, item.text) for item in covered_items)
    missing_fact_ids = tuple(_ledger_item_id(item.kind, item.text) for item in missing_items)
    coverage_rate = round(len(covered_items) / len(required_items), 4) if required_items else 0.0

    return {
        "available": True,
        "required_fact_ids": required_fact_ids,
        "covered_fact_ids": covered_fact_ids,
        "missing_fact_ids": missing_fact_ids,
        "source_excerpt_hits": tuple(item.text for item in covered_items[:6]),
        "fact_snippets": {
            _ledger_item_id(item.kind, item.text): item.text for item in required_items
        },
        "grounding_warnings": tuple(f"{item.kind} {item.text}" for item in missing_items),
        "required_fact_texts": tuple(item.text for item in required_items),
        "covered_fact_texts": tuple(item.text for item in covered_items),
        "missing_fact_texts": tuple(item.text for item in missing_items),
        "required_fact_count": len(required_items),
        "covered_fact_count": len(covered_items),
        "missing_fact_count": len(missing_items),
        "coverage_rate": coverage_rate,
        "length_ratio": 0.0,
    }, tuple(f"{item.kind} {item.text}" for item in missing_items)


def _detect_readability_soft_signals(text: str) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return ["输出为空。"]

    paragraphs = [
        block.strip()
        for block in normalized.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
        if block.strip()
    ]
    if not paragraphs:
        paragraphs = [normalized]

    soft: list[str] = []
    if len(set(paragraphs)) < len(paragraphs):
        soft.append("检测到重复段落，建议局部改写并增强段落之间的区分。")

    transition_markers = ("此外", "同时", "不过", "然而", "因此", "总之", "从这个角度看")
    marker_hits = sum(normalized.count(marker) for marker in transition_markers)
    if marker_hits >= 8:
        soft.append("过渡词重复过多，阅读感偏模板化。")
    return soft


def _dedupe_preserving_order(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _resolve_article_spec(source_text: str):
    from app.services.article_generation_service import resolve_article_spec

    return resolve_article_spec(source_text, thin=True)
