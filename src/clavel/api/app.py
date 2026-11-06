"""Run with uvicorn clavel.api.app:create_app --factory."""

from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from clavel.api.inventory import (
    InventoryCursors, InventoryRuntime, InventoryUnavailable, InventoryUnavailableResponse,
    router as inventory_router,
)
from clavel.core.correlation import RequestCorrelationMiddleware
from clavel.core.errors import ApplicationError, ErrorCode, ErrorResponse, error_response
from clavel.core.settings import Settings, load_settings
from clavel.database import Database


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


def create_app(
    *, settings: Settings | None = None,
    inventory_runtime: InventoryRuntime | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings if settings is not None else load_settings()
        app.state.database = Database(app.state.settings)
        app.state.inventory_runtime = inventory_runtime or InventoryRuntime()
        yield

    app = FastAPI(title="Clavel", lifespan=lifespan, debug=False)
    app.state.inventory_cursors = InventoryCursors()
    app.add_middleware(RequestCorrelationMiddleware)
    app.include_router(inventory_router)

    @app.exception_handler(InventoryUnavailable)
    async def inventory_unavailable(request: Request, exc: InventoryUnavailable) -> JSONResponse:
        body = InventoryUnavailableResponse(
            retryable=exc.retryable, request_id=request.state.request_id,
        )
        return JSONResponse(status_code=503, content=body.model_dump(mode="json"))

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return error_response(request, exc.code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(request, ErrorCode.VALIDATION_ERROR)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = {
            400: ErrorCode.BAD_REQUEST,
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.METHOD_NOT_ALLOWED,
        }.get(exc.status_code, ErrorCode.HTTP_ERROR)
        response = error_response(request, code, status_code=exc.status_code)
        # Preserve the router's required method metadata, never arbitrary headers.
        if exc.status_code == 405 and exc.headers and "Allow" in exc.headers:
            response.headers["Allow"] = exc.headers["Allow"]
        return response

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return error_response(request, ErrorCode.INTERNAL_ERROR)

    @app.get(
        "/health",
        response_model=HealthResponse,
        responses={500: {"model": ErrorResponse}},
    )
    async def health() -> HealthResponse:
        """Process liveness only; does not access PostgreSQL or external services."""
        return HealthResponse()

    @app.get(
        "/ready",
        response_model=HealthResponse,
        responses={503: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def ready(request: Request) -> HealthResponse:
        """Readiness requires PostgreSQL; blocking I/O runs in the thread pool."""
        if not request.app.state.database.is_ready():
            raise ApplicationError(ErrorCode.DATABASE_UNAVAILABLE)
        return HealthResponse()

    return app
