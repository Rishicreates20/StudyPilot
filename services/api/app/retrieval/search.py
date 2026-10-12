"""Finding the passages of a learner's own documents that answer a question.

Two searches run over the same set of rows and their rankings are fused (reciprocal rank fusion):

* **semantic**: the question's embedding against each passage's embedding (cosine similarity,
  exact: the search is always limited to ONE learner's ONE goal, so scanning those rows is cheap
  and there is no shared approximate index that other learners' vectors could crowd out);
* **keyword**: PostgreSQL full-text search with the language-neutral ``simple`` configuration, any
  one of the question's words matching, so exact terms (a function name, a formula) are found even
  when the vectors are vague.

A passage is returned only if the question is really about it: its semantic similarity must reach
``min_similarity``, or it must share words with the question and come close (85 % of that bar).
**No result is a valid answer**: callers must then say that the material does not cover the
question rather than invent support.

Whoever calls this passes the learner's ``user_id``, and every statement filters on it: the API's
connection also has row security on top, the worker's does not, so the filter is not optional.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

# How many candidates each search contributes before they are fused and filtered.
CANDIDATES = 40
# Reciprocal rank fusion constant: the usual 60 keeps one search from dominating the other.
RRF_K = 60
# A passage that matches the question's words need only reach this fraction of the similarity bar.
KEYWORD_SIMILARITY_FACTOR = 0.85
MAX_QUERY_TERMS = 16
MAX_QUERY_CHARS = 2000

_WORD_EDGES = (
    ".,;:!?()[]{}<>\"'`/\\|*^~@#$%&+=-_"
    "\u00b4\u201c\u201d\u2018\u2019\u00ab\u00bb\u2026\u2014\u2013"  # typographic marks
    "\u200b\u200c\u200d"  # zero-width characters
)
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "any",
        "can",
        "had",
        "her",
        "was",
        "one",
        "our",
        "out",
        "has",
        "have",
        "this",
        "that",
        "with",
        "from",
        "they",
        "will",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "does",
        "did",
        "its",
        "into",
        "than",
        "then",
        "them",
        "these",
        "those",
        "their",
        "there",
        "about",
        "would",
        "could",
        "should",
        "also",
        "been",
        "being",
        "were",
        "very",
        "your",
        "just",
    }
)


# The built-in test provider's vectors are word-overlap hashes, not meaning: cosine similarities
# are much lower than a real model's, so its bar is lower too. Real models use the setting.
FAKE_PROVIDER_BAR = 0.1


def similarity_bar(configured: float, provider_name: str) -> float:
    """How similar a passage must be to the question to count, for the provider that embedded it."""
    return min(configured, FAKE_PROVIDER_BAR) if provider_name == "fake" else configured


@dataclass(frozen=True)
class Passage:
    """One retrieved passage with everything needed to cite it. Never built from model output."""

    chunk_id: UUID
    document_id: UUID
    document_title: str
    paginated: bool
    page_start: int
    page_end: int
    section_title: str | None
    content: str
    similarity: float
    keyword_match: bool


def keyword_terms(text: str) -> list[str]:
    """The distinctive words of a question: no punctuation, no filler, no duplicates, bounded."""
    seen: dict[str, None] = {}
    for raw in text[:MAX_QUERY_CHARS].lower().split():
        word = raw.strip(_WORD_EDGES)
        if len(word) < 3 or len(word) > 40 or word in _STOPWORDS:
            continue
        word = word.replace("'", "").replace("\\", "")
        if word:
            seen.setdefault(word, None)
    return list(seen)[:MAX_QUERY_TERMS]


def tsquery_any(terms: Sequence[str]) -> str:
    """A ``to_tsquery`` string matching any term. Terms are quoted, so they cannot add syntax."""
    return " | ".join(f"'{term}'" for term in terms)


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.8g}" for value in vector) + "]"


_SEARCH = """
with
  scope as (
    select c.id, c.embedding, c.fts
    from public.document_chunks c
    join public.source_documents d on d.id = c.document_id and d.user_id = c.user_id
    where c.user_id = %(user)s
      and c.goal_id = %(goal)s
      and d.status = 'ready'
      and (%(documents)s::uuid[] is null or c.document_id = any(%(documents)s::uuid[]))
  ),
  semantic as (
    select id, row_number() over (order by distance) as rank
    from (
      select id, embedding OPERATOR(extensions.<=>) %(vector)s::extensions.vector as distance
      from scope order by distance limit %(candidates)s
    ) nearest
  ),
  keyword as (
    select id, row_number() over (order by score desc, id) as rank
    from (
      select s.id, ts_rank_cd(s.fts, q.query) as score
      from scope s, (select to_tsquery('simple', %(tsquery)s) as query) q
      where %(tsquery)s <> '' and s.fts @@ q.query
      order by score desc limit %(candidates)s
    ) matching
  ),
  fused as (
    select coalesce(s.id, k.id) as id,
           coalesce(1.0 / (%(rrf)s + s.rank), 0) + coalesce(1.0 / (%(rrf)s + k.rank), 0) as fusion,
           k.id is not null as keyword_match
    from semantic s full join keyword k on k.id = s.id
  )
select c.id as chunk_id, c.document_id, d.title as document_title, d.paginated,
       c.page_start, c.page_end, c.section_title, c.content,
       1 - (c.embedding OPERATOR(extensions.<=>) %(vector)s::extensions.vector) as similarity,
       f.keyword_match
from fused f
join public.document_chunks c on c.id = f.id and c.user_id = %(user)s
join public.source_documents d on d.id = c.document_id and d.user_id = c.user_id
where 1 - (c.embedding OPERATOR(extensions.<=>) %(vector)s::extensions.vector)
      >= %(bar)s * case when f.keyword_match
      then %(keyword_factor)s else 1 end
order by f.fusion desc, c.document_id, c.chunk_index
limit %(limit)s
"""


async def search_passages(
    connection: AsyncConnection[DictRow],
    *,
    user_id: UUID,
    goal_id: UUID,
    query: str,
    query_vector: Sequence[float],
    limit: int,
    min_similarity: float,
    document_ids: Sequence[UUID] | None = None,
) -> list[Passage]:
    """The best passages of ``user_id``'s ready documents in ``goal_id`` (maybe none)."""
    cursor = await connection.execute(
        _SEARCH,
        {
            "user": user_id,
            "goal": goal_id,
            "documents": list(document_ids) if document_ids is not None else None,
            "vector": vector_literal(query_vector),
            "tsquery": tsquery_any(keyword_terms(query)),
            "candidates": CANDIDATES,
            "rrf": RRF_K,
            "bar": min_similarity,
            "keyword_factor": KEYWORD_SIMILARITY_FACTOR,
            "limit": limit,
        },
    )
    return [
        Passage(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            document_title=row["document_title"],
            paginated=row["paginated"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            section_title=row["section_title"],
            content=row["content"],
            similarity=float(row["similarity"]),
            keyword_match=row["keyword_match"],
        )
        for row in await cursor.fetchall()
    ]


def position_text(*, paginated: bool, page_start: int, page_end: int) -> str:
    """Where a passage is, in words a learner would use: ``p. 3``, ``pp. 3 to 4`` or ``part 2``."""
    unit = "p." if paginated else "part"
    plural = "pp." if paginated else "parts"
    if page_start == page_end:
        return f"{unit} {page_start}"
    return f"{plural} {page_start}\u2013{page_end}"


def describe_position(passage: Passage) -> str:
    return position_text(
        paginated=passage.paginated, page_start=passage.page_start, page_end=passage.page_end
    )
