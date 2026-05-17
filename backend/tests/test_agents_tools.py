"""Tests for agent tools.

Phase 2: Test 3 basic tools (SearchTranscript, ValidateFact, Calculate).
"""

import pytest
from app.agents.tools import SearchTranscriptTool, ValidateFactTool, CalculateTool


class TestSearchTranscriptTool:
    """Test SearchTranscriptTool."""

    def test_search_found(self):
        """Test searching for a keyword that exists."""
        source = "This is a test document. It contains important information about testing."
        tool = SearchTranscriptTool(source)

        result = tool.execute(keyword="test")

        assert result["success"] is True
        assert result["result"]["found"] is True
        assert result["result"]["match_count"] == 2
        assert len(result["result"]["matches"]) == 2
        assert result["error"] is None

    def test_search_not_found(self):
        """Test searching for a keyword that doesn't exist."""
        source = "This is a sample document."
        tool = SearchTranscriptTool(source)

        result = tool.execute(keyword="nonexistent")

        assert result["success"] is True
        assert result["result"]["found"] is False
        assert result["result"]["match_count"] == 0
        assert len(result["result"]["matches"]) == 0

    def test_search_case_insensitive(self):
        """Test that search is case-insensitive."""
        source = "Python is a Programming language."
        tool = SearchTranscriptTool(source)

        result = tool.execute(keyword="python")

        assert result["success"] is True
        assert result["result"]["found"] is True
        assert result["result"]["match_count"] == 1

    def test_search_with_context(self):
        """Test context extraction."""
        source = "The quick brown fox jumps over the lazy dog."
        tool = SearchTranscriptTool(source)

        result = tool.execute(keyword="fox", context_chars=10)

        assert result["success"] is True
        assert result["result"]["found"] is True
        match = result["result"]["matches"][0]
        assert "fox" in match["context"]
        assert len(match["context"]) <= len(source)

    def test_search_empty_keyword(self):
        """Test searching with empty keyword."""
        source = "Some text"
        tool = SearchTranscriptTool(source)

        result = tool.execute(keyword="")

        assert result["success"] is False
        assert "empty" in result["error"]

    def test_search_limit_matches(self):
        """Test that matches are limited to 5."""
        source = "test " * 10  # 10 occurrences
        tool = SearchTranscriptTool(source)

        result = tool.execute(keyword="test")

        assert result["success"] is True
        assert result["result"]["match_count"] == 10
        assert len(result["result"]["matches"]) == 5  # Limited to 5


class TestValidateFactTool:
    """Test ValidateFactTool."""

    def test_validate_exact_match(self):
        """Test validating a fact with exact match."""
        source = "The company was founded in 2020 by John Smith."
        tool = ValidateFactTool(source)

        result = tool.execute(fact="founded in 2020")

        assert result["success"] is True
        assert result["result"]["validated"] is True
        assert result["result"]["confidence"] == "high"
        assert result["result"]["evidence"] is not None

    def test_validate_keyword_match(self):
        """Test validating a fact with keyword matching."""
        source = "The product launch happened in March. It was very successful."
        tool = ValidateFactTool(source)

        result = tool.execute(fact="product launch successful March")

        assert result["success"] is True
        assert result["result"]["validated"] is True
        assert result["result"]["confidence"] == "medium"

    def test_validate_not_found(self):
        """Test validating a fact that doesn't exist."""
        source = "The event was held in Paris."
        tool = ValidateFactTool(source)

        result = tool.execute(fact="event in London")

        assert result["success"] is True
        assert result["result"]["validated"] is False
        assert result["result"]["confidence"] == "low"

    def test_validate_empty_fact(self):
        """Test validating with empty fact."""
        source = "Some text"
        tool = ValidateFactTool(source)

        result = tool.execute(fact="")

        assert result["success"] is False
        assert "empty" in result["error"]

    def test_validate_case_insensitive(self):
        """Test that validation is case-insensitive."""
        source = "Python is a programming language."
        tool = ValidateFactTool(source)

        result = tool.execute(fact="PYTHON programming")

        assert result["success"] is True
        assert result["result"]["validated"] is True


