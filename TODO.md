# TODO

This file tracks the current development backlog for the Translation Writing Workbench.

It is intentionally scoped to the real codebase in this repository.
It does not assume auth, cloud deployment, mobile, or a generic multi-agent platform.

## Current Product Loop

Current target loop:

1. Input YouTube URL or local audio upload
2. Build `content_context_id` from deterministic ingest
   (`inspect -> captions/audio -> transcribe -> persist`)
3. Run `WriterAgent` in the user's selected `rewrite_style` against the persisted source text:
   - default `speech_verbatim`: `DetailLedger -> draft -> coverage check -> single patch for missing hard items`
   - explicit `article_longform`: legacy `resolve ArticleSpec -> outline -> draft -> validate -> revise once`
4. Surface remaining gaps as `detail_coverage_issues` for an optional "patch again" action
5. Continue revision chat
6. Export article

Contract chain:

`URL / upload -> content_context_id -> WriterAgent (rewrite_style) -> ArticleDraft -> Revision Chat -> Export`

## Review Follow-ups

These items came out of the latest repo review and are not yet fully closed in code or docs.

- [ ] Add a first-class media ingest abstraction so YouTube URL, uploaded audio, and future subtitle/transcript files share the same source contract.
- [ ] Extend the current upload fallback beyond audio so local subtitle / transcript files can also be ingested when YouTube access is blocked.
- [x] Expose the existing runtime checks in a user-facing preflight/doctor flow so cookies, yt-dlp, JS runtime, backend health, and writable tmp are visible before a long run starts.
- [x] Make job cancellation and stage timeout propagation kill child subprocesses and long-running fetches end-to-end.
- [x] Tighten YouTube error classification and user guidance for `PO_TOKEN_REQUIRED`, `COOKIE_REQUIRED`, `COOKIE_STALE`, `YOUTUBE_BOT_CHECK`, `VIDEO_REGION_BLOCKED`, `VIDEO_UNAVAILABLE`, and `YOUTUBE_429`.
- [x] Add frontend automated tests for history restore, settings persistence, and rewrite/chat request races.
- [x] Refresh README, product-contract, architecture, CONTRIBUTING, and backlog docs so they match the active ingest + rewrite flow and the new fallback behavior.
- [ ] Add a runtime supervisor / launcher boundary for the future macOS wrapper.

## Mainline Acceptance

These are the shipping gates for the current product path. They do not depend on the deleted experimental branch.

- [ ] `YouTube URL -> content_context_id -> WriterAgent -> article draft -> revision chat -> export` runs end to end.
- [ ] Local audio upload uses the same mainline path and can be reopened from history.
- [ ] YouTube failures surface structured diagnostics and an explicit fallback action.
- [ ] Rewrite failures and detail-patch failures keep the user on the page with a retry path.
- [ ] History reopen restores the usable article context, not just the source metadata.
- [ ] Backend tests, frontend lint, and frontend build stay green.

### Frontend Acceptance

These are the user-visible checks that must hold on the web UI before the mainline can be treated as stable.

- [x] `检查环境` CTA opens a real preflight/doctor flow, not just the settings panel shell.
- [x] Settings preflight checks both local runtime readiness and the currently selected provider/model/API key, then feeds that result back into submit gating.
- [ ] Preflight, history, and failure states show structured diagnostics with `error_code`, `retryable`, and a concrete recovery action instead of a single generic string.
- [ ] Reopening a session restores the historical settings semantics, including `provider`, `model`, and `rewriteStyle`, so retry/continue actions use the original session context.
- [ ] Reopening a session preserves `detailCoverageIssues`, failure state, and patch eligibility so the user can see what was still missing.
- [ ] The result page shows the original transcript/material alongside the rewrite output and chat so users can verify source fidelity and debug bad rewrites.

Detailed execution plan: [docs/AGENT_V1_PLAN.md](docs/AGENT_V1_PLAN.md)
This file keeps backlog/status. The linked plan file keeps the step-by-step implementation detail.

## Test Status

- [x] `backend/tests/test_jobs_run.py` is green on the current checkout; the old translation-stage cleanup note is stale.
- [x] `backend/tests/test_writer_agent.py::test_writer_agent_speech_verbatim_rejects_truncated_patch_output` already uses Chinese source text and passes.
- [x] Frontend automated tests now cover history restore, settings persistence, and rewrite/chat request races.

## Web UI Development Guide

This guide is the design contract for the two web pages in this repository.
The target is a web-first, ChatGPT-like workspace that later becomes the base for the client wrapper.

### Shared layout rules

- Use one left sidebar for history and one central working area.
- Keep the sidebar and main content visually aligned between the entry page and the result page.
- Do not add avatars, timestamps, or user info to the history list.
- Do not duplicate the same task bar or shadow card in the same page.
- Keep controls flat, compact, and aligned on a single row when they belong to the same action group.
- Keep the settings entry in the lower-left corner.
- Keep the history toggle and new-chat action in the same top row of the sidebar.
- Do not show the raw YouTube URL again after processing starts.

