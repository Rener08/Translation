from fastapi import APIRouter, HTTPException

from app.services.session_history_service import list_session_history, load_session_history
from app.youtube import (
    SessionHistoryDetailResponse,
    SessionHistoryListResponse,
    SessionHistorySummaryResponse,
)


router = APIRouter()


@router.get("/api/session-history", response_model=SessionHistoryListResponse)
async def session_history(limit: int = 20) -> SessionHistoryListResponse:
    return SessionHistoryListResponse(
        ok=True,
        items=[
            SessionHistorySummaryResponse.model_validate(item)
            for item in list_session_history(limit=limit)
        ],
    )


@router.get(
    "/api/session-history/{content_context_id}",
    response_model=SessionHistoryDetailResponse,
)
async def session_history_detail(content_context_id: str) -> SessionHistoryDetailResponse:
    payload = load_session_history(content_context_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Session history not found.")

    return SessionHistoryDetailResponse.model_validate(payload)