class TestCalculateTool:
    """Test CalculateTool."""

    def test_calculate_arithmetic(self):
        """Test basic arithmetic calculation."""
        tool = CalculateTool()

        result = tool.execute(expression="100 + 50")

        assert result["success"] is True
        assert result["result"]["result"] == 150
        assert result["error"] is None

    def test_calculate_multiplication(self):
        """Test multiplication."""
        tool = CalculateTool()

        result = tool.execute(expression="12 * 5")

        assert result["success"] is True
        assert result["result"]["result"] == 60

    def test_calculate_division(self):
        """Test division."""
        tool = CalculateTool()

        result = tool.execute(expression="100 / 4")

        assert result["success"] is True
        assert result["result"]["result"] == 25.0

    def test_calculate_percentage(self):
        """Test percentage calculation."""
        tool = CalculateTool()

        result = tool.execute(expression="15% of 200", operation="percentage")

        assert result["success"] is True
        assert result["result"]["result"] == 30.0

    def test_calculate_duration_to_minutes(self):
        """Test duration conversion."""
        tool = CalculateTool()

        result = tool.execute(expression="1:30:00", operation="duration_to_minutes")

        assert result["success"] is True
        assert result["result"]["result"] == 90.0

    def test_calculate_duration_seconds(self):
        """Test duration from seconds."""
        tool = CalculateTool()

        result = tool.execute(expression="3600", operation="duration_to_minutes")

        assert result["success"] is True
        assert result["result"]["result"] == 60.0

    def test_calculate_empty_expression(self):
        """Test calculation with empty expression."""
        tool = CalculateTool()

        result = tool.execute(expression="")

        assert result["success"] is False
        assert "empty" in result["error"]

    def test_calculate_invalid_expression(self):
        """Test calculation with invalid expression."""
        tool = CalculateTool()

        result = tool.execute(expression="invalid")

        assert result["success"] is False
        assert "failed" in result["error"].lower()

    def test_calculate_safe_eval(self):
        """Test that dangerous expressions are blocked."""
        tool = CalculateTool()

        # Should fail because __import__ is not available
        result = tool.execute(expression="__import__('os').system('ls')")

        assert result["success"] is False


class TestToolProtocol:
    """Test that tools implement the Tool protocol."""

    def test_search_tool_has_required_attributes(self):
        """Test SearchTranscriptTool has required attributes."""
        tool = SearchTranscriptTool("test")

        assert hasattr(tool, 'name')
        assert hasattr(tool, 'description')
        assert hasattr(tool, 'parameters_schema')
        assert hasattr(tool, 'execute')
        assert callable(tool.execute)

    def test_validate_tool_has_required_attributes(self):
        """Test ValidateFactTool has required attributes."""
        tool = ValidateFactTool("test")

        assert hasattr(tool, 'name')
        assert hasattr(tool, 'description')
        assert hasattr(tool, 'parameters_schema')
        assert hasattr(tool, 'execute')

    def test_calculate_tool_has_required_attributes(self):
        """Test CalculateTool has required attributes."""
        tool = CalculateTool()

        assert hasattr(tool, 'name')
        assert hasattr(tool, 'description')
        assert hasattr(tool, 'parameters_schema')
        assert hasattr(tool, 'execute')

    def test_tool_names_are_unique(self):
        """Test that tool names are unique."""
        search = SearchTranscriptTool("test")
        validate = ValidateFactTool("test")
        calculate = CalculateTool()

        names = {search.name, validate.name, calculate.name}
        assert len(names) == 3

    def test_parameters_schema_format(self):
        """Test that parameters_schema follows OpenAI format."""
        tool = SearchTranscriptTool("test")
        schema = tool.parameters_schema

        assert "type" in schema
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema
        assert isinstance(schema["properties"], dict)
        assert isinstance(schema["required"], list)
