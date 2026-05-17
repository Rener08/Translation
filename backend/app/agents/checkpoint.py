"""Checkpoint schema and persistence for agent loop.

Phase 3: Checkpoint mechanism for resuming interrupted executions.
"""

from dataclasses import dataclass, asdict
from typing import Any
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentCheckpoint:
    """Checkpoint for agent loop state.

    Allows resuming execution from a saved point.
    """

    job_id: str
    """Unique job identifier"""

    iteration: int
    """Loop iteration number (0-indexed)"""

    timestamp: str
    """ISO 8601 timestamp of checkpoint creation"""

    stage: str
    """Current agent stage (from AgentStage enum)"""

    agent_state: dict[str, Any]
    """Serialized AgentState"""

    last_action: dict[str, Any] | None
    """Last action taken (type, params, reason)"""

    last_result: dict[str, Any] | None
    """Result of last action"""

    draft_text: str | None
    """Current draft text (if any)"""

    can_resume: bool
    """Whether this checkpoint can be resumed"""


class CheckpointManager:
    """Manager for agent checkpoint persistence.

    Handles saving, loading, and deleting checkpoints.
    """

    def __init__(self, checkpoint_dir: str = "tmp/checkpoints"):
        """Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory for checkpoint files (relative to backend/)
        """
        self._checkpoint_dir = Path(checkpoint_dir)
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(self, checkpoint: AgentCheckpoint) -> None:
        """Save checkpoint to JSON file.

        Args:
            checkpoint: Checkpoint to save
        """
        checkpoint_path = self._get_checkpoint_path(checkpoint.job_id)

        try:
            # Convert to dict
            checkpoint_dict = asdict(checkpoint)

            # Write atomically (write to temp file, then rename)
            temp_path = checkpoint_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_dict, f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_path.replace(checkpoint_path)

            logger.info(
                "Checkpoint saved",
                extra={
                    "job_id": checkpoint.job_id,
                    "iteration": checkpoint.iteration,
                    "stage": checkpoint.stage,
                }
            )

        except Exception as e:
            logger.error(
                "Failed to save checkpoint",
                extra={"job_id": checkpoint.job_id, "error": str(e)},
                exc_info=True,
            )
            raise

    def load(self, job_id: str) -> AgentCheckpoint:
        """Load checkpoint from JSON file.

        Args:
            job_id: Job identifier

        Returns:
            Loaded checkpoint

        Raises:
            FileNotFoundError: If checkpoint doesn't exist
            ValueError: If checkpoint is invalid
        """
        checkpoint_path = self._get_checkpoint_path(job_id)

        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {job_id}")

        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                checkpoint_dict = json.load(f)

            checkpoint = AgentCheckpoint(**checkpoint_dict)

            logger.info(
                "Checkpoint loaded",
                extra={
                    "job_id": checkpoint.job_id,
                    "iteration": checkpoint.iteration,
                    "stage": checkpoint.stage,
                }
            )

            return checkpoint

        except Exception as e:
            logger.error(
                "Failed to load checkpoint",
                extra={"job_id": job_id, "error": str(e)},
                exc_info=True,
            )
            raise ValueError(f"Invalid checkpoint: {e}") from e

    def exists(self, job_id: str) -> bool:
        """Check if checkpoint exists.

        Args:
            job_id: Job identifier

        Returns:
            True if checkpoint exists
        """
        checkpoint_path = self._get_checkpoint_path(job_id)
        return checkpoint_path.exists()

    def delete(self, job_id: str) -> None:
        """Delete checkpoint file.

        Args:
            job_id: Job identifier
        """
        checkpoint_path = self._get_checkpoint_path(job_id)

        if checkpoint_path.exists():
            try:
                checkpoint_path.unlink()
                logger.info("Checkpoint deleted", extra={"job_id": job_id})
            except Exception as e:
                logger.error(
                    "Failed to delete checkpoint",
                    extra={"job_id": job_id, "error": str(e)},
                    exc_info=True,
                )

    def list_all(self) -> list[str]:
        """List all checkpoint job IDs.

        Returns:
            List of job IDs with checkpoints
        """
        if not self._checkpoint_dir.exists():
            return []

        job_ids = []
        for checkpoint_path in self._checkpoint_dir.glob("*.json"):
            job_ids.append(checkpoint_path.stem)

        return job_ids

    def _get_checkpoint_path(self, job_id: str) -> Path:
        """Get checkpoint file path for a job.

        Args:
            job_id: Job identifier

        Returns:
            Path to checkpoint file
        """
        return self._checkpoint_dir / f"{job_id}.json"


def can_resume_from_checkpoint(checkpoint: AgentCheckpoint, max_iterations: int = 10) -> bool:
    """Check if a checkpoint can be resumed.

    Args:
        checkpoint: Checkpoint to check
        max_iterations: Maximum loop iterations

    Returns:
        True if checkpoint can be resumed
    """
    # Can't resume if already marked as non-resumable
    if not checkpoint.can_resume:
        return False

    # Can't resume if stage is DONE or FAILED
    if checkpoint.stage in ("done", "failed"):
        return False

    # Can't resume if iteration exceeds max
    if checkpoint.iteration >= max_iterations:
        return False

    # Can't resume if too many errors
    error_history = checkpoint.agent_state.get("error_history", [])
    if len(error_history) >= 3:
        return False

    return True


def create_checkpoint(
    job_id: str,
    iteration: int,
    stage: str,
    agent_state: dict[str, Any],
    last_action: dict[str, Any] | None = None,
    last_result: dict[str, Any] | None = None,
    draft_text: str | None = None,
) -> AgentCheckpoint:
    """Create a checkpoint from current state.

    Args:
        job_id: Job identifier
        iteration: Current iteration
        stage: Current stage
        agent_state: Serialized agent state
        last_action: Last action taken
        last_result: Result of last action
        draft_text: Current draft text

    Returns:
        AgentCheckpoint instance
    """
    # Determine if can resume
    can_resume = stage not in ("done", "failed") and len(agent_state.get("error_history", [])) < 3

    return AgentCheckpoint(
        job_id=job_id,
        iteration=iteration,
        timestamp=datetime.now().isoformat(),
        stage=stage,
        agent_state=agent_state,
        last_action=last_action,
        last_result=last_result,
        draft_text=draft_text,
        can_resume=can_resume,
    )
