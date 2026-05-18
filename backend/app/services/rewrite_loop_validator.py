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
    metrics: dict[str, Any] = field(default_factory=dict)
    next_recommended_action: LoopActionKind = "stop"
    detail_coverage_issues: tuple[str, ...] = ()
    article_validation: ArticleValidationResult | None = None

    @property
    def passed(self) -> bool:
        return not self.hard_failures and not self.soft_failures and not self.detail_coverage_issues

    def to_snapshot(self) -> dict[str, object]:
        return {
            "hard_failures": list(self.hard_failures),
            "soft_failures": list(self.soft_failures),
            "metrics": dict(self.metrics),
            "next_recommended_action": self.next_recommended_action,
            "detail_coverage_issues": list(self.detail_coverage_issues),
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
    hard_failures: list[str] = []
    soft_failures: list[str] = []

    article_validation = validate_generated_article(normalized_text, _resolve_article_spec(normalized_source))
    if not article_validation.ok:
        hard_failures.extend(article_validation.issues)

    quality_report = check_article_quality(
        normalized_text,
        normalized_source,
        skill_config,
        detail_ledger,
    )
    detail_coverage_issues: list[str] = []
    for issue in quality_report.issues:
        if issue.check_type == "detail_coverage":
            detail_coverage_issues.append(issue.message)
            continue
        if issue.severity == "hard":
            hard_failures.append(issue.message)
        else:
            soft_failures.append(issue.message)

    missing_detail_issues: tuple[str, ...] = tuple(detail_coverage_issues)
    if detail_ledger is not None:
        coverage = analyze_detail_coverage_enhanced(detail_ledger, normalized_text)
        missing_detail_issues = tuple(
            f"{item.kind} {item.text}" for item in coverage.missing_items
        )

    soft_failures.extend(_detect_readability_soft_signals(normalized_text))

    metrics = {
        "source_chars": measure_source_text_length(normalized_source),
        "output_chars": measure_source_text_length(normalized_text),
        "section_count": article_validation.section_count,
        "section_chars": list(article_validation.section_chars),
        "hard_issue_count": len(hard_failures),
        "soft_issue_count": len(soft_failures),
        "detail_coverage_issue_count": len(missing_detail_issues),
    }
    source_chars = int(metrics["source_chars"] or 0)
    output_chars = int(metrics["output_chars"] or 0)
    metrics["length_ratio"] = round(output_chars / source_chars, 4) if source_chars else 0.0

    next_action = _recommend_action(
        hard_failures=tuple(hard_failures),
        soft_failures=tuple(soft_failures),
        missing_detail_issues=missing_detail_issues,
    )

    return ValidationReport(
        hard_failures=_dedupe_preserving_order(hard_failures),
        soft_failures=_dedupe_preserving_order(soft_failures),
        metrics=metrics,
        next_recommended_action=next_action,
        detail_coverage_issues=missing_detail_issues,
        article_validation=article_validation,
    )


def _recommend_action(
    *,
    hard_failures: tuple[str, ...],
    soft_failures: tuple[str, ...],
    missing_detail_issues: tuple[str, ...],
) -> LoopActionKind:
    if hard_failures:
        return "patch"
    if missing_detail_issues:
        return "expand"
    if soft_failures:
        return "expand"
    return "stop"


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

    return resolve_article_spec(source_text)
