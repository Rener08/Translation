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

- Backend: `python -m pytest backend/tests`
- Frontend: `cd frontend && npm run build`

If you change the desktop launcher or startup scripts, please also verify the
local run path described in `README.md`.

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
