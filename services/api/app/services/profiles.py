import structlog

from app.core.db import UserConnection
from app.core.errors import AuthenticationError
from app.core.security import Principal
from app.repositories import profiles as profiles_repo
from app.schemas.profile import Me, MeUpdate, Preferences, ProfileRow

log = structlog.get_logger("app.profiles")


def _account_gone() -> AuthenticationError:
    # A token can outlive its account: access tokens are stateless and stay valid until they
    # expire, but deleting the auth user cascades to the profile. Treat it as signed out.
    log.warning("profile.missing")
    return AuthenticationError(
        "This account no longer exists. Sign in again.", code="ACCOUNT_NOT_FOUND"
    )


def _to_me(principal: Principal, profile: ProfileRow) -> Me:
    return Me(
        id=principal.user_id,
        email=principal.email,
        display_name=profile.display_name,
        locale=profile.locale,
        timezone=profile.timezone,
        onboarding_completed=profile.onboarding_completed_at is not None,
        preferences=Preferences(
            default_daily_minutes=profile.default_daily_minutes,
            preferred_languages=profile.preferred_languages,
            learning_preferences=profile.learning_preferences,
        ),
        created_at=profile.created_at,
    )


async def get_me(connection: UserConnection, principal: Principal) -> Me:
    profile = await profiles_repo.get(connection, principal.user_id)
    if profile is None:
        raise _account_gone()
    return _to_me(principal, profile)


async def update_me(connection: UserConnection, principal: Principal, payload: MeUpdate) -> Me:
    current = await profiles_repo.get(connection, principal.user_id)
    if current is None:
        raise _account_gone()
    # Only real changes, so saving an untouched form does not rewrite the row.
    changes = {
        column: value
        for column, value in payload.changes().items()
        if value != getattr(current, column)
    }
    profile = current
    if changes:
        updated = await profiles_repo.update_fields(connection, principal.user_id, changes)
        if updated is None:
            raise _account_gone()
        profile = updated
        log.info("profile.updated", fields=sorted(changes))
    return _to_me(principal, profile)


async def complete_onboarding(connection: UserConnection, principal: Principal) -> Me:
    profile = await profiles_repo.complete_onboarding(connection, principal.user_id)
    if profile is None:
        raise _account_gone()
    log.info("onboarding.completed")
    return _to_me(principal, profile)
