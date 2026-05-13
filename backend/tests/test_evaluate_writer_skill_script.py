from __future__ import annotations

from argparse import Namespace
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from app.services.writer_skill_eval_service import (
    WriterSkillEvalModeSummary,
    WriterSkillEvalReport,
)


def _load_script_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_writer_skill.py"
    spec = spec_from_file_location("evaluate_writer_skill_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script module from {script_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_exits_non_zero_when_fail_on_error(monkeypatch, tmp_path) -> None:
    module = _load_script_module()

    summary = WriterSkillEvalModeSummary(
        mode="speech_verbatim",
        sample_count=1,
        hard_detail_rate=0.0,
        third_person_ok_rate=0.0,
        ordering_ok_rate=0.0,
        avg_compression_ratio=0.0,
        first_person_failures=0,
        ai_slop_hits=0,
        error_count=1,
        zh_subset_compression_avg=None,
    )
    report = WriterSkillEvalReport(
        generated_at="2026-05-13T00:00:00+08:00",
        manifest_path="/tmp/manifest.json",
        skill_root="/tmp/skill",
        provider="deepseek",
        model="deepseek-v4-pro",
        sample_count=1,
        samples=(),
        summaries=(summary,),
        decision_hint="provider/model error",
    )

    monkeypatch.setattr(module, "load_writer_skill_eval_manifest", lambda *args, **kwargs: (object(),))
    monkeypatch.setattr(module, "run_writer_skill_eval", lambda *args, **kwargs: report)
    monkeypatch.setattr(module, "parse_args", lambda: Namespace(
        manifest="/tmp/manifest.json",
        output_dir=str(tmp_path / "out"),
        refresh_samples=False,
        sample_id=[],
        provider="deepseek",
        model="deepseek-v4-pro",
        base_url="",
        api_key="",
        fail_on_error=True,
    ))

    assert module.main() == 1
    assert (tmp_path / "out" / "report.json").exists()
    assert (tmp_path / "out" / "report.md").exists()
