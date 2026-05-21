from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any

from app.services.article_generation_service import (
    ArticleValidationResult,
    measure_source_text_length,
    resolve_article_spec,
    validate_generated_article,
)
from app.services.detail_ledger import (
    DetailLedger,
    analyze_detail_coverage_enhanced,
    build_detail_ledger,
    build_longform_topic_ledger,
    format_detail_coverage_issues,
    merge_detail_ledgers,
)
from app.services.detail_ledger_refiner import refine_detail_ledger_with_llm
from app.services.rewrite_loop_action import LoopActionKind
from app.services.rewrite_loop_planner import decide_next_action
from app.services.rewrite_loop_state import LoopBudget, LoopTraceStep, RewriteGoal, RewriteState
from app.services.rewrite_loop_validator import ValidationReport, validate_longform_rewrite
from app.services.skill_config_service import SkillConfig
from app.services.rewrite_stage_router import THIN_LONGFORM_PROMPT_PROFILE
from app.services.writer_versions import (
    ARTICLE_LONGFORM_PROMPT_VERSION,
    WRITER_POLICY_VERSION,
    new_writer_trace_id,
)


class ContentRewriteInputError(ValueError):
    pass


@dataclass(frozen=True)
class ArticleDraft:
    text: str
    outline: tuple[str, ...]
    spec: Any
    validation: ArticleValidationResult
    revised_once: bool


@dataclass(frozen=True)
class WriterRunReport:
    rewritten_text: str
    provider: str
    model: str
    quality_issues: tuple[str, ...]
    material: Any
    draft: ArticleDraft
    rewrite_style: str
    detail_coverage_issues: tuple[str, ...] = ()
    writer_trace_id: str = ""
    writer_policy_version: str = ""
    writer_prompt_version: str = ""
    loop_state_snapshot: dict[str, object] = field(default_factory=dict)
    last_action: str = ""
    budget_usage: dict[str, object] = field(default_factory=dict)
    failure_stage: str | None = None
    next_recommended_action: str | None = None
    covered_facts_summary: tuple[str, ...] = ()


