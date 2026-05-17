# PRODUCT CONTRACT

## Product Positioning

Translation is a **link/source to Chinese article** workbench.

Primary product path:

`URL -> deterministic ingest -> content_context -> WriterAgent (speech_verbatim) -> ArticleDraft -> Revision Chat -> Export`

The default writing mode is `speech_verbatim`: it pins extracted facts (numbers, dates, names, quotes, turn/conclusion phrases) into a `DetailLedger`, generates the draft once, then runs a single coverage-driven patch when hard items are missing. The legacy `article_longform` mode (uses `ArticleSpec` length budgets and outline/draft/revise) is only used when the user explicitly selects it.

The long-form `latepost-skill` bundle is vendored in the repo under `writer-skill/latepost/references/` and is preferred before the home-directory fallback so the `article_longform` path stays reproducible across machines.
Within `article_longform`, automatic routing is intentionally narrow: it prioritizes interview / product review / infra-model-platform material, treats `01_big_company_war` as a narrow strategic fallback, and falls back to a neutral generic article template when no strong signal matches.

## Hard Boundaries

1. The ingest half is deterministic and tool-like:
   - inspect video
   - fetch captions first
   - fallback to audio + Whisper
   - persist transcript context for rewrite
2. The writing half is agent-shaped:
   - one `WriterAgent` only
   - no multi-agent orchestration in the mainline
   - `backend/app/agents/` stays experimental and off by default
3. Web is the only active product UI.
4. Cookies are not a default path:
   - default flow should work without cookie input
   - cookie is an advanced fallback for restricted videos

## API Compatibility Rules

- Keep `POST /api/jobs/run` stable.
- Keep `POST /api/content-rewrite` stable.
- Additive fields/endpoints are allowed; no breaking response shape changes in the mainline.

## Acceptance Markers

- User can generate article draft by pasting one link in Web.
- `content-rewrite` runs through `WriterAgent` internally and still returns compatible response fields.
- In restricted-video failures, UI/API copy explains cookie fallback as optional advanced recovery.
