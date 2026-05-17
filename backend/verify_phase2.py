"""Phase 2 功能验证脚本

验证 tool calling 和 error recovery 功能。
"""

import sys
sys.path.insert(0, '/Users/jack/Documents/coding/Translation/backend')

from app.agents.tools import SearchTranscriptTool, ValidateFactTool, CalculateTool
from app.agents.tool_registry import create_default_registry
from app.agents.error_recovery import classify_error, should_retry
from app.agents.tool_support import provider_supports_tool_calling


def test_tools():
    """测试 3 个基础工具"""
    print("=" * 60)
    print("测试 1: 基础工具功能")
    print("=" * 60)

    source_text = """
    Python 是一种广泛使用的编程语言。它由 Guido van Rossum 在 1991 年创建。
    Python 的设计哲学强调代码的可读性。根据统计，Python 在 2023 年的市场份额达到了 30%。
    """

    # 测试 SearchTranscriptTool
    print("\n1.1 测试 SearchTranscriptTool")
    search_tool = SearchTranscriptTool(source_text)
    result = search_tool.execute(keyword="Python")
    print(f"  搜索 'Python': 找到 {result['result']['match_count']} 处")
    print(f"  成功: {result['success']}")

    # 测试 ValidateFactTool
    print("\n1.2 测试 ValidateFactTool")
    validate_tool = ValidateFactTool(source_text)
    result = validate_tool.execute(fact="Guido van Rossum 1991")
    print(f"  验证 'Guido van Rossum 1991': {result['result']['validated']}")
    print(f"  置信度: {result['result']['confidence']}")

    # 测试 CalculateTool
    print("\n1.3 测试 CalculateTool")
    calc_tool = CalculateTool()
    result = calc_tool.execute(expression="30 * 100 / 100")
    print(f"  计算 '30 * 100 / 100': {result['result']['result']}")
    print(f"  成功: {result['success']}")


def test_tool_registry():
    """测试工具注册表"""
    print("\n" + "=" * 60)
    print("测试 2: 工具注册表")
    print("=" * 60)

    source_text = "测试文本，包含关键词 Python 和数字 42。"

    registry = create_default_registry(source_text)

    print(f"\n2.1 已注册工具: {registry.list_tools()}")

    # 测试执行工具
    print("\n2.2 通过 registry 执行工具")
    result = registry.execute("search_transcript", keyword="Python")
    print(f"  search_transcript('Python'): 找到 = {result['result']['found']}")

    result = registry.execute("calculate", expression="21 * 2")
    print(f"  calculate('21 * 2'): 结果 = {result['result']['result']}")

    # 测试 function schemas
    print("\n2.3 生成 OpenAI function calling schemas")
    schemas = registry.to_function_schemas()
    print(f"  生成了 {len(schemas)} 个 schema")
    for schema in schemas:
        print(f"    - {schema['function']['name']}: {schema['function']['description'][:30]}...")


def test_error_recovery():
    """测试错误恢复"""
    print("\n" + "=" * 60)
    print("测试 3: 错误分类和重试策略")
    print("=" * 60)

    # 测试不同类型的错误
    test_cases = [
        (Exception("Rate limit exceeded"), "Rate Limit"),
        (Exception("Connection timeout"), "Network Timeout"),
        (ValueError("Invalid input"), "Input Error"),
        (Exception("HTTP 503: Service unavailable"), "Provider 5xx"),
    ]

    for error, name in test_cases:
        classification = classify_error(error)
        should, delay = should_retry(error, attempt=0)

        print(f"\n3.{test_cases.index((error, name)) + 1} {name}")
        print(f"  分类: {classification.category.value}")
        print(f"  策略: {classification.retry_strategy.value}")
        print(f"  最大重试: {classification.max_retries}")
        print(f"  应该重试: {should}, 延迟: {delay:.1f}s")


def test_tool_support():
    """测试 provider 工具调用支持检测"""
    print("\n" + "=" * 60)
    print("测试 4: Provider 工具调用支持检测")
    print("=" * 60)

    test_cases = [
        ("openai", "gpt-4"),
        ("openai", "gpt-3.5-turbo"),
        ("deepseek", "deepseek-chat"),
        ("ollama", "llama3.1"),
        ("ollama", "llama2"),
        ("lmstudio", "any-model"),
    ]

    for provider, model in test_cases:
        supported = provider_supports_tool_calling(provider, model)
        print(f"\n4.{test_cases.index((provider, model)) + 1} {provider} / {model}")
        print(f"  支持 tool calling: {'✓' if supported else '✗'}")


def test_error_retry_sequence():
    """测试错误重试序列"""
    print("\n" + "=" * 60)
    print("测试 5: 错误重试序列（指数退避）")
    print("=" * 60)

    error = Exception("Rate limit exceeded")

    print("\n模拟 rate limit 错误的重试序列:")
    for attempt in range(4):
        should, delay = should_retry(error, attempt=attempt)
        if should:
            print(f"  尝试 {attempt + 1}: 重试，延迟 {delay:.1f}s")
        else:
            print(f"  尝试 {attempt + 1}: 不再重试（达到最大次数）")


def main():
    """运行所有验证测试"""
    print("\n" + "=" * 60)
    print("Phase 2 功能验证")
    print("=" * 60)

    try:
        test_tools()
        test_tool_registry()
        test_error_recovery()
        test_tool_support()
        test_error_retry_sequence()

        print("\n" + "=" * 60)
        print("✓ 所有验证测试通过")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
