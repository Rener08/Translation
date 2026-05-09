from __future__ import annotations

from typing import Any


def resolve(name: str, default: Any) -> Any:
    from app import main as app_main

    return getattr(app_main, name, default)
