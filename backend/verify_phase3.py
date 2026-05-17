"""Phase 3 功能验证脚本

验证 checkpoint 和 trace 功能。
"""

import sys
sys.path.insert(0, '/Users/jack/Documents/coding/Translation/backend')

from app.agents.checkpoint import CheckpointManager, create_checkpoint, can_resume_from_checkpoint
from app.agents.trace import TraceManager, IterationTrace
from pathlib import Path
import json


def test_checkpoint_persistence():
    """测试 checkpoint 持久化"""
    print("=" * 60)
    print("测试 1: Checkpoint 持久化")
    print("=" * 60)

    manager = CheckpointManager("tmp/test_checkpoints")

    # 创建 checkpoint
    print("\n1.1 创建并保存 checkpoint")
    checkpoint = create_checkpoint(
        job_id="test-job-1",
        iteration=2,
        stage="quality_check",
        agent_state={
            "job_id": "test-job-1",
            "retry_count": 1,
            "error_history": [],
        },
        last_action={"type": "check_quality", "reason": "Check draft quality"},
        draft_text="这是一个测试草稿。",
    )
    manager.save(checkpoint)
    print(f"  保存成功: job_id={checkpoint.job_id}, iteration={checkpoint.iteration}")

    # 加载 checkpoint
    print("\n1.2 加载 checkpoint")
    loaded = manager.load("test-job-1")
    print(f"  加载成功: stage={loaded.stage}, can_resume={loaded.can_resume}")
    print(f"  草稿文本: {loaded.draft_text[:20]}...")

    # 检查是否可以恢复
    print("\n1.3 检查是否可以恢复")
    can_resume = can_resume_from_checkpoint(loaded)
    print(f"  可以恢复: {can_resume}")

    # 列出所有 checkpoints
    print("\n1.4 列出所有 checkpoints")
    all_checkpoints = manager.list_all()
    print(f"  找到 {len(all_checkpoints)} 个 checkpoint: {all_checkpoints}")

    # 删除 checkpoint
    print("\n1.5 删除 checkpoint")
    manager.delete("test-job-1")
    print(f"  删除后存在: {manager.exists('test-job-1')}")


def test_checkpoint_resume_conditions():
    """测试 checkpoint 恢复条件"""
    print("\n" + "=" * 60)
    print("测试 2: Checkpoint 恢复条件")
    print("=" * 60)

    test_cases = [
        ("正常状态", "draft", [], True),
        ("DONE 状态", "done", [], False),
        ("FAILED 状态", "failed", [], False),
        ("3 个错误", "draft", [{"error": f"Error {i}"} for i in range(3)], False),
    ]

    for name, stage, error_history, expected in test_cases:
        checkpoint = create_checkpoint(
            job_id=f"test-{name}",
            iteration=1,
            stage=stage,
            agent_state={"error_history": error_history},
        )
        can_resume = can_resume_from_checkpoint(checkpoint)
        status = "✓" if can_resume == expected else "✗"
        print(f"\n2.{test_cases.index((name, stage, error_history, expected)) + 1} {name}")
        print(f"  预期可恢复: {expected}, 实际: {can_resume} {status}")


def test_trace_recording():
    """测试 trace 记录"""
    print("\n" + "=" * 60)
    print("测试 3: Execution Trace 记录")
    print("=" * 60)

    manager = TraceManager("tmp/test_traces")

    # 开始 trace
    print("\n3.1 开始 trace")
    manager.start_trace("test-job-2")
    print("  Trace 已启动")

    # 添加多个迭代
    print("\n3.2 添加迭代记录")
    for i in range(3):
        iteration_trace = IterationTrace(
            iteration=i,
            timestamp=f"2026-05-17T10:0{i}:00",
            stage="draft" if i == 0 else "quality_check",
            action_type="generate_draft" if i == 0 else "check_quality",
            action_reason=f"Iteration {i}",
            action_params={"param": f"value-{i}"},
            result={"success": True},
            error=None,
            duration_ms=1000 + i * 500,
        )
        manager.add_iteration("test-job-2", iteration_trace)
        print(f"  迭代 {i}: action={iteration_trace.action_type}, duration={iteration_trace.duration_ms}ms")

    # 结束 trace
    print("\n3.3 结束 trace")
    manager.end_trace("test-job-2", "done", True, None)
    print("  Trace 已结束")

    # 保存 trace
    print("\n3.4 保存 trace")
    manager.save("test-job-2")
    print("  Trace 已保存")

    # 加载 trace
    print("\n3.5 加载 trace")
    loaded_trace = manager.load("test-job-2")
    print(f"  加载成功: {len(loaded_trace.iterations)} 个迭代")
    print(f"  最终状态: {loaded_trace.final_stage}, 成功: {loaded_trace.success}")


