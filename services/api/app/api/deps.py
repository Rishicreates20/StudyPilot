from typing import Annotated

from fastapi import Depends, Request

from app.ai.provider import LLMProvider
from app.core.db import Database
from app.core.errors import ServiceUnavailableError
from app.core.rate_limit import SlidingWindowLimiter
from app.documents.storage import DocumentFiles
from app.exports.files import ExportFiles


def get_database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise ServiceUnavailableError(
            "The database is not configured on this server.", code="DATABASE_NOT_CONFIGURED"
        )
    return database


DatabaseDep = Annotated[Database, Depends(get_database)]


def get_files(request: Request) -> DocumentFiles | None:
    """The configured file store, or None when storage isn't set up (uploads are then refused)."""
    return request.app.state.files


def get_export_files(request: Request) -> ExportFiles | None:
    """The store for exported files, or None when storage isn't set up (exports are refused)."""
    return request.app.state.export_files


def get_provider(request: Request) -> LLMProvider | None:
    """The model provider the API uses for one thing only: embedding a search question."""
    return request.app.state.provider


def get_search_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.search_limiter


FilesDep = Annotated[DocumentFiles | None, Depends(get_files)]
ExportFilesDep = Annotated[ExportFiles | None, Depends(get_export_files)]
ProviderDep = Annotated[LLMProvider | None, Depends(get_provider)]
SearchLimiterDep = Annotated[SlidingWindowLimiter, Depends(get_search_limiter)]
