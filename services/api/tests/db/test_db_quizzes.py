"""Quizzes, answers and mastery in the database: who can read or write what, and what holds."""

import uuid
from typing import Any

import psycopg.errors
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from support.database import admin, create_auth_user
from support.lessons import Seeded, add_lesson_job, seed_learning_state
from support.quizzes import StoredQuiz, add_stored_quiz
from support.rows import add_goal, add_job, add_lesson

INSERT_QUIZ_JOB = (
    "insert into public.generation_jobs (user_id, goal_id, item_id, job_type)"
    " values (%s, %s, %s, 'quiz') returning *"
)
CONSTRAINT_VIOLATIONS = (psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)
CLIENT_TABLES = ["quizzes", "questions", "quiz_attempts", "quiz_answers", "topic_mastery"]


@pytest.fixture
def seeded(database_dsn: str) -> Seeded:
    return seed_learning_state(database_dsn)


@pytest.fixture
def stored(database_dsn: str, seeded: Seeded) -> StoredQuiz:
    return add_stored_quiz(database_dsn, seeded, seeded.topics[0])


def insert_returning_id(dsn: str, table: str, values: dict[str, Any]) -> uuid.UUID:
    query = sql.SQL("insert into public.{} ({}) values ({}) returning id").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in values),
        sql.SQL(", ").join(sql.Placeholder() for _ in values),
    )
    row = admin(dsn).fetchone(query, list(values.values()))
    assert row is not None
    return row["id"]


def on_table(template: sql.SQL, table: str) -> sql.Composed:
    """``template`` with ``{}`` replaced by a public table's name."""
    return template.format(sql.Identifier(table))


def add_attempt(dsn: str, seeded: Seeded, quiz: uuid.UUID, **fields: Any) -> uuid.UUID:
    return insert_returning_id(
        dsn,
        "quiz_attempts",
        {"user_id": seeded.user, "quiz_id": quiz, "status": "grading", **fields},
    )


def add_answer(
    dsn: str, seeded: Seeded, attempt: uuid.UUID, question: uuid.UUID, **fields: Any
) -> uuid.UUID:
    values: dict[str, Any] = {
        "answer": Jsonb({"option_id": "a"}),
        "grading_method": "deterministic",
        "is_correct": False,
        "points_awarded": 0,
        "max_points": 1,
        "feedback": Jsonb({"explanation": "Because."}),
        **fields,
    }
    return insert_returning_id(
        dsn,
        "quiz_answers",
        {"user_id": seeded.user, "attempt_id": attempt, "question_id": question, **values},
    )


# --- The answer keys are unreachable for clients ---------------------------------------------


@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_client_role_cannot_read_the_answer_keys_even_its_own(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz, role: str
) -> None:
    with admin(database_dsn).acting_as(role, seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("select * from public.question_answer_keys")


def test_a_client_cannot_read_a_single_key_column(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "select correct_option_id from public.question_answer_keys where question_id = %s",
                (stored.questions[0],),
            )


KEY_WRITES = [
    sql.SQL(
        "insert into public.question_answer_keys (question_id, user_id, correct_option_id,"
        " explanation) values (gen_random_uuid(), gen_random_uuid(), 'a', 'x')"
    ),
    sql.SQL("update public.question_answer_keys set correct_option_id = 'a'"),
    sql.SQL("delete from public.question_answer_keys"),
]


@pytest.mark.parametrize("statement", KEY_WRITES, ids=["insert", "update", "delete"])
def test_a_client_cannot_write_the_answer_keys(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz, statement: sql.SQL
) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement)


def test_the_key_table_has_row_security_on_and_no_policy(database_dsn: str) -> None:
    flags = admin(database_dsn).fetchone(
        "select relrowsecurity, relforcerowsecurity from pg_class"
        " where oid = 'public.question_answer_keys'::regclass"
    )
    policies = admin(database_dsn).scalar(
        "select count(*) from pg_policies where tablename = 'question_answer_keys'"
    )
    assert flags is not None and flags["relrowsecurity"] is True
    assert policies == 0


