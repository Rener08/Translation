from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.article_generation_service import ArticleValidationResult, resolve_article_spec
from app.services.writer_agent_service import ArticleDraft, MaterialPackage, WriterRunReport
from app.services.writer_skill_eval_service import (
    build_full_prompt_from_skill_prompt,
    load_writer_skill_eval_manifest,
    run_writer_skill_eval,
    writer_skill_eval_report_to_markdown,
)


def test_build_full_prompt_from_skill_prompt_replaces_placeholder() -> None:
    prompt = "标题：测试\n素材：\n[在这里贴入素材]\n结尾。"

    result = build_full_prompt_from_skill_prompt(prompt)

    assert "{{transcript}}" in result
    assert "[在这里贴入素材]" not in result


def test_load_writer_skill_eval_manifest_reads_relative_paths(tmp_path) -> None:
    manifest = tmp_path / "samples.json"
    transcript = tmp_path / "transcripts" / "sample.txt"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("source text", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "sample_id": "sample-1",
                        "title": "Sample",
                        "url": "https://example.com",
                        "baseline_prompt_file": "09_interview_transcript_sync.md",
                        "transcript_path": "transcripts/sample.txt",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    samples = load_writer_skill_eval_manifest(manifest)

    assert len(samples) == 1
    assert samples[0].sample_id == "sample-1"
    assert samples[0].transcript_path == "transcripts/sample.txt"


def test_run_writer_skill_eval_records_three_modes(monkeypatch, tmp_path) -> None:
    manifest = tmp_path / "samples.json"
    transcript_path = tmp_path / "transcripts" / "sample.txt"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        "NASA said 3 rockets launched at 8 pm. SpaceX confirmed it.",
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "sample_id": "sample-1",
                        "title": "Sample",
                        "url": "https://example.com",
                        "baseline_prompt_file": "09_interview_transcript_sync.md",
                        "transcript_path": "transcripts/sample.txt",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    skill_root = tmp_path / "skill"
    prompt_dir = skill_root / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir.joinpath("09_interview_transcript_sync.md").write_text(
        "标题：测试\n素材：\n[在这里贴入逐字稿 / 字幕 / 访谈内容]\n结尾。",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.writer_skill_eval_service.resolve_lastpost_skill_root",
        lambda: skill_root,
    )
    monkeypatch.setattr(
        "app.services.writer_skill_eval_service.load_rewrite_references",
        lambda: SimpleNamespace(
            article_template="通用模板",
            content_methodology="方法",
            style_examples="示例",
            skill_guide="指南",
            quality_pipeline="质检",
            reference_profile="lastpost-skill",
            category_templates={"09_interview_transcript_sync": "场景模板"},
            section_title_rules="标题规则",
        ),
    )
    monkeypatch.setattr(
        "app.services.writer_skill_eval_service._select_rewrite_template",
        lambda **kwargs: SimpleNamespace(
            key="09_interview_transcript_sync",
            label="09 访谈 / 播客 / 字幕同步稿",
            route_reason="命中测试路由",
        ),
    )

    def fake_run(self, **kwargs):
        focus = kwargs.get("rewrite_focus")
        style = kwargs.get("rewrite_style")
        if style == "speech_verbatim":
            return WriterRunReport(
                rewritten_text="NASA said 3 rockets launched at 8 pm. SpaceX confirmed it.",
                provider="deepseek",
                model="deepseek-chat",
                quality_issues=(),
                material=MaterialPackage(source_text="source"),
                draft=ArticleDraft(
                    text="NASA said 3 rockets launched at 8 pm. SpaceX confirmed it.",
                    outline=("x",),
                    spec=resolve_article_spec(kwargs["material"].source_text),
                    validation=ArticleValidationResult(
                        ok=True,
                        total_chars=1,
                        section_count=1,
                        section_chars=(1,),
                        issues=(),
                    ),
                    revised_once=False,
                ),
                rewrite_style="speech_verbatim",
                detail_coverage_issues=(),
            )
        if focus is None:
            return WriterRunReport(
                rewritten_text="这件事很重要，但仍有第一人称。",
                provider="deepseek",
                model="deepseek-chat",
                quality_issues=("检测到疑似模型自述或免责声明，建议检查是否夹带了无关说明。",),
                material=MaterialPackage(source_text="source"),
                draft=ArticleDraft(
                    text="这件事很重要，但仍有第一人称。",
                    outline=("x",),
                    spec=resolve_article_spec(kwargs["material"].source_text),
                    validation=ArticleValidationResult(
                        ok=True,
                        total_chars=1,
                        section_count=1,
                        section_chars=(1,),
                        issues=(),
                    ),
                    revised_once=False,
                ),
                rewrite_style="article_longform",
                detail_coverage_issues=("缺失细节：数字 3",),
            )
        return WriterRunReport(
            rewritten_text="这是全量 prompt 基线。",
            provider="deepseek",
            model="deepseek-chat",
            quality_issues=(),
            material=MaterialPackage(source_text="source"),
            draft=ArticleDraft(
                text="这是全量 prompt 基线。",
                outline=("full_prompt_passthrough",),
                spec=resolve_article_spec(kwargs["material"].source_text),
                validation=ArticleValidationResult(
                    ok=True,
                    total_chars=1,
                    section_count=1,
                    section_chars=(1,),
                    issues=(),
                ),
                revised_once=False,
            ),
            rewrite_style="article_longform",
            detail_coverage_issues=(),
        )

    monkeypatch.setattr("app.services.writer_skill_eval_service.WriterAgent.run", fake_run)

    report = run_writer_skill_eval(
        manifest_path=manifest,
        refresh_samples=False,
        rewrite_config={"provider": "deepseek", "model": "deepseek-chat"},
    )

    assert report.sample_count == 1
    assert len(report.samples) == 1
    assert len(report.samples[0].modes) == 3
    assert {mode.mode for mode in report.samples[0].modes} == {
        "speech_verbatim",
        "article_longform",
        "full_prompt_baseline",
    }
    assert report.samples[0].modes[1].route_label == "09 访谈 / 播客 / 字幕同步稿"
    assert "决策提示" in writer_skill_eval_report_to_markdown(report)
