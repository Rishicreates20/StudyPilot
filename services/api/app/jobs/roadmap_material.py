"""Reading a goal's ready documents for the roadmap planner: where each passage sits, no text.

Privileged like the rest of the worker, so the statement names the learner and the goal explicitly.
Only documents that finished processing (``ready``) count; one still being read or waiting for the
learner's review is not part of the plan yet, and the plan says so by not mentioning it.
"""

from typing import Any
from uuid import UUID

from app.ai.roadmap.material import MAX_DOCUMENTS, ChunkRef, MaterialDocument, build_material
from app.core.db import SystemConnection

_SQL = """
with picked as (
  select id, title, paginated, page_count, created_at
  from public.source_documents
  where user_id = %(user_id)s and goal_id = %(goal_id)s and status = 'ready'
  order by created_at, id
  limit %(limit)s
)
select p.id as document_id, p.title, p.paginated, p.page_count,
       c.id as chunk_id, c.page_start, c.page_end, c.section_title
from picked p
join public.document_chunks c on c.document_id = p.id and c.user_id = %(user_id)s
order by p.created_at, p.id, c.chunk_index
"""


async def load_material(
    connection: SystemConnection, user_id: UUID, goal_id: UUID
) -> tuple[MaterialDocument, ...]:
    cursor = await connection.execute(
        _SQL, {"user_id": user_id, "goal_id": goal_id, "limit": MAX_DOCUMENTS}
    )
    rows: list[dict[str, Any]] = await cursor.fetchall()
    return build_material(
        [
            ChunkRef(
                document_id=str(row["document_id"]),
                document_title=row["title"],
                paginated=row["paginated"],
                page_count=row["page_count"],
                chunk_id=str(row["chunk_id"]),
                page_start=row["page_start"],
                page_end=row["page_end"],
                section_title=row["section_title"],
            )
            for row in rows
        ]
    )