def test_the_questions_table_has_nowhere_to_keep_the_answer(database_dsn: str) -> None:
    columns = {
        row["column_name"]
        for row in admin(database_dsn).fetchall(
            "select column_name from information_schema.columns"
            " where table_schema = 'public' and table_name = 'questions'"
        )
    }
    assert not columns & {"correct_option_id", "explanation", "rubric", "model_answer"}


# --- Clients can read their own, and only read ----------------------------------------------


def test_a_learner_reads_their_own_quiz_and_questions(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        quizzes = connection.execute("select id from public.quizzes").fetchall()
        questions = connection.execute(
            "select id from public.questions where quiz_id = %s", (stored.quiz,)
        ).fetchall()

    assert [row["id"] for row in quizzes] == [stored.quiz]
    assert {row["id"] for row in questions} == set(stored.questions)


@pytest.mark.parametrize("table", CLIENT_TABLES)
def test_another_learner_sees_none_of_it(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz, table: str
) -> None:
    attempt = add_attempt(database_dsn, seeded, stored.quiz)
    add_answer(database_dsn, seeded, attempt, stored.questions[0])
    admin(database_dsn).execute(
        "insert into public.topic_mastery (item_id, user_id, roadmap_id, score, band,"
        " attempts_count, answers_count, low_confidence, algorithm_version)"
        " values (%s, %s, %s, 50, 'needs_practice', 1, 1, true, 'test/v1')",
        (seeded.topics[0], seeded.user, seeded.roadmap),
    )
    bob = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        rows = connection.execute(on_table(sql.SQL("select * from public.{}"), table)).fetchall()

    assert rows == []


@pytest.mark.parametrize("table", CLIENT_TABLES)
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_clients_cannot_write_assessment_tables(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz, table: str, role: str
) -> None:
    with admin(database_dsn).acting_as(role, seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(on_table(sql.SQL("insert into public.{} default values"), table))
    with admin(database_dsn).acting_as(role, seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(on_table(sql.SQL("update public.{} set user_id = user_id"), table))
    with admin(database_dsn).acting_as(role, seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(on_table(sql.SQL("delete from public.{}"), table))


def test_anon_cannot_read_assessment_tables(database_dsn: str, stored: StoredQuiz) -> None:
    for table in CLIENT_TABLES:
        with admin(database_dsn).acting_as("anon") as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(on_table(sql.SQL("select * from public.{}"), table))


# --- Always-true rules ------------------------------------------------------------------------


def test_a_quiz_can_be_attempted_only_once(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    add_attempt(database_dsn, seeded, stored.quiz)

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_attempt(database_dsn, seeded, stored.quiz)


def test_a_question_can_be_answered_only_once_per_attempt(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    attempt = add_attempt(database_dsn, seeded, stored.quiz)
    add_answer(database_dsn, seeded, attempt, stored.questions[0])

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_answer(database_dsn, seeded, attempt, stored.questions[0])


def test_the_same_idempotency_key_cannot_make_two_attempts(
    database_dsn: str, seeded: Seeded
) -> None:
    first = add_stored_quiz(database_dsn, seeded, seeded.topics[0])
    second = add_stored_quiz(database_dsn, seeded, seeded.topics[1])
    add_attempt(database_dsn, seeded, first.quiz, idempotency_key="the-same-key-1")

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_attempt(database_dsn, seeded, second.quiz, idempotency_key="the-same-key-1")


def test_an_answer_cannot_belong_to_another_learners_attempt_or_question(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    bob = create_auth_user(database_dsn)
    attempt = add_attempt(database_dsn, seeded, stored.quiz)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin(database_dsn).execute(
            "insert into public.quiz_answers (user_id, attempt_id, question_id, answer,"
            " grading_method, is_correct, points_awarded, max_points, feedback)"
            " values (%s, %s, %s, '{}', 'deterministic', false, 0, 1, '{}')",
            (bob, attempt, stored.questions[0]),
        )


def test_a_quiz_cannot_be_written_for_another_learners_topic(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    bob = create_auth_user(database_dsn)
    bobs_job = add_job(database_dsn, bob, add_goal(database_dsn, bob), status="completed")

    # Bob's own job, but Alice's roadmap, topic and lesson: every composite key refuses it.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin(database_dsn).execute(
            "insert into public.quizzes (user_id, roadmap_id, item_id, lesson_id, job_id, purpose,"
            " title, language, question_count, prompt_version, provider, model_id)"
            " select %s, roadmap_id, item_id, lesson_id, %s, purpose, title, language,"
            " question_count, prompt_version, provider, model_id"
            " from public.quizzes where id = %s",
            (bob, bobs_job, stored.quiz),
        )


def test_a_pending_answer_has_no_points_and_a_marked_one_has_some(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    attempt = add_attempt(database_dsn, seeded, stored.quiz)

    with pytest.raises(psycopg.errors.CheckViolation):
        add_answer(
            database_dsn, seeded, attempt, stored.questions[0], grading_method="pending",
            points_awarded=1, is_correct=None,
        )  # fmt: skip
    with pytest.raises(psycopg.errors.CheckViolation):
        add_answer(
            database_dsn, seeded, attempt, stored.questions[0], grading_method="ai_estimate",
            points_awarded=None, is_correct=None,
        )  # fmt: skip


def test_points_can_never_exceed_the_questions_worth(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    attempt = add_attempt(database_dsn, seeded, stored.quiz)

    with pytest.raises(psycopg.errors.CheckViolation):
        add_answer(
            database_dsn, seeded, attempt, stored.questions[0], points_awarded=2, max_points=1
        )


def test_a_graded_attempt_must_have_a_score_and_a_time(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        add_attempt(database_dsn, seeded, stored.quiz, status="graded")


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "multiple_choice", "options": None},
        {
            "kind": "short_answer",
            "options": Jsonb([{"id": "a", "text": "x"}, {"id": "b", "text": "y"}]),
        },
        {"kind": "true_false", "options": Jsonb([{"id": "true", "text": "True"}])},
        {"kind": "essay", "options": None},
        {"difficulty": "impossible"},
        {"max_points": 4},
        {"prompt": "no"},
    ],
)
def test_a_malformed_question_is_refused(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz, fields: dict[str, Any]
) -> None:
    values: dict[str, Any] = {
        "kind": "short_answer",
        "options": None,
        "prompt": "A well-formed question?",
        "difficulty": "easy",
        "max_points": 1,
        **fields,
    }
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "insert into public.questions (user_id, quiz_id, position, kind, prompt, options,"
            " objective_id, difficulty, max_points) values (%s, %s, 99, %s, %s, %s, 'o1', %s, %s)",
            (
                seeded.user,
                stored.quiz,
                values["kind"],
                values["prompt"],
                values["options"],
                values["difficulty"],
                values["max_points"],
            ),
        )


def test_a_key_is_either_an_option_or_a_rubric_never_both_or_neither(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    extra = admin(database_dsn).fetchone(
        "insert into public.questions (user_id, quiz_id, position, kind, prompt, options,"
        " objective_id, difficulty, max_points) values (%s, %s, 50, 'short_answer',"
        " 'Explain it in your words?', null, 'o1', 'easy', 1) returning id",
        (seeded.user, stored.quiz),
    )
    assert extra is not None

    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "insert into public.question_answer_keys (question_id, user_id, explanation)"
            " values (%s, %s, 'x')",
            (extra["id"], seeded.user),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "insert into public.question_answer_keys (question_id, user_id, correct_option_id,"
            " rubric, explanation) values (%s, %s, 'a', '{\"points\": []}', 'x')",
            (extra["id"], seeded.user),
        )


def test_mastery_is_one_row_per_topic(database_dsn: str, seeded: Seeded) -> None:
    insert = (
        "insert into public.topic_mastery (item_id, user_id, roadmap_id, score, band,"
        " attempts_count, answers_count, low_confidence, algorithm_version)"
        " values (%s, %s, %s, 50, 'needs_practice', 1, 1, true, 'test/v1')"
    )
    admin(database_dsn).execute(insert, (seeded.topics[0], seeded.user, seeded.roadmap))

    with pytest.raises(psycopg.errors.UniqueViolation):
        admin(database_dsn).execute(insert, (seeded.topics[0], seeded.user, seeded.roadmap))


@pytest.mark.parametrize(
    "fields",
    [
        {"score": 101},
        {"score": -1},
        {"band": "excellent"},
        {"attempts_count": 0},
        {"answers_count": 0},
    ],
)
def test_nonsense_mastery_is_refused(
    database_dsn: str, seeded: Seeded, fields: dict[str, Any]
) -> None:
    values: dict[str, Any] = {
        "score": 50,
        "band": "needs_practice",
        "attempts_count": 1,
        "answers_count": 1,
        **fields,
    }
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "insert into public.topic_mastery (item_id, user_id, roadmap_id, score, band,"
            " attempts_count, answers_count, low_confidence, algorithm_version)"
            " values (%s, %s, %s, %s, %s, %s, %s, true, 'test/v1')",
            (
                seeded.topics[1],
                seeded.user,
                seeded.roadmap,
                values["score"],
                values["band"],
                values["attempts_count"],
                values["answers_count"],
            ),
        )


def test_deleting_a_goal_removes_its_quizzes_attempts_answers_keys_and_mastery(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    attempt = add_attempt(database_dsn, seeded, stored.quiz)
    add_answer(database_dsn, seeded, attempt, stored.questions[0])
    admin(database_dsn).execute(
        "insert into public.topic_mastery (item_id, user_id, roadmap_id, score, band,"
        " attempts_count, answers_count, low_confidence, algorithm_version)"
        " values (%s, %s, %s, 50, 'needs_practice', 1, 1, true, 'test/v1')",
        (seeded.topics[0], seeded.user, seeded.roadmap),
    )
    admin(database_dsn).execute(
        "update public.learning_goals set status = 'archived' where id = %s", (seeded.goal,)
    )

    admin(database_dsn).execute("delete from public.learning_goals where id = %s", (seeded.goal,))

    for table, column in [
        ("quizzes", "id"),
        ("questions", "quiz_id"),
        ("question_answer_keys", "question_id"),
        ("quiz_attempts", "id"),
        ("quiz_answers", "attempt_id"),
        ("topic_mastery", "item_id"),
    ]:
        remaining = admin(database_dsn).scalar(
            on_table(sql.SQL("select count(*) from public.{} where user_id = %s"), table),
            (seeded.user,),
        )
        assert remaining == 0, (table, column)


# --- Queuing quiz and grading jobs ------------------------------------------------------------


def queue_as_learner(dsn: str, who: uuid.UUID, goal: uuid.UUID, item: uuid.UUID | None) -> Any:
    with admin(dsn).acting_as("authenticated", who) as connection:
        return connection.execute(INSERT_QUIZ_JOB, (who, goal, item)).fetchone()


def lesson_for(dsn: str, seeded: Seeded, item: uuid.UUID) -> uuid.UUID:
    job = add_lesson_job(dsn, seeded, item, status="completed")
    return add_lesson(dsn, seeded.user, seeded.roadmap, item, job)


def test_a_learner_can_queue_a_quiz_for_a_topic_that_has_a_lesson(
    database_dsn: str, seeded: Seeded
) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0])

    row = queue_as_learner(database_dsn, seeded.user, seeded.goal, seeded.topics[0])

    assert (row["job_type"], row["status"], row["item_id"]) == ("quiz", "queued", seeded.topics[0])
    assert row["attempt_id"] is None


def test_a_quiz_needs_a_lesson(database_dsn: str, seeded: Seeded) -> None:
    with pytest.raises(psycopg.errors.CheckViolation, match="from a lesson"):
        queue_as_learner(database_dsn, seeded.user, seeded.goal, seeded.topics[0])


def test_a_quiz_job_must_name_a_topic_and_not_a_revision_session(
    database_dsn: str, seeded: Seeded
) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0])

    with pytest.raises(psycopg.errors.CheckViolation):
        queue_as_learner(database_dsn, seeded.user, seeded.goal, None)
    with pytest.raises(psycopg.errors.CheckViolation):
        queue_as_learner(database_dsn, seeded.user, seeded.goal, seeded.revision)


def test_a_topic_of_a_superseded_roadmap_cannot_get_a_new_quiz_job(
    database_dsn: str, seeded: Seeded
) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0])
    admin(database_dsn).execute(
        "update public.roadmaps set status = 'superseded' where id = %s", (seeded.roadmap,)
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        queue_as_learner(database_dsn, seeded.user, seeded.goal, seeded.topics[0])


def test_a_learner_cannot_queue_a_quiz_for_someone_elses_topic(
    database_dsn: str, seeded: Seeded
) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0])
    bob = create_auth_user(database_dsn)

    with pytest.raises(CONSTRAINT_VIOLATIONS):
        queue_as_learner(database_dsn, bob, seeded.goal, seeded.topics[0])