### Page 1: Entry page

This page is the first landing state.

- Left sidebar:
  - Show only conversation/history entries.
  - Each history item should be compact and icon-free.
  - Use the same sidebar shell style as the second page.
  - The history drawer should expand and collapse with the same toggle button.
  - The new-chat button should use a simple pencil/compose icon.
- Main area:
  - Show the product title only once.
  - Show one flat URL composer centered in the page.
  - Show one start button only.
  - Keep the composer visually simple, like a search bar or Google query bar.
  - Do not add a second stacked task card, extra subtitle copy, or decorative duplicate panels.
- Behavior:
  - Clicking new chat clears the input and closes any open drawer.
  - Clicking history opens the same sidebar drawer.
  - Clicking settings opens the settings panel from the lower-left corner.

### Page 2: Result page

This page is the post-run workspace.

- Left sidebar:
  - Reuse the same sidebar structure as Page 1.
  - Keep it aligned to the same width and padding as the entry page.
  - Keep the top-row toggle and new-chat controls in the same placement.
  - Keep settings in the lower-left corner.
- Main area:
  - Use one large central task area for the article draft and follow-up discussion.
  - The article draft and content Q&A should live in the same conversation-style container.
  - Remove the assistant icon and any redundant helper decorations.
  - Do not split the article draft and chat into separate right-side panels.
  - Copy and export actions should sit near the content header and align with the text block.
  - The output should read like direct Chinese content, not like a tool dashboard.
- Behavior:
  - The result page should feel like a single working document.
  - The input for follow-up questions should attach to the same pane as the article result.
  - The page should not re-show the YouTube URL as a visible content block.

### Acceptance checks

- Page 1 and Page 2 use the same sidebar geometry and spacing.
- The sidebar toggle and new-chat button do not overlap.
- No duplicate shadow cards exist in either page.
- No timestamps, avatars, or user badges are shown in history.
- No extra subtitle appears under the product title.
- No secondary right sidebar appears on the result page.
- Copy and export controls are aligned with the main content header.
- Article draft and chat content share one main result surface.

## Done

- [x] Local FastAPI backend for inspect -> fetch source -> transcribe -> persist content context
- [x] Native macOS desktop app for local testing
- [x] Desktop app auto-starts backend when needed
- [x] Rewrite-first desktop result area
- [x] Desktop copy/export for rewritten output
- [x] `POST /api/content-rewrite` API
- [x] Desktop writing-style selection
- [x] Full skill prompt injection via `{{transcript}}` placeholder
- [x] Content chat as a secondary post-rewrite action
- [x] README updated to match the current rewrite-first workflow
- [x] Preserve raw rewrite text separately from rendered Markdown for copy/export/history replay
- [x] Make session-history writes merge atomically with per-session locking
- [x] Freeze PyQt desktop client and move it to `archive/desktop-legacy`
- [x] Make Web the only active product UI
- [x] Add `docs/PRODUCT_CONTRACT.md` and `docs/ARCHITECTURE.md`
- [x] Add transcript material cache in job pipeline (`video/source/language` fingerprint)
- [x] Switch `/api/content-rewrite` internals to single `WriterAgent`
- [x] Add `POST /api/jobs/{job_id}/cancel`
- [x] Add `POST /api/provider/test-connection`
- [x] Add `GET /api/system/export-logs`

## P0: Next Must-Fix

- [x] Add API authentication hook (`API_AUTH_TOKEN`) and request-level rate limiting
- [x] Harden session history key normalization to block path traversal
- [x] Centralize runtime settings with one `get_settings()` entry point
- [x] Add request_id-aware HTTP middleware and structured request logs
- [x] Add `/readyz` and `/livez` health endpoints
- [x] Persist job queue records to SQLite so status survives service restart
- [x] Replace string-based `runtime_deps.resolve` lookups with explicit FastAPI dependencies
- [x] Replace thread-only stage timeout with hard-killable process timeout for transcribe stage
- [x] Add yt-dlp subprocess timeout for audio download and subtitle fallback
- [x] Enforce `MAX_VIDEO_DURATION_SEC`, `MAX_AUDIO_BYTES`, `MAX_TRANSCRIPT_CHARS`, and `MAX_TRANSLATION_SEGMENTS` at real job/transcription boundaries
- [x] Keep hard-limit failures mapped to readable API/job errors
- [x] Move in-memory execution queue to durable worker queue (SQLite-backed claim/lease with heartbeat; Redis/Postgres remains future work)
- [x] Remove API key persistence from frontend localStorage
- [x] Tighten production CORS profile and enforce auth in deployment profile
- [x] Add user/account layer and per-user quota model before multi-user rollout

- [x] Make rewrite style behavior fully consistent between desktop prompt injection and backend fallback behavior
- [x] Decide rewrite source of truth:
  - full prompt containing `{{transcript}}` wins
  - otherwise backend-managed rewrite references and routing win
