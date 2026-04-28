from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


PromptMode = Literal["full_prompt", "style_hint"]


@dataclass(frozen=True)
class PromptValidationResult:
    mode: PromptMode
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def has_transcript_placeholder(self) -> bool:
        return self.mode == "full_prompt"


_FULL_PROMPT_HINTS = (
    "视频内容：",
    "原文：",
    "原始内容：",
    "素材：",
    "以下内容",
    "请根据以下",
    "请根据下列",
    "请根据下面",
    "根据以下",
    "正文：",
    "输出只保留正文",
)


def validate_rewrite_prompt(prompt_text: str) -> PromptValidationResult:
    normalized = str(prompt_text or "").strip()
    if not normalized:
        return PromptValidationResult(
            mode="style_hint",
            errors=("写作风格为空。请重新选择写作风格，或编辑 prompt 文件后重试。",),
        )

    invalid_placeholders = [
        match
        for match in re.findall(r"\{\{[^{}]+\}\}", normalized)
        if match != "{{transcript}}"
    ]
    if invalid_placeholders:
        examples = "、".join(invalid_placeholders[:3])
        return PromptValidationResult(
            mode="style_hint",
            errors=(
                f"改写模板包含不支持的占位符：{examples}。当前仅支持 {{{{transcript}}}}。",
            ),
        )

    if (
        re.search(r"transcript", normalized, flags=re.IGNORECASE)
        and "{{transcript}}" not in normalized
    ):
        return PromptValidationResult(
            mode="style_hint",
            errors=("检测到 transcript 占位符写法不正确。请使用 {{transcript}}。",),
        )

    unresolved = normalized.replace("{{transcript}}", "")
    if "{{" in unresolved or "}}" in unresolved:
        return PromptValidationResult(
            mode="style_hint",
            errors=("改写模板包含无法识别的占位符。当前仅支持 {{transcript}}。",),
        )

    has_transcript_placeholder = "{{transcript}}" in normalized
    if not has_transcript_placeholder and _looks_like_full_prompt(normalized):
        return PromptValidationResult(
            mode="style_hint",
            errors=(
                "该写作风格看起来是完整 Prompt，但缺少 {{transcript}}。"
                "请补上占位符，或删掉完整 prompt 结构后作为风格提示使用。",
            ),
        )

    return PromptValidationResult(
        mode="full_prompt" if has_transcript_placeholder else "style_hint",
    )


def _looks_like_full_prompt(prompt_text: str) -> bool:
    normalized = prompt_text.strip()
    if any(marker in normalized for marker in _FULL_PROMPT_HINTS):
        return True

    prompt_like_sections = sum(
        1
        for marker in ("要求：", "视频内容：", "原文：", "素材：", "输出：")
        if marker in normalized
    )
    return prompt_like_sections >= 2
