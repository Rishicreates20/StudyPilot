"""The quiz document and the code-side checks on a model's draft."""

from collections.abc import Callable
from typing import Any

import pytest

from app.ai.fake_quiz import sample_quiz
from app.ai.quiz.schema import (
    BuiltMultipleChoice,
    BuiltQuiz,
    BuiltShortAnswer,
    BuiltTrueFalse,
    DraftQuiz,
)
from app.ai.quiz.validation import build_quiz, normalize, similarity, validate_quiz
from support.quizzes import changed_quiz, make_quiz_context, valid_quiz, valid_quiz_draft


def codes(violations: list[Any]) -> set[str]:
    return {violation.code for violation in violations}


def quiz_from(draft: DraftQuiz, **context: Any) -> BuiltQuiz:
    built, violations = build_quiz(draft, make_quiz_context(**context))
    assert built is not None, violations
    return built


def first_of(quiz: BuiltQuiz, kind: type) -> int:
    return next(
        index for index, question in enumerate(quiz.questions) if isinstance(question, kind)
    )


# --- The sample is a good quiz -------------------------------------------------------------------


@pytest.mark.parametrize("count", [3, 4, 5, 8, 10])
def test_the_built_in_sample_quiz_passes_every_check_at_any_size(count: int) -> None:
    context = make_quiz_context(question_count=count)
    quiz = valid_quiz(context)

    assert len(quiz.questions) == count
    assert validate_quiz(quiz, context) == []


def test_a_practice_quiz_only_tests_its_focus_objectives() -> None:
    context = make_quiz_context(purpose="practice", focus_objective_ids=("o2",))
    quiz = valid_quiz(context)

    assert {question.objective_id for question in quiz.questions} == {"o2"}
    assert validate_quiz(quiz, context) == []


def test_a_sample_quiz_never_repeats_what_was_asked_before() -> None:
    first = make_quiz_context()
    first_prompts = tuple(q.prompt for q in valid_quiz(first).questions)
    second = make_quiz_context(previous_prompts=first_prompts)

    quiz = valid_quiz(second)

    assert validate_quiz(quiz, second) == []
    assert not {q.prompt for q in quiz.questions} & set(first_prompts)


def test_the_sample_says_it_is_a_sample() -> None:
    quiz = valid_quiz()

    assert quiz.title.startswith("Sample quiz:")
    assert all("sample" in question.explanation.casefold() for question in quiz.questions)


# --- Building the stored questions -------------------------------------------------------------


def test_every_kind_is_converted_to_its_own_typed_question() -> None:
    quiz = valid_quiz()

    kinds = {type(question) for question in quiz.questions}
    assert kinds == {BuiltMultipleChoice, BuiltTrueFalse, BuiltShortAnswer}
    mc = quiz.questions[first_of(quiz, BuiltMultipleChoice)]
    assert isinstance(mc, BuiltMultipleChoice)
    assert [option.id for option in mc.options] == ["a", "b", "c", "d"]
    assert mc.correct_option_id in {"a", "b", "c", "d"}
    tf = quiz.questions[first_of(quiz, BuiltTrueFalse)]
    assert isinstance(tf, BuiltTrueFalse)
    assert [option.id for option in tf.options] == ["true", "false"]
    sa = quiz.questions[first_of(quiz, BuiltShortAnswer)]
    assert isinstance(sa, BuiltShortAnswer)
    assert [point.id for point in sa.rubric] == ["p1", "p2", "p3"]


def test_the_correct_option_id_points_at_the_text_the_model_named() -> None:
    context = make_quiz_context()
    draft = valid_quiz_draft(context)
    quiz = quiz_from(draft, shuffle_seed="whatever")

    for built, original in zip(quiz.questions, draft.questions, strict=True):
        if isinstance(built, BuiltMultipleChoice):
            right = next(o for o in built.options if o.id == built.correct_option_id)
            assert normalize(right.text) == normalize(original.correct_option)
            # and the note for each option stays with the option it was written for
            for option in built.options:
                expected = original.option_notes[original.options.index(option.text)]
                assert built.option_notes[option.id] == expected


