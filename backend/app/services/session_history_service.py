from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any

from app.services import persistent_cache_service

try:
    import fcntl
except ImportError:  # pragma: no cover - platform dependent
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - platform dependent
    msvcrt = None  # type: ignore[assignment]


SESSION_HISTORY_NAMESPACE = "session_history"
SAFE_CONTEXT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")


def upsert_job_session(
    *,
    content_context_id: str,
    video_id: str,
    video_url: str,
    video_title: str,
    video_duration_sec: int | None = None,
    video_uploader: str | None = None,
    video_thumbnail: str | None = None,
    source_mode: str,
    source_type: str,
    translation_provider: str | None,
    translation_model: str | None,
    transcript_en_text: str,
    transcript_en_segments: list[dict[str, Any]],
    translation_zh_text: str,
    translation_zh_segments: list[dict[str, Any]],
) -> None:
    normalized_id = _normalize_key(content_context_id)
    if not normalized_id:
        return

    now = _now_iso()
    with _session_history_lock(normalized_id):
        existing = load_session_history(normalized_id) or {}
        payload = dict(existing)
        payload["content_context_id"] = normalized_id
        payload["created_at"] = str(existing.get("created_at") or now)
        payload["updated_at"] = now
        payload["video_id"] = _normalize_optional_text(video_id)
        payload["video_url"] = _normalize_optional_text(video_url)
        payload["video_title"] = _normalize_optional_text(video_title)
        payload["video_duration_sec"] = _normalize_optional_int(video_duration_sec)
        payload["video_uploader"] = _normalize_optional_text(video_uploader)
        payload["video_thumbnail"] = _normalize_optional_text(video_thumbnail)
        payload["source_mode"] = _normalize_optional_text(source_mode)
        payload["source_type"] = _normalize_optional_text(source_type)
        payload["translation_provider"] = _normalize_optional_text(translation_provider)
        payload["translation_model"] = _normalize_optional_text(translation_model)
        payload["transcript_en_text"] = transcript_en_text.strip()
        payload["transcript_en_segments"] = _normalize_dict_list(transcript_en_segments)
        payload["translation_zh_text"] = translation_zh_text.strip()
        payload["translation_zh_segments"] = _normalize_dict_list(translation_zh_segments)
        payload["rewrite_focus"] = _normalize_optional_text(payload.get("rewrite_focus"))
        payload["rewrite_source_text"] = _normalize_text(payload.get("rewrite_source_text"))
        payload["rewritten_text"] = _normalize_text(payload.get("rewritten_text"))
        payload["rewrite_quality_issues"] = _normalize_text_list(
            payload.get("rewrite_quality_issues")
        )
        payload["rewrite_provider"] = _normalize_optional_text(payload.get("rewrite_provider"))
        payload["rewrite_model"] = _normalize_optional_text(payload.get("rewrite_model"))
        payload["chat_turns"] = _normalize_chat_turns(payload.get("chat_turns"))

        persistent_cache_service.store_json_cache(
            SESSION_HISTORY_NAMESPACE, normalized_id, payload
        )


def record_rewrite_result(
    *,
    content_context_id: str,
    rewrite_focus: str | None,
    rewrite_source_text: str,
    rewritten_text: str,
    rewrite_quality_issues: list[str] | None = None,
    rewrite_provider: str,
    rewrite_model: str,
) -> None:
    normalized_id = _normalize_key(content_context_id)
    if not normalized_id:
        return

    now = _now_iso()
    with _session_history_lock(normalized_id):
        payload = load_session_history(normalized_id) or {}
        payload["content_context_id"] = normalized_id
        payload["created_at"] = str(payload.get("created_at") or now)
        payload["updated_at"] = now
        payload["rewrite_focus"] = _normalize_optional_text(rewrite_focus)
        payload["rewrite_source_text"] = rewrite_source_text.strip()
        payload["rewritten_text"] = rewritten_text.strip()
        payload["rewrite_quality_issues"] = _normalize_text_list(rewrite_quality_issues)
        payload["rewrite_provider"] = _normalize_optional_text(rewrite_provider)
        payload["rewrite_model"] = _normalize_optional_text(rewrite_model)
        payload["chat_turns"] = _normalize_chat_turns(payload.get("chat_turns"))

        persistent_cache_service.store_json_cache(
            SESSION_HISTORY_NAMESPACE, normalized_id, payload
        )


def append_chat_exchange(
    *,
    content_context_id: str,
    question: str,
    answer: str,
) -> None:
    normalized_id = _normalize_key(content_context_id)
    if not normalized_id:
        return

    now = _now_iso()
    with _session_history_lock(normalized_id):
        payload = load_session_history(normalized_id) or {}
        payload["content_context_id"] = normalized_id
        payload["created_at"] = str(payload.get("created_at") or now)
        payload["updated_at"] = now

        turns = _normalize_chat_turns(payload.get("chat_turns"))
        turns.append({"role": "user", "content": question.strip(), "created_at": now})
        turns.append({"role": "assistant", "content": answer.strip(), "created_at": now})
        payload["chat_turns"] = turns

        persistent_cache_service.store_json_cache(
            SESSION_HISTORY_NAMESPACE, normalized_id, payload
        )


