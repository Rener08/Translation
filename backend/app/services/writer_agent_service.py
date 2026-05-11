from dataclasses import dataclass
import re
from typing import Literal

from app.services.article_generation_service import (
    ArticleSpec,
    ArticleValidationResult,
    build_article_rewrite_prompt,
    resolve_article_spec,
    validate_generated_article,
)
from app.services.content_rewrite_service import (
    ContentRewriteResult,
    DEFAULT_REWRITE_STYLE,
    RewriteStyle,
    rewrite_content,
)
from app.services.content_rewrite_service import ContentRewriteInputError
from app.services.prompt_validation import validate_rewrite_prompt

DETAIL_LEDGER_MAX_ITEMS = 10
DETAIL_LEDGER_PATCH_ITEMS = 6
DETAIL_LEDGER_FRAGMENT_LIMIT = 120
DETAIL_LEDGER_SPLIT_PATTERN = re.compile(r"(?<=[.!?。！？；;])\s+|\n+")
DETAIL_LEDGER_ENTITY_PATTERN = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9'’.-]*|[A-Z]{2,}(?:-[A-Z]{2,})*)(?:\s+(?:[A-Z][A-Za-z0-9'’.-]*|[A-Z]{2,}(?:-[A-Z]{2,})*))*\b"
)
DETAIL_LEDGER_NUMBER_PATTERN = re.compile(
    r"(?:[$€£¥]\s?)?\b\d{1,4}(?:[,:/.-]\d{1,4})*(?:\.\d+)?%?\b"
)
DETAIL_LEDGER_DATE_PATTERN = re.compile(
    r"\d{2,4}\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*[日号])?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*[日号]"
    r"|\d{1,2}\s*月(?!\d)"
)
DETAIL_LEDGER_TURN_MARKERS: tuple[str, ...] = (
    "但是",
    "但",
    "不过",
    "然而",
    "其实",
    "所以",
    "因此",
    "总之",
    "总的来说",
    "归根结底",
    "关键是",
    "最重要的是",
    "结论是",
)
DETAIL_LEDGER_TURN_MAX_ITEMS = 3
DETAIL_LEDGER_TURN_SPLIT_PATTERN = re.compile(r"(?<=[.!?。！？；;])|\n+")
DETAIL_LEDGER_QUOTE_PATTERN = re.compile(r'["“](.+?)["”]')
DETAIL_LEDGER_ENTITY_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "for",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

DETAIL_LEDGER_STRONG_ENTITY_TOKENS = {
    "nasa",
    "spacex",
    "openai",
    "deepseek",
    "youtube",
    "chatgpt",
    "ollama",
    "lmstudio",
    "lm studio",
}
ARTICLE_LONGFORM_FIRST_PERSON_MARKERS: tuple[str, ...] = (
    "我想",
    "我会",
    "我认为",
    "我觉得",
    "我来",
    "我要",
    "我先",
    "我正在",
    "我们",
    "我们先",
    "我们会",
    "我们认为",
    "我们觉得",
    "咱们",
    "本人",
)


@dataclass(frozen=True)
class DetailLedgerItem:
    kind: str
    text: str
    preserve_exact: bool = True


@dataclass(frozen=True)
class DetailLedger:
    items: tuple[DetailLedgerItem, ...]

    def to_prompt_text(self, limit: int = DETAIL_LEDGER_MAX_ITEMS) -> str:
        if not self.items:
            return "未提取到可单独保留的细节，请优先保留原文顺序和口吻。"

        exact_items = [item for item in self.items if item.preserve_exact][:limit]
        soft_items = [item for item in self.items if not item.preserve_exact][:limit]

        lines: list[str] = []
        if exact_items:
            lines.append("【必须保留】")
            lines.extend(f"- {item.kind}: {item.text}" for item in exact_items)
        if soft_items:
            lines.append("【优先保留】")
            lines.extend(f"- {item.kind}: {item.text}" for item in soft_items)
        return "\n".join(lines)

    def coverage_items(self) -> tuple[DetailLedgerItem, ...]:
        return tuple(item for item in self.items if item.preserve_exact)


@dataclass(frozen=True)
class DetailCoverageResult:
    missing_items: tuple[DetailLedgerItem, ...]


@dataclass(frozen=True)
class MaterialPackage:
    source_text: str
    source_language: str = "en"
    translation_language: str = "zh-CN"


@dataclass(frozen=True)
class ArticleDraft:
    text: str
    outline: tuple[str, ...]
    spec: ArticleSpec
    validation: ArticleValidationResult
    revised_once: bool


