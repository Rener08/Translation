"""Quality check service: validate output articles against SkillConfig rules."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.detail_ledger import (
    DetailLedger,
    analyze_detail_coverage_enhanced,
    build_detail_ledger,
)
from app.services.skill_config_service import SkillConfig, SkillOutputSpec, StyleConstraint


@dataclass(frozen=True)
class QualityIssue:
    layer: str
    check_type: str
    position: int
    matched: str
    message: str
    fix_hint: str


@dataclass(frozen=True)
class QualityReport:
    passed: bool
    issues: tuple[QualityIssue, ...]
    layers_checked: int
    layers_passed: int


def _check_forbidden_words(
    text: str, constraints: tuple[StyleConstraint, ...]
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for c in constraints:
        if c.constraint_type != "forbidden_word" or not c.enabled:
            continue
        pos = text.find(c.pattern)
        if pos >= 0:
            issues.append(QualityIssue(
                layer="L1 硬性规则",
                check_type="forbidden_word",
                position=pos,
                matched=c.pattern,
                message=f"发现禁用词「{c.pattern}」",
                fix_hint=f"请替换「{c.pattern}」",
            ))
    return issues


def _check_forbidden_punctuation(
    text: str, constraints: tuple[StyleConstraint, ...]
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for c in constraints:
        if c.constraint_type != "forbidden_punctuation" or not c.enabled:
            continue
        if not c.pattern:
            continue
        pos = text.find(c.pattern)
        if pos >= 0:
            hint = c.fix_hint or f"请替换「{c.pattern}」"
            issues.append(QualityIssue(
                layer="L1 硬性规则",
                check_type="forbidden_punctuation",
                position=pos,
                matched=c.pattern,
                message=f"发现禁用标点「{c.pattern}」",
                fix_hint=hint,
            ))
    return issues


def _check_perspective(
    text: str, skill_config: SkillConfig
) -> list[QualityIssue]:
    if skill_config.perspective != "third_person":
        return []
    issues: list[QualityIssue] = []
    for marker in skill_config.perspective_markers:
        pos = text.find(marker)
        if pos >= 0:
            # Look for fix_hint from config constraints
            fix_hint = "请改成第三视角叙述"
            for c in skill_config.constraints:
                if c.constraint_type == "perspective_marker" and c.pattern == marker and c.fix_hint:
                    fix_hint = c.fix_hint
                    break
            # Also check quality_layers for a custom fix_hint
            for layer in skill_config.quality_layers:
                for check in layer.get("checks", []):
                    if isinstance(check, dict) and check.get("type") == "perspective_consistent":
                        if check.get("fix_hint"):
                            fix_hint = check["fix_hint"]
                            break
                else:
                    continue
                break

            issues.append(QualityIssue(
                layer="L1 硬约束",
                check_type="perspective",
                position=pos,
                matched=marker,
                message=f"发现第一人称标记「{marker}」，当前配置为第三人称",
                fix_hint=fix_hint,
            ))
    return issues


def _check_detail_coverage(
    text: str, source_text: str, detail_ledger: DetailLedger | None
) -> list[QualityIssue]:
    if detail_ledger is None:
        if source_text:
            detail_ledger = build_detail_ledger(source_text)
        else:
            return []
    coverage = analyze_detail_coverage_enhanced(detail_ledger, text)
    issues: list[QualityIssue] = []
    for item in coverage.missing_items:
        issues.append(QualityIssue(
            layer="L1 硬约束",
            check_type="detail_coverage",
            position=-1,
            matched=item.text,
            message=f"缺失关键细节：{item.kind} {item.text}",
            fix_hint=f"请将「{item.text}」补回正文",
        ))
    return issues


def _check_output_length(
    text: str, spec: SkillOutputSpec
) -> list[QualityIssue]:
    length = len(text)
    issues: list[QualityIssue] = []
    if spec.min_chars > 0 and length < spec.min_chars:
        issues.append(QualityIssue(
            layer="L1 硬性规则",
            check_type="output_length",
            position=-1,
            matched=str(length),
            message=f"输出字数 {length} 低于最低要求 {spec.min_chars}",
            fix_hint=f"请扩充内容至至少 {spec.min_chars} 字",
        ))
    if spec.max_chars > 0 and length > spec.max_chars:
        issues.append(QualityIssue(
            layer="L1 硬性规则",
            check_type="output_length",
            position=-1,
            matched=str(length),
            message=f"输出字数 {length} 超过最高限制 {spec.max_chars}",
            fix_hint=f"请精简内容至 {spec.max_chars} 字以内",
        ))
    return issues


_CHECK_DISPATCH: dict[str, callable] = {
    "forbidden_words": lambda text, cfg, ledger: _check_forbidden_words(text, cfg.constraints),
    "forbidden_punctuation": lambda text, cfg, ledger: _check_forbidden_punctuation(text, cfg.constraints),
    "perspective_consistent": lambda text, cfg, ledger: _check_perspective(text, cfg),
    "detail_coverage": lambda text, cfg, ledger: _check_detail_coverage(text, "", ledger),
    "no_fabrication": lambda text, cfg, ledger: [],
    "output_length": lambda text, cfg, ledger: _check_output_length(text, cfg.output),
    "rhythm_variety": lambda text, cfg, ledger: [],
    "sentence_length_mix": lambda text, cfg, ledger: [],
    "evidence_support": lambda text, cfg, ledger: [],
    "temperature": lambda text, cfg, ledger: [],
    "colloquial_density": lambda text, cfg, ledger: [],
    "specific_subjects": lambda text, cfg, ledger: [],
    "judgment_follows_fact": lambda text, cfg, ledger: [],
    "mechanism_explained": lambda text, cfg, ledger: [],
    "cost_and_boundary": lambda text, cfg, ledger: [],
    "opening_hook": lambda text, cfg, ledger: [],
    "closing_convergence": lambda text, cfg, ledger: [],
}


def check_article_quality(
    text: str,
    source_text: str,
    skill_config: SkillConfig,
    detail_ledger: DetailLedger | None = None,
) -> QualityReport:
    """Check article quality layer by layer per skill_config.quality_layers."""
    all_issues: list[QualityIssue] = []
    layers_checked = 0
    layers_passed = 0

    for layer in skill_config.quality_layers:
        layers_checked += 1
        layer_issues: list[QualityIssue] = []
        checks = layer.get("checks", [])
        for check in checks:
            check_name = check if isinstance(check, str) else check.get("type", "")
            handler = _CHECK_DISPATCH.get(check_name)
            if handler:
                if check_name == "detail_coverage":
                    layer_issues.extend(handler(text, skill_config, detail_ledger))
                else:
                    layer_issues.extend(handler(text, skill_config, detail_ledger))
        if not layer_issues:
            layers_passed += 1
        all_issues.extend(layer_issues)

    return QualityReport(
        passed=len(all_issues) == 0,
        issues=tuple(all_issues),
        layers_checked=layers_checked,
        layers_passed=layers_passed,
    )


def build_revision_prompt(report: QualityReport) -> str:
    """Build a revision prompt from quality issues."""
    if not report.issues:
        return ""
    lines = ["请修订以下问题，只改有问题的部分，保留其余内容："]
    for i, issue in enumerate(report.issues, 1):
        if issue.position >= 0:
            lines.append(f"{i}. 第{issue.position}字处{issue.message}，{issue.fix_hint}")
        else:
            lines.append(f"{i}. {issue.message}，{issue.fix_hint}")
    lines.append("只输出修订后的正文。")
    return "\n".join(lines)
