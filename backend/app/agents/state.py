"""Agent state definitions for WriterAgent loop."""

from dataclasses import dataclass
from typing import Literal

from app.services.pipelines import MaterialPackage


@dataclass
class AgentState:
    """Agent 观察到的状态。

    表示 WriterAgent 在执行过程中的当前状态，包括任务进度、
    已生成的内容、质量问题和错误历史。
    """

    job_id: str
    """任务唯一标识符"""

    current_stage: Literal["draft", "quality_check", "patch", "done"]
    """当前执行阶段：
    - draft: 生成初稿
    - quality_check: 质量检查
    - patch: 修补问题
    - done: 完成
    """

    material: MaterialPackage
    """输入素材包，包含源文本、参考文本和语言配置"""

    draft_text: str | None
    """当前生成的文章草稿，初始为 None"""

    quality_issues: list[str]
    """质量检查发现的问题列表"""

    retry_count: int
    """当前阶段的重试次数"""

    error_history: list[dict]
    """错误历史记录，每条包含 stage、error、timestamp 等信息"""
