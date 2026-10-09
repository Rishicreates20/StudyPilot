from uuid import UUID

from app.core.db import UserConnection
from app.schemas.profile import ProfileRow


async def get(connection: UserConnection, user_id: UUID) -> ProfileRow | None:
    cursor = await connection.execute(
        "select id, display_name, locale, timezone, created_at from public.profiles where id = %s",
        (user_id,),
    )
    row = await cursor.fetchone()
    return ProfileRow.model_validate(row) if row else None
