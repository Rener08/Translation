"""Tests for tool calling support detection.

Phase 2: Test provider tool calling support detection.
"""

import pytest
from app.agents.tool_support import (
    provider_supports_tool_calling,
    get_tool_calling_config,
)


class TestProviderSupportsToolCalling:
    """Test provider_supports_tool_calling function."""

    def test_openai_gpt4_supports(self):
        """Test that GPT-4 supports tool calling."""
        assert provider_supports_tool_calling("openai", "gpt-4") is True
        assert provider_supports_tool_calling("openai", "gpt-4-turbo") is True
        assert provider_supports_tool_calling("openai", "gpt-4o") is True

    def test_openai_gpt35_supports(self):
        """Test that GPT-3.5-turbo supports tool calling."""
        assert provider_supports_tool_calling("openai", "gpt-3.5-turbo") is True
        assert provider_supports_tool_calling("openai", "gpt-3.5-turbo-16k") is True

    def test_openai_other_models_no_support(self):
        """Test that other OpenAI models don't support tool calling."""
        assert provider_supports_tool_calling("openai", "text-davinci-003") is False
        assert provider_supports_tool_calling("openai", "gpt-3") is False

    def test_deepseek_chat_supports(self):
        """Test that deepseek-chat supports tool calling."""
        assert provider_supports_tool_calling("deepseek", "deepseek-chat") is True

    def test_deepseek_other_models_no_support(self):
        """Test that other DeepSeek models don't support tool calling."""
        assert provider_supports_tool_calling("deepseek", "deepseek-coder") is False

    def test_lmstudio_no_support(self):
        """Test that LM Studio doesn't support tool calling by default."""
        assert provider_supports_tool_calling("lmstudio", "any-model") is False

    def test_ollama_llama31_supports(self):
        """Test that Llama 3.1+ supports tool calling."""
        assert provider_supports_tool_calling("ollama", "llama3.1") is True
        assert provider_supports_tool_calling("ollama", "llama3.2") is True
        assert provider_supports_tool_calling("ollama", "llama3.3") is True

    def test_ollama_mistral_supports(self):
        """Test that Mistral models support tool calling."""
        assert provider_supports_tool_calling("ollama", "mistral") is True
        assert provider_supports_tool_calling("ollama", "mixtral") is True

    def test_ollama_qwen_supports(self):
        """Test that Qwen 2.5+ supports tool calling."""
        assert provider_supports_tool_calling("ollama", "qwen2.5") is True
        assert provider_supports_tool_calling("ollama", "qwen3") is True

    def test_ollama_other_models_no_support(self):
        """Test that other Ollama models don't support tool calling."""
        assert provider_supports_tool_calling("ollama", "llama2") is False
        assert provider_supports_tool_calling("ollama", "llama3.0") is False

    def test_case_insensitive_model_names(self):
        """Test that model name matching is case-insensitive."""
        assert provider_supports_tool_calling("openai", "GPT-4") is True
        assert provider_supports_tool_calling("deepseek", "DeepSeek-Chat") is True
        assert provider_supports_tool_calling("ollama", "LLAMA3.1") is True


class TestGetToolCallingConfig:
    """Test get_tool_calling_config function."""

    def test_openai_config(self):
        """Test OpenAI tool calling config."""
        config = get_tool_calling_config("openai")

        assert config["format"] == "openai"
        assert config["field_name"] == "tools"
        assert config["choice_field"] == "tool_calls"

    def test_deepseek_config(self):
        """Test DeepSeek tool calling config."""
        config = get_tool_calling_config("deepseek")

        assert config["format"] == "openai"
        assert config["field_name"] == "tools"
        assert config["choice_field"] == "tool_calls"

    def test_lmstudio_config(self):
        """Test LM Studio tool calling config."""
        config = get_tool_calling_config("lmstudio")

        assert config["format"] == "openai"
        assert config["field_name"] == "tools"
        assert config["choice_field"] == "tool_calls"

    def test_ollama_config(self):
        """Test Ollama tool calling config."""
        config = get_tool_calling_config("ollama")

        assert config["format"] == "openai"
        assert config["field_name"] == "tools"
        assert config["choice_field"] == "tool_calls"

    def test_all_providers_use_openai_format(self):
        """Test that all providers use OpenAI-compatible format."""
        providers = ["openai", "deepseek", "lmstudio", "ollama"]

        for provider in providers:
            config = get_tool_calling_config(provider)
            assert config["format"] == "openai"
            assert "field_name" in config
            assert "choice_field" in config