def run_article_longform_loop(
    *,
    material: Any,
    rewrite_focus: str | None,
    rewrite_style: str,
    rewrite_config: dict[str, object] | None,
    skill_config: SkillConfig,
    llm_call_fn=None,
    cancellation_checker=None,
) -> WriterRunReport:
    normalized_source = (material.source_text or "").strip()
    if not normalized_source:
        raise ContentRewriteInputError("material.source_text must not be empty.")

    article_source = material.article_input_text()
    if not _should_run_agent_loop(rewrite_style):
        direct_focus = (rewrite_focus or "").strip() or None
        direct_result = rewrite_content(
            source_text=article_source,
            rewrite_focus=direct_focus,
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
            skill_config=skill_config,
            cancellation_checker=cancellation_checker,
            skip_prompt_validation=True,
            rewrite_stage="draft",
            prompt_profile=THIN_LONGFORM_PROMPT_PROFILE,
        )
        spec = resolve_article_spec(normalized_source, thin=True)
        validation = validate_generated_article(direct_result.rewritten_text, spec)
        return WriterRunReport(
            rewritten_text=direct_result.rewritten_text,
            provider=direct_result.provider,
            model=direct_result.model,
            quality_issues=tuple(direct_result.quality_issues),
            material=material,
            draft=ArticleDraft(
                text=direct_result.rewritten_text,
                outline=("single_pass",),
                spec=spec,
                validation=validation,
                revised_once=False,
            ),
            rewrite_style="article_longform",
            writer_trace_id=new_writer_trace_id(),
            writer_policy_version=WRITER_POLICY_VERSION,
            writer_prompt_version=ARTICLE_LONGFORM_PROMPT_VERSION,
            next_recommended_action="stop",
        )

    trace_id = new_writer_trace_id()
    route_key = "generic"
    route_label = "通用模板"
    route_reason = "未启用晚点分类路由或未命中题材信号。"
    template_body = ""
    if (skill_config.style_name or "").strip() == "晚点" or skill_config.template_routing_enabled:
        try:
            references = load_rewrite_references()
            selected = select_rewrite_template(
                source_text=article_source,
                rewrite_focus=(rewrite_focus or "").strip() or "",
                references=references,
            )
            route_key = selected.key
            route_label = selected.label
            route_reason = selected.route_reason
            template_body = selected.body
        except Exception:
            pass

    goal = RewriteGoal(
        rewrite_focus_raw=(rewrite_focus or "").strip(),
        rewrite_style=rewrite_style,
        skill_config_name=(skill_config.style_name or "").strip(),
        route_template_key=route_key,
        route_template_label=route_label,
        route_reason=route_reason,
    )

    detail_ledger = build_detail_ledger(article_source)
    if llm_call_fn and detail_ledger.items:
        try:
            refined = refine_detail_ledger_with_llm(
                source_text=article_source,
                coarse_ledger=detail_ledger,
                llm_call_fn=llm_call_fn,
            )
            detail_ledger = refined.to_detail_ledger()
        except Exception:
            pass
    topic_ledger = build_longform_topic_ledger(article_source)
    longform_ledger = merge_detail_ledgers(detail_ledger, topic_ledger)
    spec = resolve_article_spec(normalized_source, thin=True)
    length_guidance = _build_length_guidance_line(normalized_source, skill_config)
    evidence_bundle = _build_evidence_snapshot(
        source_text=article_source,
        longform_ledger=longform_ledger,
    )
    state = RewriteState(
        job_id=trace_id,
        goal=goal,
        stage="plan",
        rounds_left=LoopBudget().max_rounds,
        covered_facts=(),
        style_constraints=_collect_style_constraints(skill_config),
        evidence_bundle=evidence_bundle,
        budget=LoopBudget(),
    )

    stage_flow: list[dict[str, object]] = []
    stage_flow.append(_stage_flow_entry(
        stage="plan",
        status="completed",
        reason="初始化写作目标与路由。",
        evidence_bundle=evidence_bundle,
    ))
    stage_flow.append(_stage_flow_entry(
        stage="collect_evidence",
        status="completed",
        reason="整理必须保留的证据快照。",
        evidence_bundle=evidence_bundle,
    ))

    if _should_cancel(cancellation_checker):
        raise ContentRewriteInputError("Rewrite cancelled.")

    outline_prompt = build_outline_prompt(
        rewrite_focus=(rewrite_focus or "").strip(),
        length_guidance=length_guidance,
        spec=spec,
        detail_ledger_text=longform_ledger.to_prompt_text(),
        template_label=route_label,
        template_reason=route_reason,
        template_body=template_body,
        evidence_bundle=evidence_bundle,
    )
    outline_result = rewrite_content(
        source_text=article_source,
        rewrite_focus=outline_prompt,
        rewrite_style="article_longform",
        rewrite_config=rewrite_config,
        skill_config=skill_config,
        cancellation_checker=cancellation_checker,
        skip_prompt_validation=True,
        rewrite_stage="outline",
        prompt_profile=THIN_LONGFORM_PROMPT_PROFILE,
    )
    outline = _extract_outline(outline_result.rewritten_text)
    state = state.with_stage("outline")
    state = _append_step(
        state,
        "outline",
        "生成写作大纲。",
        outline_prompt,
        article_source,
        outline_result.rewritten_text,
        metadata={
            "stage": "outline",
            "evidence": _compact_evidence_snapshot(evidence_bundle),
        },
    )
    stage_flow.append(_stage_flow_entry(
        stage="outline",
        status="completed",
        reason="生成写作大纲。",
        evidence_bundle=evidence_bundle,
        trace_step=state.trace[-1] if state.trace else None,
    ))

    if _should_cancel(cancellation_checker):
        raise ContentRewriteInputError("Rewrite cancelled.")

    draft_prompt = build_draft_prompt(
        rewrite_focus=(rewrite_focus or "").strip(),
        outline=outline,
        spec=spec,
        length_guidance=length_guidance,
        detail_ledger_text=longform_ledger.to_prompt_text(),
        template_label=route_label,
        template_reason=route_reason,
        evidence_bundle=evidence_bundle,
    )
    draft_result = rewrite_content(
        source_text=article_source,
        rewrite_focus=draft_prompt,
        rewrite_style="article_longform",
        rewrite_config=rewrite_config,
        skill_config=skill_config,
        cancellation_checker=cancellation_checker,
        skip_prompt_validation=True,
        rewrite_stage="draft",
        prompt_profile=THIN_LONGFORM_PROMPT_PROFILE,
    )
    final_result = draft_result
    validation = validate_longform_rewrite(
        text=final_result.rewritten_text,
        source_text=normalized_source,
        skill_config=skill_config,
        detail_ledger=longform_ledger,
    )
    evidence_bundle = _build_evidence_snapshot(
        source_text=article_source,
        longform_ledger=longform_ledger,
        current_text=final_result.rewritten_text,
        validation=validation,
    )
    state = (
        state.with_stage("validate")
        .with_draft(final_result.rewritten_text)
        .with_validation_breakdown(validation)
        .with_issues(validation.hard_failures + validation.soft_failures)
    )
    state = replace(state, covered_facts=tuple(evidence_bundle["covered_fact_ids"]))
    state = _append_step(
        state,
        "draft",
        "生成初稿。",
        draft_prompt,
        article_source,
        final_result.rewritten_text,
        validation=validation,
        metadata={
            "stage": "draft",
            "evidence": _compact_evidence_snapshot(evidence_bundle),
            "validation": validation.to_snapshot(),
        },
    )
    stage_flow.append(_stage_flow_entry(
        stage="validate",
        status="completed" if validation.passed else "needs_revision",
        reason=_validation_summary(validation) or "完成初稿验证。",
        evidence_bundle=evidence_bundle,
        validation=validation,
        trace_step=state.trace[-1] if state.trace else None,
    ))

    revision_round = 0
    failure_stage: str | None = None
    previous_signature = _validation_signature(validation, evidence_bundle)
    while state.rounds_left > 0 and state.budget.spent_tokens < state.budget.max_total_tokens:
        followup_action = decide_next_action(state, validation)
        followup_stage = str(
            followup_action.metadata.get("next_recommended_stage") or followup_action.kind
        )
        trace_action = followup_action.kind
        followup_reason = followup_action.reason
        if trace_action == "stop":
            break

        if _should_cancel(cancellation_checker):
            raise ContentRewriteInputError("Rewrite cancelled.")

        if followup_stage == "re_ground":
            next_prompt = build_re_ground_prompt(
                previous_article=final_result.rewritten_text,
                source_text=normalized_source,
                detail_ledger=longform_ledger,
                length_guidance=length_guidance,
                validation=validation,
                evidence_bundle=evidence_bundle,
            )
        elif followup_stage == "patch":
            next_prompt = build_patch_prompt(
                previous_article=final_result.rewritten_text,
                validation=validation,
                detail_ledger=longform_ledger,
                source_text=normalized_source,
                length_guidance=length_guidance,
                evidence_bundle=evidence_bundle,
            )
        elif followup_stage == "expand":
            next_prompt = build_expand_prompt(
                previous_article=final_result.rewritten_text,
                source_text=normalized_source,
                detail_ledger=longform_ledger,
                length_guidance=length_guidance,
                spec=spec,
                validation=validation,
                evidence_bundle=evidence_bundle,
            )
        elif followup_stage == "outline":
            next_prompt = outline_prompt
        else:
            next_prompt = draft_prompt

        revised_result = rewrite_content(
            source_text=article_source,
            rewrite_focus=next_prompt,
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
            skill_config=skill_config,
            cancellation_checker=cancellation_checker,
            skip_prompt_validation=True,
            rewrite_stage=followup_stage,
            prompt_profile=THIN_LONGFORM_PROMPT_PROFILE,
        )
        final_result = revised_result
        validation = validate_longform_rewrite(
            text=final_result.rewritten_text,
            source_text=normalized_source,
            skill_config=skill_config,
            detail_ledger=longform_ledger,
        )
        evidence_bundle = _build_evidence_snapshot(
            source_text=article_source,
            longform_ledger=longform_ledger,
            current_text=final_result.rewritten_text,
            validation=validation,
        )
        state = state.with_draft(final_result.rewritten_text).with_issues(
            validation.hard_failures + validation.soft_failures
        )
        state = replace(state, covered_facts=tuple(evidence_bundle["covered_fact_ids"]))
        trace_step = LoopTraceStep(
            action=trace_action,
            reason=followup_reason,
            prompt_preview=_preview(next_prompt),
            input_chars=measure_source_text_length(article_source),
            output_chars=measure_source_text_length(final_result.rewritten_text),
            tokens_used=_estimate_token_cost(final_result.rewritten_text),
            validation_summary=_validation_summary(validation),
            metadata={
                "stage": followup_stage,
                "evidence": _compact_evidence_snapshot(evidence_bundle),
                "validation": validation.to_snapshot(),
            },
        )
        state = state.append_trace(trace_step)
        state = state.increment_retry(trace_action).consume_budget(
            _estimate_token_cost(final_result.rewritten_text)
        ).consume_round()
        stage_flow.append(_stage_flow_entry(
            stage=followup_stage,
            status="completed" if validation.passed else "needs_revision",
            reason=followup_reason,
            evidence_bundle=evidence_bundle,
            validation=validation,
            trace_step=trace_step,
        ))
        revision_round += 1
        current_signature = _validation_signature(validation, evidence_bundle)
        if validation.passed:
            failure_stage = None
            break
        if current_signature == previous_signature:
            failure_stage = "plateau"
            break
        previous_signature = current_signature

    detail_coverage_issues = format_detail_coverage_issues(
        analyze_detail_coverage_enhanced(longform_ledger, final_result.rewritten_text)
    )
    if failure_stage is None and not validation.passed:
        if state.budget.spent_tokens >= state.budget.max_total_tokens:
            failure_stage = "budget"
        elif state.rounds_left <= 0:
            failure_stage = "round_limit"
        else:
            failure_stage = "validation"
    loop_snapshot = {
        "state": state.to_snapshot(),
        "goal": goal.to_snapshot(),
        "route": {"key": route_key, "label": route_label, "reason": route_reason},
        "stage_flow": stage_flow,
        "stage": {
            "current": "finalize" if validation.passed else failure_stage or "validation",
            "flow": stage_flow,
        },
        "evidence": _compact_evidence_snapshot(evidence_bundle),
        "validation": validation.to_snapshot(),
        "revision_round": revision_round,
        "failure_stage": failure_stage,
    }
    return WriterRunReport(
        rewritten_text=final_result.rewritten_text,
        provider=final_result.provider,
        model=final_result.model,
        quality_issues=tuple(final_result.quality_issues),
        material=material,
        draft=ArticleDraft(
            text=final_result.rewritten_text,
            outline=outline,
            spec=spec,
            validation=validation.article_validation or validate_generated_article(final_result.rewritten_text, spec),
            revised_once=revision_round > 0,
        ),
        rewrite_style="article_longform",
        detail_coverage_issues=detail_coverage_issues,
        writer_trace_id=trace_id,
        writer_policy_version=WRITER_POLICY_VERSION,
        writer_prompt_version=ARTICLE_LONGFORM_PROMPT_VERSION,
        loop_state_snapshot=loop_snapshot,
        last_action=state.trace[-1].action if state.trace else "stop",
        budget_usage=state.budget.to_snapshot(),
        failure_stage=failure_stage,
        next_recommended_action=validation.next_recommended_action,
        covered_facts_summary=tuple(evidence_bundle["covered_fact_texts"]),
    )


