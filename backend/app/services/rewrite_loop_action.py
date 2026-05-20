from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


LoopActionKind = Literal["collect_evidence", "outline", "draft", "re_ground", "expand", "patch", "stop"]
ALLOWED_LOOP_ACTION_KINDS: tuple[LoopActionKind, ...] = (
    "collect_evidence",
    "outline",
    "draft",
    "re_ground",
    "expand",
    "patch",
    "stop",
)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_metadata(value: Any) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _coerce_loop_action_kind(value: Any) -> LoopActionKind:
    normalized = _normalize_text(value)
    if normalized not in ALLOWED_LOOP_ACTION_KINDS:
        raise ValueError(f"Unsupported loop action kind: {value!r}")
    return normalized  # type: ignore[return-value]


def migrate_loop_action_snapshot(snapshot: Any) -> dict[str, object]:
    if isinstance(snapshot, LoopAction):
        return snapshot.to_snapshot()
    if not isinstance(snapshot, Mapping):
        return {
            "kind": "stop",
            "reason": "",
            "prompt": "",
            "metadata": {},
        }
    try:
        kind = _coerce_loop_action_kind(snapshot.get("kind", "stop"))
    except ValueError:
        kind = "stop"
    return {
        "kind": kind,
        "reason": _normalize_text(snapshot.get("reason")),
        "prompt": _normalize_text(snapshot.get("prompt")),
        "metadata": _normalize_metadata(snapshot.get("metadata")),
    }


@dataclass(frozen=True)
class LoopAction:
    kind: LoopActionKind
    reason: str
    prompt: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_loop_action_kind(self.kind))
        object.__setattr__(self, "reason", _normalize_text(self.reason))
        object.__setattr__(self, "prompt", _normalize_text(self.prompt))
        object.__setattr__(self, "metadata", _normalize_metadata(self.metadata))

    def to_snapshot(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "prompt": self.prompt,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> LoopAction:
        data = migrate_loop_action_snapshot(snapshot)
        return cls(
            kind=data["kind"],  # type: ignore[arg-type]
            reason=data["reason"],
            prompt=data["prompt"],
            metadata=data["metadata"],
        )
