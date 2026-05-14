from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SkillOutputSpec:
    min_chars: int
    target_chars: int
    max_chars: int
    min_sections: int
    max_sections: int


@dataclass(frozen=True)
class StyleConstraint:
    constraint_type: str  # "forbidden_word", "forbidden_punctuation", "perspective_marker"
    pattern: str
    fix_hint: str
    enabled: bool = True


@dataclass(frozen=True)
class SkillConfig:
    style_name: str
    perspective: str
    output: SkillOutputSpec
    constraints: tuple[StyleConstraint, ...]
    perspective_markers: tuple[str, ...]
    template_routing_enabled: bool
    content_filters: tuple[str, ...]
    quality_layers: tuple[dict, ...]


def load_skill_config(path: Path) -> SkillConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    output_raw = raw["output"]
    sections = output_raw.get("sections", {})
    output = SkillOutputSpec(
        min_chars=output_raw.get("min_chars", 0),
        target_chars=output_raw.get("target_chars", 0),
        max_chars=output_raw.get("max_chars", 0),
        min_sections=sections.get("min", 0),
        max_sections=sections.get("max", 0),
    )

    constraints: list[StyleConstraint] = []

    for word in raw.get("forbidden_words", []):
        constraints.append(StyleConstraint(
            constraint_type="forbidden_word",
            pattern=word,
            fix_hint="",
        ))

    for entry in raw.get("forbidden_punctuation", []):
        pattern = entry.get("char", "")
        constraints.append(StyleConstraint(
            constraint_type="forbidden_punctuation",
            pattern=pattern,
            fix_hint=entry.get("replace_with", ""),
        ))

    for marker in raw.get("perspective_markers", []):
        constraints.append(StyleConstraint(
            constraint_type="perspective_marker",
            pattern=marker,
            fix_hint="",
        ))

    content_filters_raw = raw.get("content_filters", [])
    quality_layers_raw = raw.get("quality_layers", [])

    return SkillConfig(
        style_name=raw.get("style_name", ""),
        perspective=raw.get("perspective", ""),
        output=output,
        constraints=tuple(constraints),
        perspective_markers=tuple(raw.get("perspective_markers", [])),
        template_routing_enabled=raw.get("template_routing_enabled", False),
        content_filters=tuple(content_filters_raw),
        quality_layers=tuple(quality_layers_raw),
    )


BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent  # backend/
REFERENCES_DIR = BACKEND_ROOT.parent / "references"


def load_default_skill_config() -> SkillConfig:
    return load_skill_config(REFERENCES_DIR / "config.yaml")


def resolve_skill_config(skill_dir: Path | None = None, config_name: str | None = None) -> SkillConfig:
    if skill_dir is not None:
        config_path = skill_dir / "config.yaml"
        if config_path.exists():
            return load_skill_config(config_path)

    if config_name is not None:
        config_path = REFERENCES_DIR / f"config_{config_name}.yaml"
        if config_path.exists():
            return load_skill_config(config_path)

    return load_default_skill_config()
