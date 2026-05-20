# ARCHITECTURE

## System Shape

- **Frontend**: Next.js Web workspace (single active UI)
- **Backend**: FastAPI API and deterministic ingest pipeline
- **Writing layer**: `WriterAgent` inside backend services
- **Storage**: local file persistence for session history and caches

## Pipeline Split

### 1) Deterministic Material Pipeline (non-agent)

`/api/jobs/run` orchestrates:

1. video inspect
2. source fetch
   - manual captions first
   - auto captions second
   - audio fallback third
3. transcription (when audio source)
4. session persistence / content-context creation

`material_transcript` cache stores transcript artifacts by `video/source/language` fingerprint to reduce repeated work.
The deterministic job pipeline stops at persisted transcript context; Chinese article generation starts in `/api/content-rewrite`.

### 2) Writing Pipeline (single-agent)

`/api/content-rewrite` delegates to `WriterAgent`. The agent picks a path based on `rewrite_style`:

**`speech_verbatim` (default)** — preserve the original speaker's voice:

1. extract a `DetailLedger` from the source (numbers, dates, quotes, named entities, turn/conclusion phrases, key sentences)
2. generate the draft in one pass with the ledger pinned in the prompt
3. run a coverage check against the ledger's hard items (`preserve_exact=True`)
4. if any hard item is missing, run a single targeted patch that only fills in the missing details
5. surface remaining gaps as `detail_coverage_issues` so the UI can offer a one-click "patch again" action

**`article_longform`** — explicit long-form magazine style (legacy path):

1. resolve `ArticleSpec` (length and section budget)
2. generate outline/plan
3. generate draft
4. validate draft against the spec
5. revise once if validation fails

The long-form reference bundle is vendored in the repo under `writer-skill/latepost/references/` and is preferred before the home-directory `~/.hermes/skills/creative/lastpost-skill` fallback. This keeps the evaluation harness and article routing reproducible on a fresh clone.
The automatic long-form template router is intentionally narrow: it auto-routes only interview / product review / infra-model-platform material, uses `01_big_company_war` only as a strategic fallback when explicit organizational signals appear, and otherwise falls back to the neutral one-page article template.

External API response remains compatible. Existing fields (`rewritten_text`, `provider`, `model`, `quality_issues`) are unchanged. `detail_coverage_issues` is an additive field; old clients can ignore it.

## Runtime Operations

- Health: `GET /health`
- Queue status: `GET /api/jobs/{job_id}`
- Queue cancel: `POST /api/jobs/{job_id}/cancel`
- Provider connectivity: `POST /api/provider/test-connection`
- Log export: `GET /api/system/export-logs`

## Legacy Boundary

The old PyQt desktop path has been removed from this checkout.
The shipping path stays in the service-layer rewrite loop and the single `WriterAgent` flow.
