#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


ERROR_PATTERNS: list[tuple[str, str]] = [
    (r"HTTP Error 429|Too Many Requests", "rate_limited_429"),
    (r"HTTP Error 403|Forbidden", "forbidden_403"),
    (r"Could not get BotGuard challenge|PoTokenProviderError", "pot_challenge_error"),
    (r"Sign in to confirm you.?re not a bot", "bot_check_signin_required"),
    (r"Requested format is not available", "requested_format_unavailable"),
    (r"This video is unavailable", "video_unavailable"),
    (r"Private video", "private_video"),
    (r"Video unavailable", "video_unavailable"),
    (r"No video formats found", "no_formats"),
]


@dataclass
class CheckResult:
    url: str
    ok: bool
    elapsed_sec: float
    reason: str
    command: list[str]
    output_excerpt: str


def _load_urls(file_path: Path | None, inline_urls: Iterable[str]) -> list[str]:
    urls = [url.strip() for url in inline_urls if url.strip()]
    if not file_path:
        return urls

    if not file_path.exists():
        raise FileNotFoundError(f"URL file not found: {file_path}")

    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def _default_auth_args() -> list[str]:
    # Keep behavior aligned with backend/app/config.py
    cookies_file = (os.getenv("YTDLP_COOKIES_FILE") or "").strip()
    if cookies_file:
        return ["--cookies", cookies_file]

    project_root = Path(__file__).resolve().parents[1]
    default_cookie_file = project_root / "youtube-cookies.txt"
    if default_cookie_file.exists():
        return ["--cookies", str(default_cookie_file)]

    cookies_from_browser = (os.getenv("YTDLP_COOKIES_FROM_BROWSER") or "").strip()
    if cookies_from_browser:
        return ["--cookies-from-browser", cookies_from_browser]

    return []


def _classify_reason(output: str, returncode: int) -> str:
    if returncode == 0:
        return "ok"

    for pattern, label in ERROR_PATTERNS:
        if re.search(pattern, output, flags=re.IGNORECASE):
            return label
    return "unknown_error"


def _build_command(
    url: str,
    fmt: str | None,
    auth_args: list[str],
    extractor_args: str | None,
    yt_dlp_bin: str,
    use_global_config: bool,
) -> list[str]:
    command = [
        yt_dlp_bin,
        *([] if use_global_config else ["--ignore-config"]),
        "--simulate",
        "--check-formats",
        "--no-playlist",
        "--no-warnings",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
    ]
    if fmt:
        command.extend(["--format", fmt])
    if extractor_args:
        command.extend(["--extractor-args", extractor_args])
    command.extend(auth_args)
    command.append(url)
    return command


def _run_check(command: list[str], timeout_sec: int) -> tuple[int, str, float]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    elapsed = time.monotonic() - started
    output = ((completed.stderr or "") + "\n" + (completed.stdout or "")).strip()
    return completed.returncode, output, elapsed


def _run_one(
    url: str,
    fmt: str | None,
    auth_args: list[str],
    extractor_args: str | None,
    yt_dlp_bin: str,
    timeout_sec: int,
    use_global_config: bool,
) -> CheckResult:
    command = _build_command(
        url=url,
        fmt=fmt,
        auth_args=auth_args,
        extractor_args=extractor_args,
        yt_dlp_bin=yt_dlp_bin,
        use_global_config=use_global_config,
    )
    started = time.monotonic()
    try:
        returncode, output, elapsed = _run_check(command, timeout_sec=timeout_sec)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        excerpt = ((exc.stderr or "") + "\n" + (exc.stdout or "")).strip()
        return CheckResult(
            url=url,
            ok=False,
            elapsed_sec=elapsed,
            reason="timeout",
            command=command,
            output_excerpt=excerpt[:500],
        )

    reason = _classify_reason(output, returncode)
    return CheckResult(
        url=url,
        ok=returncode == 0,
        elapsed_sec=elapsed,
        reason=reason,
        command=command,
        output_excerpt=output[:500],
    )


def _print_results(results: list[CheckResult]) -> None:
    print("=== YouTube Downloadability Check ===")
    print(f"Total: {len(results)}")
    print("")

    for idx, result in enumerate(results, start=1):
        status = "OK" if result.ok else "FAIL"
        print(f"[{idx}] {status} ({result.elapsed_sec:.2f}s) {result.url}")
        print(f"    reason: {result.reason}")
        if result.output_excerpt and not result.ok:
            sanitized = result.output_excerpt.replace("\n", " | ")
            print(f"    output: {sanitized[:240]}")
        print("")

    ok_count = sum(1 for item in results if item.ok)
    fail_count = len(results) - ok_count
    print(f"Summary: OK={ok_count}, FAIL={fail_count}")


def _resolve_auth_args(
    cookies_file: str | None,
    cookies_from_browser: str | None,
) -> list[str]:
    if cookies_file:
        return ["--cookies", cookies_file]
    if cookies_from_browser:
        return ["--cookies-from-browser", cookies_from_browser]
    return _default_auth_args()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch-check which YouTube URLs are currently downloadable by yt-dlp.",
    )
    parser.add_argument("urls", nargs="*", help="YouTube URLs to test")
    parser.add_argument(
        "-f",
        "--file",
        type=Path,
        help="Text file containing one URL per line (# comments supported).",
    )
    parser.add_argument(
        "--format",
        default=None,
        help="Optional yt-dlp format expression, e.g. 'b/bv*+ba'.",
    )
    parser.add_argument(
        "--cookies",
        help="Path to cookies file. Overrides env defaults.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        help="Browser profile source, e.g. chrome or 'chrome:Default'. Overrides env defaults.",
    )
    parser.add_argument(
        "--extractor-args",
        help='Pass-through extractor args, e.g. \'youtube:player-client=web_safari;data_sync_id=XXX||\'',
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-URL timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--yt-dlp-bin",
        default="yt-dlp",
        help="yt-dlp executable path/name (default: yt-dlp).",
    )
    parser.add_argument(
        "--use-global-config",
        action="store_true",
        help="Use yt-dlp global config (~/.config/yt-dlp/config). Default is ignored for stable checks.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional output JSON file path.",
    )
    args = parser.parse_args()

    try:
        urls = _load_urls(args.file, args.urls)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not urls:
        parser.print_help()
        return 2

    auth_args = _resolve_auth_args(
        cookies_file=args.cookies,
        cookies_from_browser=args.cookies_from_browser,
    )

    results: list[CheckResult] = []
    for url in urls:
        result = _run_one(
            url=url,
            fmt=args.format,
            auth_args=auth_args,
            extractor_args=args.extractor_args,
            yt_dlp_bin=args.yt_dlp_bin,
            timeout_sec=args.timeout,
            use_global_config=args.use_global_config,
        )
        results.append(result)

    _print_results(results)

    if args.json_out:
        payload = [asdict(item) for item in results]
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON report written to: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