def test_only_one_quiz_job_can_be_active_per_topic_but_a_lesson_job_does_not_block_it(
    database_dsn: str, seeded: Seeded
) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0])
    add_lesson_job(database_dsn, seeded, seeded.topics[0])  # an active lesson job
    admin(database_dsn).execute(INSERT_QUIZ_JOB, (seeded.user, seeded.goal, seeded.topics[0]))

    with pytest.raises(psycopg.errors.UniqueViolation):
        admin(database_dsn).execute(INSERT_QUIZ_JOB, (seeded.user, seeded.goal, seeded.topics[0]))


def test_a_learner_cannot_queue_a_grading_job(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    attempt = add_attempt(database_dsn, seeded, stored.quiz)

    # Without an attempt a grading job is meaningless; naming one needs a column clients can't set.
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into public.generation_jobs (user_id, goal_id, job_type)"
                " values (%s, %s, 'grade')",
                (seeded.user, seeded.goal),
            )
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "insert into public.generation_jobs (user_id, goal_id, job_type, attempt_id)"
                " values (%s, %s, 'grade', %s)",
                (seeded.user, seeded.goal, attempt),
            )


def test_a_grading_job_names_exactly_one_attempt_of_its_owner(
    database_dsn: str, seeded: Seeded, stored: StoredQuiz
) -> None:
    attempt = add_attempt(database_dsn, seeded, stored.quiz)
    bob = create_auth_user(database_dsn)
    insert = (
        "insert into public.generation_jobs (user_id, goal_id, job_type, attempt_id)"
        " values (%s, %s, 'grade', %s)"
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "insert into public.generation_jobs (user_id, goal_id, job_type, item_id, attempt_id)"
            " values (%s, %s, 'grade', %s, %s)",
            (seeded.user, seeded.goal, seeded.topics[0], attempt),
        )
    with pytest.raises(CONSTRAINT_VIOLATIONS):
        admin(database_dsn).execute(insert, (bob, seeded.goal, attempt))
    admin(database_dsn).execute(insert, (seeded.user, seeded.goal, attempt))
    with pytest.raises(psycopg.errors.UniqueViolation):  # one active grading job per attempt
        admin(database_dsn).execute(insert, (seeded.user, seeded.goal, attempt))
