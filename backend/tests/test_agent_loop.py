"""Tests for agent loop implementation - Phase 1."""

import pytest
from unittest.mock import Mock, patch

from app.agents.state import AgentState
from app.agents.loop import (
    AgentStage,
    ActionType,
    InternalState,
    InternalAction,
    decide_next_action,
    update_state,
    handle_error,
    build_report,
    run_agent_loop,
)
from app.services.pipelines import MaterialPackage, WriterRunReport


@pytest.fixture
def material():
    return MaterialPackage(
        source_text="Test source text for agent loop",
        reference_text="",
    )


@pytest.fixture
def mock_writer_report(material):
    """Create a mock WriterRunReport."""
    return WriterRunReport(
        rewritten_text="Generated article text",
        provider="openai",
        model="gpt-4",
        quality_issues=(),
        material=material,
        draft=None,  # Simplified for testing
        rewrite_style="speech_verbatim",
    )


class TestDecideNextAction:
    """Test action decision logic."""

    def test_init_stage_generates_draft(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="draft",
            material=material,
            draft_text=None,
            quality_issues=[],
            retry_count=0,
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.INIT,
            draft=None,
        )

        action = decide_next_action(state, None, "speech_verbatim")
        assert action.type == ActionType.GENERATE_DRAFT
        assert "Initial draft" in action.reason

    def test_draft_stage_checks_quality(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="draft",
            material=material,
            draft_text="Some draft",
            quality_issues=[],
            retry_count=0,
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.DRAFT,
            draft=None,
        )

        action = decide_next_action(state, None, None)
        assert action.type == ActionType.CHECK_QUALITY

    def test_quality_check_with_issues_revises(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="quality_check",
            material=material,
            draft_text="Some draft",
            quality_issues=["Issue 1", "Issue 2"],
            retry_count=0,
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.QUALITY_CHECK,
            draft=None,
        )

        action = decide_next_action(state, None, None)
        assert action.type == ActionType.REVISE_DRAFT

    def test_quality_check_without_issues_finalizes(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="quality_check",
            material=material,
            draft_text="Some draft",
            quality_issues=[],
            retry_count=0,
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.QUALITY_CHECK,
            draft=None,
        )

        action = decide_next_action(state, None, None)
        assert action.type == ActionType.FINALIZE

    def test_max_retries_finalizes(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="quality_check",
            material=material,
            draft_text="Some draft",
            quality_issues=["Issue 1"],
            retry_count=2,  # Max retries reached
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.QUALITY_CHECK,
            draft=None,
        )

        action = decide_next_action(state, None, None)
        assert action.type == ActionType.FINALIZE


class TestUpdateState:
    """Test state update logic."""

    def test_generate_draft_updates_stage(self, material, mock_writer_report):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="draft",
            material=material,
            draft_text=None,
            quality_issues=[],
            retry_count=0,
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.INIT,
            draft=None,
        )

        action = InternalAction(
            type=ActionType.GENERATE_DRAFT,
            reason="Test",
            params={},
        )
        result = {"draft": mock_writer_report}

        new_state = update_state(state, action, result)
        assert new_state.stage == AgentStage.DRAFT
        assert new_state.draft == mock_writer_report
        assert new_state.agent_state.draft_text == "Generated article text"

    def test_check_quality_updates_issues(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="draft",
            material=material,
            draft_text="Some draft",
            quality_issues=[],
            retry_count=0,
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.DRAFT,
            draft=None,
        )

        action = InternalAction(
            type=ActionType.CHECK_QUALITY,
            reason="Test",
            params={},
        )
        result = {"quality_issues": ["Issue 1", "Issue 2"]}

        new_state = update_state(state, action, result)
        assert new_state.stage == AgentStage.QUALITY_CHECK
        assert new_state.agent_state.quality_issues == ["Issue 1", "Issue 2"]

    def test_revise_draft_increments_retry(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="quality_check",
            material=material,
            draft_text="Some draft",
            quality_issues=["Issue 1"],
            retry_count=0,
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.QUALITY_CHECK,
            draft=None,
        )

        action = InternalAction(
            type=ActionType.REVISE_DRAFT,
            reason="Test",
            params={},
        )
        result = {"revised": True}

        new_state = update_state(state, action, result)
        assert new_state.stage == AgentStage.REVISION
        assert new_state.agent_state.retry_count == 1


class TestHandleError:
    """Test error handling logic."""

    def test_records_error_in_history(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="draft",
            material=material,
            draft_text=None,
            quality_issues=[],
            retry_count=0,
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.INIT,
            draft=None,
        )

        error = ValueError("Test error")
        new_state, should_retry, retry_delay = handle_error(state, error, attempt=0)

        assert len(new_state.agent_state.error_history) == 1
        assert new_state.agent_state.error_history[0]["error"] == "Test error"
        assert new_state.agent_state.error_history[0]["type"] == "ValueError"

    def test_fails_after_max_errors(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="draft",
            material=material,
            draft_text=None,
            quality_issues=[],
            retry_count=0,
            error_history=[
                {"error": "Error 1", "type": "ValueError", "stage": "init"},
                {"error": "Error 2", "type": "ValueError", "stage": "init"},
            ],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.INIT,
            draft=None,
        )

        error = ValueError("Error 3")
        new_state, should_retry, retry_delay = handle_error(state, error, attempt=0)

        assert len(new_state.agent_state.error_history) == 3
        assert new_state.stage == AgentStage.FAILED


class TestBuildReport:
    """Test report building logic."""

    def test_successful_report(self, material, mock_writer_report):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="done",
            material=material,
            draft_text="Final draft",
            quality_issues=[],
            retry_count=1,
            error_history=[],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.DONE,
            draft=mock_writer_report,
        )

        report = build_report(state)
        assert report.success is True
        assert report.iterations == 2  # retry_count + 1
        assert report.final_stage == AgentStage.DONE
        assert report.writer_report == mock_writer_report
        assert report.error_message is None

    def test_failed_report(self, material):
        agent_state = AgentState(
            job_id="test-1",
            current_stage="done",
            material=material,
            draft_text=None,
            quality_issues=[],
            retry_count=0,
            error_history=[{"error": "Fatal error", "type": "RuntimeError", "stage": "init"}],
        )
        state = InternalState(
            agent_state=agent_state,
            stage=AgentStage.FAILED,
            draft=None,
        )

        report = build_report(state)
        assert report.success is False
        assert report.final_stage == AgentStage.FAILED
        assert report.error_message == "Fatal error"


def test_run_agent_loop_integration(material):
    """Integration test: run_agent_loop with mocked WriterAgent."""
    import asyncio

    # Create mock agent
    mock_agent = Mock()
    mock_report = WriterRunReport(
        rewritten_text="Generated text",
        provider="openai",
        model="gpt-4",
        quality_issues=(),
        material=material,
        draft=None,
        rewrite_style="speech_verbatim",
    )

    # Mock the pipeline methods
    mock_strategy = Mock()
    mock_agent._select_strategy.return_value = mock_strategy
    mock_agent._execute_pipeline.return_value = mock_report
    rewrite_config = {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "api_key": "test-key",
    }

    # Run the loop
    result = asyncio.run(run_agent_loop(
        agent=mock_agent,
        material=material,
        rewrite_focus=None,
        rewrite_style="speech_verbatim",
        rewrite_config=rewrite_config,
    ))

    # Verify
    assert result == mock_report
    assert mock_agent._select_strategy.called
    assert mock_agent._execute_pipeline.called
    assert mock_agent._execute_pipeline.call_args.kwargs["rewrite_config"] == rewrite_config
