"""Finding passages: accuracy, the keyword path, "nothing relevant", and who can see what."""

import uuid
from dataclasses import dataclass

import pytest

from app.ai.fake_embedding import hashed_vector
from app.core.db import Database
from app.core.security import Principal
from app.retrieval.search import (
    Passage,
    describe_position,
    keyword_terms,
    search_passages,
    tsquery_any,
)
from support.database import admin, create_auth_user
from support.documents import add_chunk, add_document
from support.rows import add_goal

pytestmark = pytest.mark.anyio

PASSAGES = {
    "ownership": "Ownership is the rule that each value in Rust has exactly one owner, and the "
    "value is dropped when its owner goes out of scope.",
    "borrowing": "Borrowing lets code use a value through a reference without taking ownership. "
    "A mutable reference must be unique.",
    "lifetimes": "Lifetimes describe how long a reference stays valid, so the compiler can reject "
    "dangling pointers.",
    "cooking": "To make risotto, toast the rice in butter, then add warm stock one ladle "
    "at a time.",
    "astronomy": "A light year is the distance light travels in one year, about nine trillion "
    "kilometres.",
    "football": "A football team fields eleven players, and the offside rule restricts attackers.",
}


def principal_for(user_id: uuid.UUID) -> Principal:
    return Principal(
        user_id=user_id,
        email=None,
        claims={"sub": str(user_id), "role": "authenticated", "aud": "authenticated"},
    )


@dataclass
class Library:
    user: uuid.UUID
    goal: uuid.UUID
    document: uuid.UUID
    chunk_ids: dict[str, uuid.UUID]


def build_library(
    dsn: str, passages: dict[str, str] | None = None, *, kind: str = "pdf"
) -> Library:
    user = create_auth_user(dsn)
    goal = add_goal(dsn, user)
    document = add_document(dsn, user, goal, kind=kind)
    ids = {
        name: add_chunk(dsn, user, goal, document, index, text, page_start=index + 1)
        for index, (name, text) in enumerate((passages or PASSAGES).items())
    }
    return Library(user, goal, document, ids)


async def ask(
    database: Database,
    library: Library,
    question: str,
    *,
    limit: int = 3,
    bar: float = 0.1,
    documents: list[uuid.UUID] | None = None,
    as_learner: bool = True,
    user: uuid.UUID | None = None,
) -> list[Passage]:
    """Search as the learner's own request would (row security on) or as the worker (no RLS)."""
    who = user or library.user
    if as_learner:
        async with database.user_transaction(principal_for(who)) as connection:
            return await search_passages(
                connection, user_id=who, goal_id=library.goal, query=question,
                query_vector=hashed_vector(question), limit=limit, min_similarity=bar,
                document_ids=documents,
            )  # fmt: skip
    async with database.system_session() as connection:
        return await search_passages(
            connection, user_id=who, goal_id=library.goal, query=question,
            query_vector=hashed_vector(question), limit=limit, min_similarity=bar,
            document_ids=documents,
        )  # fmt: skip


# --- The query's words ------------------------------------------------------------------------


def test_keyword_terms_drop_filler_punctuation_and_duplicates() -> None:
    terms = keyword_terms("What is the Ownership rule? Ownership, again: (borrowing)!")

    assert terms == ["ownership", "rule", "again", "borrowing"]


def test_keyword_terms_are_bounded_and_cannot_carry_query_syntax() -> None:
    terms = keyword_terms("x' | & ! ( ) <-> evil:* " + " ".join(f"word{n}abc" for n in range(40)))

    assert len(terms) <= 16
    assert all("'" not in term and "\\" not in term for term in terms)
    assert tsquery_any(["ownership", "rust"]) == "'ownership' | 'rust'"


def test_a_question_of_only_filler_has_no_keywords() -> None:
    assert keyword_terms("what is the?") == []
    assert tsquery_any([]) == ""


# --- Accuracy ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What is ownership in Rust, and who owns a value?", "ownership"),
        ("How does borrowing work with a mutable reference?", "borrowing"),
        ("How long does a reference stay valid? Explain lifetimes", "lifetimes"),
        ("How do I cook risotto with stock and rice?", "cooking"),
        ("How far does light travel in a year?", "astronomy"),
        ("How many players does a football team field?", "football"),
    ],
)
async def test_the_most_relevant_passage_comes_first(
    database: Database, database_dsn: str, question: str, expected: str
) -> None:
    library = build_library(database_dsn)

    found = await ask(database, library, question)

    assert found, "a relevant passage should be found"
    assert found[0].chunk_id == library.chunk_ids[expected]
    assert found[0].similarity > 0.2


async def test_results_carry_what_a_citation_needs(database: Database, database_dsn: str) -> None:
    library = build_library(database_dsn)

    (best, *_) = await ask(database, library, "Explain lifetimes and valid references")

    assert best.document_id == library.document
    assert best.document_title == "Rust notes"
    assert best.paginated is True and (best.page_start, best.page_end) == (3, 3)
    assert best.content == PASSAGES["lifetimes"]
    assert describe_position(best) == "p. 3"


async def test_a_passage_spanning_pages_and_a_text_part_are_described_plainly(
    database: Database, database_dsn: str
) -> None:
    library = build_library(database_dsn, {"a": "Alpha beta gamma delta."})
    admin(database_dsn).execute(
        "update public.document_chunks set page_start = 2, page_end = 4 where document_id = %s",
        (library.document,),
    )
    (spanning,) = await ask(database, library, "alpha beta gamma delta")
    assert describe_position(spanning) == "pp. 2\u20134"

    text_library = build_library(database_dsn, {"a": "Alpha beta gamma delta."}, kind="text")
    (part,) = await ask(database, text_library, "alpha beta gamma delta")
    assert describe_position(part) == "part 1"


