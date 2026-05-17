"""Tests for tool registry.

Phase 2: Test tool registration, lookup, and execution.
"""

import pytest
from app.agents.tool_registry import ToolRegistry, create_default_registry
from app.agents.tools import SearchTranscriptTool, ValidateFactTool, CalculateTool


class TestToolRegistry:
    """Test ToolRegistry class."""

    def test_register_tool(self):
        """Test registering a tool."""
        registry = ToolRegistry()
        tool = CalculateTool()

        registry.register(tool)

        assert "calculate" in registry.list_tools()
        assert registry.get("calculate") is tool

    def test_register_multiple_tools(self):
        """Test registering multiple tools."""
        registry = ToolRegistry()
        calc = CalculateTool()
        search = SearchTranscriptTool("test")

        registry.register(calc)
        registry.register(search)

        assert len(registry.list_tools()) == 2
        assert "calculate" in registry.list_tools()
        assert "search_transcript" in registry.list_tools()

    def test_register_duplicate_tool_warns(self, caplog):
        """Test that registering duplicate tool logs warning."""
        registry = ToolRegistry()
        tool1 = CalculateTool()
        tool2 = CalculateTool()

        registry.register(tool1)
        registry.register(tool2)

        assert "already registered" in caplog.text.lower()
        assert registry.get("calculate") is tool2  # Second one wins

    def test_register_invalid_tool(self):
        """Test registering invalid tool raises error."""
        registry = ToolRegistry()

        with pytest.raises(ValueError, match="must implement"):
            registry.register("not a tool")

    def test_get_nonexistent_tool(self):
        """Test getting a tool that doesn't exist."""
        registry = ToolRegistry()

        result = registry.get("nonexistent")

        assert result is None

    def test_list_tools_empty(self):
        """Test listing tools when registry is empty."""
        registry = ToolRegistry()

        tools = registry.list_tools()

        assert tools == []

    def test_execute_tool_success(self):
        """Test executing a tool successfully."""
        registry = ToolRegistry()
        tool = CalculateTool()
        registry.register(tool)

        result = registry.execute("calculate", expression="10 + 5")

        assert result["success"] is True
        assert result["result"]["result"] == 15
        assert result["tool_name"] == "calculate"

    def test_execute_tool_not_found(self):
        """Test executing a nonexistent tool."""
        registry = ToolRegistry()

        result = registry.execute("nonexistent", param="value")

        assert result["success"] is False
        assert "not found" in result["error"]
        assert result["tool_name"] == "nonexistent"

    def test_execute_tool_with_error(self):
        """Test executing a tool that raises an error."""
        registry = ToolRegistry()
        tool = CalculateTool()
        registry.register(tool)

        result = registry.execute("calculate", expression="invalid")

        assert result["success"] is False
        assert result["error"] is not None
        assert result["tool_name"] == "calculate"

    def test_to_function_schemas(self):
        """Test converting tools to OpenAI function schemas."""
        registry = ToolRegistry()
        registry.register(CalculateTool())
        registry.register(SearchTranscriptTool("test"))

        schemas = registry.to_function_schemas()

        assert len(schemas) == 2
        assert all("type" in s for s in schemas)
        assert all(s["type"] == "function" for s in schemas)
        assert all("function" in s for s in schemas)

        # Check function structure
        for schema in schemas:
            func = schema["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert "type" in func["parameters"]
            assert func["parameters"]["type"] == "object"

    def test_to_function_schemas_empty(self):
        """Test converting empty registry to schemas."""
        registry = ToolRegistry()

        schemas = registry.to_function_schemas()

        assert schemas == []


class TestCreateDefaultRegistry:
    """Test create_default_registry function."""

    def test_create_default_registry(self):
        """Test creating a registry with default tools."""
        source_text = "This is a test document."

        registry = create_default_registry(source_text)

        tools = registry.list_tools()
        assert len(tools) == 3
        assert "search_transcript" in tools
        assert "validate_fact" in tools
        assert "calculate" in tools

    def test_default_tools_are_functional(self):
        """Test that default tools can be executed."""
        source_text = "Python is a programming language."

        registry = create_default_registry(source_text)

        # Test search
        result = registry.execute("search_transcript", keyword="Python")
        assert result["success"] is True
        assert result["result"]["found"] is True

        # Test validate
        result = registry.execute("validate_fact", fact="programming language")
        assert result["success"] is True
        assert result["result"]["validated"] is True

        # Test calculate
        result = registry.execute("calculate", expression="10 + 5")
        assert result["success"] is True
        assert result["result"]["result"] == 15

    def test_default_tools_use_source_text(self):
        """Test that search and validate tools use the provided source text."""
        source_text = "The answer is 42."

        registry = create_default_registry(source_text)

        # Search should find "42" in the source
        result = registry.execute("search_transcript", keyword="42")
        assert result["success"] is True
        assert result["result"]["found"] is True

        # Validate should confirm "answer is 42"
        result = registry.execute("validate_fact", fact="answer is 42")
        assert result["success"] is True
        assert result["result"]["validated"] is True

    def test_default_registry_schemas(self):
        """Test that default registry produces valid schemas."""
        registry = create_default_registry("test")

        schemas = registry.to_function_schemas()

        assert len(schemas) == 3

        # Check that all schemas have required fields
        for schema in schemas:
            assert schema["type"] == "function"
            assert "name" in schema["function"]
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]

        # Check specific tool names
        names = {s["function"]["name"] for s in schemas}
        assert names == {"search_transcript", "validate_fact", "calculate"}