@dataclass(frozen=True)
class WriterRunReport:
    rewritten_text: str
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    model: str
    quality_issues: tuple[str, ...]
    material: MaterialPackage
    draft: ArticleDraft
    rewrite_style: RewriteStyle
    detail_coverage_issues: tuple[str, ...] = ()


class WriterAgent:
    def run(
        self,
        *,
        material: MaterialPackage,
        rewrite_focus: str | None = None,
        rewrite_style: RewriteStyle | None = None,
        rewrite_config: dict[str, object] | None = None,
    ) -> WriterRunReport:
        normalized_source = (material.source_text or "").strip()
        if not normalized_source:
            raise ValueError("material.source_text must not be empty.")

        normalized_style = rewrite_style or DEFAULT_REWRITE_STYLE

        normalized_focus = None
        if rewrite_focus is not None:
            normalized_focus = rewrite_focus.strip()
            if not normalized_focus:
                raise ContentRewriteInputError(
                    "改写提示为空。请重新选择写作风格，或移除空白 rewrite_focus 后重试。"
                )
            validation = validate_rewrite_prompt(normalized_focus)
            if not validation.is_valid:
                raise ContentRewriteInputError("；".join(validation.errors))
            if validation.has_transcript_placeholder:
                direct_result = rewrite_content(
                    source_text=normalized_source,
                    rewrite_focus=normalized_focus,
                    rewrite_style=normalized_style,
                    rewrite_config=rewrite_config,
                )
                spec = resolve_article_spec(normalized_source)
                draft_validation = validate_generated_article(direct_result.rewritten_text, spec)
                return WriterRunReport(
                    rewritten_text=direct_result.rewritten_text,
                    provider=direct_result.provider,
                    model=direct_result.model,
                    quality_issues=tuple(direct_result.quality_issues),
                    material=material,
                    draft=ArticleDraft(
                        text=direct_result.rewritten_text,
                        outline=("full_prompt_passthrough",),
                        spec=spec,
                        validation=draft_validation,
                        revised_once=False,
                    ),
                    rewrite_style=normalized_style,
                )

        spec = resolve_article_spec(normalized_source)
        if normalized_style == "speech_verbatim":
            detail_ledger = _build_detail_ledger(normalized_source)
            direct_result = rewrite_content(
                source_text=normalized_source,
                rewrite_focus=normalized_focus,
                rewrite_style=normalized_style,
                rewrite_config=rewrite_config,
                detail_ledger=detail_ledger.to_prompt_text(),
            )
            coverage = _analyze_detail_coverage(
                detail_ledger,
                direct_result.rewritten_text,
            )
            final_result = direct_result
            patched_once = False
            if coverage.missing_items:
                patched_once = True
                patch_result = rewrite_content(
                    source_text=normalized_source,
                    rewrite_focus=_build_detail_patch_prompt(coverage.missing_items),
                    rewrite_style=normalized_style,
                    rewrite_config=rewrite_config,
                    detail_ledger=_build_detail_patch_ledger(coverage.missing_items),
                )
                final_result = patch_result
                coverage = _analyze_detail_coverage(
                    detail_ledger,
                    final_result.rewritten_text,
                )

            validation = _build_soft_validation(final_result.rewritten_text)
            return WriterRunReport(
                rewritten_text=final_result.rewritten_text,
                provider=final_result.provider,
                model=final_result.model,
                quality_issues=tuple(final_result.quality_issues),
                material=material,
                draft=ArticleDraft(
                    text=final_result.rewritten_text,
                    outline=("speech_verbatim",),
                    spec=spec,
                    validation=validation,
                    revised_once=patched_once,
                ),
                rewrite_style=normalized_style,
                detail_coverage_issues=_format_detail_coverage_issues(coverage),
            )

        planning_result = rewrite_content(
            source_text=normalized_source,
            rewrite_focus=_build_outline_prompt(spec=spec, rewrite_focus=normalized_focus),
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
        )
        outline = _extract_outline(planning_result.rewritten_text)

        draft_result = rewrite_content(
            source_text=normalized_source,
            rewrite_focus=_build_draft_prompt(
                spec=spec,
                rewrite_focus=normalized_focus,
                outline=outline,
            ),
            rewrite_style="article_longform",
            rewrite_config=rewrite_config,
        )
        validation = validate_generated_article(draft_result.rewritten_text, spec)
        style_issues = _detect_article_longform_style_issues(draft_result.rewritten_text)
        final_result = draft_result
        revised_once = False

        if not validation.ok or style_issues:
            revised_once = True
            revise_prompt = build_article_rewrite_prompt(
                previous_article=draft_result.rewritten_text,
                spec=spec,
                validation=validation,
                style_issues=style_issues,
            )
            final_result = rewrite_content(
                source_text=normalized_source,
                rewrite_focus=revise_prompt,
                rewrite_style="article_longform",
                rewrite_config=rewrite_config,
            )
            validation = validate_generated_article(final_result.rewritten_text, spec)
            style_issues = _detect_article_longform_style_issues(final_result.rewritten_text)

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
                validation=validation,
                revised_once=revised_once,
            ),
            rewrite_style=normalized_style,
        )


