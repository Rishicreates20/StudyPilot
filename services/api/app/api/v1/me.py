from fastapi import APIRouter

from app.api.deps import DatabaseDep
from app.core.security import CurrentPrincipal
from app.schemas.profile import Me
from app.services import profiles as profiles_service

router = APIRouter(tags=["me"])


@router.get("/me", response_model=Me, summary="The signed-in user")
async def read_me(principal: CurrentPrincipal, database: DatabaseDep) -> Me:
    """Who the API believes the caller is, derived only from the verified access token."""
    async with database.user_transaction(principal) as connection:
        return await profiles_service.get_me(connection, principal)
