# Translation Writing Workbench MVP

This repository contains a local macOS-first workbench for turning YouTube videos,
transcripts, and source material into rewritten Chinese article output.

The current product direction is:

- deterministic media pipeline for inspect -> fetch source -> transcribe -> translate
- single `WriterAgent` flow for article generation -> validation -> revise once
- follow-up revision chat for summary, explanation, and secondary edits
- Web UI as the only active product interface

Documentation map:

- [`docs/README.md`](docs/README.md)
- [`docs/PRODUCT_CONTRACT.md`](docs/PRODUCT_CONTRACT.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

Rewrite precedence is explicit:

1. If web or API sends a full writing prompt containing `{{transcript}}`, backend injects source text directly and uses that prompt as the source of truth.
2. Otherwise backend falls back to its managed rewrite references and routing logic.

## Project Structure

```text
.
|-- backend/
|   |-- app/
|   |   |-- main.py
|   |   |-- services/
|   |   |   |-- audio_download_service.py
|   |   |   |-- caption_service.py
|   |   |   |-- job_run_service.py
|   |   |   |-- translation_service.py
|   |   |   |-- transcription_service.py
|   |   |   |-- video_source_service.py
|   |   |   `-- yt_dlp_service.py
|   |   `-- youtube.py
|   |-- requirements.txt
|   |-- tests/
|   |   |-- test_fetch_source.py
|   |   |-- test_jobs_run.py
|   |   |-- test_translate.py
|   |   |-- test_transcribe.py
|   |   |-- test_video_inspect.py
|   |   `-- test_youtube.py
|   `-- uvicorn.cmd
|-- frontend/
|   |-- app/
|   |   |-- components/
|   |   |-- lib/
|   |   |-- globals.css
|   |   |-- layout.tsx
|   |   `-- page.tsx
|   |-- next-env.d.ts
|   |-- next.config.ts
|   |-- npm.cmd
|   |-- package-lock.json
|   |-- package.json
|   `-- tsconfig.json
|-- .env.example
`-- README.md
```

Local generated files created during setup or runtime, not source directories:

- `backend/.venv/`
- `frontend/node_modules/`
- `tmp/`

## Tech Stack

- Frontend: Next.js
- Backend: FastAPI
- Runtime: Node.js 20+, Python 3.11

## Local Prerequisites

- Python 3.11.9
- Node.js 20.19.4
- yt-dlp 2026.03.03 in `backend/.venv`
- Backend virtual environment created at `backend/.venv`
- Frontend dependencies installed in `frontend/node_modules`

## Environment Variables

Copy `.env.example` to `.env` if you want a local environment file.

Current local setup uses:

- `NEXT_PUBLIC_API_BASE_URL`: frontend backend base URL
- `DEEPSEEK_API_KEY`: required when the default translation provider is `deepseek`
- `TRANSLATION_PROVIDER`: default translation provider when request settings do not override it
- `WHISPER_MODEL`: local Whisper model name, for example `small`
- `WHISPER_DEVICE`: local Whisper device, default `cpu`
- `WHISPER_COMPUTE_TYPE`: local Whisper compute type, default `int8`
- `YTDLP_COOKIES_FROM_BROWSER`: optional browser cookies source for yt-dlp, for example `edge` or `chrome`
- `YTDLP_COOKIES_FILE`: optional cookies.txt path for yt-dlp
- `YTDLP_ENABLE_DEFAULT_COOKIES_FILE`: whether backend auto-loads repo `youtube-cookies.txt` (default `0`)
- `YTDLP_REMOTE_COMPONENTS`: optional `yt-dlp` remote components flag, for example `ejs:github`
- `API_AUTH_TOKEN`: optional API bearer token for `/api/*` routes
- `API_RATE_LIMIT_PER_MINUTE`: write-request rate limit per client IP
- `JOB_QUEUE_DB_PATH`: SQLite file path for persisted job records

## Local Whisper And Translation Keys

Audio transcription now runs locally through `faster-whisper`.

Translation can use either:

- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`

You can configure it in either of these ways:

macOS or Linux in the current terminal:

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
export TRANSLATION_PROVIDER="deepseek"
export WHISPER_MODEL="small"
```

Or create a project-level `.env` file from `.env.example`:

```bash
cp .env.example .env
```

Then edit `.env` and set:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
TRANSLATION_PROVIDER=deepseek
OPENAI_TRANSLATION_MODEL=gpt-4.1-mini
DEEPSEEK_TRANSLATION_MODEL=deepseek-chat
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
YTDLP_COOKIES_FROM_BROWSER=
YTDLP_COOKIES_FILE=
YTDLP_REMOTE_COMPONENTS=
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## yt-dlp Installation

The backend uses `yt-dlp` for video inspection and audio download.
Remote components are opt-in through `YTDLP_REMOTE_COMPONENTS`; leave it empty unless you explicitly need them.

Install backend dependencies inside the project virtual environment:

```bash
cd backend
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Install `ffmpeg` once on macOS if you have not already:

```bash
brew install ffmpeg
```

Optional verification:

```bash
cd backend
./.venv/bin/python -m yt_dlp --version
./.venv/bin/python -c "from faster_whisper import WhisperModel; print('whisper ok')"
```

No extra conversion tool is required at this stage. When audio is downloaded, the file keeps the audio-only format selected by `yt-dlp`, such as `.m4a` or `.webm`.

If YouTube returns `Sign in to confirm you're not a bot`, first retry the normal subtitle/audio pipeline. Only for restricted videos, configure one of these advanced fallbacks:

- `YTDLP_COOKIES_FROM_BROWSER=edge`
- `YTDLP_COOKIES_FROM_BROWSER=chrome`
- `YTDLP_COOKIES_FILE=C:\path\to\cookies.txt`

The backend forwards those settings to every `yt-dlp` metadata and audio request.

## Backend

### Run

```bash
cd backend
./.venv/bin/python -m uvicorn app.main:app --reload
```

Or from the project root:

```bash
./start-backend.sh
```

Run backend in background:

```bash
./start-backend.sh --daemon
```

### Test

Open [http://localhost:8000/health](http://localhost:8000/health)

Expected response:

```json
{"status":"ok"}
```

Parse endpoint:

```bash
curl -X POST http://localhost:8000/api/parse-youtube ^
  -H "Content-Type: application/json" ^
  -d "{\"url\":\"https://youtu.be/abc123xyz?t=12\"}"
```

Expected response:

```json
{"ok":true,"video_id":"abc123xyz","normalized_url":"https://www.youtube.com/watch?v=abc123xyz"}
```

Video inspect endpoint:

```bash
curl -X POST http://localhost:8000/api/video/inspect ^
  -H "Content-Type: application/json" ^
  -d "{\"url\":\"https://www.youtube.com/watch?v=BaW_jenozKc\"}"
```

Expected response shape:

```json
{
  "ok": true,
  "video_id": "BaW_jenozKc",
  "title": "youtube-dl test video",
  "duration_sec": 10,
  "uploader": "Philipp Hagemeister",
  "thumbnail": "https://...",
  "subtitles": ["en"],
  "automatic_captions": []
}
```

Fetch source endpoint:

```bash
curl -X POST http://localhost:8000/api/video/fetch-source ^
  -H "Content-Type: application/json" ^
  -d "{\"url\":\"https://www.youtube.com/watch?v=dQw4w9WgXcQ\"}"
```

Caption response:

```json
{
  "ok": true,
  "source_type": "captions",
  "language": "en",
  "text": "..."
}
```

Audio response:

```json
{
  "ok": true,
  "source_type": "audio",
  "audio_file_path": "tmp/xxxx.m4a"
}
```

Transcribe endpoint:

```bash
curl -X POST http://localhost:8000/api/transcribe ^
  -H "Content-Type: application/json" ^
  -d "{\"audio_file_path\":\"tmp/dQw4w9WgXcQ.webm\"}"
```

Expected response shape:

```json
{
  "ok": true,
  "language": "en",
  "text": "full transcript",
  "segments": [
    {
      "index": 0,
      "start": 0.0,
      "end": 5.2,
      "text": "Hello everyone..."
    }
  ]
}
```

Notes:

- The transcription request uses local `faster-whisper`, not a hosted API.
- The backend checks that the file exists before transcription.
- The first local transcription run may download the selected Whisper model.
- This MVP uses English transcription only.

Translate endpoint:

```bash
curl -X POST http://localhost:8000/api/translate ^
  -H "Content-Type: application/json" ^
  -d "{\"segments\":[{\"index\":0,\"start\":0.0,\"end\":5.2,\"text\":\"Hello everyone...\"}],\"translation_config\":{\"provider\":\"deepseek\",\"api_key\":\"your_deepseek_api_key\",\"base_url\":\"https://api.deepseek.com\",\"model\":\"deepseek-chat\"}}"
```

Expected response shape:

```json
{
  "ok": true,
  "translations": [
    {
      "index": 0,
      "start": 0.0,
      "end": 5.2,
      "source_text": "Hello everyone...",
      "translated_text": "\u5927\u5bb6\u597d\u2026\u2026"
    }
  ]
}
```

Translation prompt design:

- One provider request per segment, never a full-document translation.
- System instructions require Simplified Chinese, preserved proper nouns, no summary, no omission, and one-to-one segment alignment.
- The backend requests structured JSON with a strict schema so the API returns `translated_text` in a predictable format.
- Translation now supports `openai` and `deepseek`.
- Request-level translation settings can override the provider, API key, base URL, model, and extra headers.
- Audio transcription runs locally through `faster-whisper` in this MVP.

Submit async job endpoint:

```bash
curl -X POST http://localhost:8000/api/jobs/run ^
  -H "Content-Type: application/json" ^
  -d "{\"url\":\"https://www.youtube.com/watch?v=dQw4w9WgXcQ\"}"
```

Expected response shape:

```json
{
  "ok": true,
  "job_id": "3f7a1f1e9f5e4d56a1d0f4b7d1a4d2c3",
  "status": "queued",
  "progress_value": 0,
  "progress_text": "已加入队列"
}
```

Poll job status endpoint:

```bash
curl http://localhost:8000/api/jobs/3f7a1f1e9f5e4d56a1d0f4b7d1a4d2c3
```

When the job finishes, `done` responses include `result`, and `failed` responses include `error`.

Job orchestration notes:

- The backend parses and normalizes the YouTube URL first.
- Metadata and source selection share the same `yt-dlp` inspection payload, so the job does not inspect the same video twice.
- The pipeline prefers English captions. If captions are unavailable, it downloads audio to `tmp/`, transcribes in English, then translates to Simplified Chinese.
- The job request can include `translation_config` so the UI can switch between OpenAI and DeepSeek without editing backend files.
- `POST /api/jobs/run` submits the full metadata -> source -> transcript -> translation flow to an in-memory job queue and returns immediately with `202 Accepted`.
- `GET /api/jobs/{job_id}` polls job progress. `done` responses include `result`, and `failed` responses include `error`.
- The queue is in-memory and designed for local single-process development. Restarting the backend drops queued and running job state.

Run tests:

```bash
cd backend
./.venv/bin/python -m pytest
```

## Frontend

### Run

```bash
cd frontend
npm run dev
```

Or from the project root:

```bash
./start-frontend.sh
```

Run frontend in background:

```bash
./start-frontend.sh --daemon
```

Open [http://localhost:3000](http://localhost:3000)

### Start Both

From the project root:

```bash
./start-dev.sh
```

This starts FastAPI and Next.js in the background.

Check status:

```bash
./status-dev.sh
```

Stop both:

```bash
./stop-dev.sh
```

### Docker Compose

From project root:

```bash
cp .env.example .env
docker compose up --build
```

- frontend: [http://localhost:3000](http://localhost:3000)
- backend: [http://localhost:8000/health](http://localhost:8000/health)

### Desktop Legacy

The PyQt desktop client is frozen and deprecated.

- Legacy files moved to `archive/desktop-legacy/`
- New features are Web + FastAPI only
- Root `./start-desktop.sh` now exits with a deprecation message

Writing styles are local prompt files in `skills/`.

- Supported files: `*.md`, `*.txt`
- File name becomes the dropdown label in the web settings panel
- If a prompt contains `{{transcript}}`, backend treats it as a full prompt and injects the source text there
- If a prompt does not contain `{{transcript}}`, backend uses it as a style hint and falls back to managed rewrite references and routing

See [docs/writing_style_prompt_format.md](docs/writing_style_prompt_format.md) for the current format contract.

### Phase 8 UI

- The homepage now uses a minimal centered input layout inspired by notebook-style tools.
- The initial screen only shows the product title, a short description, one large input box, and one start button.
- A small built-in settings section lets you pick the translation provider and optionally override API key, base URL, model, and custom headers.
- The result area keeps four states visually distinct: ready, processing, completed, and failed.
- Successful runs can feed transcript and translation content into the rewrite pipeline.
- The web app is rewrite-first: the main result view prioritizes Chinese rewritten output, with `Content Chat` as a secondary follow-up layer.
- The web app includes a session history sidebar with search for reopening recent runs and reviewing saved rewrite/chat state.
- The web app preserves raw rewrite text separately from the rendered view so copy and export keep Markdown structure intact.
- The web app validates imported writing prompts before rewrite and clearly labels full prompts versus style hints.
- The web app includes a built-in default writing style, rewrite quality checks, one-click rewrite again, and chat shortcuts for summary / explanation / polish / reframe.
- The web app remembers the last provider, model, source mode, and writing style across launches.
- Export defaults now prefer the video title or the first rewritten heading when naming files.
- Export supports `docx`, `md`, `txt`, `html`, and `json`.
- Export can open the exported file location after saving.
- Runtime logs can be exported through `GET /api/system/export-logs`.
- Keyboard shortcuts cover run, copy, export, and send chat.
- Frontend structure is split into `app/components` and `app/lib` so the page, settings panel, status panel, and result panel are no longer coupled in one file.

## Local Development Flow

Recommended local loop:

1. Start backend on port `8000`.
2. Start frontend on port `3000`.
3. Enter a YouTube link.
4. Run deterministic ingest: inspect -> captions/audio -> transcribe -> translate.
5. Let `POST /api/content-rewrite` run through `WriterAgent` (`spec -> outline -> draft -> quality check -> revise once`).
6. Continue revision in chat and export the article.

Web frontend loop for component development:

1. Start backend on port `8000`.
2. Start frontend on port `3000`.
3. Open the frontend page.
4. Enter a YouTube link and complete the same inspect -> source -> transcribe -> translate -> rewrite flow.
5. Verify that rewrite output is available from the result panel.

## Current Phase Scope

- Includes `GET /health`
- Includes `POST /api/parse-youtube`
- Includes `POST /api/video/inspect`
- Includes `POST /api/video/fetch-source`
- Includes `POST /api/transcribe`
- Includes `POST /api/translate`
- Includes `POST /api/content-rewrite`
- Includes `POST /api/jobs/run`
- Includes `POST /api/jobs/{job_id}/cancel`
- Includes `POST /api/provider/test-connection`
- Includes `GET /api/system/export-logs`
- Uses an in-memory queue for async job runs and `GET /api/jobs/{job_id}` polling
- Supports `youtube.com/watch?v=...`
- Supports `youtu.be/...`
- Supports extra query parameters and normalizes the URL
- Returns `400` for invalid links
- Uses `yt-dlp` to inspect metadata without downloading audio
- Supports optional browser cookies or cookies.txt for `yt-dlp` as advanced fallback
- Prioritizes manual English captions, then automatic English captions, then audio-only download
- Downloads audio-only files into `tmp/`
- Transcribes local audio files through `faster-whisper`
- Translates transcript segments through the OpenAI responses API
- Translates transcript segments through either OpenAI or DeepSeek
- Submits the full metadata -> source -> transcript -> translation flow through the in-memory job queue
- Exposes `POST /api/content-rewrite` as a single `WriterAgent` writing layer on top of the translation pipeline
- Supports web-selected writing prompts / skills for rewrite requests
- Validates selected writing prompts before rewrite, blocking empty bodies and broken placeholders
- If the selected rewrite prompt contains `{{transcript}}`, backend injects source text into that prompt directly
- Falls back to backend-managed rewrite references and routing when no full skill prompt is provided
- Treats rewritten Chinese article text as the primary product result
- Preserves raw rewrite text separately from rendered Markdown for copy/export and history replay
- Provides post-generation `Content Chat` for follow-up questions, summary, explanation, and secondary edits
- Includes rewrite quality checks and a built-in default writing style for non-imported prompt users
- Supports one-click rewrite again from the current source text and prompt
- Provides chat shortcuts for summary, explanation, polish, and reframing
- Supports copy/export of rewrite output from the web workspace
- Supports DOCX export in addition to markdown, text, HTML, and JSON
- Supports opening the exported file location after save
- Includes backend/frontend runtime log export for debugging
- Persists local session history for the job run, rewrite result, and chat turns
- Persists intermediate debugging artifacts including inspect metadata, source mode, transcript text, and translated text
- Keeps session-history writes atomic per `content_context_id` so rewrite and chat updates do not clobber each other
- Exposes `GET /api/session-history` and `GET /api/session-history/{content_context_id}` for local history viewing and search-backed reopening
- Stores explicit saved sections for raw transcript, translated Chinese, rewritten Chinese, and chat follow-ups
- Remembers the last provider, model, source mode, and style selection in the web app
- Shows explicit busy state and clearer captions vs audio progress in the web app
- Normalizes user-facing errors for cookie, auth, upstream disconnect, and Whisper failures
- Reads `DEEPSEEK_API_KEY` and `TRANSLATION_PROVIDER` from environment variables or `.env`
- Reads `WHISPER_MODEL`, `WHISPER_DEVICE`, and `WHISPER_COMPUTE_TYPE` from environment variables or `.env`
- Rejects missing files before transcription
- Preserves per-segment timestamps and returns one-to-one aligned Chinese translations
- Returns subtitle and automatic caption language lists
- Returns a clear error when `yt-dlp` is not installed
- Includes a production Web frontend as the single active UI
- Includes frontend to backend full-job flow and content-rewrite flow
- Includes backend CORS for local development
- Does not include auth, database-backed persistence, or deployment

## Verification Notes

- Backend runtime verified successfully with local `/health` response.
- YouTube parsing and video inspection logic are covered by backend tests.
- Source-fetch logic is covered by backend tests.
- Transcription logic is covered by backend tests.
- Translation logic is covered by backend tests.
- Full job orchestration is covered by backend tests.
- `POST /api/video/fetch-source` was verified on a public video and returned `captions`.
- Audio download was verified with a real file written to `tmp/dQw4w9WgXcQ.webm`.
- Frontend UI was updated to a minimal centered layout and verified with local build and page load checks.
- Translation provider switching and request-level translation settings are covered by backend tests.
- Real end-to-end translation depends on valid provider credentials and available billing/quota.
- Real `POST /api/jobs/run` audio fallback depends on a working local Whisper model download and local CPU time, not on `OPENAI_API_KEY`.
- Python, pip, node, and npm are installed and available.

## yt-dlp Cookie Troubleshooting

- If `yt-dlp` says it could not copy the Chrome cookie database, fully close all Chrome processes and restart the backend.
- On Windows, the more reliable option is exporting a `cookies.txt` file and setting `YTDLP_COOKIES_FILE` in `.env`.
- `YTDLP_COOKIES_FILE` takes priority over `YTDLP_COOKIES_FROM_BROWSER`.
- If YouTube says `Sign in to confirm you're not a bot`, you usually need valid logged-in cookies for that specific video.