def load_session_history(content_context_id: str) -> dict[str, Any] | None:
    normalized_id = _normalize_key(content_context_id)
    if not normalized_id:
        return None

    payload = persistent_cache_service.load_json_cache(
        SESSION_HISTORY_NAMESPACE, normalized_id
    )
    if not isinstance(payload, dict):
        return None

    return _normalize_session_payload(payload)


def list_session_history(limit: int | None = 20) -> list[dict[str, Any]]:
    history_dir = _history_dir()
    if not history_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in history_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        records.append(_normalize_session_payload(payload))

    records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    if limit is not None and limit > 0:
        records = records[:limit]

    return [_session_summary(item) for item in records]


def _session_summary(payload: dict[str, Any]) -> dict[str, Any]:
    chat_turns = _normalize_chat_turns(payload.get("chat_turns"))
    return {
        "content_context_id": payload.get("content_context_id", ""),
        "video_id": payload.get("video_id"),
        "video_url": payload.get("video_url"),
        "video_title": payload.get("video_title"),
        "video_duration_sec": payload.get("video_duration_sec"),
        "video_uploader": payload.get("video_uploader"),
        "video_thumbnail": payload.get("video_thumbnail"),
        "source_mode": payload.get("source_mode"),
        "source_type": payload.get("source_type"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
        "has_rewrite": bool(_normalize_text(payload.get("rewritten_text"))),
        "chat_turn_count": len(chat_turns),
        "transcript_preview": _preview_text(payload.get("transcript_en_text")),
        "translation_preview": _preview_text(payload.get("translation_zh_text")),
        "rewritten_preview": _preview_text(payload.get("rewritten_text")),
        "rewrite_quality_issue_count": len(_normalize_text_list(payload.get("rewrite_quality_issues"))),
    }


def _normalize_session_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["content_context_id"] = _normalize_text(normalized.get("content_context_id"))
    normalized["video_id"] = _normalize_optional_text(normalized.get("video_id"))
    normalized["video_url"] = _normalize_optional_text(normalized.get("video_url"))
    normalized["video_title"] = _normalize_optional_text(normalized.get("video_title"))
    normalized["video_duration_sec"] = _normalize_optional_int(
        normalized.get("video_duration_sec")
    )
    normalized["video_uploader"] = _normalize_optional_text(
        normalized.get("video_uploader")
    )
    normalized["video_thumbnail"] = _normalize_optional_text(
        normalized.get("video_thumbnail")
    )
    normalized["source_mode"] = _normalize_optional_text(normalized.get("source_mode"))
    normalized["source_type"] = _normalize_optional_text(normalized.get("source_type"))
    normalized["translation_provider"] = _normalize_optional_text(
        normalized.get("translation_provider")
    )
    normalized["translation_model"] = _normalize_optional_text(
        normalized.get("translation_model")
    )
    normalized["transcript_en_text"] = _normalize_text(normalized.get("transcript_en_text"))
    normalized["translation_zh_text"] = _normalize_text(normalized.get("translation_zh_text"))
    normalized["rewrite_focus"] = _normalize_optional_text(normalized.get("rewrite_focus"))
    normalized["rewrite_source_text"] = _normalize_text(normalized.get("rewrite_source_text"))
    normalized["rewritten_text"] = _normalize_text(normalized.get("rewritten_text"))
    normalized["rewrite_quality_issues"] = _normalize_text_list(
        normalized.get("rewrite_quality_issues")
    )
    normalized["rewrite_provider"] = _normalize_optional_text(
        normalized.get("rewrite_provider")
    )
    normalized["rewrite_model"] = _normalize_optional_text(normalized.get("rewrite_model"))
    normalized["chat_turns"] = _normalize_chat_turns(normalized.get("chat_turns"))
    return normalized


def _normalize_dict_list(value: object | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _normalize_chat_turns(value: object | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    turns: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = _normalize_text(item.get("role"))
        content = _normalize_text(item.get("content"))
        if role not in {"user", "assistant"} or not content:
            continue
        turns.append(
            {
                "role": role,
                "content": content,
                "created_at": _normalize_text(item.get("created_at")) or _now_iso(),
            }
        )
    return turns


def _normalize_text_list(value: object | None) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        text = _normalize_text(item)
        if text:
            normalized.append(text)
    return normalized


def _preview_text(value: object | None, limit: int = 120) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _normalize_key(value: object | None) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        return ""
    if not SAFE_CONTEXT_ID_PATTERN.fullmatch(normalized):
        return ""
    return normalized


def _normalize_optional_text(value: object | None) -> str | None:
    text = _normalize_text(value)
    return text or None


def _normalize_optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _normalize_text(value: object | None) -> str:
    return str(value or "").strip()


def _history_dir() -> Path:
    return persistent_cache_service.CACHE_ROOT_DIR / SESSION_HISTORY_NAMESPACE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _session_history_lock(content_context_id: str):
    lock_path = _history_dir() / f"{content_context_id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        _acquire_lock(handle)
        try:
            yield
        finally:
            _release_lock(handle)


def _acquire_lock(handle) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    if msvcrt is not None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)


def _release_lock(handle) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
