"""Agent loop: observe → decide → act → check cycle for WriterAgent.

Phase 1: Basic agent loop infrastructure with state management and decision logic.
Phase 2: Added tool calling, error recovery, and retry logic.
Phase 3: Added checkpoint persistence and execution trace.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, replace, asdict
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.agents.state import AgentState
from app.agents.action import AgentAction
from app.agents.tool_registry import ToolRegistry, create_default_registry
from app.agents.error_recovery import classify_error, should_retry
from app.agents.checkpoint import CheckpointManager, create_checkpoint, can_resume_from_checkpoint
from app.agents.trace import TraceManager, IterationTrace
from app.services.pipelines import MaterialPackage, WriterRunReport

if TYPE_CHECKING:
    from app.services.content_rewrite_service import RewriteStyle
    from app.services.skill_config_service import SkillConfig

logger = logging.getLogger(__name__)


class AgentStage(str, Enum):
    """Agent execution stages (for internal use)."""
    INIT = "init"
    DRAFT = "draft"
    QUALITY_CHECK = "quality_check"
    REVISION = "revision"
    DONE = "done"
    FAILED = "failed"


class ActionType(str, Enum):
    """Agent action types (for internal use)."""
    GENERATE_DRAFT = "generate_draft"
    CHECK_QUALITY = "check_quality"
    REVISE_DRAFT = "revise_draft"
    FINALIZE = "finalize"
    ABORT = "abort"


@dataclass
class InternalAction:
    """Internal action definition (different from AgentAction in action.py)."""
    type: ActionType
    reason: str
    params: dict[str, Any]


@dataclass
class InternalState:
    """Internal state tracking (wraps AgentState from state.py)."""
    agent_state: AgentState
    stage: AgentStage
    draft: WriterRunReport | None


@dataclass
class LoopReport:
    """Agent loop execution report."""
    success: bool
    iterations: int
    final_stage: AgentStage
    writer_report: WriterRunReport | None
    error_message: str | None


def _map_stage_to_current_stage(stage: AgentStage) -> str:
    """Map internal AgentStage to AgentState.current_stage."""
    mapping = {
        AgentStage.INIT: "draft",
        AgentStage.DRAFT: "draft",
        AgentStage.QUALITY_CHECK: "quality_check",
        AgentStage.REVISION: "patch",
        AgentStage.DONE: "done",
        AgentStage.FAILED: "done",
    }
    return mapping.get(stage, "draft")


def decide_next_action(
    state: InternalState,
    rewrite_focus: str | None,
    rewrite_style: str | None,
) -> InternalAction:
    """Decide next action based on current state.

    Decision logic:
    - INIT → generate draft
    - DRAFT → check quality
    - QUALITY_CHECK → revise if issues, finalize if clean
    - REVISION → check quality again
    - Max 2 retries → force finalize
    - FAILED → abort
    """
    if state.stage == AgentStage.INIT:
        return InternalAction(
            type=ActionType.GENERATE_DRAFT,
            reason="Initial draft generation",
            params={
                "rewrite_focus": rewrite_focus,
                "rewrite_style": rewrite_style,
            }
        )

    elif state.stage == AgentStage.DRAFT:
        return InternalAction(
            type=ActionType.CHECK_QUALITY,
            reason="Check draft quality",
            params={}
        )

    elif state.stage == AgentStage.QUALITY_CHECK:
        if state.agent_state.quality_issues and state.agent_state.retry_count < 2:
            return InternalAction(
                type=ActionType.REVISE_DRAFT,
                reason=f"Revise draft to fix {len(state.agent_state.quality_issues)} issues",
                params={"issues": state.agent_state.quality_issues}
            )
        else:
            return InternalAction(
                type=ActionType.FINALIZE,
                reason="Quality acceptable or max retries reached",
                params={}
            )

    elif state.stage == AgentStage.REVISION:
        return InternalAction(
            type=ActionType.CHECK_QUALITY,
            reason="Re-check quality after revision",
            params={}
        )

    elif state.stage == AgentStage.FAILED:
        return InternalAction(
            type=ActionType.ABORT,
            reason="Too many errors",
            params={}
        )

    else:
        return InternalAction(
            type=ActionType.FINALIZE,
            reason="Unknown stage, finalizing",
            params={}
        )


def execute_action(
    agent: Any,
    action: InternalAction,
    state: InternalState,
    skill_config: Any = None,
    rewrite_config: dict[str, Any] | None = None,
    llm_call_fn: Any = None,
    cancellation_checker: Any = None,
    tool_registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    """Execute an agent action.

    Phase 2: Added tool_registry parameter for future tool calling support.
    """
    if action.type == ActionType.GENERATE_DRAFT:
        # Get default skill config if not provided
        if skill_config is None:
            from app.services.skill_config_service import load_default_skill_config
            skill_config = load_default_skill_config()

        # Select strategy using existing logic
        strategy = agent._select_strategy(
            action.params.get("rewrite_style"),
            skill_config=skill_config,
            llm_call_fn=llm_call_fn,
        )

        # Execute pipeline
        report = agent._execute_pipeline(
            strategy=strategy,
            material=state.agent_state.material,
            rewrite_focus=action.params.get("rewrite_focus"),
            rewrite_config=rewrite_config,
            cancellation_checker=cancellation_checker,
        )

        return {"draft": report}

    elif action.type == ActionType.CHECK_QUALITY:
        # Extract quality issues from draft
        if state.draft:
            issues = list(state.draft.quality_issues) if state.draft.quality_issues else []
            return {"quality_issues": issues}
        return {"quality_issues": []}

    elif action.type == ActionType.REVISE_DRAFT:
        # For Phase 1, we don't actually revise - just mark as revised
        # Future phases will implement actual revision logic
        return {"revised": True}

    elif action.type == ActionType.FINALIZE:
        return {"finalized": True}

    elif action.type == ActionType.ABORT:
        return {"aborted": True}

    else:
        return {}


def update_state(
    state: InternalState,
    action: InternalAction,
    result: dict[str, Any],
) -> InternalState:
    """Update agent state based on action result."""
    new_agent_state = state.agent_state
    new_stage = state.stage
    new_draft = state.draft

    if action.type == ActionType.GENERATE_DRAFT:
        new_draft = result.get("draft")
        new_stage = AgentStage.DRAFT
        new_agent_state = replace(
            new_agent_state,
            draft_text=new_draft.rewritten_text if new_draft else None,
            current_stage=_map_stage_to_current_stage(new_stage),
        )

    elif action.type == ActionType.CHECK_QUALITY:
        quality_issues = result.get("quality_issues", [])
        new_stage = AgentStage.QUALITY_CHECK
        new_agent_state = replace(
            new_agent_state,
            quality_issues=quality_issues,
            current_stage=_map_stage_to_current_stage(new_stage),
        )

    elif action.type == ActionType.REVISE_DRAFT:
        new_stage = AgentStage.REVISION
        new_agent_state = replace(
            new_agent_state,
            retry_count=new_agent_state.retry_count + 1,
            current_stage=_map_stage_to_current_stage(new_stage),
        )

    elif action.type == ActionType.FINALIZE:
        new_stage = AgentStage.DONE
        new_agent_state = replace(
            new_agent_state,
            current_stage=_map_stage_to_current_stage(new_stage),
        )

    elif action.type == ActionType.ABORT:
        new_stage = AgentStage.FAILED
        new_agent_state = replace(
            new_agent_state,
            current_stage=_map_stage_to_current_stage(new_stage),
        )

    return InternalState(
        agent_state=new_agent_state,
        stage=new_stage,
        draft=new_draft,
    )


def handle_error(
    state: InternalState,
    error: Exception,
    attempt: int = 0
) -> tuple[InternalState, bool, float]:
    """Handle execution error and update state.

    Phase 2: Added error classification and retry logic.

    Args:
        state: Current internal state
        error: The exception that occurred
        attempt: Current retry attempt (0-indexed)

    Returns:
        Tuple of (new_state, should_retry, retry_delay)
    """
    classification = classify_error(error)
    should_retry_flag, retry_delay = should_retry(error, attempt, classification)

    logger.warning(
        "Agent action error",
        extra={
            "error": str(error),
            "error_type": type(error).__name__,
            "category": classification.category.value,
            "retry_strategy": classification.retry_strategy.value,
            "should_retry": should_retry_flag,
            "retry_delay": retry_delay,
            "attempt": attempt,
        }
    )

    new_error_history = state.agent_state.error_history + [
        {
            "error": str(error),
            "type": type(error).__name__,
            "stage": state.stage.value,
            "category": classification.category.value,
            "retry_strategy": classification.retry_strategy.value,
            "attempt": attempt,
        }
    ]

    new_agent_state = replace(
        state.agent_state,
        error_history=new_error_history,
    )

    new_stage = state.stage
    # Fail after 3 errors OR if error is permanent
    from app.agents.error_recovery import ErrorCategory
    if len(new_error_history) >= 3 or classification.category == ErrorCategory.PERMANENT:
        new_stage = AgentStage.FAILED
        new_agent_state = replace(
            new_agent_state,
            current_stage=_map_stage_to_current_stage(new_stage),
        )
        should_retry_flag = False

    new_state = InternalState(
        agent_state=new_agent_state,
        stage=new_stage,
        draft=state.draft,
    )

    return new_state, should_retry_flag, retry_delay


def build_report(state: InternalState) -> LoopReport:
    """Build final loop execution report."""
    return LoopReport(
        success=(state.stage == AgentStage.DONE),
        iterations=state.agent_state.retry_count + 1,
        final_stage=state.stage,
        writer_report=state.draft,
        error_message=state.agent_state.error_history[-1]["error"] if state.agent_state.error_history else None,
    )


async def run_agent_loop(
    agent: Any,
    material: MaterialPackage,
    rewrite_focus: str | None = None,
    rewrite_style: str | None = None,
    rewrite_config: dict[str, object] | None = None,
    skill_config: Any = None,
    llm_call_fn: Any = None,
    cancellation_checker: Any = None,
    max_iterations: int = 10,
) -> WriterRunReport:
    """Run agent loop: observe → decide → act → check.

    Phase 3: Added checkpoint persistence and execution trace.

    Args:
        agent: WriterAgent instance
        material: Input material package
        rewrite_focus: Optional rewrite focus prompt
        rewrite_style: Rewrite style (speech_verbatim, article_longform, etc.)
        rewrite_config: Optional rewrite configuration
        skill_config: Optional skill configuration
        llm_call_fn: Optional LLM call function for refiner
        cancellation_checker: Optional cancellation checker
        max_iterations: Maximum loop iterations

    Returns:
        WriterRunReport with execution results
    """
    # Initialize managers
    checkpoint_manager = CheckpointManager()
    trace_manager = TraceManager()
    tool_registry = create_default_registry(material.source_text)

    # Initialize state
    job_id = str(uuid.uuid4())
    agent_state = AgentState(
        job_id=job_id,
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

    # Start trace
    trace_manager.start_trace(job_id)

    logger.info(
        "Agent loop starting",
        extra={"job_id": job_id, "stage": state.stage.value}
    )

    # Main loop
    for i in range(max_iterations):
        iteration_start = datetime.now()

        # 1. Observe
        logger.info(
            "Agent loop iteration",
            extra={
                "job_id": job_id,
                "iteration": i,
                "stage": state.stage.value,
                "retry_count": state.agent_state.retry_count,
            }
        )

        # 2. Decide
        action = decide_next_action(state, rewrite_focus, rewrite_style)
        logger.info(
            "Agent action decided",
            extra={
                "job_id": job_id,
                "action_type": action.type.value,
                "reason": action.reason,
            }
        )

        # 3. Act (with retry logic)
        action_attempt = 0
        max_action_retries = 3
        result = None
        error_msg = None

        while action_attempt < max_action_retries:
            try:
                result = execute_action(
                    agent, action, state,
                    skill_config=skill_config,
                    rewrite_config=rewrite_config,
                    llm_call_fn=llm_call_fn,
                    cancellation_checker=cancellation_checker,
                    tool_registry=tool_registry,
                )
                state = update_state(state, action, result)
                break  # Success, exit retry loop

            except Exception as exc:
                error_msg = str(exc)
                logger.error(
                    "Agent action failed",
                    extra={
                        "job_id": job_id,
                        "action_type": action.type.value,
                        "error": error_msg,
                        "attempt": action_attempt,
                    },
                    exc_info=True,
                )

                new_state, should_retry_flag, retry_delay = handle_error(
                    state, exc, action_attempt
                )
                state = new_state

                if not should_retry_flag:
                    break  # Don't retry, exit loop

                action_attempt += 1
                if action_attempt < max_action_retries and retry_delay > 0:
                    logger.info(
                        f"Retrying action after {retry_delay:.1f}s delay",
                        extra={
                            "job_id": job_id,
                            "attempt": action_attempt,
                        }
                    )
                    time.sleep(retry_delay)

        # Record iteration trace
        iteration_end = datetime.now()
        duration_ms = int((iteration_end - iteration_start).total_seconds() * 1000)

        iteration_trace = IterationTrace(
            iteration=i,
            timestamp=iteration_start.isoformat(),
            stage=state.stage.value,
            action_type=action.type.value,
            action_reason=action.reason,
            action_params=action.params,
            result=result,
            error=error_msg,
            duration_ms=duration_ms,
        )
        trace_manager.add_iteration(job_id, iteration_trace)

        # Save checkpoint
        try:
            checkpoint = create_checkpoint(
                job_id=job_id,
                iteration=i,
                stage=state.stage.value,
                agent_state=asdict(state.agent_state),
                last_action={
                    "type": action.type.value,
                    "reason": action.reason,
                    "params": action.params,
                },
                last_result=result,
                draft_text=state.draft.rewritten_text if state.draft else None,
            )
            checkpoint_manager.save(checkpoint)
        except Exception as e:
            logger.warning(
                "Failed to save checkpoint",
                extra={"job_id": job_id, "error": str(e)}
            )

        # 4. Check
        if state.stage in (AgentStage.DONE, AgentStage.FAILED):
            break

    # Build final report
    loop_report = build_report(state)

    # End trace
    trace_manager.end_trace(
        job_id=job_id,
        final_stage=loop_report.final_stage.value,
        success=loop_report.success,
        error_message=loop_report.error_message,
    )
    trace_manager.save(job_id)

    # Clean up checkpoint (success or failure)
    if state.stage in (AgentStage.DONE, AgentStage.FAILED):
        checkpoint_manager.delete(job_id)

    logger.info(
        "Agent loop completed",
        extra={
            "job_id": job_id,
            "success": loop_report.success,
            "iterations": loop_report.iterations,
            "final_stage": loop_report.final_stage.value,
        }
    )

    if not loop_report.success:
        raise RuntimeError(f"Agent loop failed: {loop_report.error_message}")

    if not loop_report.writer_report:
        raise RuntimeError("Agent loop completed but no report generated")

    return loop_report.writer_report
