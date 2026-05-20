# Translation Writing Agent V1 Plan

This document is the detailed execution plan for the business-focused agent-like rewrite loop.
The backlog and status tracker remains in [../TODO.md](../TODO.md).

## Summary

- Goal: make the existing `article_longform` path more agent-like and more useful, not build a generic agent platform.
- Primary success criteria: fewer hallucinations, fewer missing facts, fewer ineffective revision rounds, and more stable latepost-style output.
- Scope: backend-only V1. `speech_verbatim` stays as-is. No multi-agent orchestration. No open-ended tool calling. No trace UI.

## Design Decisions

- Keep the production entrypoint in `backend/app/services/writer_agent_service.py` and `backend/app/services/rewrite_loop_executor.py`.
- Treat any experimental research helpers as non-production, and keep the shipping path in the main services layer.
- Favor evidence-first control flow over free-form generation.
- Use program-controlled tools only. Do not let the model autonomously choose tools in V1.
- Keep checkpoint-based recovery out of V1 unless quality gains are already proven.

## Implementation Changes

### 1. Build a baseline before changing behavior

- Add fixed sample fixtures for at least four classes of longform inputs:
  - number/time-heavy transcripts
  - multi-speaker interviews
  - opinionated but loosely structured transcripts
  - longform latepost-style target articles
- For each sample, define the expected facts that must survive rewrite, the hallucination cases that must not appear, and the expected revision outcome.
- Measure the current loop before making changes:
  - fact coverage rate
  - missing fact count
  - hard issue count
  - soft issue count
  - revision rounds
  - final recommended action

### 2. Make the main loop evidence-driven

- Expand the current stage model from `outline -> draft -> validate -> patch|expand -> stop` into:
  - `plan`
  - `collect_evidence`
  - `outline`
  - `draft`
  - `validate`
  - `re_ground`
  - `patch`
  - `expand`
  - `finalize`
  - `fail`
- `plan` prepares the goal, style constraints, length guidance, and budget snapshot without calling the model.
- `collect_evidence` gathers the facts and excerpts the draft will be allowed to rely on.
- `re_ground` is the new action for when the draft is structurally acceptable but fact grounding is weak.
- `patch` is only for local fixes.
- `expand` is only for missing coverage or insufficient density.
- `finalize` is only for a passed validation state or an explicit stop condition.

### 3. Add a lightweight evidence bundle

- Define a small evidence bundle with:
  - source excerpt hits
  - required fact ids
  - covered fact ids
  - missing fact ids
  - fact snippets
  - grounding warnings
- Reuse the existing detail ledger and topic ledger as the fact source.
- Reuse coverage analysis for covered vs missing facts.
- Keep the structure small enough to live inside the existing loop snapshot and session history payloads.

### 4. Upgrade the planner

- Change `backend/app/services/rewrite_loop_planner.py` from direct `if/else` mapping to a real decision policy.
- Planner inputs:
  - current stage
  - validation report
  - evidence bundle
  - remaining rounds
  - token budget
  - recent action history
  - per-action retry counts
- Planner outputs:
  - action kind
  - reason
  - expected outcome
  - fallback action
  - retryable flag
- Decision rules:
  - no evidence, collect evidence first
  - no outline, outline first
  - no draft, draft first
  - grounding failures, `re_ground` first
  - structural failures, `patch`
  - coverage or length gaps, `expand`
  - repeated no-gain revisions, stop or fail
  - validation pass, finalize

### 5. Split validation into grounding and writing signals

- Extend `backend/app/services/rewrite_loop_validator.py` so it separates:
  - grounding failures
  - writing failures
- Grounding failures cover factual mismatch, missing facts, number errors, and unsupported expansion.
- Writing failures cover structure, perspective, repetition, and weak readability.
- `next_recommended_action` should be derived from these categories rather than a single flat issue list.
- Keep the metrics explicit so the baseline comparison is measurable.

### 6. Use tools in a controlled way

- Reuse the controlled tool ideas from the prior research loop if needed, but keep the production path deterministic.
- `search_transcript` only in evidence collection and re-grounding.
- `validate_fact` only in validation or grounding recovery.
- `calculate` only for ratio and duration checks.
- Do not expose open-ended tool choice to the model in V1.

### 7. Keep prompts narrow and stage-specific

- The outline prompt should explain the target, required facts, and template routing.
- The draft prompt should only write a first version from the evidence bundle and outline.
- The patch prompt should only repair named failures.
- The expand prompt should only add missing facts or density.
- The re-ground prompt should only recover evidence, not produce a new article.

### 8. Keep trace and session history aligned

- Keep the existing response shape compatible.
- Expand `loop_state_snapshot` to include:
  - current stage
  - goal snapshot
  - evidence summary
  - validation summary
  - recent trace preview
  - budget snapshot
  - failure reason
- Keep `writer_trace_id`, `last_action`, `budget_usage`, `failure_stage`, and `next_recommended_action`.
- Continue writing the result into session history, but make the stored payload reflect the new stage model.

### 9. Explicitly defer these items

- Multi-agent debate or planner-worker splitting.
- Open-ended function calling.
- Full checkpoint resume in V1.
- Trace UI work.
- Reworking `speech_verbatim`.
- Replacing the current web product flow.

## Test Plan

- Unit tests:
  - planner branch selection across every new stage
  - validator classification into grounding vs writing issues
  - evidence bundle construction and fact coverage
  - no-gain plateau handling
- Integration tests:
  - happy-path longform rewrite
  - missing facts leading to `re_ground` before `patch`
  - coverage gaps leading to `expand`
  - repeated no-gain revisions stopping correctly
  - session history persistence of the expanded loop snapshot
- Regression tests:
  - `speech_verbatim` remains unchanged
  - latepost routing still works
  - current API response compatibility is preserved

## Acceptance Criteria

- When the rewrite is missing facts, the loop re-checks evidence instead of blindly polishing text.
- On the fixed sample set, the new loop improves fact coverage and reduces missing facts relative to the baseline.
- The loop can explain its final action through the stored snapshot and history payload.
- Existing non-agent behavior continues to work.
- If the baseline does not show quality gains, do not enable the new behavior by default.

## Execution Order

1. Add the sample fixtures and baseline measurements.
2. Extend the state and validation data structures.
3. Implement the evidence bundle and `re_ground` action.
4. Upgrade the planner rules.
5. Adjust executor prompts and stage flow.
6. Align response payloads and session history storage.
7. Add unit and integration tests.
8. Re-run the baseline comparison and decide whether to default-enable.

## Assumptions

- V1 stays backend-only.
- The main business goal is better rewrite quality, not a complete agent framework.
- `USE_AGENT_LOOP` can remain a guarded switch until the new behavior proves better.
- If a reusable experimental helper does not fit the mainline, duplicating the small amount of logic is acceptable.
