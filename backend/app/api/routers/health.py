import os
from pathlib import Path

from fastapi import APIRouter
from fastapi import HTTPException

from app.config import ROOT_DIR, get_settings


router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/livez")
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict[str, object]:
    checks: dict[str, str] = {}
    ok = True

    try:
        cache_root = ROOT_DIR / "tmp"
        cache_root.mkdir(parents=True, exist_ok=True)
        probe_file = cache_root / ".readyz_probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
        checks["tmp_writable"] = "ok"
    except OSError as error:
        ok = False
        checks["tmp_writable"] = f"failed: {error}"

    db_path = get_settings().job_queue_db_path
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            os.utime(db_path, None)
        checks["job_queue_db"] = "ok"
    except OSError as error:
        ok = False
        checks["job_queue_db"] = f"failed: {error}"

    if not ok:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})
    return {"status": "ok", "checks": checks}
