"""SQL for a learner's own flashcards and review history. Data access only; the rules live in the
service (``app.services.flashcards``).

Every query filters on ``user_id`` as well as on the row security the database applies, and all
of it runs in the caller's request transaction as the ``authenticated`` role, so a learner can only
ever reach their own rows. "Now" is the database's transaction time (``now()``), so which cards
are due and when a review happened come from one clock.
"""

from datetime import datetime
from uuid import UUID

from app.core.db import UserConnection
from app.learning.scheduling import Rating, Scheduled
from app.schemas.flashcards import Flashcard, FlashcardReview, FlashcardSummary

_CARD = (
    "id, goal_id, item_id, origin, front, back, due_at, due_at <= now() as is_due,"
    " interval_days, ease_factor::float8 as ease_factor, repetitions, lapses, last_reviewed_at,"
    " scheduler_version, created_at, updated_at"
)
_REVIEW = (
    "id, card_id, rating, scheduler_version, reviewed_at, interval_before,"
    " ease_before::float8 as ease_before, interval_after, ease_after::float8 as ease_after,"
    " due_after"
)


async def database_now(connection: UserConnection) -> datetime:
    cursor = await connection.execute("select now() as now")
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("select now() returned no row")
    return row["now"]


async def insert(
    connection: UserConnection,
    user_id: UUID,
    goal_id: UUID,
    *,
    front: str,
    back: str,
    item_id: UUID | None,
) -> Flashcard:
    cursor = await connection.execute(
        "insert into public.flashcards (user_id, goal_id, item_id, front, back)"  # noqa: S608
        " values (%s, %s, %s, %s, %s)"
        f" returning {_CARD}",
        (user_id, goal_id, item_id, front, back),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("flashcard insert returned no row")
    return Flashcard.model_validate(row)


async def get(
    connection: UserConnection, user_id: UUID, card_id: UUID, *, for_update: bool = False
) -> Flashcard | None:
    """One of the caller's cards. ``for_update`` locks it until the transaction ends, so two
    reviews of the same card cannot both start from the same schedule."""
    lock = " for update" if for_update else ""
    cursor = await connection.execute(
        f"select {_CARD} from public.flashcards where id = %s and user_id = %s{lock}",  # noqa: S608
        (card_id, user_id),
    )
    row = await cursor.fetchone()
    return Flashcard.model_validate(row) if row else None


async def list_for_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID, *, limit: int
) -> list[Flashcard]:
    cursor = await connection.execute(
        f"select {_CARD} from public.flashcards"  # noqa: S608
        " where user_id = %s and goal_id = %s order by created_at desc, id limit %s",
        (user_id, goal_id, limit),
    )
    return [Flashcard.model_validate(row) for row in await cursor.fetchall()]


async def due_for_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID, *, limit: int
) -> list[Flashcard]:
    """Cards whose time has come, the most overdue first."""
    cursor = await connection.execute(
        f"select {_CARD} from public.flashcards"  # noqa: S608
        " where user_id = %s and goal_id = %s and due_at <= now()"
        " order by due_at, created_at, id limit %s",
        (user_id, goal_id, limit),
    )
    return [Flashcard.model_validate(row) for row in await cursor.fetchall()]


async def summary(connection: UserConnection, user_id: UUID, goal_id: UUID) -> FlashcardSummary:
    cursor = await connection.execute(
        "select count(*) as total,"
        " count(*) filter (where c.due_at <= now()) as due_now,"
        " min(c.due_at) filter (where c.due_at > now()) as next_due_at,"
        " (select count(*) from public.flashcard_reviews r"
        "   join public.flashcards rc on rc.id = r.card_id and rc.user_id = r.user_id"
        "   where r.user_id = %(user)s and rc.goal_id = %(goal)s"
        "     and r.reviewed_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'"
        " ) as reviewed_today"
        " from public.flashcards c where c.user_id = %(user)s and c.goal_id = %(goal)s",
        {"user": user_id, "goal": goal_id},
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("flashcard summary returned no row")
    return FlashcardSummary.model_validate(row)


async def topic_belongs_to_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID, item_id: UUID
) -> bool:
    cursor = await connection.execute(
        "select 1 from public.roadmap_items i"
        " join public.roadmaps r on r.id = i.roadmap_id and r.user_id = i.user_id"
        " where i.id = %s and i.user_id = %s and r.goal_id = %s",
        (item_id, user_id, goal_id),
    )
    return await cursor.fetchone() is not None


