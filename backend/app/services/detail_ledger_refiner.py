"""LLM-based refinement of DetailLedger items.

Takes a coarse regex-based ledger and uses an LLM to:
- Deduplicate similar items
- Assign priority (high/medium/low)
- Supplement missing critical details from source text

Only used in article_longform mode for cost control.
"""

from dataclasses import dataclass
import json
import re

from app.services.detail_ledger import (
    DetailLedger,
    DetailLedgerItem,
)


@dataclass(frozen=True)
class RefinedDetailItem:
    kind: str
    text: str
    priority: str  # "high", "medium", "low"


@dataclass(frozen=True)
class RefinedDetailLedger:
    items: tuple[RefinedDetailItem, ...]

    def to_detail_ledger(self) -> DetailLedger:
        """Convert back to a DetailLedger with preserve_exact set by priority."""
        return DetailLedger(items=tuple(
            DetailLedgerItem(
                kind=item.kind,
                text=item.text,
                preserve_exact=(item.priority == "high"),
            )
            for item in self.items
        ))

    def high_items(self) -> tuple[RefinedDetailItem, ...]:
        return tuple(i for i in self.items if i.priority == "high")


_REFINE_SYSTEM_PROMPT = """你是一个细节提取和优先级标注助手。

任务：分析用户提供的"原文"和"粗筛细节清单"，输出一个精炼后的细节清单。

规则：
1. 去除重复或高度相似的条目。
2. 为每个条目标注 priority：
   - "high": 关键数字、核心人名/公司名、直接引语。改写时必须保留。
   - "medium": 重要转折句、关键观点。改写时优先保留。
   - "low": 补充性细节。有则更好。
3. 如果原文中有粗筛漏掉的关键细节（如重要数字、核心引语），补充进来。
4. 输出 JSON 数组，每个元素格式：{"kind": "...", "text": "...", "priority": "..."}
5. 最多输出 12 个条目。
6. 只输出 JSON，不要其他内容。"""


def refine_detail_ledger_with_llm(
    *,
    source_text: str,
    coarse_ledger: DetailLedger,
    llm_call_fn,
) -> RefinedDetailLedger:
    """Refine a coarse DetailLedger using an LLM.

    Args:
        source_text: The original source text.
        coarse_ledger: The regex-extracted coarse ledger.
        llm_call_fn: A callable(system_prompt, user_prompt) -> str that returns the LLM response.

    Returns:
        A RefinedDetailLedger with deduplicated and prioritized items.
    """
    if not coarse_ledger.items:
        return RefinedDetailLedger(items=())

    coarse_text = coarse_ledger.to_prompt_text()
    source_excerpt = source_text[:4000] if len(source_text) > 4000 else source_text

    user_prompt = (
        f"【原文】\n{source_excerpt}\n\n"
        f"【粗筛细节清单】\n{coarse_text}\n\n"
        "请输出精炼后的 JSON 数组。"
    )

    try:
        raw_response = llm_call_fn(_REFINE_SYSTEM_PROMPT, user_prompt)
        items = _parse_refine_response(raw_response)
        return RefinedDetailLedger(items=tuple(items))
    except Exception:
        # On any failure, fall back to coarse ledger with all items as high priority
        return RefinedDetailLedger(items=tuple(
            RefinedDetailItem(
                kind=item.kind,
                text=item.text,
                priority="high" if item.preserve_exact else "medium",
            )
            for item in coarse_ledger.items
        ))


def _parse_refine_response(raw: str) -> list[RefinedDetailItem]:
    """Parse the LLM JSON response into RefinedDetailItems."""
    cleaned = raw.strip()
    # Strip markdown code blocks if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    parsed = json.loads(cleaned)
    if not isinstance(parsed, list):
        return []

    items: list[RefinedDetailItem] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "")).strip()
        text = str(entry.get("text", "")).strip()
        priority = str(entry.get("priority", "medium")).strip().lower()
        if not kind or not text:
            continue
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        items.append(RefinedDetailItem(kind=kind, text=text, priority=priority))

    return items[:12]