def rewrite_content(**kwargs):
    from app.services.content_rewrite_service import rewrite_content as _rewrite_content

    return _rewrite_content(**kwargs)


def load_rewrite_references():
    from app.services.rewrite_template_service import load_rewrite_references as _load_rewrite_references

    return _load_rewrite_references()


def select_rewrite_template(**kwargs):
    from app.services.rewrite_template_service import select_rewrite_template as _select_rewrite_template

    return _select_rewrite_template(**kwargs)


def build_outline_prompt(
    *,
    rewrite_focus: str,
    length_guidance: str | None,
    spec,
    detail_ledger_text: str,
    template_label: str,
    template_reason: str,
    template_body: str,
    evidence_bundle: dict[str, object] | None = None,
) -> str:
    lines = [
        "请基于原始素材先给出写作规划。",
        "",
        f"写作目标：{rewrite_focus or '科技深度中文文章'}",
        "写作视角：报道视角，围绕变化、机制和边界组织，不要按人物发言顺序列提纲。",
        f"题材路由：{template_label}",
        f"路由原因：{template_reason}",
    ]
    if template_body:
        lines.extend(["", "场景模板摘要：", template_body])
    if length_guidance:
        lines.append(length_guidance)
    if evidence_bundle:
        lines.extend(["", _format_evidence_bundle(evidence_bundle)])
    lines.extend(
        [
            f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）",
            "",
            "只输出一个简短大纲，每行一个要点。",
            "",
            f"必须保留的关键细节：\n{detail_ledger_text}",
        ]
    )
    return "\n".join(lines)