def test_the_shuffle_is_repeatable_and_does_not_always_put_the_answer_first() -> None:
    draft = valid_quiz_draft()
    same_a = quiz_from(draft, shuffle_seed="job-1")
    same_b = quiz_from(draft, shuffle_seed="job-1")
    positions: set[str] = set()
    for seed in range(12):
        quiz = quiz_from(draft, shuffle_seed=f"job-{seed}")
        mc = quiz.questions[first_of(quiz, BuiltMultipleChoice)]
        assert isinstance(mc, BuiltMultipleChoice)
        positions.add(mc.correct_option_id)

    assert same_a == same_b
    assert len(positions) > 1


def three_options(question: dict[str, Any]) -> None:
    question["options"] = question["options"][:3]


def blank_option(question: dict[str, Any]) -> None:
    question["options"] = [*question["options"][:3], ""]


def repeated_option(question: dict[str, Any]) -> None:
    question["options"][3] = question["options"][2].upper()


def key_not_among_options(question: dict[str, Any]) -> None:
    question["correct_option"] = "not one of the options"


def empty_key(question: dict[str, Any]) -> None:
    question["correct_option"] = ""


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (three_options, "OPTIONS"),
        (blank_option, "OPTIONS"),
        (repeated_option, "DUPLICATE_OPTION"),
        (key_not_among_options, "ANSWER_KEY"),
        (empty_key, "ANSWER_KEY"),
    ],
)
def test_a_multiple_choice_question_with_a_broken_key_or_options_is_reported(
    edit: Callable[[dict[str, Any]], None], code: str
) -> None:
    def apply(data: dict[str, Any]) -> None:
        edit(data["questions"][0])

    draft = changed_quiz(valid_quiz_draft(), apply)

    built, violations = build_quiz(draft, make_quiz_context())

    assert built is None
    assert codes(violations) == {code}
    assert violations[0].message.startswith("Question 1")


def test_a_true_false_question_needs_a_true_or_false_key() -> None:
    def apply(data: dict[str, Any]) -> None:
        data["questions"][2]["correct_option"] = "maybe"

    built, violations = build_quiz(changed_quiz(valid_quiz_draft(), apply), make_quiz_context())

    assert built is None and codes(violations) == {"ANSWER_KEY"}
    assert "Question 3" in violations[0].message


@pytest.mark.parametrize("spelling", ["True", " TRUE ", "true."])
def test_the_spelling_of_true_and_false_does_not_matter(spelling: str) -> None:
    def apply(data: dict[str, Any]) -> None:
        data["questions"][2]["correct_option"] = spelling

    draft = changed_quiz(valid_quiz_draft(), apply)

    built, _ = build_quiz(draft, make_quiz_context())
    assert built is not None
    tf = built.questions[2]
    assert isinstance(tf, BuiltTrueFalse) and tf.correct_option_id == "true"


def one_rubric_point(question: dict[str, Any]) -> None:
    question["rubric"] = question["rubric"][:1]


def no_rubric(question: dict[str, Any]) -> None:
    question["rubric"] = []


def no_model_answer(question: dict[str, Any]) -> None:
    question["model_answer"] = ""


@pytest.mark.parametrize("edit", [one_rubric_point, no_rubric, no_model_answer])
def test_a_short_answer_needs_a_rubric_of_two_to_five_points_and_a_model_answer(
    edit: Callable[[dict[str, Any]], None],
) -> None:
    def apply(data: dict[str, Any]) -> None:
        edit(data["questions"][4])

    built, violations = build_quiz(changed_quiz(valid_quiz_draft(), apply), make_quiz_context())

    assert built is None and codes(violations) == {"RUBRIC"}


