"""Agent action definitions for WriterAgent loop."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class AgentAction:
    """Agent 决策的动作。

    表示 WriterAgent 在当前状态下决定执行的操作，
    包括动作类型、执行参数和预期耗时。
    """

    type: Literal["generate_draft", "check_quality", "patch_draft", "complete"]
    """动作类型：
    - generate_draft: 生成文章初稿
    - check_quality: 执行质量检查
    - patch_draft: 修补已发现的问题
    - complete: 完成任务
    """

    params: dict
    """动作执行参数，具体内容取决于 type：
    - generate_draft: {"rewrite_focus": str, "rewrite_style": str, ...}
    - check_quality: {"draft_text": str, "source_text": str, ...}
    - patch_draft: {"issues": list[str], "previous_draft": str, ...}
    - complete: {}
    """

    expected_duration_seconds: int
    """预期执行时长（秒），用于超时控制和进度估算"""
