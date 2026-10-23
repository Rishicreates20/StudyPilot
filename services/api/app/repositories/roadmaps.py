"""SQL for reading a learner's own roadmaps and switching which version is current.

Roadmaps are written only by the worker. From the API's side the content is read-only; the single
write is flipping a version between `current` and `superseded`, which the database restricts to
that one column.
"""

from collections import defaultdict
from uuid import UUID

from app.core.db import ReadConnection, UserConnection
from app.repositories import lessons as lessons_repo
from app.schemas.roadmaps import (
    Objective,
    Roadmap,
    RoadmapItem,
    RoadmapModule,
    RoadmapSummary,
)

# Topics whose lesson the learner has finished (any version of it), counted by the database.
_COMPLETED_TOPICS = """
    (select count(distinct l.item_id)
       from public.lesson_progress p
       join public.lessons l on l.id = p.lesson_id and l.user_id = p.user_id
       join public.roadmap_items i on i.id = l.item_id
      where l.roadmap_id = r.id and l.user_id = r.user_id
        and i.kind = 'topic' and p.status = 'completed')::integer as completed_topics
"""

_SUMMARY_COLUMNS = f"""
    r.id, r.goal_id, r.version, r.status, r.title, r.language, r.topic_count, r.total_minutes,
    r.total_days, r.daily_minutes, r.target_date, r.revision_feedback, r.based_on_roadmap_id,
    r.is_synthetic, r.created_at, {_COMPLETED_TOPICS}
"""


async def list_versions(
    connection: UserConnection, user_id: UUID, goal_id: UUID
) -> list[RoadmapSummary]:
    """Every version of a goal's roadmap, newest first."""
    cursor = await connection.execute(
        f"select {_SUMMARY_COLUMNS} from public.roadmaps r"  # noqa: S608 - a module constant
        " where r.user_id = %s and r.goal_id = %s order by r.version desc",
        (user_id, goal_id),
    )
    return [RoadmapSummary.model_validate(row) for row in await cursor.fetchall()]


async def get_summary(
    connection: UserConnection, user_id: UUID, roadmap_id: UUID, *, for_update: bool = False
) -> RoadmapSummary | None:
    lock = " for update" if for_update else ""
    cursor = await connection.execute(
        f"select {_SUMMARY_COLUMNS} from public.roadmaps r"  # noqa: S608
        f" where r.id = %s and r.user_id = %s{lock}",
        (roadmap_id, user_id),
    )
    row = await cursor.fetchone()
    return RoadmapSummary.model_validate(row) if row else None


async def get_current_id(connection: UserConnection, user_id: UUID, goal_id: UUID) -> UUID | None:
    cursor = await connection.execute(
        "select id from public.roadmaps where user_id = %s and goal_id = %s and status = 'current'",
        (user_id, goal_id),
    )
    row = await cursor.fetchone()
    return row["id"] if row else None


async def get_detail(connection: ReadConnection, user_id: UUID, roadmap_id: UUID) -> Roadmap | None:
    cursor = await connection.execute(
        f"select r.*, {_COMPLETED_TOPICS} from public.roadmaps r"  # noqa: S608
        " where r.id = %s and r.user_id = %s",
        (roadmap_id, user_id),
    )
    head = await cursor.fetchone()
    if head is None:
        return None

    cursor = await connection.execute(
        "select id, position, title, summary from public.roadmap_modules"
        " where roadmap_id = %s and user_id = %s order by position",
        (roadmap_id, user_id),
    )
    module_rows = await cursor.fetchall()

    cursor = await connection.execute(
        "select item_id, prerequisite_id from public.roadmap_item_prerequisites"
        " where roadmap_id = %s and user_id = %s",
        (roadmap_id, user_id),
    )
    prerequisites: dict[UUID, list[UUID]] = defaultdict(list)
    for link in await cursor.fetchall():
        prerequisites[link["item_id"]].append(link["prerequisite_id"])

    cursor = await connection.execute(
        "select id, module_id, kind, position, item_key, title, description, practice_task,"
        " objective_ids, estimated_minutes, day_number from public.roadmap_items"
        " where roadmap_id = %s and user_id = %s order by position",
        (roadmap_id, user_id),
    )
    study = await lessons_repo.study_by_item(connection, user_id, roadmap_id)
    topics_by_module: dict[UUID, list[RoadmapItem]] = defaultdict(list)
    revisions: list[RoadmapItem] = []
    enrichment: list[RoadmapItem] = []
    for row in await cursor.fetchall():
        item = RoadmapItem(
            id=row["id"],
            kind=row["kind"],
            position=row["position"],
            key=row["item_key"],
            title=row["title"],
            description=row["description"],
            practice_task=row["practice_task"],
            objective_ids=list(row["objective_ids"]),
            estimated_minutes=row["estimated_minutes"],
            day_number=row["day_number"],
            prerequisite_ids=sorted(prerequisites.get(row["id"], []), key=str),
            study=study.get(row["id"], lessons_repo.NOT_STARTED),
        )
        if item.kind == "topic":
            topics_by_module[row["module_id"]].append(item)
        elif item.kind == "revision":
            revisions.append(item)
        else:
            enrichment.append(item)

    summary = RoadmapSummary.model_validate(head)
    return Roadmap(
        **summary.model_dump(),
        overview=head["overview"],
        target_outcome=head["target_outcome"],
        syllabus_basis=head["syllabus_basis"],
        assumptions=list(head["assumptions"]),
        unknowns=list(head["unknowns"]),
        objectives=[Objective.model_validate(o) for o in head["objectives"]],
        prompt_version=head["prompt_version"],
        modules=[
            RoadmapModule(
                id=m["id"],
                position=m["position"],
                title=m["title"],
                summary=m["summary"],
                topics=topics_by_module.get(m["id"], []),
            )
            for m in module_rows
        ],
        revision_sessions=revisions,
        enrichment=enrichment,
    )


async def make_current(
    connection: UserConnection, user_id: UUID, goal_id: UUID, roadmap_id: UUID
) -> None:
    """Switch the goal's current version. Two statements in the caller's transaction: the old
    current version is demoted first because at most one version may be current."""
    await connection.execute(
        "update public.roadmaps set status = 'superseded'"
        " where user_id = %s and goal_id = %s and status = 'current' and id <> %s",
        (user_id, goal_id, roadmap_id),
    )
    await connection.execute(
        "update public.roadmaps set status = 'current' where id = %s and user_id = %s",
        (roadmap_id, user_id),
    )
