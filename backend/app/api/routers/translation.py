from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from app.api.error_mapping import raise_mapped_http_exception
from app.api.runtime_deps import resolve
from app.services.translation_service import translate_segments_to_chinese
from app.youtube import TranslateItemResponse, TranslateRequest, TranslateResponse


router = APIRouter()


@router.post("/api/translate", response_model=TranslateResponse)
async def translate_segments(request: TranslateRequest) -> TranslateResponse:
    try:
        translations = await run_in_threadpool(
            resolve("translate_segments_to_chinese", translate_segments_to_chinese),
            [segment.model_dump() for segment in request.segments],
            translation_config=(
                request.translation_config.model_dump()
                if request.translation_config
                else None
            ),
        )
    except Exception as error:
        raise_mapped_http_exception(error)

    return TranslateResponse(
        ok=True,
        translations=[
            TranslateItemResponse(
                index=item.index,
                start=item.start,
                end=item.end,
                source_text=item.source_text,
                translated_text=item.translated_text,
            )
            for item in translations
        ],
    )
