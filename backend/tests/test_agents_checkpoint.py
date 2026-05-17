"""Tests for checkpoint persistence.

Phase 3: Test checkpoint save, load, and resume logic.
"""

import pytest
import json
from pathlib import Path
from app.agents.checkpoint import (
    AgentCheckpoint,
    CheckpointManager,
    can_resume_from_checkpoint,
    create_checkpoint,
)


@pytest.fixture
def checkpoint_dir(tmp_path):
    """Create a temporary checkpoint directory."""
    return str(tmp_path / "checkpoints")


@pytest.fixture
def checkpoint_manager(checkpoint_dir):
    """Create a checkpoint manager with temp directory."""
    return CheckpointManager(checkpoint_dir)


class TestAgentCheckpoint:
    """Test AgentCheckpoint dataclass."""

    def test_checkpoint_creation(self):
        """Test creating a checkpoint."""
        checkpoint = AgentCheckpoint(
            job_id="test-job-1",
            iteration=0,
            timestamp="2026-05-17T10:00:00",
            stage="draft",
            agent_state={"job_id": "test-job-1", "current_stage": "draft"},
            last_action={"type": "generate_draft"},
            last_result={"draft": "test"},
            draft_text="Test draft",
            can_resume=True,
        )

        assert checkpoint.job_id == "test-job-1"
        assert checkpoint.iteration == 0
        assert checkpoint.can_resume is True


class TestCheckpointManager:
    """Test CheckpointManager class."""

    def test_save_checkpoint(self, checkpoint_manager):
        """Test saving a checkpoint."""
        checkpoint = create_checkpoint(
            job_id="test-job-1",
            iteration=0,
            stage="draft",
            agent_state={"job_id": "test-job-1"},
        )

        checkpoint_manager.save(checkpoint)

        assert checkpoint_manager.exists("test-job-1")

    def test_load_checkpoint(self, checkpoint_manager):
        """Test loading a checkpoint."""
        checkpoint = create_checkpoint(
            job_id="test-job-2",
            iteration=1,
            stage="quality_check",
            agent_state={"job_id": "test-job-2", "retry_count": 1},
        )

        checkpoint_manager.save(checkpoint)
        loaded = checkpoint_manager.load("test-job-2")

        assert loaded.job_id == "test-job-2"
        assert loaded.iteration == 1
        assert loaded.stage == "quality_check"

    def test_load_nonexistent_checkpoint(self, checkpoint_manager):
        """Test loading a checkpoint that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            checkpoint_manager.load("nonexistent")

    def test_exists(self, checkpoint_manager):
        """Test checking if checkpoint exists."""
        assert checkpoint_manager.exists("test-job-3") is False

        checkpoint = create_checkpoint(
            job_id="test-job-3",
            iteration=0,
            stage="init",
            agent_state={},
        )
        checkpoint_manager.save(checkpoint)

        assert checkpoint_manager.exists("test-job-3") is True

    def test_delete_checkpoint(self, checkpoint_manager):
        """Test deleting a checkpoint."""
        checkpoint = create_checkpoint(
            job_id="test-job-4",
            iteration=0,
            stage="draft",
            agent_state={},
        )
        checkpoint_manager.save(checkpoint)

        assert checkpoint_manager.exists("test-job-4") is True

        checkpoint_manager.delete("test-job-4")

        assert checkpoint_manager.exists("test-job-4") is False

    def test_delete_nonexistent_checkpoint(self, checkpoint_manager):
        """Test deleting a checkpoint that doesn't exist (should not error)."""
        checkpoint_manager.delete("nonexistent")  # Should not raise

    def test_list_all_checkpoints(self, checkpoint_manager):
        """Test listing all checkpoints."""
        # Create multiple checkpoints
        for i in range(3):
            checkpoint = create_checkpoint(
                job_id=f"test-job-{i}",
                iteration=0,
                stage="draft",
                agent_state={},
            )
            checkpoint_manager.save(checkpoint)

        job_ids = checkpoint_manager.list_all()

        assert len(job_ids) == 3
        assert "test-job-0" in job_ids
        assert "test-job-1" in job_ids
        assert "test-job-2" in job_ids

    def test_list_all_empty(self, checkpoint_manager):
        """Test listing checkpoints when none exist."""
        job_ids = checkpoint_manager.list_all()

        assert job_ids == []

    def test_checkpoint_file_format(self, checkpoint_manager, checkpoint_dir):
        """Test that checkpoint is saved as valid JSON."""
        checkpoint = create_checkpoint(
            job_id="test-job-5",
            iteration=2,
            stage="revision",
            agent_state={"job_id": "test-job-5", "retry_count": 2},
            draft_text="Draft text",
        )
        checkpoint_manager.save(checkpoint)

        # Read file directly
        checkpoint_path = Path(checkpoint_dir) / "test-job-5.json"
        with open(checkpoint_path, 'r') as f:
            data = json.load(f)

        assert data["job_id"] == "test-job-5"
        assert data["iteration"] == 2
        assert data["stage"] == "revision"
        assert data["draft_text"] == "Draft text"


