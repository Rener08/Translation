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
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert len(calls) == 3
    assert report.draft.revised_once is True
    assert report.draft.validation.ok is True
    assert report.provider == "ollama"
    assert report.model == "qwen3.5:4b"


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
            },
        )(),
    )

    result = run_writer_agent(
        source_text="原文",
        rewrite_focus="改写",
        rewrite_config={"provider": "deepseek"},
    )
    assert result.rewritten_text == "最终正文"
    assert result.provider == "deepseek"
    assert result.model == "deepseek-chat"
    assert result.quality_issues == ("issue-a",)
