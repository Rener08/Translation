import json
from hashlib import sha1
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR


CACHE_ROOT_DIR = ROOT_DIR / "tmp" / "persistent_cache"


def build_cache_key(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha1(serialized.encode("utf-8")).hexdigest()


def load_json_cache(namespace: str, key: str) -> Any | None:
    path = _cache_path(namespace, key)
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def store_json_cache(namespace: str, key: str, payload: object) -> None:
    path = _cache_path(namespace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        return


def cache_file_exists(path_value: str) -> bool:
    return Path(path_value).exists()


def _cache_path(namespace: str, key: str) -> Path:
    return CACHE_ROOT_DIR / namespace / f"{key}.json"
