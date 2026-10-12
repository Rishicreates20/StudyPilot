"""Finding the learner's own material for a lesson: retrieve passages, label them for the model.

The topic's title, description and objectives are embedded as a question and the learner's ready
documents for THIS goal are searched (privileged connection, so every statement names the learner
explicitly: see ``app.retrieval.search``). The passages that clear the similarity bar become the
lesson's ``source_material``: each gets a short label ("S1" per document, "P1" per passage) that the
model cites, while the real document id, passage id and position stay here for ``ground_lesson`` to
swap in. Nothing is retrieved, and no model call is made, when the goal has no ready documents.
"""

from dataclasses import dataclass

import structlog

from app.ai.calls import CallRecord, call_embed
from app.ai.lesson.context import EvidenceChunk, TopicFacts, without_page_references
from app.ai.provider import EMBEDDING_DIMENSIONS, EmbeddingTask
from app.jobs import queue
from app.jobs.errors import JobFailure
from app.jobs.queue import Job
from app.jobs.runtime import Lease, WorkerEnv, set_stage
from app.retrieval.search import describe_position, search_passages, similarity_bar

log = structlog.get_logger("app.jobs")

# A passage is shown to the model up to this long (chunks are about 1200 characters).
MAX_PASSAGE_CHARS = 2000
MAX_QUERY_CHARS = 1000


@dataclass(frozen=True)
class Evidence:
    chunks: tuple[EvidenceChunk, ...]
    # Whether the goal has any ready documents (so "nothing matched" can be told apart from "none").
    has_documents: bool


def topic_query(facts: TopicFacts) -> str:
    """The question a lesson's topic poses to the learner's material."""
    parts = [facts.title, facts.description, *facts.objectives]
    return without_page_references(" ".join(parts))[:MAX_QUERY_CHARS]


async def ready_documents(env: WorkerEnv, job: Job) -> int:
    async with env.database.system_session() as connection:
        cursor = await connection.execute(
            "select count(*) as total from public.source_documents"
            " where user_id = %s and goal_id = %s and status = 'ready'",
            (job.user_id, job.goal_id),
        )
        row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def gather_evidence(env: WorkerEnv, job: Job, lease: Lease, facts: TopicFacts) -> Evidence:
    provider = env.provider
    if provider is None or await ready_documents(env, job) == 0:
        return Evidence((), False)

    await set_stage(env, job, "searching", 12)
    lease.check()
    query = topic_query(facts)

    async def observe(record: CallRecord) -> None:
        async with env.database.system_session() as connection:
            await queue.record_usage(connection, job, record)

    embedded = await call_embed(
        provider, [query], EmbeddingTask.QUERY, purpose="embed.query", observer=observe
    )
    if len(embedded.vectors) != 1 or len(embedded.vectors[0]) != EMBEDDING_DIMENSIONS:
        raise JobFailure(
            "EMBEDDING_INVALID", "The embedding service returned vectors of the wrong size."
        )
    async with env.database.system_session() as connection:
        found = await search_passages(
            connection,
            user_id=job.user_id,
            goal_id=job.goal_id,
            query=query,
            query_vector=embedded.vectors[0],
            limit=env.settings.retrieval_top_k,
            min_similarity=similarity_bar(env.settings.retrieval_min_similarity, provider.name),
        )

    source_labels: dict[object, str] = {}
    chunks: list[EvidenceChunk] = []
    for number, passage in enumerate(found, start=1):
        label = source_labels.setdefault(passage.document_id, f"S{len(source_labels) + 1}")
        chunks.append(
            EvidenceChunk(
                source_id=label,
                chunk_id=f"P{number}",
                title=passage.document_title,
                text=passage.content[:MAX_PASSAGE_CHARS],
                document_id=str(passage.document_id),
                real_chunk_id=str(passage.chunk_id),
                position=describe_position(passage),
            )
        )
    # Counts only: the topic and the passages are the learner's content and stay out of logs.
    log.info(
        "lesson.evidence", job_id=str(job.id), passages=len(chunks), documents=len(source_labels)
    )
    return Evidence(tuple(chunks), True)
