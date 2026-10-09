import structlog

from app.core.db import UserConnection
from app.core.errors import AuthenticationError
from app.core.security import Principal
from app.repositories import profiles as profiles_repo
from app.schemas.profile import Me

log = structlog.get_logger("app.profiles")


async def get_me(connection: UserConnection, principal: Principal) -> Me:
    profile = await profiles_repo.get(connection, principal.user_id)
    if profile is None:
        # A token can outlive its account: access tokens are stateless and stay valid until they
        # expire, but deleting the auth user cascades to the profile. Treat it as signed out.
        log.warning("profile.missing", user_id=str(principal.user_id))
        raise AuthenticationError(
            "This account no longer exists. Sign in again.", code="ACCOUNT_NOT_FOUND"
        )
    return Me(
        id=principal.user_id,
        email=principal.email,
        display_name=profile.display_name,
        locale=profile.locale,
        timezone=profile.timezone,
        created_at=profile.created_at,
    )