def test_content_that_is_too_long_is_reported_by_where_it_is_and_never_quoted() -> None:
    secret = "words of the model that must not be echoed " * 60  # about 2,500 characters

    def apply(data: dict[str, Any]) -> None:
        data["questions"][0]["explanation"] = secret

    built, violations = build_quiz(changed_quiz(valid_quiz_draft(), apply), make_quiz_context())

    assert built is None and codes(violations) == {"STRUCTURE"}
    message = violations[0].message
    assert "questions.0.multiple_choice.explanation" in message
    assert "must not be echoed" not in message


# --- The checks ------------------------------------------------------------------------------


def test_the_wrong_number_of_questions_is_reported() -> None:
    context = make_quiz_context(question_count=6)

    assert "COUNT" in codes(validate_quiz(valid_quiz(make_quiz_context()), context))


def test_a_quiz_in_the_wrong_language_is_rejected() -> None:
    quiz = valid_quiz(make_quiz_context(language="en"))

    assert "LANGUAGE" in codes(validate_quiz(quiz, make_quiz_context(language="hi")))


def test_too_many_short_answers_and_no_multiple_choice_are_reported() -> None:
    quiz = valid_quiz()

    too_many = validate_quiz(quiz, make_quiz_context(max_short_answers=0))
    assert "KIND_MIX" in codes(too_many)

    def only_tf(data: dict[str, Any]) -> None:
        for question in data["questions"]:
            question.update(
                kind="true_false",
                correct_option="true",
                options=[],
                rubric=[],
                model_answer="",
            )

    tf_quiz = quiz_from(changed_quiz(valid_quiz_draft(), only_tf))
    assert "KIND_MIX" in codes(validate_quiz(tf_quiz, make_quiz_context()))


def test_a_question_about_an_objective_that_is_not_on_the_roadmap_is_reported() -> None:
    def apply(data: dict[str, Any]) -> None:
        data["questions"][1]["objective_id"] = "o99"

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    violations = validate_quiz(quiz, make_quiz_context())

    assert "OBJECTIVE" in codes(violations)
    assert any("Question 2" in v.message and "o99" in v.message for v in violations)


def test_a_practice_quiz_may_not_wander_off_its_focus() -> None:
    context = make_quiz_context(purpose="practice", focus_objective_ids=("o2",))
    quiz = valid_quiz(make_quiz_context())  # tests both objectives

    assert "OBJECTIVE_FOCUS" in codes(validate_quiz(quiz, context))


def test_every_objective_has_to_be_covered_when_there_is_room() -> None:
    def apply(data: dict[str, Any]) -> None:
        for question in data["questions"]:
            question["objective_id"] = "o1"

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    violations = validate_quiz(quiz, make_quiz_context())

    assert "COVERAGE" in codes(violations)
    assert any("o2" in v.message for v in violations)


def test_two_questions_that_ask_the_same_thing_are_reported() -> None:
    def apply(data: dict[str, Any]) -> None:
        data["questions"][1]["prompt"] = data["questions"][0]["prompt"].upper() + "!"

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    violations = validate_quiz(quiz, make_quiz_context())

    assert "DUPLICATE" in codes(violations)
    assert any("Questions 1 and 2" in v.message for v in violations)


def test_a_question_asked_in_an_earlier_quiz_is_reported() -> None:
    quiz = valid_quiz()
    context = make_quiz_context(previous_prompts=(quiz.questions[3].prompt,))

    violations = validate_quiz(quiz, context)

    assert "REPEATS_EARLIER" in codes(violations)
    assert any("Question 4" in v.message for v in violations)


@pytest.mark.parametrize(
    "option",
    ["All of the above", "none of these", "Both A and B", "A and B are correct", "Neither of them"],
)
def test_options_that_depend_on_other_options_are_ambiguous(option: str) -> None:
    def apply(data: dict[str, Any]) -> None:
        data["questions"][0]["options"][3] = option
        data["questions"][0]["correct_option"] = data["questions"][0]["options"][0]

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    assert "AMBIGUOUS" in codes(validate_quiz(quiz, make_quiz_context()))


