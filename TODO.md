# TODO

This file tracks the current development backlog for the Translation Writing Workbench.

It is intentionally scoped to the real codebase in this repository.
It does not assume auth, cloud deployment, mobile, or a generic multi-agent platform.

## Current Product Loop

Current target loop:

1. Input YouTube URL
2. Inspect video
3. Fetch captions or audio
4. Transcribe when needed
5. Translate to Chinese
6. Rewrite into Chinese article output
7. Use chat for follow-up questions or local revisions
8. Copy or export result

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
  - Use one large central task area for translated content and follow-up discussion.
  - Translation output and content Q&A should live in the same conversation-style container.
  - Remove the assistant icon and any redundant helper decorations.
  - Do not split translation and chat into separate right-side panels.
  - Copy and export actions should sit near the content header and align with the text block.
  - The output should read like direct Chinese content, not like a tool dashboard.
- Behavior:
  - The result page should feel like a single working document.
  - The input for follow-up questions should attach to the same pane as the translation result.
  - The page should not re-show the YouTube URL as a visible content block.

### Acceptance checks

- Page 1 and Page 2 use the same sidebar geometry and spacing.
- The sidebar toggle and new-chat button do not overlap.
- No duplicate shadow cards exist in either page.
- No timestamps, avatars, or user badges are shown in history.
- No extra subtitle appears under the product title.
- No secondary right sidebar appears on the result page.
- Copy and export controls are aligned with the main content header.
- Translation output and chat content share one main result surface.

## Done

- [x] Local FastAPI backend for inspect -> fetch source -> transcribe -> translate
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

## P0: Next Must-Fix

- [x] Make rewrite style behavior fully consistent between desktop prompt injection and backend fallback behavior
- [x] Decide rewrite source of truth:
  - full prompt containing `{{transcript}}` wins
  - otherwise backend-managed rewrite references and routing win
- [x] Add one integration test for the full desktop-facing rewrite path:
  - translated text generated
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
  - translation result
  - rewritten result
  - chat turns
- [x] Add local history sidebar in desktop app
- [x] Add search over local history
- [x] Add “reopen previous run” flow from history
- [x] Add explicit result sections in saved data:
  - raw transcript
  - translated Chinese
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
  - translated text
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

- [x] Decide whether the web frontend remains:
  - a dev/debug surface
  - or a real user-facing interface
- [x] If kept, align web UI with the desktop rewrite-first workflow
- [x] Remove old translation-only wording from remaining frontend UI copy
- [x] Align web result panels with current desktop terminology

## Deferred / Out Of Scope For Now

- [ ] Auth and user accounts
- [ ] Cloud deployment work
- [ ] Mobile / Expo client
- [ ] Generic multi-agent orchestration platform
- [ ] Database-backed run queue
- [ ] Multi-language expansion beyond current Chinese-first writing flow
- [ ] Broad SaaS productization work unrelated to the current local app

## Decisions

- Writing styles are treated as validated skill packages in the desktop app, while backend fallback routing remains the source of truth when no full prompt is provided.
- Imported prompts are validated before use, not treated as raw unstructured text.
- Chat history is stored per rewritten article / `content_context_id`, not as a global thread list.
- Export targets an article package with metadata when the format supports it, while Markdown / TXT can still be body-first exports.