def run_writer_agent(
    *,
    source_text: str,
    rewrite_focus: str | None = None,
    rewrite_style: RewriteStyle | None = None,
    rewrite_config: dict[str, object] | None = None,
) -> ContentRewriteResult:
    agent = WriterAgent()
    material = MaterialPackage(source_text=source_text)
    report = agent.run(
        material=material,
        rewrite_focus=rewrite_focus,
        rewrite_style=rewrite_style,
        rewrite_config=rewrite_config,
    )
    return ContentRewriteResult(
        rewritten_text=report.rewritten_text,
        provider=report.provider,
        model=report.model,
        quality_issues=report.quality_issues,
        detail_coverage_issues=report.detail_coverage_issues,
    )


def _build_soft_validation(text: str) -> ArticleValidationResult:
    normalized_text = (text or "").strip()
    if not normalized_text:
        return ArticleValidationResult(
            ok=False,
            total_chars=0,
            section_count=0,
            section_chars=(),
            issues=("Article is empty.",),
        )

    sections = tuple(
        section.strip()
        for section in normalized_text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
        if section.strip()
    )
    if not sections:
        sections = (normalized_text,)

    section_chars = tuple(len(section) for section in sections)
    return ArticleValidationResult(
        ok=True,
        total_chars=sum(section_chars),
        section_count=len(sections),
        section_chars=section_chars,
        issues=(),
    )


def _detect_article_longform_style_issues(text: str) -> tuple[str, ...]:
    normalized_text = _strip_quoted_spans(text)
    if not normalized_text.strip():
        return ()

    if any(marker in normalized_text for marker in ARTICLE_LONGFORM_FIRST_PERSON_MARKERS):
        return (
            "文章仍包含第一人称自述，请改成第三视角叙述，不要使用我/我们/咱们作为叙述主语。",
        )

    return ()


def _build_detail_ledger(source_text: str) -> DetailLedger:
    normalized_source = (source_text or "").strip()
    if not normalized_source:
        return DetailLedger(items=())

    items: list[DetailLedgerItem] = []
    seen: set[tuple[str, str]] = set()

    for token in _extract_detail_tokens(normalized_source):
        _append_detail_item(items, seen, token)
        if len(items) >= DETAIL_LEDGER_MAX_ITEMS:
            break

    if not items:
        for fragment in _split_detail_fragments(normalized_source):
            candidate = fragment.strip()
            if len(candidate) < 24:
                continue
            _append_detail_item(
                items,
                seen,
                DetailLedgerItem(
                    kind="关键句",
                    text=_trim_detail_text(candidate),
                    preserve_exact=False,
                ),
            )
            if len(items) >= DETAIL_LEDGER_MAX_ITEMS:
                break

    return DetailLedger(items=tuple(items))


def _extract_detail_tokens(source_text: str) -> tuple[DetailLedgerItem, ...]:
    items: list[DetailLedgerItem] = []
    seen: set[tuple[str, str]] = set()

    for number in _find_detail_numbers(source_text):
        _append_detail_item(
            items,
            seen,
            DetailLedgerItem(kind="数字", text=number, preserve_exact=True),
        )

    for date in _find_detail_dates(source_text):
        _append_detail_item(
            items,
            seen,
            DetailLedgerItem(kind="日期", text=date, preserve_exact=True),
        )

    for entity in _find_detail_entities(source_text):
        _append_detail_item(items, seen, entity)

    for quote in _find_detail_quotes(source_text):
        _append_detail_item(
            items,
            seen,
            DetailLedgerItem(kind="原话", text=quote, preserve_exact=True),
        )

    for turn in _find_detail_turns(source_text):
        _append_detail_item(
            items,
            seen,
            DetailLedgerItem(kind="转折/结论句", text=turn, preserve_exact=False),
        )

    for fragment in _find_detail_fragments(source_text):
        _append_detail_item(
            items,
            seen,
            DetailLedgerItem(kind="关键句", text=fragment, preserve_exact=False),
        )

    return tuple(items[:DETAIL_LEDGER_MAX_ITEMS])