def test_two_options_that_say_nearly_the_same_thing_are_ambiguous() -> None:
    def apply(data: dict[str, Any]) -> None:
        question = data["questions"][0]
        question["options"][0] = "one two three four five six seven eight nine ten"
        question["options"][1] = "one two three four five six seven eight nine ten eleven"
        question["correct_option"] = question["options"][2]

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    assert "AMBIGUOUS" in codes(validate_quiz(quiz, make_quiz_context()))


def test_a_question_that_contains_its_own_answer_is_reported() -> None:
    def apply(data: dict[str, Any]) -> None:
        question = data["questions"][0]
        question["prompt"] = f"Is it true that {question['correct_option'].lower()}? Choose below."

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    assert "ANSWER_LEAK" in codes(validate_quiz(quiz, make_quiz_context()))


def test_an_explanation_that_defends_a_different_option_is_reported() -> None:
    def apply(data: dict[str, Any]) -> None:
        question = data["questions"][0]
        wrong = next(o for o in question["options"] if o != question["correct_option"])
        question["explanation"] = f"The right choice is “{wrong}” because it is the usual one."

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    violations = validate_quiz(quiz, make_quiz_context())

    assert "EXPLANATION_CONFLICT" in codes(violations)
    assert any("question 1" in v.message for v in violations)


def test_an_explanation_that_names_the_right_answer_is_fine_even_if_it_mentions_others() -> None:
    def apply(data: dict[str, Any]) -> None:
        question = data["questions"][0]
        wrong = next(o for o in question["options"] if o != question["correct_option"])
        question["explanation"] = (
            f"“{question['correct_option']}” is right; “{wrong}” is a common mistake."
        )

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    assert "EXPLANATION_CONFLICT" not in codes(validate_quiz(quiz, make_quiz_context()))


def test_a_web_address_anywhere_in_a_question_is_rejected() -> None:
    def apply(data: dict[str, Any]) -> None:
        data["questions"][2]["explanation"] += " See https://example.com/more for details."

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    assert "LINK" in codes(validate_quiz(quiz, make_quiz_context()))


def test_four_or_more_questions_must_not_all_have_one_difficulty() -> None:
    def apply(data: dict[str, Any]) -> None:
        for question in data["questions"]:
            question["difficulty"] = "easy"

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    assert "DIFFICULTY_MIX" in codes(validate_quiz(quiz, make_quiz_context()))


def test_messages_say_where_a_problem_is_and_never_quote_the_model() -> None:
    def apply(data: dict[str, Any]) -> None:
        data["questions"][1]["prompt"] = data["questions"][0]["prompt"]
        data["questions"][0]["options"][3] = "All of the above, said the model"

    quiz = quiz_from(changed_quiz(valid_quiz_draft(), apply))

    violations = validate_quiz(quiz, make_quiz_context())

    assert violations
    assert all("said the model" not in v.message for v in violations)
    assert all(quiz.questions[0].prompt not in v.message for v in violations)


# --- Comparing text ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("Same words here", "same WORDS, here!", 1.0),
        ("one two three four", "one two three five", 0.6),
        ("alpha beta", "gamma delta", 0.0),
        ("", "anything", 0.0),
    ],
)
def test_similarity_compares_the_words_not_the_punctuation_or_case(
    a: str, b: str, expected: float
) -> None:
    assert similarity(a, b) == pytest.approx(expected)


def test_normalize_collapses_case_punctuation_and_space() -> None:
    assert normalize("  Hello,   WORLD!! ") == "hello world"


def test_sample_quizzes_never_repeat_a_question_however_many_are_taken() -> None:
    asked: list[str] = []
    for round_number in range(9):  # more than any of the sample question banks holds
        context = make_quiz_context(
            previous_prompts=tuple(asked), shuffle_seed=f"round-{round_number}"
        )
        built, violations = build_quiz(sample_quiz(context.input_data()), context)

        assert built is not None and violations == [], (round_number, violations)
        prompts = [question.prompt for question in built.questions]
        assert set(prompts).isdisjoint(asked), round_number
        asked.extend(prompts)

    assert len(set(asked)) == len(asked) == 45
