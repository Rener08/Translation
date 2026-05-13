"""DetailLedger: regex-based extraction of key details for content rewriting."""

from dataclasses import dataclass
import re

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
    "但是", "但", "不过", "然而", "其实", "所以", "因此",
    "总之", "总的来说", "归根结底", "关键是", "最重要的是", "结论是",
)
DETAIL_LEDGER_TURN_MAX_ITEMS = 3
DETAIL_LEDGER_TURN_SPLIT_PATTERN = re.compile(r"(?<=[.!?。！？；;])|\n+")
DETAIL_LEDGER_QUOTE_PATTERN = re.compile(r'["「"「](.+?)["」"」]')
DETAIL_LEDGER_CJK_QUOTE_PATTERN = re.compile(r'[「『](.+?)[」』]')
DETAIL_LEDGER_CJK_ENTITY_PATTERN = re.compile(
    r'[一-鿿]{2,6}(?:公司|集团|平台|产品|引擎|模型|系统|技术|芯片|基金|大学|研究院|实验室|团队|部门)'
    r'|[一-鿿]{2,4}(?:\.ai|AI|GPT|LLM)'
)
DETAIL_LEDGER_RELATIVE_DATE_PATTERN = re.compile(
    r'(?:去年|今年|明年|上月|本月|下月|上周|本周|下周|去年底|今年初|近期|近日|目前)'
)
DETAIL_LEDGER_ENTITY_STOPWORDS = {
    "a", "an", "and", "as", "at", "but", "for", "in", "into",
    "is", "it", "of", "on", "or", "the", "to", "with",
}
DETAIL_LEDGER_STRONG_ENTITY_TOKENS = {
    "nasa", "spacex", "openai", "deepseek", "youtube", "chatgpt",
    "ollama", "lmstudio", "lm studio",
}


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


def build_detail_ledger(source_text: str) -> DetailLedger:
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
                items, seen,
                DetailLedgerItem(
                    kind="关键句", text=_trim_detail_text(candidate),
                    preserve_exact=False,
                ),
            )
            if len(items) >= DETAIL_LEDGER_MAX_ITEMS:
                break

    return DetailLedger(items=tuple(items))


def analyze_detail_coverage(
    ledger: DetailLedger,
    rewritten_text: str,
) -> DetailCoverageResult:
    """Check coverage of exact-preserve items only (backward compatible)."""
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


def analyze_detail_coverage_enhanced(
    ledger: DetailLedger,
    rewritten_text: str,
) -> DetailCoverageResult:
    """Check coverage with fuzzy matching for non-exact items.

    - preserve_exact=True items: exact substring match
    - preserve_exact=False items: fuzzy match (strip punctuation and whitespace)
    """
    normalized_rewrite = _normalize_detail_token(rewritten_text)
    fuzzy_rewrite = _normalize_for_fuzzy_match(rewritten_text)
    missing: list[DetailLedgerItem] = []

    for item in ledger.items:
        if item.preserve_exact:
            token = _normalize_detail_token(item.text)
            if not token:
                continue
            if token in normalized_rewrite:
                continue
        else:
            token = _normalize_for_fuzzy_match(item.text)
            if len(token) < 4:
                continue
            if token in fuzzy_rewrite:
                continue
        missing.append(item)

    return DetailCoverageResult(missing_items=tuple(missing))


def _normalize_for_fuzzy_match(value: str) -> str:
    """Strip punctuation and whitespace for fuzzy coverage matching."""
    result = re.sub(r'[^\w一-鿿]', '', (value or '').strip().lower())
    return result


def build_detail_patch_prompt(missing_items: tuple[DetailLedgerItem, ...]) -> str:
    lines = [
        "请只补足下面缺失的细节，不要重写整篇，不要压缩，不要新增事实。",
        "",
        "缺失细节：",
    ]
    for item in missing_items[:DETAIL_LEDGER_PATCH_ITEMS]:
        lines.append(f"- {item.kind}: {item.text}")
    lines.extend([
        "",
        "要求：把这些细节自然补回正文中，保留原作者口吻和顺序，只输出正文。",
    ])
    return "\n".join(lines)


