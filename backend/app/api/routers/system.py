from __future__ import annotations

from datetime import datetime
from pathlib import Path
import zipfile

from fastapi import APIRouter

from app.config import ROOT_DIR, get_settings
from app.youtube import SystemExportLogsResponse


router = APIRouter()


@router.get("/api/system/export-logs", response_model=SystemExportLogsResponse)
async def export_logs() -> SystemExportLogsResponse:
    export_dir = ROOT_DIR / "tmp" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    archive_path = export_dir / f"translation-logs-{timestamp}.zip"
    settings = get_settings()
    source_files = [
        settings.backend_log_file,
        settings.frontend_log_file,
    ]

    included: list[str] = []
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in source_files:
            if not file_path.exists() or not file_path.is_file():
                continue
            zf.write(file_path, arcname=file_path.name)
            included.append(file_path.name)

    return SystemExportLogsResponse(
        ok=True,
        archive_path=str(archive_path),
        included_files=included,
    )
