from dataclasses import dataclass

from app.services.persistent_cache_service import (
    build_cache_key,
    load_json_cache,
    store_json_cache,
)


@dataclass(frozen=True)
class ContentContext:
    content_context_id: str
    account_id: str | None = None
    video_id: str | None = None
    video_url: str | None = None
    video_title: str | None = None
    video_duration_sec: int | None = None
    video_uploader: str | None = None
    video_thumbnail: str | None = None
    source_type: str | None = None
    transcript_en: str = ""
    translation_zh: str = ""


def create_content_context(
    *,
    video_id: str | None = None,
    video_url: str | None = None,
    video_title: str | None,
    video_duration_sec: int | None = None,
    video_uploader: str | None = None,
    video_thumbnail: str | None = None,
    source_type: str | None = None,
    transcript_en: str,
    translation_zh: str,
    account_id: str | None = None,
) -> str:
    normalized_account_id = _normalize_optional_text(account_id)
    cache_payload = {
        "video_id": (video_id or "").strip(),
        "video_url": (video_url or "").strip(),
        "video_title": (video_title or "").strip(),
        "video_duration_sec": str(video_duration_sec or ""),
        "video_uploader": (video_uploader or "").strip(),
        "video_thumbnail": (video_thumbnail or "").strip(),
        "source_type": (source_type or "").strip(),
        "transcript_en": transcript_en.strip(),
        "translation_zh": translation_zh.strip(),
    }
    if normalized_account_id:
        cache_payload["account_id"] = normalized_account_id

    content_context_id = build_cache_key(cache_payload)
    store_json_cache(
        "content_context",
        content_context_id,
        {
            "account_id": normalized_account_id,
            "video_id": (video_id or "").strip() or None,
            "video_url": (video_url or "").strip() or None,
            "video_title": (video_title or "").strip() or None,
            "video_duration_sec": video_duration_sec,
            "video_uploader": (video_uploader or "").strip() or None,
            "video_thumbnail": (video_thumbnail or "").strip() or None,
            "source_type": (source_type or "").strip() or None,
            "transcript_en": transcript_en.strip(),
            "translation_zh": translation_zh.strip(),
        },
    )
    return content_context_id


def load_content_context(
    content_context_id: str,
    *,
    account_id: str | None = None,
) -> ContentContext | None:
    normalized_id = content_context_id.strip()
    if not normalized_id:
        return None

    payload = load_json_cache("content_context", normalized_id)
    if not isinstance(payload, dict):
        return None

    normalized_account_id = _normalize_optional_text(account_id)
    stored_account_id = _normalize_optional_text(payload.get("account_id"))
    if normalized_account_id is not None and not _payload_matches_account(
        stored_account_id,
        normalized_account_id,
    ):
        return None

    transcript_en = str(payload.get("transcript_en") or "").strip()
    translation_zh = str(payload.get("translation_zh") or "").strip()
    if not transcript_en:
        return None

    video_id = str(payload.get("video_id") or "").strip() or None
    video_url = str(payload.get("video_url") or "").strip() or None
    video_title = str(payload.get("video_title") or "").strip() or None
    video_duration_sec = _coerce_optional_int(payload.get("video_duration_sec"))
    video_uploader = str(payload.get("video_uploader") or "").strip() or None
    video_thumbnail = str(payload.get("video_thumbnail") or "").strip() or None
    source_type = str(payload.get("source_type") or "").strip() or None
    return ContentContext(
        content_context_id=normalized_id,
        account_id=stored_account_id,
        video_id=video_id,
        video_url=video_url,
        video_title=video_title,
        video_duration_sec=video_duration_sec,
        video_uploader=video_uploader,
        video_thumbnail=video_thumbnail,
        source_type=source_type,
        transcript_en=transcript_en,
        translation_zh=translation_zh,
    )


def _payload_matches_account(
    payload_account_id: str | None,
    account_id: str | None,
) -> bool:
    normalized_account_id = _normalize_optional_text(account_id)
    if normalized_account_id is None:
        return True

    normalized_payload_account_id = _normalize_optional_text(payload_account_id)
    if normalized_payload_account_id == normalized_account_id:
        return True
    if normalized_payload_account_id is None and normalized_account_id.startswith("anonymous:"):
        return True
    if normalized_payload_account_id is None and normalized_account_id == "anonymous-localhost":
        return True
    return False


def _normalize_optional_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None
