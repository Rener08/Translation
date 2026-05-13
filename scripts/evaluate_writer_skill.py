#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
BACKEND_VENV_LIB = BACKEND_DIR / ".venv" / "lib"
for site_packages_dir in sorted(BACKEND_VENV_LIB.glob("python*/site-packages")):
    if str(site_packages_dir) not in sys.path:
        sys.path.insert(0, str(site_packages_dir))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.writer_skill_eval_service import (  # noqa: E402
    DEFAULT_MANIFEST_PATH,
    DEFAULT_OUTPUT_ROOT,
    load_writer_skill_eval_manifest,
    run_writer_skill_eval,
    writer_skill_eval_report_to_dict,
    writer_skill_eval_report_to_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Translation writer-skill evaluation harness."
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Path to the sample manifest JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Where to write the JSON/Markdown report. Defaults to tmp/writer_skill_eval/<timestamp>.",
    )
    parser.add_argument(
        "--refresh-samples",
        action="store_true",
        help="Refresh transcript snapshots from the sample URLs before running.",
    )
    parser.add_argument(
        "--sample-id",
        action="append",
        default=[],
        help="Only evaluate the given sample id. Can be repeated.",
    )
    parser.add_argument(
        "--provider",
        default="",
        help="Optional rewrite provider override (for example deepseek, openai, ollama, lmstudio).",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Optional rewrite model override.",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Optional rewrite base URL override.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Optional rewrite API key override.",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit with a non-zero status if any mode reports an error.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser()
    sample_count = len(load_writer_skill_eval_manifest(manifest_path))
    if not sample_count:
        raise SystemExit("Writer skill eval manifest did not contain any samples.")

    rewrite_config = _build_rewrite_config(args)
    output_dir = _resolve_output_dir(args.output_dir)

    report = run_writer_skill_eval(
        manifest_path=manifest_path,
        rewrite_config=rewrite_config,
        refresh_samples=args.refresh_samples,
        sample_ids=args.sample_id or None,
    )

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(writer_skill_eval_report_to_dict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(writer_skill_eval_report_to_markdown(report), encoding="utf-8")

    print(f"report.json: {json_path}")
    print(f"report.md: {md_path}")
    print(report.decision_hint)
    if args.fail_on_error and any(summary.error_count > 0 for summary in report.summaries):
        return 1
    return 0


def _build_rewrite_config(args: argparse.Namespace) -> dict[str, object] | None:
    if not args.provider:
        return None
    config: dict[str, object] = {
        "provider": args.provider,
        "model": args.model or None,
        "base_url": args.base_url or None,
        "api_key": args.api_key or None,
        "extra_headers": {},
    }
    return config


def _resolve_output_dir(raw_output_dir: str) -> Path:
    if raw_output_dir.strip():
        return Path(raw_output_dir).expanduser()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_OUTPUT_ROOT / timestamp


if __name__ == "__main__":
    raise SystemExit(main())