def build_draft_prompt(
    *,
    rewrite_focus: str,
    outline: tuple[str, ...],
    spec,
    length_guidance: str | None,
    detail_ledger_text: str,
    template_label: str,
    template_reason: str,
    evidence_bundle: dict[str, object] | None = None,
) -> str:
    outline_text = "\n".join(f"- {line}" for line in outline) if outline else "- 按素材主线组织段落"
    lines = [
        "请按以下要求输出中文文章初稿。",
        "",
        f"写作目标：{rewrite_focus or '保留原意并提升中文可读性'}",
        "视角要求：第三视角报道写法，人物只作为信息来源，不要让发言顺序主导段落顺序。",
        f"题材路由：{template_label}",
        f"路由原因：{template_reason}",
    ]
    if length_guidance:
        lines.append(length_guidance)
    if evidence_bundle:
        lines.extend(["", _format_evidence_bundle(evidence_bundle)])
    lines.extend(
        [
            f"总字数：{spec.min_total_chars}-{spec.max_total_chars}（目标 {spec.target_total_chars}）",
            f"每段字数：{spec.min_chars_per_section}-{spec.max_chars_per_section}（建议 {spec.target_chars_per_section}）",
            f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）",
            "",
            "大纲：",
            outline_text,
            "",
            "要求：不编造事实，段落之间空行，只输出正文。",
            "",
            f"必须保留的关键细节：\n{detail_ledger_text}",
        ]
    )
    return "\n".join(lines)


