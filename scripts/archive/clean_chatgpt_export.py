#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LEADING_NOISE_PATTERNS = (
    re.compile(
        r"^(Browsing|Reading|Exploring|Searching|Opening|Requesting|Inspecting|Clarifying|Planning|Analyzing|Suggesting|Citing)\b"
    ),
    re.compile(r"^GitHub - "),
    re.compile(r"^raw\.githubusercontent\.com$"),
    re.compile(r"^Translation/.+GitHub$"),
    re.compile(r"^Thought for \d+s$"),
    re.compile(r"^I[’']m\b"),
    re.compile(r"^The user is\b"),
)


@dataclass
class CleanResult:
    text: str
    removed_prefix_lines: int


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return any(pattern.search(stripped) for pattern in LEADING_NOISE_PATTERNS)


def is_substantive_response_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^[\u4e00-\u9fff]", stripped):
        return True
    if re.match(r"^\d+[.、]\s*[\u4e00-\u9fffA-Za-z]", stripped):
        return True
    if re.match(r"^(flowchart|erDiagram|```|#)", stripped):
        return True
    return False


def clean_assistant_text(text: str) -> CleanResult:
    normalized = normalize_text(text)
    if not normalized:
        return CleanResult(text="", removed_prefix_lines=0)

    lines = normalized.split("\n")
    index = 0
    removed = 0
    while index < len(lines):
        current = lines[index].strip()
        if is_noise_line(current):
            removed += 1
            index += 1
            continue
        if not is_substantive_response_start(current):
            removed += 1
            index += 1
            continue
        break

    cleaned = "\n".join(lines[index:]).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return CleanResult(text=cleaned, removed_prefix_lines=removed)


def clean_prompt_text(text: str) -> str:
    return normalize_text(text)


def load_export(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cleaned_messages: list[dict[str, Any]] = []
    removed_prefix_total = 0
    emptied_messages = 0

    for index, message in enumerate(messages):
        role = str(message.get("role", "")).strip()
        content = str(message.get("say", ""))
        time_value = str(message.get("time", "")).strip()

        if role == "Response":
            result = clean_assistant_text(content)
            cleaned = result.text
            removed_prefix_total += result.removed_prefix_lines
        else:
            cleaned = clean_prompt_text(content)

        if not cleaned:
            emptied_messages += 1
            continue

        cleaned_messages.append(
            {
                "index": index,
                "role": "user" if role == "Prompt" else "assistant",
                "source_role": role,
                "time": time_value,
                "content": cleaned,
            }
        )

    stats = {
        "raw_messages": len(messages),
        "cleaned_messages": len(cleaned_messages),
        "removed_prefix_lines": removed_prefix_total,
        "dropped_empty_messages": emptied_messages,
    }
    return cleaned_messages, stats


def build_markdown(
    *,
    source_path: Path,
    metadata: dict[str, Any],
    cleaned_messages: list[dict[str, Any]],
    stats: dict[str, int],
) -> str:
    lines: list[str] = []
    title = str(metadata.get("title") or source_path.stem)
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Source")
    lines.append(f"- File: `{source_path}`")
    link = str(metadata.get("link") or "").strip()
    if link:
        lines.append(f"- Link: {link}")
    dates = metadata.get("dates") or {}
    if isinstance(dates, dict):
        for key in ("created", "updated", "exported"):
            value = str(dates.get(key) or "").strip()
            if value:
                lines.append(f"- {key.capitalize()}: {value}")
    lines.append("")
    lines.append("## Cleaning Stats")
    for key, value in stats.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Prompt Outline")
    prompt_count = 0
    for message in cleaned_messages:
        if message["role"] != "user":
            continue
        prompt_count += 1
        outline = " ".join(str(message["content"]).split())
        lines.append(f"{prompt_count}. {outline[:220]}")
    lines.append("")
    lines.append("## Cleaned Transcript")

    turn_number = 0
    for message in cleaned_messages:
        if message["role"] == "user":
            turn_number += 1
        role_label = "User" if message["role"] == "user" else "Assistant"
        time_label = f" · {message['time']}" if message.get("time") else ""
        lines.append("")
        lines.append(f"### Turn {turn_number} · {role_label}{time_label}")
        lines.append("")
        lines.append(message["content"])

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean a ChatGPT Exporter JSON transcript.")
    parser.add_argument("input", help="Path to the exported JSON file")
    parser.add_argument(
        "--output-prefix",
        help="Optional output prefix without extension. Defaults to <input>.cleaned",
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    payload = load_export(input_path)
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        raise SystemExit("Unsupported export format: missing messages array.")

    cleaned_messages, stats = clean_messages(messages)

    output_prefix = (
        Path(args.output_prefix).expanduser().resolve()
        if args.output_prefix
        else input_path.with_suffix("")
    )
    json_output = output_prefix.parent / f"{output_prefix.name}.cleaned.json"
    md_output = output_prefix.parent / f"{output_prefix.name}.cleaned.md"

    cleaned_payload = {
        "metadata": metadata,
        "source_file": str(input_path),
        "stats": stats,
        "messages": cleaned_messages,
    }
    json_output.write_text(
        json.dumps(cleaned_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_output.write_text(
        build_markdown(
            source_path=input_path,
            metadata=metadata if isinstance(metadata, dict) else {},
            cleaned_messages=cleaned_messages,
            stats=stats,
        ),
        encoding="utf-8",
    )

    print(json_output)
    print(md_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
