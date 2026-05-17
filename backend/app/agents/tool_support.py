"""Provider tool calling support detection.

Phase 2: Detect which providers support tool calling.
"""

from typing import Literal


def provider_supports_tool_calling(
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"],
    model: str
) -> bool:
    """Check if a provider/model supports tool calling.

    Args:
        provider: LLM provider name
        model: Model identifier

    Returns:
        True if tool calling is supported
    """
    # OpenAI: GPT-4 and GPT-3.5-turbo support function calling
    if provider == "openai":
        model_lower = model.lower()
        return any(x in model_lower for x in ["gpt-4", "gpt-3.5-turbo"])

    # DeepSeek: deepseek-chat supports function calling
    if provider == "deepseek":
        return "deepseek-chat" in model.lower()

    # LM Studio: depends on model, assume no support by default
    if provider == "lmstudio":
        # Some models support it, but we can't reliably detect
        # User can enable via config if their model supports it
        return False

    # Ollama: some models support it (llama3.1+, mistral, etc.)
    if provider == "ollama":
        model_lower = model.lower()
        # Known models with tool support
        return any(x in model_lower for x in [
            "llama3.1", "llama3.2", "llama3.3",
            "mistral", "mixtral",
            "qwen2.5", "qwen3"
        ])

    return False


def get_tool_calling_config(
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
) -> dict[str, str]:
    """Get tool calling configuration for a provider.

    Returns:
        Dict with 'format' (openai/ollama) and 'field_name' (tools/functions)
    """
    if provider in {"openai", "deepseek", "lmstudio"}:
        return {
            "format": "openai",
            "field_name": "tools",
            "choice_field": "tool_calls"
        }

    # Ollama uses same format as OpenAI
    return {
        "format": "openai",
        "field_name": "tools",
        "choice_field": "tool_calls"
    }