def build_detail_patch_ledger(missing_items: tuple[DetailLedgerItem, ...]) -> str:
    if not missing_items:
        return ""
    return "\n".join(
        f"- {item.kind}: {item.text}" for item in missing_items[:DETAIL_LEDGER_PATCH_ITEMS]
    )


def format_detail_coverage_issues(coverage: DetailCoverageResult) -> tuple[str, ...]:
    if not coverage.missing_items:
        return ()
    return tuple(
        f"缺失细节：{item.kind} {item.text}"
        for item in coverage.missing_items[:DETAIL_LEDGER_PATCH_ITEMS]
    )


# --- internal helpers ---

def _extract_detail_tokens(source_text: str) -> tuple[DetailLedgerItem, ...]:
    items: list[DetailLedgerItem] = []
    seen: set[tuple[str, str]] = set()

    for number in _find_detail_numbers(source_text):
        _append_detail_item(items, seen,
            DetailLedgerItem(kind="数字", text=number, preserve_exact=True))

    for date in _find_detail_dates(source_text):
        _append_detail_item(items, seen,
            DetailLedgerItem(kind="日期", text=date, preserve_exact=True))

    for date in _find_detail_relative_dates(source_text):
        _append_detail_item(items, seen,
            DetailLedgerItem(kind="相对时间", text=date, preserve_exact=False))

    for entity in _find_detail_entities(source_text):
        _append_detail_item(items, seen, entity)

    for entity in _find_detail_cjk_entities(source_text):
        _append_detail_item(items, seen, entity)

    for quote in _find_detail_quotes(source_text):
        _append_detail_item(items, seen,
            DetailLedgerItem(kind="原话", text=quote, preserve_exact=True))

    for turn in _find_detail_turns(source_text):
        _append_detail_item(items, seen,
            DetailLedgerItem(kind="转折/结论句", text=turn, preserve_exact=False))

    for fragment in _find_detail_fragments(source_text):
        _append_detail_item(items, seen,
            DetailLedgerItem(kind="关键句", text=fragment, preserve_exact=False))

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


def _find_detail_relative_dates(source_text: str) -> tuple[str, ...]:
    dates: list[str] = []
    seen: set[str] = set()
    for match in DETAIL_LEDGER_RELATIVE_DATE_PATTERN.finditer(source_text):
        token = _trim_detail_text(match.group(0))
        if not token:
            continue
        normalized = _normalize_detail_token(token)
        if normalized in seen:
            continue
        seen.add(normalized)
        dates.append(token)
    return tuple(dates)


def _find_detail_cjk_entities(source_text: str) -> tuple[DetailLedgerItem, ...]:
    entities: list[DetailLedgerItem] = []
    seen: set[str] = set()
    for match in DETAIL_LEDGER_CJK_ENTITY_PATTERN.finditer(source_text):
        token = _trim_detail_text(match.group(0))
        if not token:
            continue
        normalized = _normalize_detail_token(token)
        if normalized in seen:
            continue
        seen.add(normalized)
        entities.append(DetailLedgerItem(
            kind="专有名词", text=token, preserve_exact=True,
        ))
    return tuple(entities)


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
        entities.append(DetailLedgerItem(
            kind="专有名词", text=token, preserve_exact=preserve_exact,
        ))
    return tuple(entities)


def _find_detail_quotes(source_text: str) -> tuple[str, ...]:
    quotes: list[str] = []
    seen: set[str] = set()
    for pattern in (DETAIL_LEDGER_QUOTE_PATTERN, DETAIL_LEDGER_CJK_QUOTE_PATTERN):
        for match in pattern.finditer(source_text):
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
    return [f for f in DETAIL_LEDGER_SPLIT_PATTERN.split(source_text) if f.strip()]


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
            "subscribe", "subscribe to", "thanks for watching",
            "thank you for watching", "please like", "like and subscribe",
            "欢迎订阅", "感谢收看", "点赞", "订阅",
        )
    )