class TestCanResumeFromCheckpoint:
    """Test can_resume_from_checkpoint function."""

    def test_can_resume_normal_checkpoint(self):
        """Test that normal checkpoint can be resumed."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=1,
            stage="draft",
            agent_state={"error_history": []},
        )

        assert can_resume_from_checkpoint(checkpoint) is True

    def test_cannot_resume_done_checkpoint(self):
        """Test that DONE checkpoint cannot be resumed."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=1,
            stage="done",
            agent_state={},
        )

        assert can_resume_from_checkpoint(checkpoint) is False

    def test_cannot_resume_failed_checkpoint(self):
        """Test that FAILED checkpoint cannot be resumed."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=1,
            stage="failed",
            agent_state={},
        )

        assert can_resume_from_checkpoint(checkpoint) is False

    def test_cannot_resume_max_iterations(self):
        """Test that checkpoint at max iterations cannot be resumed."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=10,
            stage="draft",
            agent_state={},
        )

        assert can_resume_from_checkpoint(checkpoint, max_iterations=10) is False

    def test_cannot_resume_too_many_errors(self):
        """Test that checkpoint with too many errors cannot be resumed."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=1,
            stage="draft",
            agent_state={
                "error_history": [
                    {"error": "Error 1"},
                    {"error": "Error 2"},
                    {"error": "Error 3"},
                ]
            },
        )

        assert can_resume_from_checkpoint(checkpoint) is False

    def test_cannot_resume_marked_non_resumable(self):
        """Test that checkpoint marked as non-resumable cannot be resumed."""
        checkpoint = AgentCheckpoint(
            job_id="test-job",
            iteration=1,
            timestamp="2026-05-17T10:00:00",
            stage="draft",
            agent_state={},
            last_action=None,
            last_result=None,
            draft_text=None,
            can_resume=False,
        )

        assert can_resume_from_checkpoint(checkpoint) is False


class TestCreateCheckpoint:
    """Test create_checkpoint function."""

    def test_create_checkpoint_basic(self):
        """Test creating a basic checkpoint."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=0,
            stage="draft",
            agent_state={"job_id": "test-job"},
        )

        assert checkpoint.job_id == "test-job"
        assert checkpoint.iteration == 0
        assert checkpoint.stage == "draft"
        assert checkpoint.can_resume is True

    def test_create_checkpoint_with_all_fields(self):
        """Test creating a checkpoint with all fields."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=2,
            stage="revision",
            agent_state={"job_id": "test-job", "retry_count": 2},
            last_action={"type": "revise_draft"},
            last_result={"revised": True},
            draft_text="Revised draft",
        )

        assert checkpoint.last_action == {"type": "revise_draft"}
        assert checkpoint.last_result == {"revised": True}
        assert checkpoint.draft_text == "Revised draft"

    def test_create_checkpoint_done_not_resumable(self):
        """Test that DONE checkpoint is marked as non-resumable."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=5,
            stage="done",
            agent_state={},
        )

        assert checkpoint.can_resume is False

    def test_create_checkpoint_failed_not_resumable(self):
        """Test that FAILED checkpoint is marked as non-resumable."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=3,
            stage="failed",
            agent_state={},
        )

        assert checkpoint.can_resume is False

    def test_create_checkpoint_too_many_errors_not_resumable(self):
        """Test that checkpoint with 3+ errors is marked as non-resumable."""
        checkpoint = create_checkpoint(
            job_id="test-job",
            iteration=2,
            stage="draft",
            agent_state={
                "error_history": [
                    {"error": "Error 1"},
                    {"error": "Error 2"},
                    {"error": "Error 3"},
                ]
            },
        )

        assert checkpoint.can_resume is False
