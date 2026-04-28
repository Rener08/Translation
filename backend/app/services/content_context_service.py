from dataclasses import dataclass

from app.services.persistent_cache_service import (
    build_cache_key,
    load_json_cache,
    store_json_cache,
)


@dataclass(frozen=True)
class ContentContext:
    content_context_id: str
    video_title: str | None
    transcript_en: str
    translation_zh: str


def create_content_context(
    *,
    video_title: str | None,
    transcript_en: str,
    translation_zh: str,
) -> str:
    content_context_id = build_cache_key(
        {
            "video_title": (video_title or "").strip(),
            "transcript_en": transcript_en.strip(),
            "translation_zh": translation_zh.strip(),
        }
    )
    store_json_cache(
        "content_context",
        content_context_id,
        {
            "video_title": (video_title or "").strip() or None,
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

    video_title = str(payload.get("video_title") or "").strip() or None
    return ContentContext(
        content_context_id=normalized_id,
        video_title=video_title,
        transcript_en=transcript_en,
        translation_zh=translation_zh,
    )