def build_expand_prompt(
    *,
    previous_article: str,
    source_text: str,
    detail_ledger: DetailLedger,
    length_guidance: str | None,
    spec,
    validation: ValidationReport,
    evidence_bundle: dict[str, object] | None = None,
) -> str:
    issue_lines = "\n".join(f"- {issue}" for issue in (validation.soft_failures or validation.hard_failures))
    source_length = measure_source_text_length(source_text)
    current_chars = measure_source_text_length(previous_article)
    deficit = max(0, spec.min_total_chars - current_chars)
    lines = [
        "请基于下面这版内容进行一次扩写式重写，目标是补足篇幅和报道层次，不要只做局部润色。",
        f"篇幅标准：{length_guidance or f'总长度尽量达到 {spec.min_total_chars}-{spec.max_total_chars} 字。'}",
        f"当前稿件约 {current_chars} 字，原文约 {source_length} 字，目标区间 {spec.min_total_chars}-{spec.max_total_chars} 字，当前至少还需要补足约 {deficit} 字。",
        "- 这不是摘要压缩任务，而是扩写任务；如果当前稿子偏短，请补出机制、代价、边界、对比和下一步判断。",
        "- 叙事主语优先使用事件、变化、系统、平台和产业链，不要沿着演讲顺序逐条复述。",
        "- 继续保持报道视角，不要把人物发言顺序当成段落顺序。",
        "- 每一段都要有明确的事实锚点或机制锚点，避免空泛判断。",
        "- 如果仍然像逐字稿，先重组结构，再补充细节。",
        f"当前软硬问题：\n{issue_lines}",
        *(
            ["", _format_evidence_bundle(evidence_bundle)]
            if evidence_bundle
            else []
        ),
        "",
        "待扩写文本：",
        previous_article.strip(),
        "",
        f"必须保留的关键细节：\n{detail_ledger.to_prompt_text()}",
    ]
    return "\n".join(lines)


def build_patch_prompt(
    *,
    previous_article: str,
    validation: ValidationReport,
    detail_ledger: DetailLedger,
    source_text: str,
    length_guidance: str | None,
    evidence_bundle: dict[str, object] | None = None,
) -> str:
    lines = [
        "请修订下面这版文章，只改有问题的部分，保留其余内容。",
        "",
    ]
    if validation.article_validation and validation.article_validation.issues:
        lines.append("当前结构问题：")
        for issue in validation.article_validation.issues:
            lines.append(f"- {issue}")
    if validation.hard_failures:
        lines.append("当前硬性问题：")
        for issue in validation.hard_failures:
            lines.append(f"- {issue}")
    if validation.detail_coverage_issues:
        lines.append("缺失细节：")
        for issue in validation.detail_coverage_issues:
            lines.append(f"- {issue}")
    if validation.soft_failures:
        lines.append("当前软性提示：")
        for issue in validation.soft_failures:
            lines.append(f"- {issue}")
    if length_guidance:
        lines.extend(["", f"篇幅标准：{length_guidance}"])
    if evidence_bundle:
        lines.extend(["", _format_evidence_bundle(evidence_bundle)])
    lines.extend(
        [
            "",
            "处理原则：仅返回修订后的正文，不要解释。",
            "",
            "原始素材：",
            source_text.strip(),
            "",
            "当前完整草稿：",
            previous_article.strip(),
            "",
            f"必须保留的关键细节：\n{detail_ledger.to_prompt_text()}",
        ]
    )
    return "\n".join(lines)