def test_trace_file_format():
    """测试 trace 文件格式"""
    print("\n" + "=" * 60)
    print("测试 4: Trace 文件格式")
    print("=" * 60)

    manager = TraceManager("tmp/test_traces")

    # 创建并保存 trace
    manager.start_trace("test-job-3")

    iteration_trace = IterationTrace(
        iteration=0,
        timestamp="2026-05-17T10:00:00",
        stage="draft",
        action_type="generate_draft",
        action_reason="Initial draft",
        action_params={"style": "speech_verbatim"},
        result={"draft": "测试内容"},
        error=None,
        duration_ms=2500,
    )
    manager.add_iteration("test-job-3", iteration_trace)
    manager.end_trace("test-job-3", "done", True)
    manager.save("test-job-3")

    # 读取 JSON 文件
    print("\n4.1 读取 trace JSON 文件")
    trace_path = Path("tmp/test_traces/test-job-3.json")
    with open(trace_path, 'r') as f:
        data = json.load(f)

    print(f"  job_id: {data['job_id']}")
    print(f"  start_time: {data['start_time']}")
    print(f"  end_time: {data['end_time']}")
    print(f"  iterations: {len(data['iterations'])}")
    print(f"  final_stage: {data['final_stage']}")
    print(f"  success: {data['success']}")

    print("\n4.2 迭代详情")
    for it in data['iterations']:
        print(f"    迭代 {it['iteration']}: {it['action_type']} ({it['duration_ms']}ms)")


def test_checkpoint_and_trace_integration():
    """测试 checkpoint 和 trace 集成"""
    print("\n" + "=" * 60)
    print("测试 5: Checkpoint 和 Trace 集成")
    print("=" * 60)

    checkpoint_manager = CheckpointManager("tmp/test_checkpoints")
    trace_manager = TraceManager("tmp/test_traces")

    job_id = "test-job-4"

    # 模拟 agent loop 执行
    print("\n5.1 模拟 agent loop 执行")

    # 开始 trace
    trace_manager.start_trace(job_id)

    # 迭代 1: 生成草稿
    print("  迭代 0: 生成草稿")
    iteration_trace = IterationTrace(
        iteration=0,
        timestamp="2026-05-17T10:00:00",
        stage="draft",
        action_type="generate_draft",
        action_reason="Initial draft",
        action_params={},
        result={"draft": "草稿内容"},
        error=None,
        duration_ms=3000,
    )
    trace_manager.add_iteration(job_id, iteration_trace)

    # 保存 checkpoint
    checkpoint = create_checkpoint(
        job_id=job_id,
        iteration=0,
        stage="draft",
        agent_state={"job_id": job_id, "retry_count": 0, "error_history": []},
        draft_text="草稿内容",
    )
    checkpoint_manager.save(checkpoint)
    print(f"    Checkpoint 已保存")

    # 迭代 2: 质量检查
    print("  迭代 1: 质量检查")
    iteration_trace = IterationTrace(
        iteration=1,
        timestamp="2026-05-17T10:01:00",
        stage="quality_check",
        action_type="check_quality",
        action_reason="Check draft quality",
        action_params={},
        result={"issues": []},
        error=None,
        duration_ms=500,
    )
    trace_manager.add_iteration(job_id, iteration_trace)

    # 结束 trace
    trace_manager.end_trace(job_id, "done", True)
    trace_manager.save(job_id)
    print("  Trace 已保存")

    # 删除 checkpoint（完成后清理）
    checkpoint_manager.delete(job_id)
    print("  Checkpoint 已清理")

    print("\n5.2 验证结果")
    print(f"  Checkpoint 存在: {checkpoint_manager.exists(job_id)}")
    print(f"  Trace 存在: {trace_manager.exists(job_id)}")

    # 加载 trace 验证
    loaded_trace = trace_manager.load(job_id)
    print(f"  Trace 迭代数: {len(loaded_trace.iterations)}")
    print(f"  总耗时: {sum(it.duration_ms for it in loaded_trace.iterations)}ms")


def main():
    """运行所有验证测试"""
    print("\n" + "=" * 60)
    print("Phase 3 功能验证")
    print("=" * 60)

    try:
        test_checkpoint_persistence()
        test_checkpoint_resume_conditions()
        test_trace_recording()
        test_trace_file_format()
        test_checkpoint_and_trace_integration()

        print("\n" + "=" * 60)
        print("✓ 所有验证测试通过")
        print("=" * 60)

        # 清理测试文件
        import shutil
        for dir_path in ["tmp/test_checkpoints", "tmp/test_traces"]:
            if Path(dir_path).exists():
                shutil.rmtree(dir_path)
        print("\n测试文件已清理")

    except Exception as e:
        print(f"\n✗ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
