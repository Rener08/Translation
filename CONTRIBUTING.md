# Contributing

Thanks for helping improve this project.

## Before You Start

- Keep changes small and focused.
- Do not commit generated environments or build output such as `backend/.venv/`,
  `frontend/node_modules/`, or `frontend/.next/`.
- Prefer ASCII unless the file already uses another convention.

## Local Setup

```bash
cd backend
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

```bash
cd frontend
npm install
```

## Verification

- Backend full suite: `cd backend && ./.venv/bin/python -m pytest`
- Backend MVP regressions (queue + jobs):  
  `./.venv/bin/python -m pytest tests/test_job_queue_service.py tests/test_jobs_run.py`
- Writer skill eval report:  
  `python3 scripts/evaluate_writer_skill.py --manifest backend/tests/fixtures/writer_skill_eval/samples.json`
- Frontend: `cd frontend && npm run build`
- Mainline acceptance is defined in [`TODO.md`](TODO.md#mainline-acceptance).

If you change the desktop launcher or startup scripts, please also verify the
local run path described in `README.md`.

## MVP manual smoke checklist

Before merging backend queue/routes/UI paths changes, run through:

1. `GET http://localhost:8000/health` returns `{"status":"ok"}`.
2. `GET http://localhost:8000/readyz` returns `200` with `checks.tmp_writable` and `checks.job_queue_db` equal to `ok`.
3. Paste a **short public** YouTube URL in the web app, complete ingest → rewrite → article draft appears.
4. **Export** article Markdown and confirm the file ends with source title/link attribution footer.
5. Optional: restart backend mid-queue job once and confirm UI reports retry/interrupted messaging (`JOB_INTERRUPTED_RESTART`).

## Pull Requests

- Describe what changed and why.
- Call out any environment variables, data files, or manual steps needed.
- Include screenshots or logs for UI or runtime changes when helpful.
- Mention any follow-up work that should happen in a separate PR.

## Issues

When filing an issue, please include:

- The exact error message or unexpected behavior.
- Steps to reproduce.
- Your OS, Python version, and Node version.
- Whether the problem happened in backend, frontend, or desktop flow.
