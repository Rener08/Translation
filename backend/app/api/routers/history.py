from fastapi import APIRouter, HTTPException, Request

from app.services.session_history_service import list_session_history, load_session_history
from app.youtube import (
    SessionHistoryDetailResponse,
    SessionHistoryListResponse,
    SessionHistorySummaryResponse,
)


router = APIRouter()


@router.get("/api/session-history", response_model=SessionHistoryListResponse)
async def session_history(
    request: Request,
    limit: int = 20,
) -> SessionHistoryListResponse:
    account_id = str(getattr(request.state, "account_id", "") or "").strip()
    return SessionHistoryListResponse(
        ok=True,
        items=[
            SessionHistorySummaryResponse.model_validate(item)
            for item in list_session_history(limit=limit, account_id=account_id or None)
        ],
    )


@router.get(
    "/api/session-history/{content_context_id}",
    response_model=SessionHistoryDetailResponse,
)
async def session_history_detail(
    request: Request,
    content_context_id: str,
) -> SessionHistoryDetailResponse:
    account_id = str(getattr(request.state, "account_id", "") or "").strip()
    payload = load_session_history(content_context_id, account_id=account_id or None)
    if payload is None:
        raise HTTPException(status_code=404, detail="Session history not found.")

    return SessionHistoryDetailResponse.model_validate(payload)
