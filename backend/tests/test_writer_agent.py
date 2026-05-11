from app.services.content_rewrite_service import ContentRewriteResult
from app.services.writer_agent_service import MaterialPackage, WriterAgent, run_writer_agent


def test_writer_agent_runs_outline_draft_and_single_revision(monkeypatch) -> None:
    calls: list[str] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        focus = str(kwargs["rewrite_focus"])
        calls.append(focus)
        if "只输出一个简短大纲" in focus:
            return ContentRewriteResult(
                rewritten_text="- 第一部分\n- 第二部分",
                provider="ollama",
                model="qwen3.5:4b",
            )
        if "输出中文文章初稿" in focus:
            return ContentRewriteResult(
                rewritten_text="第一段太短。\n\n第二段太短。",
                provider="ollama",
                model="qwen3.5:4b",
                quality_issues=("too short",),
            )
        revised_text = (
            "第一段" + ("甲" * 500) + "\n\n"
            "第二段" + ("乙" * 500) + "\n\n"
            "第三段" + ("丙" * 500)
        )
        return ContentRewriteResult(
            rewritten_text=revised_text,
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.writer_agent_service.rewrite_content",
        fake_rewrite_content,
    )

    report = WriterAgent().run(
        material=MaterialPackage(source_text="a" * 2400),
        rewrite_focus="改写成结构清晰的中文文章。",
        rewrite_style="article_longform",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert len(calls) == 3
    assert report.draft.revised_once is True
    assert report.draft.validation.ok is True
    assert report.provider == "ollama"
    assert report.model == "qwen3.5:4b"
    assert report.rewrite_style == "article_longform"


def test_writer_agent_speech_verbatim_skips_article_pipeline(monkeypatch) -> None:
    calls: list[str] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        focus = str(kwargs["rewrite_focus"])
        calls.append(focus)
        assert kwargs["rewrite_style"] == "speech_verbatim"
        return ContentRewriteResult(
            rewritten_text="保留口吻后的正文。",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.writer_agent_service.rewrite_content",
        fake_rewrite_content,
    )

    report = WriterAgent().run(
        material=MaterialPackage(source_text="a" * 2400),
        rewrite_focus="保留原作者说话节奏。",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert len(calls) == 1
    assert report.draft.revised_once is False
    assert report.draft.validation.ok is True
    assert report.provider == "ollama"
    assert report.model == "qwen3.5:4b"
    assert report.rewrite_style == "speech_verbatim"


def test_writer_agent_speech_verbatim_patches_missing_detail_items(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        if len(calls) == 1:
            assert kwargs["rewrite_style"] == "speech_verbatim"
            assert "NASA" in str(kwargs["detail_ledger"])
            assert "3" in str(kwargs["detail_ledger"])
            assert "SpaceX" in str(kwargs["detail_ledger"])
            return ContentRewriteResult(
                rewritten_text="NASA said rockets launched. SpaceX confirmed it.",
                provider="ollama",
                model="qwen3.5:4b",
            )

        assert "补足下面缺失的细节" in str(kwargs["rewrite_focus"])
        assert kwargs["rewrite_style"] == "speech_verbatim"
        assert "3" in str(kwargs["detail_ledger"])
        assert "8" in str(kwargs["detail_ledger"])
        assert "SpaceX" not in str(kwargs["detail_ledger"])
        return ContentRewriteResult(
            rewritten_text="NASA said 3 rockets launched at 8 pm. SpaceX confirmed it.",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.writer_agent_service.rewrite_content",
        fake_rewrite_content,
    )

    report = WriterAgent().run(
        material=MaterialPackage(
            source_text="NASA said 3 rockets launched at 8 pm. SpaceX confirmed it.",
        ),
        rewrite_focus="保留原作者说话节奏。",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert len(calls) == 2
    assert report.draft.revised_once is True
    assert report.draft.validation.ok is True
    assert report.rewrite_style == "speech_verbatim"
    assert report.detail_coverage_issues == ()


def test_writer_agent_speech_verbatim_keeps_transliterated_names_without_patch(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        assert kwargs["rewrite_style"] == "speech_verbatim"
        return ContentRewriteResult(
            rewritten_text="贾里德·艾萨克曼说 3 枚火箭发射成功，SpaceX 也确认了。",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.writer_agent_service.rewrite_content",
        fake_rewrite_content,
    )

    report = WriterAgent().run(
        material=MaterialPackage(
            source_text="Jared Isaacman said 3 rockets launched successfully, and SpaceX confirmed it.",
        ),
        rewrite_focus="保留原作者说话节奏。",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert len(calls) == 1
    assert report.draft.revised_once is False
    assert report.detail_coverage_issues == ()
    assert report.rewrite_style == "speech_verbatim"


def test_run_writer_agent_returns_content_rewrite_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.writer_agent_service.WriterAgent.run",
        lambda self, **kwargs: type(
            "FakeReport",
            (),
            {
                "rewritten_text": "最终正文",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "quality_issues": ("issue-a",),
                "detail_coverage_issues": ("缺失细节：数字 3",),
            },
        )(),
    )

    result = run_writer_agent(
        source_text="原文",
        rewrite_focus="改写",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "deepseek"},
    )
    assert result.rewritten_text == "最终正文"
    assert result.provider == "deepseek"
    assert result.model == "deepseek-chat"
    assert result.quality_issues == ("issue-a",)
    assert result.detail_coverage_issues == ("缺失细节：数字 3",)


def test_writer_agent_speech_verbatim_treats_chinese_dates_as_hard_coverage(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        if len(calls) == 1:
            ledger = str(kwargs.get("detail_ledger") or "")
            assert "2025 年 6 月" in ledger
            return ContentRewriteResult(
                rewritten_text="我们发布了产品，并开了一次会议。",
                provider="ollama",
                model="qwen3.5:4b",
            )

        assert "补足下面缺失的细节" in str(kwargs["rewrite_focus"])
        assert "2025 年 6 月" in str(kwargs["rewrite_focus"])
        return ContentRewriteResult(
            rewritten_text="我们在 2025 年 6 月发布了产品，并开了一次会议。",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.writer_agent_service.rewrite_content",
        fake_rewrite_content,
    )

    report = WriterAgent().run(
        material=MaterialPackage(
            source_text="我们在 2025 年 6 月发布了产品，并开了一次会议。"
        ),
        rewrite_focus="保留原作者说话节奏。",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert len(calls) == 2
    assert report.draft.revised_once is True
    assert report.detail_coverage_issues == ()
    assert report.rewrite_style == "speech_verbatim"


def test_writer_agent_speech_verbatim_does_not_patch_for_missing_turn_phrase(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        ledger = str(kwargs.get("detail_ledger") or "")
        assert "转折/结论句" in ledger
        assert "但是这次有几个问题需要修" in ledger
        return ContentRewriteResult(
            rewritten_text="用户说体验不错，已经处理了几个问题。",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.writer_agent_service.rewrite_content",
        fake_rewrite_content,
    )

    report = WriterAgent().run(
        material=MaterialPackage(
            source_text=(
                "用户说体验还行。但是这次有几个问题需要修。我们已经处理了。"
            ),
        ),
        rewrite_focus="保留原作者说话节奏。",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert len(calls) == 1
    assert report.draft.revised_once is False
    assert report.detail_coverage_issues == ()
    assert report.rewrite_style == "speech_verbatim"