- [x] Add one integration test for the full desktop-facing rewrite path:
  - rewrite output generated
  - selected prompt passed through
  - rewritten Chinese returned
- [x] Add better rewrite error reporting in backend responses:
  - missing skill prompt
  - invalid placeholder usage
  - provider failure
  - empty rewrite output
- [x] Document the current writing-style format expected by desktop-imported prompt files

## P1: Core Product Improvements

- [x] Persist local session history
  - URL
  - transcript source
  - rewrite result
  - chat turns
- [x] Add local history sidebar in desktop app
- [x] Add search over local history
- [x] Add “reopen previous run” flow from history
- [x] Add explicit result sections in saved data:
  - raw transcript
  - rewritten Chinese
  - chat follow-ups
- [x] Add richer export formats from desktop app
  - current: md / txt / html / json / docx
  - next: publisher-friendly rich text polish
- [x] Add export naming strategy based on video title or first heading

## P1: Writing Quality Improvements

- [x] Define one stable built-in default writing style for users who do not import prompts
- [x] Add prompt validation before running rewrite:
  - blocks empty prompt bodies
  - blocks obviously broken placeholders
  - blocks full-prompt style files that omit `{{transcript}}`
- [x] Add rewrite quality checks after generation:
  - empty sections
  - repeated paragraphs
  - obvious hallucination markers
  - malformed headings or broken formatting
- [x] Add one-click “rewrite again” action with same source and prompt
- [x] Add one-click “summarize / explain / polish / reframe” chat shortcuts

## P1: Pipeline Robustness

- [x] Improve long-video progress visibility in desktop app
- [x] Add clearer distinction between:
  - captions path
  - audio + whisper path
- [x] Persist intermediate artifacts for debugging:
  - inspect metadata
  - fetched source mode
  - transcript text
  - rewrite output
- [x] Add a lightweight local run log view inside desktop app
- [x] Normalize user-facing errors for:
  - yt-dlp cookie failures
  - model auth failures
  - upstream disconnects
  - whisper runtime problems

## P2: UX Cleanup

- [x] Reduce settings friction in desktop app:
  - remember last provider
  - remember last model
  - remember last selected style
- [x] Add “open exported file location” action after export
- [x] Improve empty-state copy for rewrite/chat areas
- [x] Add shortcut keys for:
  - run
  - copy result
  - export result
  - send chat
- [x] Add explicit busy state when rewrite is running

## P2: Frontend Web Path

- [x] Web is the only active product UI
- [x] Remove old translation-only wording from entry and sidebar
- [x] Reposition cookie hints as advanced fallback only
- [x] Remove unreferenced legacy frontend components and dead helper exports
- [x] Promote article draft as the only primary result block (transcript/source details)

## MVP manual smoke (repeat before releases)

See [`CONTRIBUTING.md`](CONTRIBUTING.md) section **MVP manual smoke checklist**.

## Writing Skill Evaluation

- [x] Add a fixed sample set and CLI evaluation harness for:
  - `speech_verbatim`
  - `article_longform`
  - `{{transcript}}` full-prompt baseline
- [x] Emit JSON + Markdown reports with detail coverage, ordering, third-person, compression, and AI-slop signals
- [x] Use the report to keep the current prompt routing structure narrow and shrink `lastpost-skill` for `article_longform` fallback only

## Deferred / Out Of Scope For Now

- [ ] Auth and user accounts
- [ ] Cloud deployment work
- [ ] Mobile / Expo client
- [ ] Generic multi-agent orchestration platform
- [ ] Database-backed run queue (beyond current SQLite job store + JSON session cache)
- [ ] Multi-language expansion beyond current Chinese-first writing flow
- [ ] Broad SaaS productization work unrelated to the current local app
- [ ] Multi-replica queue coordination (`UPDATE … RETURNING`), Redis / cloud queues
- [ ] Billing (Stripe), quotas per user, referral programs
- [ ] SSO / RBAC / full audit logs for enterprise
- [ ] Content knowledge graphs, collaborative filtering, semantic translation dedupe caches
- [ ] Third-party plugin market and public developer APIs
- [ ] Major refactor split of `translation_service.py` until driven by concrete incidents

## Decisions

- Writing styles are treated as validated skill packages in the web app, while backend fallback routing remains the source of truth when no full prompt is provided.
- Imported prompts are validated before use, not treated as raw unstructured text.
- Chat history is stored per rewritten article / `content_context_id`, not as a global thread list.
- Export targets an article package with metadata when the format supports it, while Markdown / TXT can still be body-first exports.
- Cookie-based YouTube auth is an advanced fallback, not a default input path.
- `WriterAgent` is a single-agent writing pipeline, not a multi-agent framework. `speech_verbatim` is the default mode and uses a `DetailLedger`-driven coverage loop instead of length validation; `article_longform` is the only mode that still uses `ArticleSpec` and the outline/draft/validate/revise loop. The lastpost-skill reference templates only feed `article_longform`.