def build_re_ground_prompt(
    *,
    previous_article: str,
    source_text: str,
    detail_ledger: DetailLedger,
    length_guidance: str | None,
    validation: ValidationReport,
    evidence_bundle: dict[str, object] | None = None,
) -> str:
    lines = [
        "请先回查证据，再重写当前稿件。",
        "",
        "当前问题：",
    ]
    if validation.hard_failures:
        lines.extend(f"- {issue}" for issue in validation.hard_failures)
    if validation.detail_coverage_issues:
        lines.append("缺失细节：")
        lines.extend(f"- {issue}" for issue in validation.detail_coverage_issues)
    if validation.soft_failures:
        lines.append("软性提示：")
        lines.extend(f"- {issue}" for issue in validation.soft_failures)
    if evidence_bundle:
        lines.extend(["", _format_evidence_bundle(evidence_bundle)])
    if length_guidance:
        lines.extend(["", f"篇幅标准：{length_guidance}"])
    lines.extend(
        [
            "",
            "处理原则：先修正事实锚点和信息顺序，再输出修订后的正文，不要只做表面润色。",
            "",
            "原始素材：",
            source_text.strip(),
            "",
            "当前完整草稿：",
            previous_article.strip(),
            "",
            f"必须保留的关键细节：\n{detail_ledger.to_prompt_text()}",
        ]
    )
    return "\n".join(lines)


def _build_followup_prompt(
    *,
    action_kind: LoopActionKind,
    previous_article: str,
    source_text: str,
    detail_ledger: DetailLedger,
    length_guidance: str | None,
    spec,
    validation: ValidationReport,
) -> str:
    if action_kind == "expand":
        issue_lines = "\n".join(f"- {issue}" for issue in validation.soft_failures or validation.hard_failures)
        source_length = measure_source_text_length(source_text)
        current_chars = measure_source_text_length(previous_article)
        deficit = max(0, spec.min_total_chars - current_chars)
        return "\n".join(
            [
                "请基于下面这版内容进行一次扩写式重写，目标是补足篇幅和报道层次，不要只做局部润色。",
                f"篇幅标准：{length_guidance or f'总长度尽量达到 {spec.min_total_chars}-{spec.max_total_chars} 字。'}",
                f"当前稿件约 {current_chars} 字，原文约 {source_length} 字，目标区间 {spec.min_total_chars}-{spec.max_total_chars} 字，当前至少还需要补足约 {deficit} 字。",
                "- 这不是摘要压缩任务，而是扩写任务；如果当前稿子偏短，请补出机制、代价、边界、对比和下一步判断。",
                "- 叙事主语优先使用事件、变化、系统、平台和产业链，不要沿着演讲顺序逐条复述。",
                "- 继续保持报道视角，不要把人物发言顺序当成段落顺序。",
                "- 每一段都要有明确的事实锚点或机制锚点，避免空泛判断。",
                "- 如果仍然像逐字稿，先重组结构，再补充细节。",
                f"当前软硬问题：\n{issue_lines}",
                "",
                "待扩写文本：",
                previous_article.strip(),
                "",
                f"必须保留的关键细节：\n{detail_ledger.to_prompt_text()}",
            ]
        )
    return "\n".join(
        [
            "请修订下面这版文章，只改有问题的部分，保留其余内容。",
            "",
            "当前硬性问题：",
            *[f"- {issue}" for issue in validation.hard_failures],
            "",
            "当前软性提示：",
            *[f"- {issue}" for issue in validation.soft_failures],
            "",
            f"篇幅标准：{length_guidance or f'总长度尽量控制在原文的 40%-60% 之间。'}",
            "",
            "处理原则：仅返回修订后的正文，不要解释。",
            "",
            "原始素材：",
            source_text.strip(),
            "",
            "当前完整草稿：",
            previous_article.strip(),
            "",
            f"必须保留的关键细节：\n{detail_ledger.to_prompt_text()}",
        ]
    )


def _build_evidence_snapshot(
    *,
    source_text: str,
    longform_ledger: DetailLedger,
    current_text: str | None = None,
    validation: ValidationReport | None = None,
) -> dict[str, object]:
    coverage_items = list(longform_ledger.coverage_items())
    required_fact_ids = [_ledger_item_id(item.kind, item.text) for item in coverage_items]
    required_fact_texts = [item.text for item in coverage_items]
    covered_fact_ids: list[str] = []
    covered_fact_texts: list[str] = []
    missing_fact_ids: list[str] = []
    missing_fact_texts: list[str] = []
    coverage_ratio = 0.0

    if current_text is not None:
        coverage = analyze_detail_coverage_enhanced(longform_ledger, current_text)
        missing_lookup = {
            _ledger_item_id(item.kind, item.text)
            for item in coverage.missing_items
        }
        covered_items = [
            item for item in coverage_items
            if _ledger_item_id(item.kind, item.text) not in missing_lookup
        ]
        covered_fact_ids = [_ledger_item_id(item.kind, item.text) for item in covered_items]
        covered_fact_texts = [item.text for item in covered_items]
        missing_fact_ids = [_ledger_item_id(item.kind, item.text) for item in coverage.missing_items]
        missing_fact_texts = [item.text for item in coverage.missing_items]
        total_items = len(required_fact_ids)
        if total_items:
            coverage_ratio = round(len(covered_fact_ids) / total_items, 4)

    grounding_warnings: list[str] = []
    if missing_fact_texts:
        grounding_warnings.append(f"缺失 {len(missing_fact_texts)} 个关键细节。")
    if validation and validation.hard_failures:
        grounding_warnings.extend(validation.hard_failures[:3])
    if validation and validation.detail_coverage_issues:
        grounding_warnings.extend(validation.detail_coverage_issues[:3])

    return {
        "required_fact_ids": required_fact_ids,
        "required_fact_texts": required_fact_texts,
        "covered_fact_ids": covered_fact_ids,
        "covered_fact_texts": covered_fact_texts,
        "missing_fact_ids": missing_fact_ids,
        "missing_fact_texts": missing_fact_texts,
        "source_excerpt_hits": list(_collect_source_excerpt_hits(source_text, required_fact_texts)),
        "grounding_warnings": list(dict.fromkeys(filter(None, grounding_warnings))),
        "coverage_ratio": coverage_ratio,
        "validation": validation.to_snapshot() if validation else {},
    }


