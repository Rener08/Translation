import logging

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.error_mapping import raise_mapped_http_exception
from app.api.runtime_deps import get_discover_provider_models
from app.youtube import (
    ProviderModelsRequest,
    ProviderModelsResponse,
    ProviderTestConnectionRequest,
    ProviderTestConnectionResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/provider-models", response_model=ProviderModelsResponse)
async def provider_models(
    request: ProviderModelsRequest,
    discover_provider_models_fn=Depends(get_discover_provider_models),
) -> ProviderModelsResponse:
    try:
        models = await run_in_threadpool(
            discover_provider_models_fn,
            provider=request.provider,
            base_url=request.base_url or "",
            api_key=request.api_key or "",
            extra_headers=request.extra_headers,
        )
    except Exception as error:
        logger.exception("Failed to discover provider models for %s", request.provider)
        raise_mapped_http_exception(error)

    return ProviderModelsResponse(ok=True, provider=request.provider, models=models)


@router.post(
    "/api/provider/test-connection",
    response_model=ProviderTestConnectionResponse,
)
async def test_provider_connection(
    request: ProviderTestConnectionRequest,
    discover_provider_models_fn=Depends(get_discover_provider_models),
) -> ProviderTestConnectionResponse:
    try:
        models = await run_in_threadpool(
            discover_provider_models_fn,
            provider=request.provider,
            base_url=request.base_url or "",
            api_key=request.api_key or "",
            extra_headers=request.extra_headers,
        )
    except Exception as error:
        logger.exception("Provider connectivity test failed for %s", request.provider)
        raise_mapped_http_exception(error)

    selected_model = (request.model or "").strip() or (models[0] if models else None)
    return ProviderTestConnectionResponse(
        ok=True,
        provider=request.provider,
        reachable=True,
        selected_model=selected_model,
        discovered_models=models,
        message="连接成功。",
    )