async def update_text(
    connection: UserConnection,
    user_id: UUID,
    card_id: UUID,
    *,
    front: str | None,
    back: str | None,
    set_item: bool,
    item_id: UUID | None,
) -> Flashcard | None:
    """Change the sides and/or topic. ``front``/``back`` of None keep the stored value;
    ``set_item`` says whether ``item_id`` (possibly None, to detach) replaces the stored topic."""
    cursor = await connection.execute(
        "update public.flashcards set"  # noqa: S608
        " front = coalesce(%(front)s, front), back = coalesce(%(back)s, back),"
        " item_id = case when %(set_item)s then %(item)s else item_id end"
        " where id = %(card)s and user_id = %(user)s"
        f" returning {_CARD}",
        {
            "front": front,
            "back": back,
            "set_item": set_item,
            "item": item_id,
            "card": card_id,
            "user": user_id,
        },
    )
    row = await cursor.fetchone()
    return Flashcard.model_validate(row) if row else None


async def delete(connection: UserConnection, user_id: UUID, card_id: UUID) -> bool:
    cursor = await connection.execute(
        "delete from public.flashcards where id = %s and user_id = %s returning id",
        (card_id, user_id),
    )
    return await cursor.fetchone() is not None


async def count_for_goal(connection: UserConnection, user_id: UUID, goal_id: UUID) -> int:
    cursor = await connection.execute(
        "select count(*) as n from public.flashcards where user_id = %s and goal_id = %s",
        (user_id, goal_id),
    )
    row = await cursor.fetchone()
    return int(row["n"]) if row else 0


async def apply_schedule(
    connection: UserConnection,
    user_id: UUID,
    card_id: UUID,
    scheduled: Scheduled,
    *,
    reviewed_at: datetime,
    scheduler_version: str,
) -> Flashcard:
    cursor = await connection.execute(
        "update public.flashcards set due_at = %(due)s, interval_days = %(interval)s,"  # noqa: S608
        " ease_factor = %(ease)s, repetitions = %(reps)s, lapses = %(lapses)s,"
        " last_reviewed_at = %(at)s, scheduler_version = %(version)s"
        " where id = %(card)s and user_id = %(user)s"
        f" returning {_CARD}",
        {
            "due": scheduled.due_at,
            "interval": scheduled.interval_days,
            "ease": scheduled.ease_factor,
            "reps": scheduled.repetitions,
            "lapses": scheduled.lapses,
            "at": reviewed_at,
            "version": scheduler_version,
            "card": card_id,
            "user": user_id,
        },
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("schedule update returned no row")
    return Flashcard.model_validate(row)


async def insert_review(
    connection: UserConnection,
    user_id: UUID,
    card_id: UUID,
    *,
    rating: Rating,
    scheduler_version: str,
    interval_before: int,
    ease_before: float,
    scheduled: Scheduled,
    idempotency_key: str | None,
) -> FlashcardReview:
    cursor = await connection.execute(
        # `reviewed_at` is not inserted: learners have no privilege on it, so it cannot be
        # backdated, and its default (the transaction's now()) is the same instant the card's
        # `last_reviewed_at` is given.
        "insert into public.flashcard_reviews (user_id, card_id, rating, scheduler_version,"  # noqa: S608
        " interval_before, ease_before, interval_after, ease_after,"
        " repetitions_after, lapses_after, due_after, idempotency_key)"
        " values (%(user)s, %(card)s, %(rating)s, %(version)s, %(ib)s, %(eb)s, %(ia)s,"
        " %(ea)s, %(ra)s, %(la)s, %(due)s, %(key)s)"
        f" returning {_REVIEW}",
        {
            "user": user_id,
            "card": card_id,
            "rating": rating,
            "version": scheduler_version,
            "ib": interval_before,
            "eb": ease_before,
            "ia": scheduled.interval_days,
            "ea": scheduled.ease_factor,
            "ra": scheduled.repetitions,
            "la": scheduled.lapses,
            "due": scheduled.due_at,
            "key": idempotency_key,
        },
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("review insert returned no row")
    return FlashcardReview.model_validate(row)


async def find_review_by_key(
    connection: UserConnection, user_id: UUID, card_id: UUID, key: str
) -> FlashcardReview | None:
    cursor = await connection.execute(
        f"select {_REVIEW} from public.flashcard_reviews"  # noqa: S608
        " where user_id = %s and card_id = %s and idempotency_key = %s",
        (user_id, card_id, key),
    )
    row = await cursor.fetchone()
    return FlashcardReview.model_validate(row) if row else None


async def list_reviews(
    connection: UserConnection, user_id: UUID, card_id: UUID, *, limit: int
) -> list[FlashcardReview]:
    cursor = await connection.execute(
        f"select {_REVIEW} from public.flashcard_reviews"  # noqa: S608
        " where user_id = %s and card_id = %s order by reviewed_at desc, id limit %s",
        (user_id, card_id, limit),
    )
    return [FlashcardReview.model_validate(row) for row in await cursor.fetchall()]