def _collect_source_excerpt_hits(source_text: str, fact_texts: list[str], limit: int = 8) -> tuple[str, ...]:
    normalized_source = (source_text or "").strip()
    if not normalized_source:
        return ()

    hits: list[str] = []
    for fact_text in fact_texts:
        normalized_fact = " ".join((fact_text or "").split())
        if not normalized_fact:
            continue
        index = normalized_source.find(normalized_fact)
        if index < 0 and normalized_fact:
            for token in normalized_fact.split():
                if len(token) >= 4:
                    index = normalized_source.find(token)
                    if index >= 0:
                        break
        if index < 0:
            continue
        start = max(0, index - 60)
        end = min(len(normalized_source), index + len(normalized_fact) + 100)
        excerpt = " ".join(normalized_source[start:end].split())
        if excerpt and excerpt not in hits:
            hits.append(excerpt)
        if len(hits) >= limit:
            break
    return tuple(hits)


def _compact_evidence_snapshot(evidence_bundle: dict[str, object]) -> dict[str, object]:
    return {
        "required_fact_ids": list(evidence_bundle.get("required_fact_ids", ()) or ()),
        "covered_fact_ids": list(evidence_bundle.get("covered_fact_ids", ()) or ()),
        "missing_fact_ids": list(evidence_bundle.get("missing_fact_ids", ()) or ()),
        "source_excerpt_hits": list(evidence_bundle.get("source_excerpt_hits", ()) or ()),
        "grounding_warnings": list(evidence_bundle.get("grounding_warnings", ()) or ()),
        "coverage_ratio": evidence_bundle.get("coverage_ratio", 0.0),
        "validation": evidence_bundle.get("validation", {}),
    }


def _format_evidence_bundle(evidence_bundle: dict[str, object]) -> str:
    required_fact_texts = [str(item).strip() for item in evidence_bundle.get("required_fact_texts", ()) or () if str(item).strip()]
    covered_fact_texts = [str(item).strip() for item in evidence_bundle.get("covered_fact_texts", ()) or () if str(item).strip()]
    missing_fact_texts = [str(item).strip() for item in evidence_bundle.get("missing_fact_texts", ()) or () if str(item).strip()]
    source_excerpt_hits = [str(item).strip() for item in evidence_bundle.get("source_excerpt_hits", ()) or () if str(item).strip()]
    grounding_warnings = [str(item).strip() for item in evidence_bundle.get("grounding_warnings", ()) or () if str(item).strip()]

    lines = ["证据快照："]
    if required_fact_texts:
        lines.append("必须保留的关键细节：")
        lines.extend(f"- {item}" for item in required_fact_texts[:8])
    if covered_fact_texts:
        lines.append("当前已覆盖：")
        lines.extend(f"- {item}" for item in covered_fact_texts[:8])
    if missing_fact_texts:
        lines.append("当前缺失：")
        lines.extend(f"- {item}" for item in missing_fact_texts[:8])
    if source_excerpt_hits:
        lines.append("原文命中片段：")
        lines.extend(f"- {item}" for item in source_excerpt_hits[:4])
    if grounding_warnings:
        lines.append("证据警告：")
        lines.extend(f"- {item}" for item in grounding_warnings[:4])
    coverage_ratio = evidence_bundle.get("coverage_ratio")
    if isinstance(coverage_ratio, (int, float)) and coverage_ratio:
        lines.append(f"覆盖率：{coverage_ratio:.2%}")
    return "\n".join(lines)