def _find_detail_numbers(source_text: str) -> tuple[str, ...]:
    numbers: list[str] = []
    seen: set[str] = set()
    for match in DETAIL_LEDGER_NUMBER_PATTERN.finditer(source_text):
        token = _trim_detail_text(match.group(0))
        if not token:
            continue
        normalized = _normalize_detail_token(token)
        if normalized in seen:
            continue
        seen.add(normalized)
        numbers.append(token)
    return tuple(numbers)


def _find_detail_dates(source_text: str) -> tuple[str, ...]:
    dates: list[str] = []
    seen: set[str] = set()
    for match in DETAIL_LEDGER_DATE_PATTERN.finditer(source_text):
        token = _trim_detail_text(match.group(0))
        if not token:
            continue
        normalized = _normalize_detail_token(token)
        if normalized in seen:
            continue
        seen.add(normalized)
        dates.append(token)
    return tuple(dates)


def _find_detail_turns(source_text: str) -> tuple[str, ...]:
    turns: list[str] = []
    seen: set[str] = set()
    for fragment in DETAIL_LEDGER_TURN_SPLIT_PATTERN.split(source_text or ""):
        candidate = _trim_detail_text(fragment)
        if len(candidate) < 8:
            continue
        if not _starts_with_turn_marker(candidate):
            continue
        normalized = _normalize_detail_token(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        turns.append(_trim_detail_text(candidate, DETAIL_LEDGER_FRAGMENT_LIMIT))
        if len(turns) >= DETAIL_LEDGER_TURN_MAX_ITEMS:
            break
    return tuple(turns)


def _starts_with_turn_marker(value: str) -> bool:
    head = (value or "").lstrip()
    if not head:
        return False
    for marker in DETAIL_LEDGER_TURN_MARKERS:
        if head.startswith(marker):
            return True
    return False


def _find_detail_entities(source_text: str) -> tuple[DetailLedgerItem, ...]:
    entities: list[DetailLedgerItem] = []
    seen: set[str] = set()
    for match in DETAIL_LEDGER_ENTITY_PATTERN.finditer(source_text):
        token = _trim_detail_text(match.group(0))
        if not token:
            continue
        normalized = _normalize_detail_token(token)
        if normalized in DETAIL_LEDGER_ENTITY_STOPWORDS:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        preserve_exact = _is_strong_entity_anchor(token)
        entities.append(
            DetailLedgerItem(
                kind="专有名词",
                text=token,
                preserve_exact=preserve_exact,
            )
        )
    return tuple(entities)


def _find_detail_quotes(source_text: str) -> tuple[str, ...]:
    quotes: list[str] = []
    seen: set[str] = set()
    for match in DETAIL_LEDGER_QUOTE_PATTERN.finditer(source_text):
        token = _trim_detail_text(match.group(1))
        if len(token) < 4:
            continue
        normalized = _normalize_detail_token(token)
        if normalized in seen:
            continue
        seen.add(normalized)
        quotes.append(token)
    return tuple(quotes)


def _find_detail_fragments(source_text: str) -> tuple[str, ...]:
    fragments: list[str] = []
    seen: set[str] = set()
    for fragment in _split_detail_fragments(source_text):
        candidate = _trim_detail_text(fragment)
        if len(candidate) < 24:
            continue
        if _looks_like_boilerplate(candidate):
            continue
        normalized = _normalize_detail_token(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        fragments.append(_trim_detail_text(candidate, DETAIL_LEDGER_FRAGMENT_LIMIT))
        if len(fragments) >= 4:
            break
    return tuple(fragments)


def _split_detail_fragments(source_text: str) -> list[str]:
    return [fragment for fragment in DETAIL_LEDGER_SPLIT_PATTERN.split(source_text) if fragment.strip()]


def _append_detail_item(
    items: list[DetailLedgerItem],
    seen: set[tuple[str, str]],
    item: DetailLedgerItem,
) -> None:
    normalized = (_normalize_detail_token(item.kind), _normalize_detail_token(item.text))
    if normalized in seen:
        return
    seen.add(normalized)
    items.append(item)


def _normalize_detail_token(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def _is_strong_entity_anchor(token: str) -> bool:
    normalized = _normalize_detail_token(token)
    if normalized in DETAIL_LEDGER_STRONG_ENTITY_TOKENS:
        return True
    return token.isupper() and len(token) <= 12


def _trim_detail_text(value: str, limit: int = DETAIL_LEDGER_FRAGMENT_LIMIT) -> str:
    normalized = re.sub(r"\s+", " ", (value or "").strip())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _looks_like_boilerplate(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in (
            "subscribe",
            "subscribe to",
            "thanks for watching",
            "thank you for watching",
            "please like",
            "like and subscribe",
            "欢迎订阅",
            "感谢收看",
            "点赞",
            "订阅",
        )
    )


def _analyze_detail_coverage(
    ledger: DetailLedger,
    rewritten_text: str,
) -> DetailCoverageResult:
    normalized_rewrite = _normalize_detail_token(rewritten_text)
    missing: list[DetailLedgerItem] = []
    for item in ledger.coverage_items():
        token = _normalize_detail_token(item.text)
        if not token:
            continue
        if token in normalized_rewrite:
            continue
        missing.append(item)
    return DetailCoverageResult(missing_items=tuple(missing))


def _build_detail_patch_prompt(missing_items: tuple[DetailLedgerItem, ...]) -> str:
    lines = [
        "请只补足下面缺失的细节，不要重写整篇，不要压缩，不要新增事实。",
        "",
        "缺失细节：",
    ]
    for item in missing_items[:DETAIL_LEDGER_PATCH_ITEMS]:
        lines.append(f"- {item.kind}: {item.text}")
    lines.extend(
        [
            "",
            "要求：把这些细节自然补回正文中，保留原作者口吻和顺序，只输出正文。",
        ]
    )
    return "\n".join(lines)


def _build_detail_patch_ledger(missing_items: tuple[DetailLedgerItem, ...]) -> str:
    if not missing_items:
        return ""
    return "\n".join(
        f"- {item.kind}: {item.text}" for item in missing_items[:DETAIL_LEDGER_PATCH_ITEMS]
    )


def _format_detail_coverage_issues(coverage: DetailCoverageResult) -> tuple[str, ...]:
    if not coverage.missing_items:
        return ()
    return tuple(
        f"缺失细节：{item.kind} {item.text}" for item in coverage.missing_items[:DETAIL_LEDGER_PATCH_ITEMS]
    )


def _build_outline_prompt(*, spec: ArticleSpec, rewrite_focus: str | None) -> str:
    focus_text = (rewrite_focus or "科技深度中文文章").strip()
    return (
        "请基于原始素材先给出写作规划。\n\n"
        f"写作目标：{focus_text}\n"
        f"目标字数：{spec.target_total_chars}（允许 {spec.min_total_chars}-{spec.max_total_chars}）\n"
        f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）\n\n"
        "只输出一个简短大纲，每行一个要点。"
    )


def _build_draft_prompt(
    *,
    spec: ArticleSpec,
    rewrite_focus: str | None,
    outline: tuple[str, ...],
) -> str:
    focus_text = (rewrite_focus or "保留原意并提升中文可读性").strip()
    outline_text = "\n".join(f"- {line}" for line in outline) if outline else "- 按素材主线组织段落"
    return (
        "请按以下要求输出中文文章初稿。\n\n"
        f"写作目标：{focus_text}\n"
        f"总字数：{spec.min_total_chars}-{spec.max_total_chars}（目标 {spec.target_total_chars}）\n"
        f"段落数：{spec.min_sections}-{spec.max_sections}（推荐 {spec.recommended_sections}）\n"
        f"每段字数：{spec.min_chars_per_section}-{spec.max_chars_per_section}（建议 {spec.target_chars_per_section}）\n\n"
        "大纲：\n"
        f"{outline_text}\n\n"
        "要求：不编造事实，段落之间空行，只输出正文。"
    )


def _extract_outline(text: str) -> tuple[str, ...]:
    lines = [line.strip(" -\t") for line in (text or "").splitlines()]
    cleaned = tuple(line for line in lines if line)
    if cleaned:
        return cleaned[:8]
    return ("按素材主线组织段落",)


def _strip_quoted_spans(text: str) -> str:
    normalized = text or ""
    normalized = re.sub(r'"[^"]*"', " ", normalized)
    normalized = re.sub(r"“[^”]*”", " ", normalized)
    normalized = re.sub(r"『[^』]*』", " ", normalized)
    normalized = re.sub(r"「[^」]*」", " ", normalized)
    return normalized
