from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
from typing import Iterable, Literal

from app.services.caption_service import CaptionServiceError
from app.services.content_rewrite_service import (
    ARTICLE_LONGFORM_DEFAULT_FOCUS,
    RewriteStyle,
)
from app.services.rewrite_template_service import (
    load_rewrite_references,
    select_rewrite_template,
)
from app.services.video_source_service import fetch_video_source
from app.services.rewrite_quality_service import guess_output_language
from app.services.writer_agent_service import (
    ARTICLE_LONGFORM_FIRST_PERSON_MARKERS,
    MaterialPackage,
    WriterAgent,
    analyze_detail_coverage,
    build_detail_ledger,
    format_detail_coverage_issues,
    _strip_quoted_spans,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PINNED_LASTPOST_SKILL_DIR = REPO_ROOT / "writer-skill" / "latepost" / "references"
_LEGACY_LASTPOST_SKILL_DIR = Path.home() / ".hermes" / "skills" / "creative" / "lastpost-skill"
DEFAULT_MANIFEST_PATH = (
    REPO_ROOT / "backend" / "tests" / "fixtures" / "writer_skill_eval" / "samples.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp" / "writer_skill_eval"
FULL_PROMPT_PLACEHOLDER_PATTERN = re.compile(r"\[[^\]]*在这里贴入[^\]]*\]")
# 辅助参考指标：精确匹配改写输出是否含明确的 AI 模型自述/免责声明。
# 扩展方式：人工 review report.md 的输出节选，发现新形式时追加；不引入 LLM 分类器。
AI_SLOP_MARKERS = (
    "作为一个ai",
    "作为ai",
    "作为 an ai",
    "根据我的训练数据",
    "我无法访问",
    "我不能提供",
    "免责声明",
    "我是一个ai",
    "ai语言模型",
)
ZH_SUBSET_SAMPLE_IDS = (
    "nasa_force_talent",
    "steve_jobs_stanford",
    "tim_cook_mit",
    "vision_pro_review",
)


@dataclass(frozen=True)
class WriterSkillEvalSample:
    sample_id: str
    title: str
    url: str
    baseline_prompt_file: str
    transcript_path: str
    category: str = ""
    notes: str = ""


@dataclass(frozen=True)
class WriterSkillEvalModeResult:
    mode: str
    rewrite_style: RewriteStyle
    provider: str
    model: str
    rewritten_text: str
    source_chars: int
    output_chars: int
    compression_ratio: float
    quality_issues: tuple[str, ...]
    agent_detail_coverage_issues: tuple[str, ...]
    detail_coverage_issues: tuple[str, ...]
    hard_detail_total: int
    hard_detail_covered: int
    hard_detail_missing: tuple[str, ...]
    ordering_ok: bool
    first_person_hits: tuple[str, ...]
    ai_slop_hits: tuple[str, ...]
    validation_ok: bool
    revised_once: bool
    paragraph_count: int
    output_language_guess: str = ""
    compression_anomaly: bool = False
    route_key: str | None = None
    route_label: str | None = None
    route_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class WriterSkillEvalSampleResult:
    sample: WriterSkillEvalSample
    transcript_size: int
    modes: tuple[WriterSkillEvalModeResult, ...]


@dataclass(frozen=True)
class WriterSkillEvalModeSummary:
    mode: str
    sample_count: int
    hard_detail_rate: float
    third_person_ok_rate: float
    ordering_ok_rate: float
    avg_compression_ratio: float
    first_person_failures: int
    ai_slop_hits: int
    error_count: int
    zh_subset_compression_avg: float | None = None


@dataclass(frozen=True)
class WriterSkillEvalReport:
    generated_at: str
    manifest_path: str
    skill_root: str
    provider: str
    model: str
    sample_count: int
    samples: tuple[WriterSkillEvalSampleResult, ...]
    summaries: tuple[WriterSkillEvalModeSummary, ...]
    decision_hint: str


def load_writer_skill_eval_manifest(manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> tuple[WriterSkillEvalSample, ...]:
    manifest_file = Path(manifest_path).expanduser()
    if not manifest_file.exists():
        raise FileNotFoundError(f"Writer skill eval manifest not found: {manifest_file}")

    raw = json.loads(manifest_file.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = raw.get("samples") or []
    else:
        raise ValueError("Writer skill eval manifest must be a list or a dict with a samples key.")

    samples: list[WriterSkillEvalSample] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        samples.append(
            WriterSkillEvalSample(
                sample_id=str(entry.get("sample_id") or entry.get("id") or "").strip(),
                title=str(entry.get("title") or "").strip(),
                url=str(entry.get("url") or "").strip(),
                baseline_prompt_file=str(
                    entry.get("baseline_prompt_file") or entry.get("baseline_prompt") or ""
                ).strip(),
                transcript_path=str(entry.get("transcript_path") or "").strip(),
                category=str(entry.get("category") or "").strip(),
                notes=str(entry.get("notes") or "").strip(),
            )
        )

    validated: list[WriterSkillEvalSample] = []
    for sample in samples:
        if not sample.sample_id:
            raise ValueError("Writer skill eval sample is missing sample_id.")
        if not sample.title:
            raise ValueError(f"Writer skill eval sample {sample.sample_id} is missing title.")
        if not sample.url:
            raise ValueError(f"Writer skill eval sample {sample.sample_id} is missing url.")
        if not sample.baseline_prompt_file:
            raise ValueError(
                f"Writer skill eval sample {sample.sample_id} is missing baseline_prompt_file."
            )
        if not sample.transcript_path:
            raise ValueError(
                f"Writer skill eval sample {sample.sample_id} is missing transcript_path."
            )
        validated.append(sample)

    return tuple(validated)


def ensure_writer_skill_eval_transcript(
    sample: WriterSkillEvalSample,
    *,
    manifest_dir: str | Path,
    refresh: bool = False,
) -> str:
    transcript_file = resolve_writer_skill_eval_transcript_path(sample, manifest_dir=manifest_dir)
    if transcript_file.exists() and not refresh:
        return transcript_file.read_text(encoding="utf-8").strip()

    transcript_file.parent.mkdir(parents=True, exist_ok=True)
    text = _fetch_transcript_text(sample.url)
    transcript_file.write_text(text.strip() + "\n", encoding="utf-8")
    return text.strip()


def resolve_writer_skill_eval_transcript_path(
    sample: WriterSkillEvalSample,
    *,
    manifest_dir: str | Path,
) -> Path:
    manifest_root = Path(manifest_dir).expanduser()
    transcript_path = Path(sample.transcript_path)
    if transcript_path.is_absolute():
        return transcript_path
    return manifest_root / transcript_path


def resolve_lastpost_skill_root() -> Path:
    configured_path = (
        os.environ.get("LATEPOST_SKILL_DIR")
        or os.environ.get("LASTPOST_SKILL_DIR")
        or os.environ.get("REWRITE_SKILL_DIR")
    )
    if configured_path:
        configured_root = Path(configured_path).expanduser()
        if configured_root.exists():
            if (configured_root / "references").exists() and not (configured_root / "prompts").exists():
                return configured_root / "references"
            return configured_root

    if PINNED_LASTPOST_SKILL_DIR.exists():
        return PINNED_LASTPOST_SKILL_DIR

    if _LEGACY_LASTPOST_SKILL_DIR.exists():
        return _LEGACY_LASTPOST_SKILL_DIR

    raise FileNotFoundError(
        "写作参考资料未找到。请确认 writer-skill/latepost/references 目录存在，或设置 LATEPOST_SKILL_DIR / LASTPOST_SKILL_DIR 环境变量。"
    )


def build_full_prompt_from_skill_prompt(prompt_text: str) -> str:
    normalized = str(prompt_text or "").strip()
    if not normalized:
        raise ValueError("Prompt template must not be empty.")

    transformed = FULL_PROMPT_PLACEHOLDER_PATTERN.sub("{{transcript}}", normalized)
    if "{{transcript}}" not in transformed:
        transformed = f"{transformed}\n\n{{{{transcript}}}}"
    return transformed


def run_writer_skill_eval(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    rewrite_config: dict[str, object] | None = None,
    refresh_samples: bool = False,
    skill_root: str | Path | None = None,
    sample_ids: Iterable[str] | None = None,
) -> WriterSkillEvalReport:
    manifest_file = Path(manifest_path).expanduser()
    samples = load_writer_skill_eval_manifest(manifest_file)
    if sample_ids:
        sample_id_set = {str(item).strip() for item in sample_ids if str(item).strip()}
        samples = tuple(sample for sample in samples if sample.sample_id in sample_id_set)
    manifest_dir = manifest_file.parent
    resolved_skill_root = Path(skill_root).expanduser() if skill_root else resolve_lastpost_skill_root()
    if (resolved_skill_root / "references").exists() and not (resolved_skill_root / "prompts").exists():
        resolved_skill_root = resolved_skill_root / "references"

    skill_prompt_cache: dict[str, str] = {}
    references = load_rewrite_references()
    agent = WriterAgent()

    sample_results: list[WriterSkillEvalSampleResult] = []
    for sample in samples:
        transcript = ensure_writer_skill_eval_transcript(
            sample,
            manifest_dir=manifest_dir,
            refresh=refresh_samples,
        )
        mode_results: list[WriterSkillEvalModeResult] = []

        mode_results.append(
            _run_mode(
                agent=agent,
                sample=sample,
                transcript=transcript,
                mode="speech_verbatim",
                rewrite_style="speech_verbatim",
                rewrite_focus=None,
                rewrite_config=rewrite_config,
                references=references,
            )
        )

        mode_results.append(
            _run_mode(
                agent=agent,
                sample=sample,
                transcript=transcript,
                mode="article_longform",
                rewrite_style="article_longform",
                rewrite_focus=None,
                rewrite_config=rewrite_config,
                references=references,
            )
        )

        baseline_prompt = skill_prompt_cache.get(sample.baseline_prompt_file)
        if baseline_prompt is None:
            prompt_path = resolved_skill_root / "prompts" / sample.baseline_prompt_file
            baseline_prompt = build_full_prompt_from_skill_prompt(
                prompt_path.read_text(encoding="utf-8")
            )
            skill_prompt_cache[sample.baseline_prompt_file] = baseline_prompt

        mode_results.append(
            _run_mode(
                agent=agent,
                sample=sample,
                transcript=transcript,
                mode="full_prompt_baseline",
                rewrite_style="article_longform",
                rewrite_focus=baseline_prompt,
                rewrite_config=rewrite_config,
                references=references,
            )
        )

        sample_results.append(
            WriterSkillEvalSampleResult(
                sample=sample,
                transcript_size=len(transcript.strip()),
                modes=tuple(mode_results),
            )
        )

    summaries = _summarize_modes(sample_results)
    decision_hint = _build_decision_hint(summaries)
    provider = _rewrite_config_provider(rewrite_config)
    model = _rewrite_config_model(rewrite_config)

    return WriterSkillEvalReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        manifest_path=str(manifest_file),
        skill_root=str(resolved_skill_root),
        provider=provider,
        model=model,
        sample_count=len(sample_results),
        samples=tuple(sample_results),
        summaries=summaries,
        decision_hint=decision_hint,
    )


def write_writer_skill_eval_report(
    report: WriterSkillEvalReport,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_ROOT,
) -> tuple[Path, Path]:
    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"

    json_path.write_text(
        json.dumps(writer_skill_eval_report_to_dict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(writer_skill_eval_report_to_markdown(report), encoding="utf-8")
    return json_path, md_path


def writer_skill_eval_report_to_dict(report: WriterSkillEvalReport) -> dict[str, object]:
    return asdict(report)


def writer_skill_eval_report_to_markdown(report: WriterSkillEvalReport) -> str:
    lines: list[str] = []
    lines.extend(
        [
            "# 写作 Skill 有效性评测报告",
            "",
            f"- 生成时间：{report.generated_at}",
            f"- manifest：`{report.manifest_path}`",
            f"- skill root：`{report.skill_root}`",
            f"- provider：`{report.provider}`",
            f"- model：`{report.model}`",
            f"- 样本数：{report.sample_count}",
            "",
            "## 总览",
            "",
            "| mode | 样本数 | 硬细节覆盖率 | 第三视角通过率 | 顺序通过率 | 平均压缩比 | 中文子集压缩 | 第一人称失败 | AI/免责声明命中 | 错误数 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for summary in report.summaries:
        lines.append(
            "| "
            + " | ".join(
                [
                    summary.mode,
                    str(summary.sample_count),
                    _format_rate(summary.hard_detail_rate),
                    _format_rate(summary.third_person_ok_rate),
                    _format_rate(summary.ordering_ok_rate),
                    f"{summary.avg_compression_ratio:.2f}",
                    _format_optional_rate(summary.zh_subset_compression_avg),
                    str(summary.first_person_failures),
                    str(summary.ai_slop_hits),
                    str(summary.error_count),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 决策提示",
            "",
            report.decision_hint,
            "",
        ]
    )

    for sample in report.samples:
        lines.extend(
            [
                f"## {sample.sample.sample_id}",
                "",
                f"- 标题：{sample.sample.title}",
                f"- URL：{sample.sample.url}",
                f"- 类别：{sample.sample.category or '未标注'}",
                f"- baseline prompt：`{sample.sample.baseline_prompt_file}`",
                f"- transcript chars：{sample.transcript_size}",
                f"- 备注：{sample.sample.notes or '无'}",
                "",
            ]
        )

        lines.append(
            "| mode | rewrite_style | 硬覆盖 | 第三视角 | 顺序 | 压缩比 | 语言 | 压缩异常 | revised_once | 错误 |"
        )
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |")
        for mode in sample.modes:
            hard_total = mode.hard_detail_total or 0
            hard_covered = mode.hard_detail_covered or 0
            hard_rate = 0.0 if mode.error or not hard_total else hard_covered / hard_total
            lines.append(
                "| "
                + " | ".join(
                    [
                        mode.mode,
                        str(mode.rewrite_style),
                        _format_rate(hard_rate),
                        "否" if mode.error else ("是" if not mode.first_person_hits else "否"),
                        "否" if mode.error else ("是" if mode.ordering_ok else "否"),
                        f"{mode.compression_ratio:.2f}",
                        mode.output_language_guess or "无",
                        "是" if mode.compression_anomaly else "否",
                        "是" if mode.revised_once else "否",
                        "无" if not mode.error else mode.error,
                    ]
                )
                + " |"
            )

            if mode.route_label or mode.route_reason:
                lines.append(
                    f"  - 路由：{mode.route_label or '无'} / {mode.route_reason or '无'}"
                )
            if mode.detail_coverage_issues:
                lines.append(
                    "  - 细节缺失："
                    + "; ".join(mode.detail_coverage_issues)
                )
            if mode.quality_issues:
                lines.append("  - 质量问题：" + "; ".join(mode.quality_issues))
            if mode.first_person_hits:
                lines.append("  - 第一人称命中：" + "、".join(mode.first_person_hits))
            if mode.ai_slop_hits:
                lines.append("  - AI/免责声明命中：" + "、".join(mode.ai_slop_hits))
            if mode.output_language_guess:
                lines.append("  - 输出语言判定：" + mode.output_language_guess)
            if mode.compression_anomaly:
                lines.append("  - 压缩异常：是")

            lines.extend(
                [
                    "",
                    "<details>",
                    "<summary>输出节选</summary>",
                    "",
                    "```text",
                    _truncate_text(mode.rewritten_text),
                    "```",
                    "",
                    "</details>",
                    "",
                ]
            )

    return "\n".join(lines).strip() + "\n"


def writer_skill_eval_report_from_dict(value: dict[str, object]) -> WriterSkillEvalReport:
    samples_raw = value.get("samples") or []
    summaries_raw = value.get("summaries") or []
    samples: list[WriterSkillEvalSampleResult] = []
    for sample_value in samples_raw:
        if not isinstance(sample_value, dict):
            continue
        sample_raw = sample_value.get("sample") or {}
        sample = WriterSkillEvalSample(
            sample_id=str(sample_raw.get("sample_id") or ""),
            title=str(sample_raw.get("title") or ""),
            url=str(sample_raw.get("url") or ""),
            baseline_prompt_file=str(sample_raw.get("baseline_prompt_file") or ""),
            transcript_path=str(sample_raw.get("transcript_path") or ""),
            category=str(sample_raw.get("category") or ""),
            notes=str(sample_raw.get("notes") or ""),
        )
        modes: list[WriterSkillEvalModeResult] = []
        for mode_value in sample_value.get("modes") or []:
            if not isinstance(mode_value, dict):
                continue
            modes.append(_mode_result_from_dict(mode_value))
        samples.append(
            WriterSkillEvalSampleResult(
                sample=sample,
                transcript_size=int(sample_value.get("transcript_size") or 0),
                modes=tuple(modes),
            )
        )

    summaries: list[WriterSkillEvalModeSummary] = []
    for summary_value in summaries_raw:
        if not isinstance(summary_value, dict):
            continue
        summaries.append(
            WriterSkillEvalModeSummary(
                mode=str(summary_value.get("mode") or ""),
                sample_count=int(summary_value.get("sample_count") or 0),
                hard_detail_rate=float(summary_value.get("hard_detail_rate") or 0.0),
                third_person_ok_rate=float(summary_value.get("third_person_ok_rate") or 0.0),
                ordering_ok_rate=float(summary_value.get("ordering_ok_rate") or 0.0),
                avg_compression_ratio=float(summary_value.get("avg_compression_ratio") or 0.0),
                first_person_failures=int(summary_value.get("first_person_failures") or 0),
                ai_slop_hits=int(summary_value.get("ai_slop_hits") or 0),
                error_count=int(summary_value.get("error_count") or 0),
                zh_subset_compression_avg=(
                    float(summary_value["zh_subset_compression_avg"])
                    if summary_value.get("zh_subset_compression_avg") is not None
                    else None
                ),
            )
        )

    return WriterSkillEvalReport(
        generated_at=str(value.get("generated_at") or ""),
        manifest_path=str(value.get("manifest_path") or ""),
        skill_root=str(value.get("skill_root") or ""),
        provider=str(value.get("provider") or ""),
        model=str(value.get("model") or ""),
        sample_count=int(value.get("sample_count") or 0),
        samples=tuple(samples),
        summaries=tuple(summaries),
        decision_hint=str(value.get("decision_hint") or ""),
    )


def _run_mode(
    *,
    agent: WriterAgent,
    sample: WriterSkillEvalSample,
    transcript: str,
    mode: str,
    rewrite_style: RewriteStyle,
    rewrite_focus: str | None,
    rewrite_config: dict[str, object] | None,
    references,
) -> WriterSkillEvalModeResult:
    source_text = transcript.strip()
    baseline_route = None
    if mode == "article_longform":
        focus_for_route = rewrite_focus or ARTICLE_LONGFORM_DEFAULT_FOCUS
        selected_template = select_rewrite_template(
            source_text=source_text,
            rewrite_focus=focus_for_route,
            references=references,
        )
        baseline_route = selected_template

    try:
        report = agent.run(
            material=MaterialPackage(source_text=source_text),
            rewrite_focus=rewrite_focus,
            rewrite_style=rewrite_style,
            rewrite_config=rewrite_config,
        )
        rewritten_text = report.rewritten_text
        quality_issues = tuple(report.quality_issues)
        agent_detail_coverage_issues = tuple(report.detail_coverage_issues)
        validation_ok = report.draft.validation.ok
        revised_once = report.draft.revised_once
        provider = report.provider
        model = report.model
    except Exception as error:
        return WriterSkillEvalModeResult(
            mode=mode,
            rewrite_style=rewrite_style,
            provider=_rewrite_config_provider(rewrite_config),
            model=_rewrite_config_model(rewrite_config),
            rewritten_text="",
            source_chars=len(source_text),
            output_chars=0,
            compression_ratio=0.0,
            quality_issues=(),
            agent_detail_coverage_issues=(),
            detail_coverage_issues=(str(error),),
            hard_detail_total=0,
            hard_detail_covered=0,
            hard_detail_missing=(),
            ordering_ok=False,
            first_person_hits=(),
            ai_slop_hits=(str(error),),
            validation_ok=False,
            revised_once=False,
            paragraph_count=0,
            output_language_guess="错误",
            compression_anomaly=False,
            route_key=baseline_route.key if baseline_route else None,
            route_label=baseline_route.label if baseline_route else None,
            route_reason=baseline_route.route_reason if baseline_route else None,
            error=str(error),
        )

    ledger = build_detail_ledger(source_text)
    coverage = analyze_detail_coverage(ledger, rewritten_text)
    detail_coverage_issues = format_detail_coverage_issues(coverage)
    first_person_hits = _detect_first_person_hits(rewritten_text)
    ai_slop_hits = _detect_ai_slop_hits(rewritten_text)
    output_language_guess = guess_output_language(rewritten_text)
    ordering_ok = _are_hard_items_in_source_order(ledger, rewritten_text)
    paragraph_count = _count_paragraphs(rewritten_text)
    output_chars = len(rewritten_text.strip())
    hard_total = len(ledger.coverage_items())
    hard_covered = hard_total - len(coverage.missing_items)
    compression_ratio = output_chars / max(1, len(source_text))
    compression_anomaly = compression_ratio > 1.0

    return WriterSkillEvalModeResult(
        mode=mode,
        rewrite_style=rewrite_style,
        provider=provider,
        model=model,
        rewritten_text=rewritten_text,
        source_chars=len(source_text),
        output_chars=output_chars,
        compression_ratio=compression_ratio,
        quality_issues=quality_issues,
        agent_detail_coverage_issues=agent_detail_coverage_issues,
        detail_coverage_issues=detail_coverage_issues,
        hard_detail_total=hard_total,
        hard_detail_covered=hard_covered,
        hard_detail_missing=tuple(item.text for item in coverage.missing_items),
        ordering_ok=ordering_ok,
        first_person_hits=first_person_hits,
        ai_slop_hits=ai_slop_hits,
        validation_ok=validation_ok,
        revised_once=revised_once,
        paragraph_count=paragraph_count,
        output_language_guess=output_language_guess,
        compression_anomaly=compression_anomaly,
        route_key=baseline_route.key if baseline_route else None,
        route_label=baseline_route.label if baseline_route else None,
        route_reason=baseline_route.route_reason if baseline_route else None,
    )


def _rewrite_config_provider(rewrite_config: dict[str, object] | None) -> str:
    if not rewrite_config:
        return ""
    return str(rewrite_config.get("provider") or "")


def _rewrite_config_model(rewrite_config: dict[str, object] | None) -> str:
    if not rewrite_config:
        return ""
    return str(rewrite_config.get("model") or "")


def _summarize_modes(
    sample_results: Iterable[WriterSkillEvalSampleResult],
) -> tuple[WriterSkillEvalModeSummary, ...]:
    mode_buckets: dict[str, list[WriterSkillEvalModeResult]] = {}
    subset_buckets: dict[str, list[float]] = {}
    for sample_result in sample_results:
        for mode in sample_result.modes:
            mode_buckets.setdefault(mode.mode, []).append(mode)
            if sample_result.sample.sample_id in ZH_SUBSET_SAMPLE_IDS and not mode.error:
                subset_buckets.setdefault(mode.mode, []).append(mode.compression_ratio)

    summaries: list[WriterSkillEvalModeSummary] = []
    for mode_name, results in mode_buckets.items():
        sample_count = len(results)
        if not sample_count:
            continue
        hard_rates = []
        third_person_flags = []
        ordering_flags = []
        compression_ratios = []
        for result in results:
            if result.error:
                hard_rates.append(0.0)
                third_person_flags.append(0.0)
                ordering_flags.append(0.0)
                compression_ratios.append(0.0)
                continue
            hard_rates.append(
                (result.hard_detail_covered / result.hard_detail_total)
                if result.hard_detail_total
                else 1.0
            )
            third_person_flags.append(1.0 if not result.first_person_hits else 0.0)
            ordering_flags.append(1.0 if result.ordering_ok else 0.0)
            compression_ratios.append(result.compression_ratio)
        first_person_failures = sum(1 for result in results if result.first_person_hits)
        ai_slop_hits = sum(len(result.ai_slop_hits) for result in results)
        error_count = sum(1 for result in results if result.error)
        subset_ratios = subset_buckets.get(mode_name) or []
        summaries.append(
            WriterSkillEvalModeSummary(
                mode=mode_name,
                sample_count=sample_count,
                hard_detail_rate=sum(hard_rates) / sample_count,
                third_person_ok_rate=sum(third_person_flags) / sample_count,
                ordering_ok_rate=sum(ordering_flags) / sample_count,
                avg_compression_ratio=sum(compression_ratios) / sample_count,
                first_person_failures=first_person_failures,
                ai_slop_hits=ai_slop_hits,
                error_count=error_count,
                zh_subset_compression_avg=(
                    sum(subset_ratios) / len(subset_ratios) if subset_ratios else None
                ),
            )
        )

    order = {"speech_verbatim": 0, "article_longform": 1, "full_prompt_baseline": 2}
    return tuple(sorted(summaries, key=lambda summary: order.get(summary.mode, 99)))


def _build_decision_hint(summaries: tuple[WriterSkillEvalModeSummary, ...]) -> str:
    lookup = {summary.mode: summary for summary in summaries}
    article = lookup.get("article_longform")
    baseline = lookup.get("full_prompt_baseline")
    speech = lookup.get("speech_verbatim")

    if article is None or baseline is None or speech is None:
        return "评测尚不完整，暂时不要下结论。"

    if any(summary.error_count > 0 for summary in summaries):
        return "评测过程中存在 provider/model 错误，暂时不要下结论；先换成可用的模型把三路样本跑完整。"

    article_first_person = article.first_person_failures > 0
    article_coverage_weak = article.hard_detail_rate < 0.8
    baseline_better_coverage = baseline.hard_detail_rate > article.hard_detail_rate + 0.05
    speech_coverage_ok = speech.hard_detail_rate >= 0.8

    if article_first_person or article_coverage_weak or baseline_better_coverage:
        reasons: list[str] = []
        if article_first_person:
            reasons.append("article_longform 仍有第一人称泄漏")
        if article_coverage_weak:
            reasons.append("article_longform 细节保真率偏低")
        if baseline_better_coverage:
            reasons.append("全量 prompt 基线在硬细节覆盖上明显更稳")
        return "；".join(reasons) + "。建议先收缩 latepost-skill，再决定是否抽通用 runner。"

    if speech_coverage_ok and not article_first_person:
        return "当前两条主线都能跑通，但 article_longform 没显示出足够优势。建议先保留现有结构，只继续修具体失败样本。"

    return "三路结果接近，暂时不引入新的 runner 抽象，继续用样本迭代规则。"


def _fetch_transcript_text(url: str) -> str:
    source = fetch_video_source(url)
    if source.source_type == "captions" and source.text:
        return source.text.strip()

    if source.source_type == "audio" and source.audio_file_path:
        from app.services.transcription_service import transcribe_audio_file

        transcript = transcribe_audio_file(source.audio_file_path)
        return transcript.text.strip()

    raise CaptionServiceError("Could not fetch transcript text from the provided URL.")


def _detect_first_person_hits(text: str) -> tuple[str, ...]:
    normalized = _strip_quoted_spans(text)
    hits: list[str] = []
    lowered = normalized.lower()
    for marker in ARTICLE_LONGFORM_FIRST_PERSON_MARKERS:
        if marker in normalized or marker.lower() in lowered:
            hits.append(marker)
    return tuple(hits)


def _detect_ai_slop_hits(text: str) -> tuple[str, ...]:
    normalized = _strip_quoted_spans(text)
    lowered = normalized.lower()
    hits: list[str] = []
    for marker in AI_SLOP_MARKERS:
        if marker in lowered:
            hits.append(marker)
    deduped: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        if hit in seen:
            continue
        seen.add(hit)
        deduped.append(hit)
    return tuple(deduped)


def _are_hard_items_in_source_order(ledger, text: str) -> bool:
    """检查改写文本里**实际出现的** hard items 是否按 ledger 顺序排列。

    把"缺失"和"倒序"分开判定：
    - 如果 item 整体不在 text 里 → 由 hard_detail_rate 单独统计，这里跳过。
    - 如果 item 在 text 里但只出现在 cursor 之前 → 真乱序，返回 False。

    这样"顺序通过率"才能独立于"覆盖率"反映 agent 真实的顺序保持能力。
    """
    normalized_text = _normalize_text(text)
    cursor = 0
    for item in ledger.coverage_items():
        token = _normalize_text(item.text)
        if not token:
            continue
        if token not in normalized_text:
            continue
        position = normalized_text.find(token, cursor)
        if position < 0:
            return False
        cursor = position + len(token)
    return True


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def _count_paragraphs(text: str) -> int:
    paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", text or "") if segment.strip()]
    return len(paragraphs)


def _truncate_text(text: str, limit: int = 1200) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _format_rate(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_optional_rate(value: float | None) -> str:
    if value is None:
        return "-"
    return _format_rate(value)


def _mode_result_from_dict(value: dict[str, object]) -> WriterSkillEvalModeResult:
    return WriterSkillEvalModeResult(
        mode=str(value.get("mode") or ""),
        rewrite_style=str(value.get("rewrite_style") or "article_longform"),
        provider=str(value.get("provider") or ""),
        model=str(value.get("model") or ""),
        rewritten_text=str(value.get("rewritten_text") or ""),
        source_chars=int(value.get("source_chars") or 0),
        output_chars=int(value.get("output_chars") or 0),
        compression_ratio=float(value.get("compression_ratio") or 0.0),
        quality_issues=tuple(value.get("quality_issues") or ()),
        agent_detail_coverage_issues=tuple(value.get("agent_detail_coverage_issues") or ()),
        detail_coverage_issues=tuple(value.get("detail_coverage_issues") or ()),
        hard_detail_total=int(value.get("hard_detail_total") or 0),
        hard_detail_covered=int(value.get("hard_detail_covered") or 0),
        hard_detail_missing=tuple(value.get("hard_detail_missing") or ()),
        ordering_ok=bool(value.get("ordering_ok")),
        first_person_hits=tuple(value.get("first_person_hits") or ()),
        ai_slop_hits=tuple(value.get("ai_slop_hits") or ()),
        output_language_guess=str(value.get("output_language_guess") or ""),
        compression_anomaly=bool(value.get("compression_anomaly")),
        validation_ok=bool(value.get("validation_ok")),
        revised_once=bool(value.get("revised_once")),
        paragraph_count=int(value.get("paragraph_count") or 0),
        route_key=value.get("route_key") or None,
        route_label=value.get("route_label") or None,
        route_reason=value.get("route_reason") or None,
        error=value.get("error") or None,
    )
