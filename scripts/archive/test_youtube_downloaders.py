#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    ok: bool
    elapsed_sec: float
    reason: str
    command: str
    output_excerpt: str


def _run(
    name: str,
    cmd: list[str],
    timeout_sec: int,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> CheckResult:
    started = time.monotonic()
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        elapsed = time.monotonic() - started
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        output = ((exc.stderr or "") + "\n" + (exc.stdout or "")).strip()
        return CheckResult(
            name=name,
            ok=False,
            elapsed_sec=elapsed,
            reason="timeout",
            command=" ".join(shlex.quote(part) for part in cmd),
            output_excerpt=output[:1000],
        )

    output = ((p.stderr or "") + "\n" + (p.stdout or "")).strip()
    reason = "ok" if p.returncode == 0 else f"exit_{p.returncode}"
    detected_error = False
    lowered = output.lower()
    if "error:" in lowered or "traceback" in lowered:
        detected_error = True
    if "Too Many Requests" in output or "HTTP Error 429" in output:
        reason = "rate_limited_429"
        detected_error = True
    if "HTTP Error 403" in output or "Forbidden" in output:
        reason = "forbidden_403"
        detected_error = True
    if "not a bot" in output:
        reason = "bot_check"
        detected_error = True
    if "ConnectionRefused" in output or "Unable to connect" in output:
        reason = "connection_refused"
        detected_error = True
    if "No valid URL to decipher" in output:
        reason = "signature_decipher_failed"
        detected_error = True
    if "Missing required Data Sync ID" in output:
        reason = "missing_data_sync_id"
        detected_error = True

    return CheckResult(
        name=name,
        ok=p.returncode == 0 and not detected_error,
        elapsed_sec=elapsed,
        reason=reason,
        command=" ".join(shlex.quote(part) for part in cmd),
        output_excerpt=output[:1000],
    )


def _python_probe_pytubefix(url: str, timeout_sec: int) -> CheckResult:
    code = f"""
from pytubefix import YouTube
yt = YouTube({url!r})
print(yt.title)
"""
    return _run(
        name="pytubefix_probe",
        cmd=["python3", "-c", code],
        timeout_sec=timeout_sec,
    )


def _proxy_env() -> dict[str, str]:
    env = os.environ.copy()
    proxies = urllib.request.getproxies()
    proxy = proxies.get("https") or proxies.get("http")
    if proxy:
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            env[key] = proxy
    return env


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run multiple downloader backends against one YouTube URL and report what works.",
    )
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--cookies-from-browser", default="chrome")
    parser.add_argument(
        "--ypd-repo",
        type=Path,
        default=Path("/Users/jack/Documents/coding/Translation/tmp/repo_checks/youtube-playlist-downloader"),
        help="Path to youtube-playlist-downloader repository",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/Users/jack/Documents/coding/Translation/tmp/downloader_checks"),
        help="Directory for temporary downloads",
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    results: list[CheckResult] = []

    yt_sim = [
        "yt-dlp",
        "--ignore-config",
        "--simulate",
        "--check-formats",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--no-playlist",
        "--cookies-from-browser",
        args.cookies_from_browser,
        args.url,
    ]
    results.append(_run("yt-dlp_simulate", yt_sim, args.timeout))

    yt_dl = [
        "yt-dlp",
        "--ignore-config",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--no-playlist",
        "--cookies-from-browser",
        args.cookies_from_browser,
        "-f",
        "18",
        "-o",
        str(args.output_dir / "yt_dlp_18.%(ext)s"),
        args.url,
    ]
    results.append(_run("yt-dlp_download_f18", yt_dl, args.timeout))

    results.append(
        _run(
            "you-get_info",
            ["you-get", "--debug", "--info", args.url],
            args.timeout,
        )
    )

    results.append(_python_probe_pytubefix(args.url, args.timeout))

    if args.ypd_repo.exists():
        ypd_cmd = [
            "bun",
            "run",
            "cli:video",
            "--video-id",
            args.url.split("v=")[-1].split("&")[0],
            "--output-folder",
            str(args.output_dir / "ypd"),
        ]
        (args.output_dir / "ypd").mkdir(parents=True, exist_ok=True)
        results.append(
            _run(
                "youtube-playlist-downloader_cli-video",
                ypd_cmd,
                args.timeout,
                cwd=args.ypd_repo,
                env=_proxy_env(),
            )
        )

    print("=== Downloader Check ===")
    print(f"URL: {args.url}")
    print("")
    for r in results:
        status = "OK" if r.ok else "FAIL"
        print(f"[{status}] {r.name} ({r.elapsed_sec:.2f}s) reason={r.reason}")
        if not r.ok and r.output_excerpt:
            print(f"  {r.output_excerpt.replace(chr(10), ' | ')[:260]}")
    ok_count = sum(1 for r in results if r.ok)
    print("")
    print(f"Summary: OK={ok_count}, FAIL={len(results) - ok_count}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON report written to: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
