"""The built-in answers of ``FakeProvider`` to a quiz request and a short-answer marking request.

They build a small, always-valid quiz (and a plausible marking) from the same facts the real
prompts are rendered from, and they say so: the title, every explanation and the stored
``is_synthetic`` flag all state that this is a sample from the test provider and not AI-generated
content. They exist so the whole pipeline (queue, worker, validation, storage, grading, mastery,
UI) can be exercised without a model. The questions are generic study-habit questions, deliberately
NOT about the topic, so nobody can mistake them for real assessment of it.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.ai.fake import Reply
from app.ai.grading.grader import DraftGrade, DraftGrades
from app.ai.provider import StructuredRequest
from app.ai.quiz.schema import DraftQuestion, DraftQuiz, DraftRubricPoint

_SAMPLE = "This is a sample question from the built-in test provider, not an AI-generated one."

# (question, correct, three wrong options)
_MULTIPLE_CHOICE: tuple[tuple[str, str, tuple[str, str, str]], ...] = (
    (
        "Which habit helps most when you want to remember a new idea for a long time?",
        "Reviewing it again after a few days",
        (
            "Reading it once very quickly",
            "Copying it without thinking",
            "Leaving it until the exam",
        ),
    ),
    (
        "What is a good first step when a problem looks too big to start?",
        "Splitting it into smaller parts",
        (
            "Waiting until you feel ready",
            "Choosing the hardest part first",
            "Asking for the answer",
        ),
    ),
    (
        "Why is explaining an idea aloud useful for learning?",
        "It shows which parts you cannot yet explain",
        ("It makes the idea shorter", "It replaces practising", "It is quicker than reading"),
    ),
    (
        "Which study session is usually most effective for focus?",
        "A short block with one clear goal",
        ("A long block with no break", "A block with many open tabs", "A block with no plan"),
    ),
    (
        "What should you do after getting a practice question wrong?",
        "Find out why the answer was wrong",
        ("Move on and forget it", "Memorise the right letter", "Skip similar questions"),
    ),
    (
        "How does testing yourself differ from rereading?",
        "It makes you pull the answer from memory",
        ("It takes no effort at all", "It only works the day before", "It cannot show mistakes"),
    ),
    (
        "Which note is the most helpful to write down?",
        "A question you could not answer",
        ("Every word you hear", "Only the titles", "Things you already know well"),
    ),
    (
        "When is a break most useful during hard study?",
        "When your attention starts to drift",
        ("Before you have started", "Only at the very end", "Never, to save time"),
    ),
    (
        "What does spacing your practice over several days do?",
        "It makes what you learn last longer",
        (
            "It wastes the earlier effort",
            "It is slower with no benefit",
            "It only helps with maths",
        ),
    ),
    (
        "What is the best use of a worked example?",
        "Study each step, then try a similar one yourself",
        ("Read the answer only", "Skip it and guess", "Copy it into your notes unread"),
    ),
)

# (statement, is it true?)
_TRUE_FALSE: tuple[tuple[str, bool], ...] = (
    ("Making mistakes while practising is a normal and useful part of learning.", True),
    ("Cramming everything the night before is the best way to remember it for months.", False),
    ("Mixing different kinds of problems in one session can improve your understanding.", True),
    ("You only learn when a lesson feels easy and smooth.", False),
    ("Writing a short summary in your own words can show gaps in your understanding.", True),
    ("A good score on a quiz proves you will never forget the topic.", False),
)

# (question, rubric point texts, model answer)
_SHORT_ANSWER: tuple[tuple[str, tuple[str, str, str], str], ...] = (
    (
        "In two or three sentences, explain how you would use a short quiz to plan "
        "what to study next.",
        (
            "Says the quiz shows which questions were wrong",
            "Says to focus the next session on the weak parts",
            "Mentions checking again afterwards",
        ),
        "A quiz shows which questions I got wrong. I would spend my next session on those weak "
        "parts, and check them again afterwards to see if I improved.",
    ),
    (
        "In two or three sentences, describe why spreading study over several days helps memory.",
        (
            "Says that memory fades if an idea is not revisited",
            "Says that reviewing again strengthens what is remembered",
            "Gives an example such as reviewing after a few days",
        ),
        "Memory fades if I do not revisit an idea. Reviewing it again strengthens what I remember, "
        "for example by going over my notes a few days later.",
    ),
    (
        "In two or three sentences, say what you would do after finding a gap in "
        "your understanding.",
        (
            "Says to go back to the explanation or lesson",
            "Says to try a similar question to practise",
            "Says to write down what was unclear",
        ),
        "I would go back to the lesson, write down what was unclear, and then try a similar "
        "question to practise it again.",
    ),
    (
        "In two or three sentences, explain why explaining an idea aloud can help you learn.",
        (
            "Says it shows what you cannot yet explain",
            "Says it makes you organise the idea",
            "Says to fix the gaps afterwards",
        ),
        "Explaining aloud shows me what I cannot yet explain. It makes me organise the idea, and "
        "then I can fix the gaps I noticed.",
    ),
)

_DIFFICULTIES = (
    "easy",
    "medium",
    "hard",
    "medium",
    "easy",
    "hard",
    "medium",
    "easy",
    "medium",
    "hard",
)


_CYCLE_MARK = " (built-in test question set"


def _cycled(prompt: str, index: int, bank_size: int) -> str:
    """The prompt for position ``index`` of a bank. Once a bank has been used up, the questions
    come round again with a visible note, so a long run of sample quizzes never repeats a prompt."""
    cycle = index // bank_size
    return prompt if cycle == 0 else f"{prompt}{_CYCLE_MARK} number {cycle + 1})"


def _asked(previous: Sequence[str], bank: Sequence[str]) -> int:
    """How many of the earlier prompts came from ``bank`` (whatever cycle they were on)."""
    known = set(bank)
    return sum(1 for prompt in previous if prompt.split(_CYCLE_MARK)[0] in known)


def sample_quiz(input_data: Mapping[str, Any]) -> DraftQuiz:
    quiz: Mapping[str, Any] = input_data["quiz"]
    count = int(quiz["question_count"])
    max_short = int(quiz["max_short_answers"])
    objectives = [str(o["id"]) for o in input_data["objectives"]]
    focus = [str(i) for i in input_data["focus_objective_ids"]]
    targets = focus or objectives
    # Questions already asked about this topic: carry on through each bank so none repeats.
    earlier: Sequence[Any] = input_data.get("do_not_repeat") or []
    previous = [str(prompt) for prompt in earlier]
    asked = {
        "multiple_choice": _asked(previous, [q[0] for q in _MULTIPLE_CHOICE]),
        "true_false": _asked(previous, [q[0] for q in _TRUE_FALSE]),
        "short_answer": _asked(previous, [q[0] for q in _SHORT_ANSWER]),
    }
    shorts = 1 if max_short >= 1 and count >= 4 else 0

    questions: list[DraftQuestion] = []
    seen = {"multiple_choice": 0, "true_false": 0, "short_answer": 0}
    for position in range(count):
        objective = targets[position % len(targets)]
        difficulty = _DIFFICULTIES[position % len(_DIFFICULTIES)]
        if position >= count - shorts:
            index = asked["short_answer"] + seen["short_answer"]
            prompt, points, model = _SHORT_ANSWER[index % len(_SHORT_ANSWER)]
            prompt = _cycled(prompt, index, len(_SHORT_ANSWER))
            seen["short_answer"] += 1
            questions.append(
                DraftQuestion(
                    kind="short_answer",
                    prompt=prompt,
                    objective_id=objective,
                    difficulty="medium",
                    explanation=f"A complete answer covers each rubric point. {_SAMPLE}",
                    rubric=[DraftRubricPoint(text=text, points=1) for text in points],
                    model_answer=model,
                )
            )
        elif position % 3 == 2:
            index = asked["true_false"] + seen["true_false"]
            statement, truth = _TRUE_FALSE[index % len(_TRUE_FALSE)]
            statement = _cycled(statement, index, len(_TRUE_FALSE))
            seen["true_false"] += 1
            questions.append(
                DraftQuestion(
                    kind="true_false",
                    prompt=statement,
                    objective_id=objective,
                    difficulty=difficulty,
                    correct_option="true" if truth else "false",
                    explanation=(
                        f"The statement is {'true' if truth else 'false'}, as most study guidance "
                        f"agrees. {_SAMPLE}"
                    ),
                )
            )
        else:
            index = asked["multiple_choice"] + seen["multiple_choice"]
            prompt, correct, wrong = _MULTIPLE_CHOICE[index % len(_MULTIPLE_CHOICE)]
            prompt = _cycled(prompt, index, len(_MULTIPLE_CHOICE))
            seen["multiple_choice"] += 1
            options = [correct, *wrong]
            questions.append(
                DraftQuestion(
                    kind="multiple_choice",
                    prompt=prompt,
                    objective_id=objective,
                    difficulty=difficulty,
                    options=options,
                    correct_option=correct,
                    option_notes=[
                        "This is the best choice." if option == correct else "This works less well."
                        for option in options
                    ],
                    explanation=f"“{correct}” is the best choice here. {_SAMPLE}",
                )
            )
    return DraftQuiz(
        language=str(input_data["language"]),
        title=f"Sample quiz: {str(input_data['topic']['title']).strip()}"[:200],
        questions=questions,
    )


def quiz_responder(request: StructuredRequest) -> Reply:
    return sample_quiz(request.input_data)


def _significant_words(text: str) -> set[str]:
    return {word for word in re.split(r"\W+", text.casefold()) if len(word) >= 6}


def sample_grades(input_data: Mapping[str, Any]) -> DraftGrades:
    """A plausible marking: a rubric point is met if the answer shares a longer word with it."""
    grades: list[DraftGrade] = []
    for answer in input_data["answers"]:
        learner = _significant_words(str(answer["learner_answer"]))
        met = [
            str(point["id"])
            for point in answer["rubric"]
            if _significant_words(str(point["text"])) & learner
        ]
        grades.append(
            DraftGrade(
                answer_id=str(answer["answer_id"]),
                met_point_ids=met,
                comment=(
                    f"Sample marking: {len(met)} of {len(answer['rubric'])} rubric points matched "
                    "by shared words. This is not an AI-generated estimate."
                ),
            )
        )
    return DraftGrades(grades=grades)


def grading_responder(request: StructuredRequest) -> Reply:
    return sample_grades(request.input_data)
