from fastapi import APIRouter

from app.api.deps import DatabaseDep
from app.core.security import CurrentPrincipal
from app.schemas.profile import Me, MeUpdate
from app.services import profiles as profiles_service

router = APIRouter(tags=["me"])


@router.get("/me", response_model=Me, summary="The signed-in user")
async def read_me(principal: CurrentPrincipal, database: DatabaseDep) -> Me:
    """Who the API believes the caller is, derived only from the verified access token."""
    async with database.user_transaction(principal) as connection:
        return await profiles_service.get_me(connection, principal)


@router.patch("/me", response_model=Me, summary="Update the caller's profile and preferences")
async def update_me(payload: MeUpdate, principal: CurrentPrincipal, database: DatabaseDep) -> Me:
    """Changes only the fields sent. Preferences pre-fill new goals; they never alter old ones."""
    async with database.user_transaction(principal) as connection:
        return await profiles_service.update_me(connection, principal, payload)


@router.post("/me/onboarding/complete", response_model=Me, summary="Finish (or skip) onboarding")
async def complete_onboarding(principal: CurrentPrincipal, database: DatabaseDep) -> Me:
    """Marks onboarding as done. Calling it again is harmless; the first time is kept."""
    async with database.user_transaction(principal) as connection:
        return await profiles_service.complete_onboarding(connection, principal)
