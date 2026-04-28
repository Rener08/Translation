import json
import os
from hashlib import sha1
from pathlib import Path
from typing import Any
import tempfile

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
    temp_name = ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, path)
    except OSError:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
        return


def cache_file_exists(path_value: str) -> bool:
    return Path(path_value).exists()


def _cache_path(namespace: str, key: str) -> Path:
    return CACHE_ROOT_DIR / namespace / f"{key}.json"
