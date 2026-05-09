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
4. translation
5. session persistence

`material_transcript` cache stores transcript artifacts by `video/source/language` fingerprint to reduce repeated work.

### 2) Writing Pipeline (single-agent)

`/api/content-rewrite` delegates to `WriterAgent`:

1. resolve `ArticleSpec`
2. generate outline/plan
3. generate draft
4. validate draft
5. revise once if validation fails

External API response remains compatible (`rewritten_text`, `provider`, `model`, `quality_issues`).

## Runtime Operations

- Health: `GET /health`
- Queue status: `GET /api/jobs/{job_id}`
- Queue cancel: `POST /api/jobs/{job_id}/cancel`
- Provider connectivity: `POST /api/provider/test-connection`
- Log export: `GET /api/system/export-logs`

## Legacy Boundary

- PyQt desktop code moved to `archive/desktop-legacy`.
- No new feature work should target the legacy desktop path.
