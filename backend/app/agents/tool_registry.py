"""Tool registry for agent tool management.

Phase 2: Tool registration, lookup, and execution.
"""

from typing import Any
import logging

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for managing agent tools.

    Provides tool registration, lookup, and execution.
    """

    def __init__(self):
        self._tools: dict[str, Any] = {}  # name -> tool instance

    def register(self, tool: Any) -> None:
        """Register a tool.

        Args:
            tool: Tool instance implementing the Tool protocol
        """
        if not hasattr(tool, 'name') or not hasattr(tool, 'execute'):
            raise ValueError(f"Tool must implement name and execute: {tool}")

        name = tool.name
        if name in self._tools:
            logger.warning(f"Tool '{name}' already registered, overwriting")

        self._tools[name] = tool
        logger.info(f"Registered tool: {name}")

    def get(self, name: str) -> Any | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def execute(self, tool_name: str, **kwargs) -> dict[str, Any]:
        """Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            **kwargs: Tool parameters

        Returns:
            Tool execution result
        """
        tool = self.get(tool_name)
        if tool is None:
            return {
                "success": False,
                "result": None,
                "error": f"Tool '{tool_name}' not found",
                "tool_name": tool_name
            }

        try:
            result = tool.execute(**kwargs)
            result["tool_name"] = tool_name
            return result
        except Exception as e:
            logger.error(f"Tool '{tool_name}' execution failed", exc_info=True)
            return {
                "success": False,
                "result": None,
                "error": f"Tool execution failed: {str(e)}",
                "tool_name": tool_name
            }

    def to_function_schemas(self) -> list[dict[str, Any]]:
        """Convert tools to OpenAI function calling schemas.

        Returns:
            List of function schemas for LLM tool calling
        """
        schemas = []
        for tool in self._tools.values():
            schema = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema
                }
            }
            schemas.append(schema)
        return schemas


def create_default_registry(source_text: str) -> ToolRegistry:
    """Create a registry with default tools.

    Args:
        source_text: Source text for context-dependent tools

    Returns:
        ToolRegistry with default tools registered
    """
    from app.agents.tools import SearchTranscriptTool, ValidateFactTool, CalculateTool

    registry = ToolRegistry()
    registry.register(SearchTranscriptTool(source_text))
    registry.register(ValidateFactTool(source_text))
    registry.register(CalculateTool())

    return registry
