from __future__ import annotations

from uuid import uuid4

WRITER_POLICY_VERSION = "2026-05-14"
SPEECH_VERBATIM_PROMPT_VERSION = "2026-05-14-speech-verbatim-v1"
ARTICLE_LONGFORM_PROMPT_VERSION = "2026-05-14-article-longform-v1"
FULL_PROMPT_PROMPT_VERSION = "2026-05-14-full-prompt-v1"


def new_writer_trace_id(prefix: str = "writer") -> str:
    return f"{prefix}-{uuid4().hex}"
