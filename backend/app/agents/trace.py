"""Execution trace for agent loop.

Phase 3: Trace mechanism for recording agent execution history.
"""

from dataclasses import dataclass, asdict
from typing import Any
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class IterationTrace:
    """Trace of a single agent loop iteration."""

    iteration: int
    """Iteration number (0-indexed)"""

    timestamp: str
    """ISO 8601 timestamp when iteration started"""

    stage: str
    """Agent stage at this iteration"""

    action_type: str
    """Type of action taken"""

    action_reason: str
    """Reason for taking this action"""

    action_params: dict[str, Any]
    """Parameters passed to action"""

    result: dict[str, Any] | None
    """Result of action execution (None if failed)"""

    error: str | None
    """Error message if action failed"""

    duration_ms: int
    """Duration of iteration in milliseconds"""


@dataclass
class ExecutionTrace:
    """Complete execution trace for an agent loop."""

    job_id: str
    """Unique job identifier"""

    start_time: str
    """ISO 8601 timestamp when execution started"""

    end_time: str | None
    """ISO 8601 timestamp when execution ended (None if still running)"""

    iterations: list[IterationTrace]
    """List of iteration traces"""

    final_stage: str | None
    """Final stage reached (None if still running)"""

    success: bool | None
    """Whether execution succeeded (None if still running)"""

    error_message: str | None
    """Final error message if execution failed"""


class TraceManager:
    """Manager for agent execution traces.

    Handles recording and persisting execution traces.
    """

    def __init__(self, trace_dir: str = "tmp/traces"):
        """Initialize trace manager.

        Args:
            trace_dir: Directory for trace files (relative to backend/)
        """
        self._trace_dir = Path(trace_dir)
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._active_traces: dict[str, ExecutionTrace] = {}

    def start_trace(self, job_id: str) -> None:
        """Start a new execution trace.

        Args:
            job_id: Job identifier
        """
        trace = ExecutionTrace(
            job_id=job_id,
            start_time=datetime.now().isoformat(),
            end_time=None,
            iterations=[],
            final_stage=None,
            success=None,
            error_message=None,
        )

        self._active_traces[job_id] = trace

        logger.info("Execution trace started", extra={"job_id": job_id})

    def add_iteration(
        self,
        job_id: str,
        iteration_trace: IterationTrace,
    ) -> None:
        """Add an iteration trace to the execution trace.

        Args:
            job_id: Job identifier
            iteration_trace: Iteration trace to add
        """
        if job_id not in self._active_traces:
            logger.warning(
                "Cannot add iteration to non-existent trace",
                extra={"job_id": job_id}
            )
            return

        trace = self._active_traces[job_id]
        trace.iterations.append(iteration_trace)

        logger.debug(
            "Iteration trace added",
            extra={
                "job_id": job_id,
                "iteration": iteration_trace.iteration,
                "action_type": iteration_trace.action_type,
            }
        )

    def end_trace(
        self,
        job_id: str,
        final_stage: str,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """End an execution trace.

        Args:
            job_id: Job identifier
            final_stage: Final stage reached
            success: Whether execution succeeded
            error_message: Error message if failed
        """
        if job_id not in self._active_traces:
            logger.warning(
                "Cannot end non-existent trace",
                extra={"job_id": job_id}
            )
            return

        trace = self._active_traces[job_id]
        trace.end_time = datetime.now().isoformat()
        trace.final_stage = final_stage
        trace.success = success
        trace.error_message = error_message

        logger.info(
            "Execution trace ended",
            extra={
                "job_id": job_id,
                "final_stage": final_stage,
                "success": success,
                "iterations": len(trace.iterations),
            }
        )

    def save(self, job_id: str) -> None:
        """Save trace to JSON file.

        Args:
            job_id: Job identifier
        """
        if job_id not in self._active_traces:
            logger.warning(
                "Cannot save non-existent trace",
                extra={"job_id": job_id}
            )
            return

        trace = self._active_traces[job_id]
        trace_path = self._get_trace_path(job_id)

        try:
            # Convert to dict
            trace_dict = asdict(trace)

            # Write to file
            with open(trace_path, 'w', encoding='utf-8') as f:
                json.dump(trace_dict, f, indent=2, ensure_ascii=False)

            logger.info(
                "Trace saved",
                extra={
                    "job_id": job_id,
                    "iterations": len(trace.iterations),
                }
            )

            # Remove from active traces
            del self._active_traces[job_id]

        except Exception as e:
            logger.error(
                "Failed to save trace",
                extra={"job_id": job_id, "error": str(e)},
                exc_info=True,
            )
            raise

    def load(self, job_id: str) -> ExecutionTrace:
        """Load trace from JSON file.

        Args:
            job_id: Job identifier

        Returns:
            Loaded execution trace

        Raises:
            FileNotFoundError: If trace doesn't exist
            ValueError: If trace is invalid
        """
        trace_path = self._get_trace_path(job_id)

        if not trace_path.exists():
            raise FileNotFoundError(f"Trace not found: {job_id}")

        try:
            with open(trace_path, 'r', encoding='utf-8') as f:
                trace_dict = json.load(f)

            # Convert iterations back to IterationTrace objects
            iterations = [
                IterationTrace(**it) for it in trace_dict.get("iterations", [])
            ]
            trace_dict["iterations"] = iterations

            trace = ExecutionTrace(**trace_dict)

            logger.info(
                "Trace loaded",
                extra={
                    "job_id": job_id,
                    "iterations": len(trace.iterations),
                }
            )

            return trace

        except Exception as e:
            logger.error(
                "Failed to load trace",
                extra={"job_id": job_id, "error": str(e)},
                exc_info=True,
            )
            raise ValueError(f"Invalid trace: {e}") from e

    def exists(self, job_id: str) -> bool:
        """Check if trace exists.

        Args:
            job_id: Job identifier

        Returns:
            True if trace exists
        """
        trace_path = self._get_trace_path(job_id)
        return trace_path.exists()

    def list_all(self) -> list[str]:
        """List all trace job IDs.

        Returns:
            List of job IDs with traces
        """
        if not self._trace_dir.exists():
            return []

        job_ids = []
        for trace_path in self._trace_dir.glob("*.json"):
            job_ids.append(trace_path.stem)

        return job_ids

    def _get_trace_path(self, job_id: str) -> Path:
        """Get trace file path for a job.

        Args:
            job_id: Job identifier

        Returns:
            Path to trace file
        """
        return self._trace_dir / f"{job_id}.json"
