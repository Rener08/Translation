from fastapi import APIRouter, File, UploadFile

from app.api.error_mapping import raise_mapped_http_exception
from app.services.upload_audio_service import save_uploaded_audio_file
from app.youtube import UploadAudioResponse


router = APIRouter()


@router.post(
    "/api/uploads/audio",
    response_model=UploadAudioResponse,
    response_model_exclude_none=True,
)
async def upload_audio(file: UploadFile = File(...)) -> UploadAudioResponse:
    try:
        audio_file_path, title, original_filename, byte_count = await save_uploaded_audio_file(file)
    except Exception as error:
        raise_mapped_http_exception(error)

    return UploadAudioResponse(
        ok=True,
        audio_file_path=audio_file_path,
        title=title,
        original_filename=original_filename,
        media_type=file.content_type,
        byte_count=byte_count,
    )
