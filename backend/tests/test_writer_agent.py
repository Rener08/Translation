from app.services.content_rewrite_service import ContentRewriteResult
from app.services.quality_check_service import QualityReport
from app.services.skill_config_service import SkillConfig, SkillOutputSpec, StyleConstraint
from app.services.writer_agent_service import MaterialPackage, WriterAgent, run_writer_agent


def _passing_quality_report(*args, **kwargs):
    return QualityReport(passed=True, issues=(), layers_checked=0, layers_passed=0)


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
                rewritten_text="第一段" + ("太短。" * 120) + "\n\n第二段" + ("太短。" * 120),
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
        "app.services.pipelines.rewrite_content",
        fake_rewrite_content,
    )

    report = WriterAgent().run(
        material=MaterialPackage(source_text="a" * 2400),
        rewrite_focus="改写成结构清晰的中文文章。",
        rewrite_style="article_longform",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
    )

    assert len(calls) == 4
    assert report.draft.revised_once is True
    assert report.draft.validation.ok is True
    assert report.provider == "ollama"
    assert report.model == "qwen3.5:4b"
    assert report.rewrite_style == "article_longform"


def test_writer_agent_speech_verbatim_skips_article_pipeline(monkeypatch) -> None:
    from app.services.detail_ledger import DetailCoverageResult

    calls: list[str] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        focus = str(kwargs["rewrite_focus"])
        calls.append(focus)
        assert kwargs["rewrite_style"] == "speech_verbatim"
        return ContentRewriteResult(
            rewritten_text="保留口吻后的正文。" * 180,
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.pipelines.rewrite_content",
        fake_rewrite_content,
    )
    monkeypatch.setattr(
        "app.services.pipelines.analyze_detail_coverage_enhanced",
        lambda ledger, text: DetailCoverageResult(missing_items=()),
    )
    monkeypatch.setattr(
        "app.services.pipelines.check_article_quality",
        _passing_quality_report,
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


def test_writer_agent_latepost_skill_forces_article_longform_pipeline(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    latepost_config = SkillConfig(
        style_name="晚点",
        perspective="third_person",
        output=SkillOutputSpec(
            min_chars=2000,
            target_chars=4000,
            max_chars=6000,
            min_sections=3,
            max_sections=6,
        ),
        constraints=(
            StyleConstraint(
                constraint_type="forbidden_word",
                pattern="说白了",
                fix_hint="请替换",
            ),
        ),
        perspective_markers=("我", "我们"),
        template_routing_enabled=True,
        content_filters=("跳过广告和赞助内容",),
        quality_layers=(),
    )

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        assert kwargs["rewrite_style"] == "article_longform"
        assert kwargs["skill_config"].style_name == "晚点"
        if len(calls) == 1:
            assert "【原始英文素材】" in str(kwargs["source_text"])
            assert "English reference" in str(kwargs["source_text"])
            return ContentRewriteResult(
                rewritten_text="- 第一部分\n- 第二部分\n- 第三部分",
                provider="ollama",
                model="qwen3.5:4b",
            )
        return ContentRewriteResult(
            rewritten_text="这是一篇第三视角的晚点文章。" + ("甲" * 1200) + "\n\n第二部分" + ("乙" * 1200),
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.pipelines.rewrite_content",
        fake_rewrite_content,
    )
    monkeypatch.setattr(
        "app.services.pipelines.check_article_quality",
        _passing_quality_report,
    )

    report = WriterAgent().run(
        material=MaterialPackage(
            source_text="中文素材正文。",
            reference_text="English reference",
        ),
        rewrite_focus="改写成晚点风格的第三视角中文报道文章。",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
        skill_config=latepost_config,
    )

    assert len(calls) == 2
    assert report.rewrite_style == "article_longform"
    assert report.draft.revised_once is False
    assert report.provider == "ollama"
    assert report.model == "qwen3.5:4b"


def test_writer_agent_speech_verbatim_patches_missing_detail_items(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        if len(calls) == 1:
            assert kwargs["rewrite_style"] == "speech_verbatim"
            assert kwargs["source_text"] == "NASA said 3 rockets launched at 8 pm. SpaceX confirmed it."
            assert "NASA" in str(kwargs["detail_ledger"])
            assert "3" in str(kwargs["detail_ledger"])
            assert "SpaceX" in str(kwargs["detail_ledger"])
            return ContentRewriteResult(
                rewritten_text="NASA said rockets launched. SpaceX confirmed it.",
                provider="ollama",
                model="qwen3.5:4b",
            )

        assert "原始素材" in str(kwargs["rewrite_focus"])
        assert "当前完整草稿" in str(kwargs["rewrite_focus"])
        assert "必须输出修订后的完整正文" in str(kwargs["rewrite_focus"])
        assert kwargs["rewrite_style"] == "speech_verbatim"
        assert kwargs["source_text"] == "NASA said rockets launched. SpaceX confirmed it."
        assert "3" in str(kwargs["detail_ledger"])
        assert "8" in str(kwargs["detail_ledger"])
        return ContentRewriteResult(
            rewritten_text="NASA said 3 rockets launched at 8 pm. SpaceX confirmed it.",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.pipelines.rewrite_content",
        fake_rewrite_content,
    )
    monkeypatch.setattr(
        "app.services.pipelines.check_article_quality",
        _passing_quality_report,
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
    assert report.rewritten_text == "NASA said 3 rockets launched at 8 pm. SpaceX confirmed it."
    assert report.rewrite_style == "speech_verbatim"
    assert report.detail_coverage_issues == ()


def test_writer_agent_speech_verbatim_rejects_truncated_patch_output(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        if len(calls) == 1:
            assert kwargs["rewrite_style"] == "speech_verbatim"
            return ContentRewriteResult(
                rewritten_text="NASA said rockets launched. SpaceX confirmed it.",
                provider="ollama",
                model="qwen3.5:4b",
            )

        assert "当前完整草稿" in str(kwargs["rewrite_focus"])
        assert "必须输出修订后的完整正文" in str(kwargs["rewrite_focus"])
        assert kwargs["rewrite_style"] == "speech_verbatim"
        return ContentRewriteResult(
            rewritten_text="补充：3 rockets at 8 pm.",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.pipelines.rewrite_content",
        fake_rewrite_content,
    )
    monkeypatch.setattr(
        "app.services.pipelines.check_article_quality",
        _passing_quality_report,
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
    assert report.rewritten_text == "NASA said rockets launched. SpaceX confirmed it."
    assert report.detail_coverage_issues == (
        "缺失细节：数字 3",
        "缺失细节：数字 8",
        "缺失细节：关键句 NASA said 3 rockets launched at 8 pm.",
    )
    assert report.rewrite_style == "speech_verbatim"


def test_writer_agent_speech_verbatim_keeps_transliterated_names_without_patch(
    monkeypatch,
) -> None:
    from app.services.detail_ledger import DetailCoverageResult

    calls: list[dict[str, object]] = []

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        assert kwargs["rewrite_style"] == "speech_verbatim"
        return ContentRewriteResult(
            rewritten_text="贾里德·艾萨克曼说 3 枚火箭发射成功，SpaceX 也确认了。这次发射保持了原有节奏，没有额外扩写，也没有改动事实。",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.pipelines.rewrite_content",
        fake_rewrite_content,
    )
    monkeypatch.setattr(
        "app.services.pipelines.analyze_detail_coverage_enhanced",
        lambda ledger, text: DetailCoverageResult(missing_items=()),
    )
    monkeypatch.setattr(
        "app.services.pipelines.check_article_quality",
        _passing_quality_report,
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
                "writer_trace_id": "writer-trace-1",
                "writer_policy_version": "policy-v1",
                "writer_prompt_version": "prompt-v1",
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
    assert result.writer_trace_id == "writer-trace-1"
    assert result.writer_policy_version == "policy-v1"
    assert result.writer_prompt_version == "prompt-v1"


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

        assert "当前完整草稿" in str(kwargs["rewrite_focus"])
        assert "必须输出修订后的完整正文" in str(kwargs["rewrite_focus"])
        assert "2025 年 6 月" in str(kwargs["rewrite_focus"])
        return ContentRewriteResult(
            rewritten_text="我们在 2025 年 6 月发布了产品，并开了一次会议。",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.pipelines.rewrite_content",
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
    from app.services.detail_ledger import DetailCoverageResult

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
        "app.services.pipelines.rewrite_content",
        fake_rewrite_content,
    )
    monkeypatch.setattr(
        "app.services.pipelines.analyze_detail_coverage_enhanced",
        lambda ledger, text: DetailCoverageResult(missing_items=()),
    )
    monkeypatch.setattr(
        "app.services.pipelines.check_article_quality",
        _passing_quality_report,
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


def test_writer_agent_article_longform_rewrites_first_person_to_third_person(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    third_person_config = SkillConfig(
        style_name="test",
        perspective="third_person",
        output=SkillOutputSpec(min_chars=1200, target_chars=1500, max_chars=1800, min_sections=2, max_sections=3),
        constraints=(
            StyleConstraint(constraint_type="perspective_marker", pattern="我", fix_hint="请改成第三视角叙述"),
        ),
        perspective_markers=("我", "我们"),
        template_routing_enabled=False,
        content_filters=(),
        quality_layers=(
            {"name": "L1 硬约束", "checks": ["perspective_consistent", "forbidden_words"]},
        ),
    )

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        calls.append(kwargs)
        if len(calls) == 1:
            assert kwargs["rewrite_style"] == "article_longform"
            return ContentRewriteResult(
                rewritten_text="- 第一部分\n- 第二部分\n- 第三部分",
                provider="ollama",
                model="qwen3.5:4b",
            )

        if len(calls) == 2:
            assert kwargs["rewrite_style"] == "article_longform"
            return ContentRewriteResult(
                rewritten_text=(
                    "我认为这件事很重要。" + ("甲" * 450) + "\n\n"
                    "我们先看第一点。" + ("乙" * 450) + "\n\n"
                    "我再强调一次。" + ("丙" * 450)
                ),
                provider="ollama",
                model="qwen3.5:4b",
            )

        assert kwargs["rewrite_style"] == "article_longform"
        assert "修订" in str(kwargs["rewrite_focus"])
        return ContentRewriteResult(
            rewritten_text=(
                "这件事很重要。" + ("甲" * 450) + "\n\n"
                "首先看第一点。" + ("乙" * 450) + "\n\n"
                "这里需要再强调一次。" + ("丙" * 450)
            ),
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.pipelines.rewrite_content",
        fake_rewrite_content,
    )

    report = WriterAgent().run(
        material=MaterialPackage(source_text="a" * 2400),
        rewrite_focus="改写成结构清晰的中文文章。",
        rewrite_style="article_longform",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
        skill_config=third_person_config,
    )

    assert len(calls) == 3
    assert report.draft.revised_once is True
    assert report.draft.validation.ok is True
    assert report.rewrite_style == "article_longform"


def test_speech_verbatim_uses_refiner_when_llm_call_fn_provided(monkeypatch) -> None:
    from app.services.detail_ledger import DetailCoverageResult

    refiner_calls: list[tuple[str, str]] = []
    rewrite_calls: list[dict[str, object]] = []

    def fake_llm_call(system_prompt, user_prompt):
        refiner_calls.append((system_prompt, user_prompt))
        return '[{"kind": "数字", "text": "42", "priority": "high"}]'

    def fake_rewrite_content(**kwargs) -> ContentRewriteResult:
        rewrite_calls.append(kwargs)
        return ContentRewriteResult(
            rewritten_text="结果是 42，已经确认。",
            provider="ollama",
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(
        "app.services.pipelines.rewrite_content",
        fake_rewrite_content,
    )
    monkeypatch.setattr(
        "app.services.pipelines.analyze_detail_coverage_enhanced",
        lambda ledger, text: DetailCoverageResult(missing_items=()),
    )
    monkeypatch.setattr(
        "app.services.pipelines.check_article_quality",
        _passing_quality_report,
    )

    report = WriterAgent().run(
        material=MaterialPackage(source_text="The answer is 42 confirmed by NASA."),
        rewrite_focus="保留原作者说话节奏。",
        rewrite_style="speech_verbatim",
        rewrite_config={"provider": "ollama", "model": "qwen3.5:4b"},
        llm_call_fn=fake_llm_call,
    )

    assert len(refiner_calls) == 1
    assert len(rewrite_calls) == 1
    assert "42" in rewrite_calls[0]["detail_ledger"]
    assert report.draft.revised_once is False
    assert report.rewrite_style == "speech_verbatim"
