from dataclasses import dataclass

from app.services.persistent_cache_service import (
    build_cache_key,
    load_json_cache,
    store_json_cache,
)


@dataclass(frozen=True)
class ContentContext:
    content_context_id: str
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
) -> str:
    content_context_id = build_cache_key(
        {
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
    )
    store_json_cache(
        "content_context",
        content_context_id,
        {
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


def load_content_context(content_context_id: str) -> ContentContext | None:
    normalized_id = content_context_id.strip()
    if not normalized_id:
        return None

    payload = load_json_cache("content_context", normalized_id)
    if not isinstance(payload, dict):
        return None

    transcript_en = str(payload.get("transcript_en") or "").strip()
    translation_zh = str(payload.get("translation_zh") or "").strip()
    if not transcript_en or not translation_zh:
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


def _coerce_optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None
