from __future__ import annotations

import re


HALLUCINATION_MARKERS = (
    "作为ai",
    "作为 an ai",
    "根据我的训练数据",
    "我无法访问",
    "我不能提供",
    "无法提供",
    "仅供参考",
    "不构成",
    "免责声明",
    "我不知道",
    "抱歉，",
)


def guess_output_language(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return "混合"

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", normalized))
    latin_chars = len(re.findall(r"[A-Za-z]", normalized))

    if latin_chars >= 40 and latin_chars > chinese_chars * 2:
        return "英文主导"
    if chinese_chars >= 8 and chinese_chars >= latin_chars:
        return "简中"
    if chinese_chars == 0 and latin_chars > 0:
        return "英文主导"
    return "混合"


def analyze_rewrite_quality(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return ["改写结果为空。"]

    issues: list[str] = []
    issues.extend(_detect_empty_sections(normalized))
    issues.extend(_detect_repeated_paragraphs(normalized))
    issues.extend(_detect_hallucination_markers(normalized))
    issues.extend(_detect_malformed_headings(normalized))
    if guess_output_language(normalized) == "英文主导":
        issues.append("检测到输出疑似以英文为主，建议改为简体中文稿。")

    # 去重但保留顺序
    deduped: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        if issue in seen:
            continue
        seen.add(issue)
        deduped.append(issue)
    return deduped


def _detect_empty_sections(text: str) -> list[str]:
    lines = text.splitlines()
    issues: list[str] = []
    heading_pattern = re.compile(r"^(#{1,6})\s+(.*)$")
    heading_indices: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = heading_pattern.match(line.strip())
        if match:
            heading_indices.append((index, match.group(2).strip()))

    for idx, (line_index, heading) in enumerate(heading_indices):
        next_index = heading_indices[idx + 1][0] if idx + 1 < len(heading_indices) else len(lines)
        body_lines = [line.strip() for line in lines[line_index + 1 : next_index] if line.strip()]
        if not body_lines:
            issues.append(f"标题“{heading}”下方没有正文。")
    return issues


def _detect_repeated_paragraphs(text: str) -> list[str]:
    paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", text) if segment.strip()]
    normalized_paragraphs = [" ".join(paragraph.split()) for paragraph in paragraphs]
    counts: dict[str, int] = {}
    for paragraph in normalized_paragraphs:
        counts[paragraph] = counts.get(paragraph, 0) + 1
    repeated = [paragraph for paragraph, count in counts.items() if count > 1]
    if repeated:
        return ["存在重复段落，建议合并或删减重复表述。"]
    return []


def _detect_hallucination_markers(text: str) -> list[str]:
    lowered = text.lower()
    if any(marker in lowered for marker in HALLUCINATION_MARKERS):
        return ["检测到疑似模型自述或免责声明，建议检查是否夹带了无关说明。"]
    return []


def _detect_malformed_headings(text: str) -> list[str]:
    issues: list[str] = []
    for line in text.splitlines():
        stripped = line.rstrip()
        if not stripped.startswith("#"):
            continue
        if re.match(r"^#{1,6}\s+\S+", stripped):
            continue
        issues.append(f"标题格式可能有问题：{stripped[:40]}")
        break
    return issues
