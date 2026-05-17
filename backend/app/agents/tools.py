"""Tool definitions for WriterAgent.

Phase 2: Tool calling infrastructure with 3 basic tools.
"""

from typing import Protocol, Any
from dataclasses import dataclass


class Tool(Protocol):
    """Tool protocol for agent actions.

    Tools are callable objects that the agent can invoke during execution.
    Each tool has a name, description, and parameter schema for LLM discovery.
    """

    @property
    def name(self) -> str:
        """Unique tool identifier."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description for LLM."""
        ...

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema for tool parameters (OpenAI function calling format)."""
        ...

    def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the tool with given parameters.

        Returns:
            dict with 'success' (bool), 'result' (Any), and optional 'error' (str)
        """
        ...


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool execution."""
    success: bool
    result: Any
    error: str | None = None
    tool_name: str = ""


class SearchTranscriptTool:
    """Search for keywords in the source transcript."""

    def __init__(self, source_text: str):
        self._source_text = source_text

    @property
    def name(self) -> str:
        return "search_transcript"

    @property
    def description(self) -> str:
        return "在原文中搜索关键词或短语，返回包含该关键词的上下文片段。用于验证细节是否存在于原文中。"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "要搜索的关键词或短语"
                },
                "context_chars": {
                    "type": "integer",
                    "description": "返回的上下文字符数（前后各取多少字符）",
                    "default": 100
                }
            },
            "required": ["keyword"]
        }

    def execute(self, keyword: str, context_chars: int = 100) -> dict[str, Any]:
        """Search for keyword in source text."""
        keyword = str(keyword or "").strip()
        if not keyword:
            return {
                "success": False,
                "result": None,
                "error": "keyword must not be empty"
            }

        # Case-insensitive search
        lower_text = self._source_text.lower()
        lower_keyword = keyword.lower()

        matches = []
        start = 0
        while True:
            idx = lower_text.find(lower_keyword, start)
            if idx == -1:
                break

            # Extract context
            context_start = max(0, idx - context_chars)
            context_end = min(len(self._source_text), idx + len(keyword) + context_chars)
            context = self._source_text[context_start:context_end]

            matches.append({
                "position": idx,
                "context": context,
                "matched_text": self._source_text[idx:idx + len(keyword)]
            })
            start = idx + 1

        return {
            "success": True,
            "result": {
                "keyword": keyword,
                "found": len(matches) > 0,
                "match_count": len(matches),
                "matches": matches[:5]  # Limit to 5 matches
            },
            "error": None
        }


class ValidateFactTool:
    """Validate if a fact/statement exists in the source text."""

    def __init__(self, source_text: str):
        self._source_text = source_text

    @property
    def name(self) -> str:
        return "validate_fact"

    @property
    def description(self) -> str:
        return "验证某个事实陈述是否在原文中出现。返回是否找到以及相关证据。"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "要验证的事实陈述"
                }
            },
            "required": ["fact"]
        }

    def execute(self, fact: str) -> dict[str, Any]:
        """Validate if fact appears in source text."""
        fact = str(fact or "").strip()
        if not fact:
            return {
                "success": False,
                "result": None,
                "error": "fact must not be empty"
            }

        # Simple substring matching (can be enhanced with fuzzy matching)
        lower_text = self._source_text.lower()
        lower_fact = fact.lower()

        # Try exact match first
        if lower_fact in lower_text:
            idx = lower_text.find(lower_fact)
            context_start = max(0, idx - 50)
            context_end = min(len(self._source_text), idx + len(fact) + 50)
            evidence = self._source_text[context_start:context_end]

            return {
                "success": True,
                "result": {
                    "validated": True,
                    "confidence": "high",
                    "evidence": evidence
                },
                "error": None
            }

        # Try keyword-based matching
        keywords = [w for w in fact.split() if len(w) > 3]
        keyword_matches = sum(1 for kw in keywords if kw.lower() in lower_text)

        if keywords and keyword_matches >= len(keywords) * 0.6:  # 60% keywords found
            return {
                "success": True,
                "result": {
                    "validated": True,
                    "confidence": "medium",
                    "evidence": f"Found {keyword_matches}/{len(keywords)} keywords"
                },
                "error": None
            }

        return {
            "success": True,
            "result": {
                "validated": False,
                "confidence": "low",
                "evidence": None
            },
            "error": None
        }


class CalculateTool:
    """Perform simple calculations (percentages, durations, etc.)."""

    @property
    def name(self) -> str:
        return "calculate"

    @property
    def description(self) -> str:
        return "执行简单计算，如百分比、时长转换、数值比较等。支持基本算术运算。"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的表达式，如 '100 * 0.15' 或 '3600 / 60'"
                },
                "operation": {
                    "type": "string",
                    "enum": ["arithmetic", "percentage", "duration_to_minutes"],
                    "description": "计算类型",
                    "default": "arithmetic"
                }
            },
            "required": ["expression"]
        }

    def execute(self, expression: str, operation: str = "arithmetic") -> dict[str, Any]:
        """Execute calculation."""
        expression = str(expression or "").strip()
        if not expression:
            return {
                "success": False,
                "result": None,
                "error": "expression must not be empty"
            }

        try:
            if operation == "percentage":
                # Parse "X% of Y" or "X * Y%"
                import re
                match = re.search(r'(\d+\.?\d*)\s*%\s*of\s*(\d+\.?\d*)', expression)
                if match:
                    percent = float(match.group(1))
                    value = float(match.group(2))
                    result = (percent / 100) * value
                else:
                    # Fallback to eval
                    result = eval(expression.replace('%', '/100*'), {"__builtins__": {}})

            elif operation == "duration_to_minutes":
                # Parse "HH:MM:SS" or seconds
                import re
                match = re.match(r'(\d+):(\d+):(\d+)', expression)
                if match:
                    hours = int(match.group(1))
                    minutes = int(match.group(2))
                    seconds = int(match.group(3))
                    result = hours * 60 + minutes + seconds / 60
                else:
                    # Assume seconds
                    result = float(expression) / 60

            else:  # arithmetic
                # Safe eval with limited scope
                allowed_names = {"__builtins__": {}}
                result = eval(expression, allowed_names)

            return {
                "success": True,
                "result": {
                    "expression": expression,
                    "result": result,
                    "formatted": f"{result:.2f}" if isinstance(result, float) else str(result)
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "result": None,
                "error": f"Calculation failed: {str(e)}"
            }
