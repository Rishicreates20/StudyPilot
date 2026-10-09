from typing import Annotated

from fastapi import Depends, Request

from app.core.db import Database
from app.core.errors import ServiceUnavailableError


def get_database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise ServiceUnavailableError(
            "The database is not configured on this server.", code="DATABASE_NOT_CONFIGURED"
        )
    return database


DatabaseDep = Annotated[Database, Depends(get_database)]
