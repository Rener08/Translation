from __future__ import annotations

from pathlib import Path

from app.services.content_context_service import create_content_context, load_content_context


def _use_tmp_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.services.persistent_cache_service.CACHE_ROOT_DIR",
        tmp_path / "persistent_cache",
    )


def test_content_context_service_enforces_account_owner(monkeypatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)

    content_context_id = create_content_context(
        video_title="Demo video",
        transcript_en="Hello everyone.",
        translation_zh="大家好。",
        account_id="user:alice",
    )

    same_account = load_content_context(content_context_id, account_id="user:alice")
    other_account = load_content_context(content_context_id, account_id="user:bob")

    assert same_account is not None
    assert same_account.account_id == "user:alice"
    assert same_account.transcript_en == "Hello everyone."
    assert other_account is None


def test_content_context_service_allows_legacy_anonymous_contexts(monkeypatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)

    content_context_id = create_content_context(
        video_title="Legacy video",
        transcript_en="Hello everyone.",
        translation_zh="大家好。",
    )

    legacy_context = load_content_context(content_context_id, account_id="anonymous:testclient")

    assert legacy_context is not None
    assert legacy_context.account_id is None
    assert legacy_context.video_title == "Legacy video"
