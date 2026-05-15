from fastapi import APIRouter

from app.api.routers import (
    content,
    health,
    history,
    jobs,
    provider_models,
    system,
    transcription,
    translation,
    upload,
    video,
)


def build_api_router() -> APIRouter:
    router = APIRouter()
    router.include_router(health.router)
    router.include_router(provider_models.router)
    router.include_router(video.router)
    router.include_router(upload.router)
    router.include_router(transcription.router)
    router.include_router(translation.router)
    router.include_router(content.router)
    router.include_router(history.router)
    router.include_router(jobs.router)
    router.include_router(system.router)
    return router
