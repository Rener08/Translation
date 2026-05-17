"""Tests for execution trace.

Phase 3: Test trace recording and persistence.
"""

import pytest
import json
from pathlib import Path
from app.agents.trace import (
    IterationTrace,
    ExecutionTrace,
    TraceManager,
)


@pytest.fixture
def trace_dir(tmp_path):
    """Create a temporary trace directory."""
    return str(tmp_path / "traces")


@pytest.fixture
def trace_manager(trace_dir):
    """Create a trace manager with temp directory."""
    return TraceManager(trace_dir)


class TestIterationTrace:
    """Test IterationTrace dataclass."""

    def test_iteration_trace_creation(self):
        """Test creating an iteration trace."""
        trace = IterationTrace(
            iteration=0,
            timestamp="2026-05-17T10:00:00",
            stage="draft",
            action_type="generate_draft",
            action_reason="Initial draft generation",
            action_params={"rewrite_style": "speech_verbatim"},
            result={"draft": "test"},
            error=None,
            duration_ms=1500,
        )

        assert trace.iteration == 0
        assert trace.action_type == "generate_draft"
        assert trace.duration_ms == 1500


class TestExecutionTrace:
    """Test ExecutionTrace dataclass."""

    def test_execution_trace_creation(self):
        """Test creating an execution trace."""
        trace = ExecutionTrace(
            job_id="test-job-1",
            start_time="2026-05-17T10:00:00",
            end_time=None,
            iterations=[],
            final_stage=None,
            success=None,
            error_message=None,
        )

        assert trace.job_id == "test-job-1"
        assert trace.iterations == []
        assert trace.success is None