def _validation_signature(report: ValidationReport, evidence_bundle: dict[str, object]) -> tuple[object, ...]:
    metrics = report.metrics or {}
    return (
        tuple(report.hard_failures),
        tuple(report.soft_failures),
        tuple(report.detail_coverage_issues),
        int(metrics.get("output_chars") or 0),
        int(metrics.get("hard_issue_count") or 0),
        int(metrics.get("soft_issue_count") or 0),
        tuple(evidence_bundle.get("covered_fact_ids", ()) or ()),
        tuple(evidence_bundle.get("missing_fact_ids", ()) or ()),
    )


def _stage_flow_entry(
    *,
    stage: str,
    status: str,
    reason: str,
    evidence_bundle: dict[str, object] | None = None,
    validation: ValidationReport | None = None,
    trace_step: LoopTraceStep | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "stage": stage,
        "status": status,
        "reason": reason,
    }
    if evidence_bundle is not None:
        entry["evidence"] = _compact_evidence_snapshot(evidence_bundle)
    if validation is not None:
        entry["validation"] = validation.to_snapshot()
    if trace_step is not None:
        entry["trace"] = trace_step.to_snapshot()
    return entry


def _append_step(
    state: RewriteState,
    action: str,
    reason: str,
    prompt: str,
    source_text: str,
    output_text: str,
    validation: ValidationReport | None = None,
    metadata: dict[str, object] | None = None,
) -> RewriteState:
    step = LoopTraceStep(
        action=action,  # type: ignore[arg-type]
        reason=reason,
        prompt_preview=_preview(prompt),
        input_chars=measure_source_text_length(source_text),
        output_chars=measure_source_text_length(output_text),
        tokens_used=_estimate_token_cost(output_text),
        validation_summary=_validation_summary(validation) if validation else "",
        metadata=dict(metadata or {}),
    )
    state = state.append_trace(step)
    state = state.consume_budget(_estimate_token_cost(output_text)).consume_round()
    return state


def _collect_style_constraints(skill_config: SkillConfig) -> tuple[str, ...]:
    return tuple(
        f"{constraint.constraint_type}:{constraint.pattern}"
        for constraint in skill_config.constraints
        if constraint.enabled
    )


def _build_length_guidance_line(source_text: str, skill_config: SkillConfig) -> str | None:
    output = getattr(skill_config, "output", None)
    ratio_min = getattr(output, "source_length_ratio_min", None)
    ratio_max = getattr(output, "source_length_ratio_max", None)
    if ratio_min is None and ratio_max is None:
        return None

    source_length = measure_source_text_length(source_text)
    if source_length <= 0:
        return None

    min_ratio = ratio_min if ratio_min is not None else 0.0
    max_ratio = ratio_max if ratio_max is not None else 1.0
    if max_ratio < min_ratio:
        min_ratio, max_ratio = max_ratio, min_ratio

    min_chars = max(1, round(source_length * min_ratio))
    max_chars = max(min_chars, round(source_length * max_ratio))
    suggested_sections = 5 if source_length >= 10000 else 4 if source_length >= 6000 else 3
    suggested_chars_per_section = max(1, round(((min_chars + max_chars) / 2) / suggested_sections))
    return (
        f"篇幅建议：总长度尽量控制在原文的 {int(min_ratio * 100)}%-{int(max_ratio * 100)}% "
        f"之间，当前原文约 {source_length} 字，建议输出约 {min_chars}-{max_chars} 字。"
        f"建议分 {suggested_sections} 段左右，每段约 {suggested_chars_per_section} 字。"
    )


def _extract_outline(text: str) -> tuple[str, ...]:
    lines = [line.strip(" -\t") for line in (text or "").splitlines()]
    cleaned = tuple(line for line in lines if line)
    return cleaned[:8] if cleaned else ("按素材主线组织段落",)


def _ledger_item_id(kind: str, text: str) -> str:
    return f"{kind}:{' '.join((text or '').split())}"


def _preview(text: str, limit: int = 200) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def _estimate_token_cost(text: str) -> int:
    return max(1, measure_source_text_length(text) // 4 or 1)


def _validation_summary(report: ValidationReport | None) -> str:
    if report is None:
        return ""
    if report.passed:
        return "passed"
    return "; ".join(report.hard_failures[:2] or report.soft_failures[:2])


def _should_cancel(cancellation_checker) -> bool:
    return bool(callable(cancellation_checker) and cancellation_checker())


def _should_run_agent_loop(rewrite_style: str | None) -> bool:
    return os.getenv("USE_AGENT_LOOP", "false").lower() == "true" and rewrite_style == "article_longform"