async def test_the_number_of_results_is_bounded(database: Database, database_dsn: str) -> None:
    library = build_library(database_dsn)

    found = await ask(database, library, "reference value ownership borrowing", limit=2)

    assert len(found) == 2


# --- "The material doesn't cover it" is a real answer -----------------------------------------


async def test_a_question_the_material_does_not_cover_finds_nothing(
    database: Database, database_dsn: str
) -> None:
    library = build_library(database_dsn)

    found = await ask(database, library, "Who won the 1998 World Cup final?", bar=0.3)

    assert found == []


async def test_a_goal_with_no_documents_finds_nothing(
    database: Database, database_dsn: str
) -> None:
    user = create_auth_user(database_dsn)
    empty = Library(user, add_goal(database_dsn, user), uuid.uuid4(), {})

    assert await ask(database, empty, "ownership") == []


async def test_a_shared_filler_word_alone_is_not_evidence(
    database: Database, database_dsn: str
) -> None:
    library = build_library(
        database_dsn, {"cat": "The cat sat on a mat.", "dog": "Dogs bark when the postman comes."}
    )

    found = await ask(database, library, "The quarterly budget forecast", bar=0.3)

    assert found == []


async def test_exact_words_rescue_a_passage_whose_vector_is_only_a_near_miss(
    database: Database, database_dsn: str
) -> None:
    library = build_library(
        database_dsn,
        {
            "near": "alpha beta gamma delta",
            "other": "the cat sat on the mat today",
        },
    )

    # Shares only "alpha" with the question: similarity is 0.25, under the 0.28 bar, but it is a
    # word match, so it qualifies at 85 % of the bar (0.238). The other passage shares only "the".
    found = await ask(database, library, "alpha omega sigma pi the", bar=0.28)

    assert [p.chunk_id for p in found] == [library.chunk_ids["near"]]
    assert found[0].keyword_match is True and 0.2 < found[0].similarity < 0.28


# --- Only documents the learner may see -------------------------------------------------------


async def test_another_learners_passages_are_never_returned(
    database: Database, database_dsn: str
) -> None:
    ada = build_library(database_dsn)
    bob = build_library(database_dsn, {"secret": "Bob's private note about ownership of a boat."})

    for as_learner in (True, False):
        found = await ask(
            database, ada, "ownership of a value, and of a boat", as_learner=as_learner
        )
        assert found and {p.chunk_id for p in found} <= set(ada.chunk_ids.values())
        assert bob.chunk_ids["secret"] not in {p.chunk_id for p in found}


async def test_naming_someone_elses_goal_or_document_finds_nothing(
    database: Database, database_dsn: str
) -> None:
    ada = build_library(database_dsn)
    bob = build_library(database_dsn, {"secret": "Bob's private note about ownership of a boat."})
    question = "ownership of a boat"

    # Ada asks about Bob's goal; Bob's rows are hidden by row security AND by the explicit filter.
    stolen_goal = Library(ada.user, bob.goal, bob.document, bob.chunk_ids)
    for as_learner in (True, False):
        assert await ask(database, stolen_goal, question, as_learner=as_learner) == []

    # Ada asks for Bob's document inside her own goal.
    for as_learner in (True, False):
        found = await ask(database, ada, question, documents=[bob.document], as_learner=as_learner)
        assert found == []


async def test_row_security_alone_hides_other_learners_even_without_the_explicit_filter(
    database: Database, database_dsn: str
) -> None:
    ada = build_library(database_dsn)
    bob = build_library(database_dsn, {"secret": "Bob's private note about ownership of a boat."})

    # The caller (wrongly) claims to be Bob inside Ada's session: the database still says no.
    async with database.user_transaction(principal_for(ada.user)) as connection:
        found = await search_passages(
            connection, user_id=bob.user, goal_id=bob.goal, query="ownership of a boat",
            query_vector=hashed_vector("ownership of a boat"), limit=3, min_similarity=0.1,
        )  # fmt: skip

    assert found == []


async def test_a_document_that_is_not_ready_is_not_searched(
    database: Database, database_dsn: str
) -> None:
    library = build_library(database_dsn)
    admin(database_dsn).execute(
        "update public.source_documents set status = 'review', indexed_at = null where id = %s",
        (library.document,),
    )

    assert await ask(database, library, "What is ownership in Rust?") == []


async def test_a_search_can_be_limited_to_chosen_documents(
    database: Database, database_dsn: str
) -> None:
    library = build_library(database_dsn)
    second = add_document(database_dsn, library.user, library.goal, title="Cooking", kind="text")
    add_chunk(
        database_dsn, library.user, library.goal, second, 0, "Rust ownership of a risotto pan."
    )

    found = await ask(database, library, "ownership", documents=[second])

    assert {p.document_id for p in found} == {second}


async def test_deleted_documents_leave_nothing_to_find(
    database: Database, database_dsn: str
) -> None:
    library = build_library(database_dsn)
    admin(database_dsn).execute(
        "delete from public.source_documents where id = %s", (library.document,)
    )

    assert await ask(database, library, "What is ownership in Rust?", as_learner=False) == []
    left = admin(database_dsn).fetchone(
        "select count(*) as n from public.document_chunks where document_id = %s",
        (library.document,),
    )
    assert left is not None and left["n"] == 0