class TestTraceManager:
    """Test TraceManager class."""

    def test_start_trace(self, trace_manager):
        """Test starting a new trace."""
        trace_manager.start_trace("test-job-1")

        # Trace should be in active traces
        assert "test-job-1" in trace_manager._active_traces

    def test_add_iteration(self, trace_manager):
        """Test adding an iteration to a trace."""
        trace_manager.start_trace("test-job-2")

        iteration_trace = IterationTrace(
            iteration=0,
            timestamp="2026-05-17T10:00:00",
            stage="draft",
            action_type="generate_draft",
            action_reason="Initial draft",
            action_params={},
            result={"draft": "test"},
            error=None,
            duration_ms=1000,
        )

        trace_manager.add_iteration("test-job-2", iteration_trace)

        trace = trace_manager._active_traces["test-job-2"]
        assert len(trace.iterations) == 1
        assert trace.iterations[0].iteration == 0

    def test_add_iteration_to_nonexistent_trace(self, trace_manager, caplog):
        """Test adding iteration to non-existent trace logs warning."""
        iteration_trace = IterationTrace(
            iteration=0,
            timestamp="2026-05-17T10:00:00",
            stage="draft",
            action_type="generate_draft",
            action_reason="Test",
            action_params={},
            result=None,
            error=None,
            duration_ms=100,
        )

        trace_manager.add_iteration("nonexistent", iteration_trace)

        assert "non-existent trace" in caplog.text.lower()

    def test_end_trace(self, trace_manager):
        """Test ending a trace."""
        trace_manager.start_trace("test-job-3")

        trace_manager.end_trace(
            job_id="test-job-3",
            final_stage="done",
            success=True,
            error_message=None,
        )

        trace = trace_manager._active_traces["test-job-3"]
        assert trace.end_time is not None
        assert trace.final_stage == "done"
        assert trace.success is True

    def test_end_nonexistent_trace(self, trace_manager, caplog):
        """Test ending a non-existent trace logs warning."""
        trace_manager.end_trace(
            job_id="nonexistent",
            final_stage="done",
            success=True,
        )

        assert "non-existent trace" in caplog.text.lower()

    def test_save_trace(self, trace_manager):
        """Test saving a trace to file."""
        trace_manager.start_trace("test-job-4")

        iteration_trace = IterationTrace(
            iteration=0,
            timestamp="2026-05-17T10:00:00",
            stage="draft",
            action_type="generate_draft",
            action_reason="Test",
            action_params={},
            result={"draft": "test"},
            error=None,
            duration_ms=1000,
        )
        trace_manager.add_iteration("test-job-4", iteration_trace)

        trace_manager.end_trace("test-job-4", "done", True)
        trace_manager.save("test-job-4")

        # Trace should be removed from active traces
        assert "test-job-4" not in trace_manager._active_traces

        # Trace file should exist
        assert trace_manager.exists("test-job-4")

    def test_save_nonexistent_trace(self, trace_manager, caplog):
        """Test saving a non-existent trace logs warning."""
        trace_manager.save("nonexistent")

        assert "non-existent trace" in caplog.text.lower()

    def test_load_trace(self, trace_manager):
        """Test loading a trace from file."""
        # Create and save a trace
        trace_manager.start_trace("test-job-5")

        iteration_trace = IterationTrace(
            iteration=0,
            timestamp="2026-05-17T10:00:00",
            stage="draft",
            action_type="generate_draft",
            action_reason="Test",
            action_params={"param": "value"},
            result={"draft": "test"},
            error=None,
            duration_ms=1500,
        )
        trace_manager.add_iteration("test-job-5", iteration_trace)

        trace_manager.end_trace("test-job-5", "done", True)
        trace_manager.save("test-job-5")

        # Load the trace
        loaded_trace = trace_manager.load("test-job-5")

        assert loaded_trace.job_id == "test-job-5"
        assert len(loaded_trace.iterations) == 1
        assert loaded_trace.iterations[0].iteration == 0
        assert loaded_trace.final_stage == "done"
        assert loaded_trace.success is True

    def test_load_nonexistent_trace(self, trace_manager):
        """Test loading a non-existent trace raises error."""
        with pytest.raises(FileNotFoundError):
            trace_manager.load("nonexistent")

    def test_exists(self, trace_manager):
        """Test checking if trace exists."""
        assert trace_manager.exists("test-job-6") is False

        trace_manager.start_trace("test-job-6")
        trace_manager.end_trace("test-job-6", "done", True)
        trace_manager.save("test-job-6")

        assert trace_manager.exists("test-job-6") is True

    def test_list_all_traces(self, trace_manager):
        """Test listing all traces."""
        # Create multiple traces
        for i in range(3):
            trace_manager.start_trace(f"test-job-{i}")
            trace_manager.end_trace(f"test-job-{i}", "done", True)
            trace_manager.save(f"test-job-{i}")

        job_ids = trace_manager.list_all()

        assert len(job_ids) == 3
        assert "test-job-0" in job_ids
        assert "test-job-1" in job_ids
        assert "test-job-2" in job_ids

    def test_list_all_empty(self, trace_manager):
        """Test listing traces when none exist."""
        job_ids = trace_manager.list_all()

        assert job_ids == []

    def test_trace_file_format(self, trace_manager, trace_dir):
        """Test that trace is saved as valid JSON."""
        trace_manager.start_trace("test-job-7")

        iteration_trace = IterationTrace(
            iteration=0,
            timestamp="2026-05-17T10:00:00",
            stage="draft",
            action_type="generate_draft",
            action_reason="Test",
            action_params={},
            result={"draft": "test"},
            error=None,
            duration_ms=2000,
        )
        trace_manager.add_iteration("test-job-7", iteration_trace)

        trace_manager.end_trace("test-job-7", "done", True, None)
        trace_manager.save("test-job-7")

        # Read file directly
        trace_path = Path(trace_dir) / "test-job-7.json"
        with open(trace_path, 'r') as f:
            data = json.load(f)

        assert data["job_id"] == "test-job-7"
        assert data["final_stage"] == "done"
        assert data["success"] is True
        assert len(data["iterations"]) == 1
        assert data["iterations"][0]["duration_ms"] == 2000

    def test_multiple_iterations(self, trace_manager):
        """Test trace with multiple iterations."""
        trace_manager.start_trace("test-job-8")

        # Add 3 iterations
        for i in range(3):
            iteration_trace = IterationTrace(
                iteration=i,
                timestamp=f"2026-05-17T10:0{i}:00",
                stage="draft",
                action_type="generate_draft",
                action_reason=f"Iteration {i}",
                action_params={},
                result={"draft": f"draft-{i}"},
                error=None,
                duration_ms=1000 + i * 100,
            )
            trace_manager.add_iteration("test-job-8", iteration_trace)

        trace_manager.end_trace("test-job-8", "done", True)
        trace_manager.save("test-job-8")

        # Load and verify
        loaded_trace = trace_manager.load("test-job-8")

        assert len(loaded_trace.iterations) == 3
        assert loaded_trace.iterations[0].iteration == 0
        assert loaded_trace.iterations[1].iteration == 1
        assert loaded_trace.iterations[2].iteration == 2

    def test_trace_with_error(self, trace_manager):
        """Test trace that ends with error."""
        trace_manager.start_trace("test-job-9")

        iteration_trace = IterationTrace(
            iteration=0,
            timestamp="2026-05-17T10:00:00",
            stage="draft",
            action_type="generate_draft",
            action_reason="Test",
            action_params={},
            result=None,
            error="Test error message",
            duration_ms=500,
        )
        trace_manager.add_iteration("test-job-9", iteration_trace)

        trace_manager.end_trace(
            job_id="test-job-9",
            final_stage="failed",
            success=False,
            error_message="Test error message",
        )
        trace_manager.save("test-job-9")

        # Load and verify
        loaded_trace = trace_manager.load("test-job-9")

        assert loaded_trace.success is False
        assert loaded_trace.error_message == "Test error message"
        assert loaded_trace.iterations[0].error == "Test error message"
