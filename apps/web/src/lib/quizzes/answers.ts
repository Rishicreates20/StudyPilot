import type { AttemptSubmit, QuizDetail } from "@/lib/api/server";

type Answers = NonNullable<AttemptSubmit["answers"]>;

export const MAX_ANSWER_CHARS = 2000;
const OPTION_ID = /^[a-z0-9]{1,8}$/;

/** The form field a question's answer is sent under. */
export const answerField = (questionId: string): string => `q_${questionId}`;

/**
 * The answers of a submitted form, read against the quiz's own questions. A multiple-choice or
 * true/false question carries the chosen option's id, a short answer carries its text; a question
 * left empty is simply not sent (the API counts it as skipped). Anything the form carries beyond
 * the quiz's own questions is ignored, and the API checks every answer again.
 */
export function readAnswers(quiz: Pick<QuizDetail, "questions">, formData: FormData): Answers {
  const answers: Answers = [];
  for (const question of quiz.questions) {
    const value = formData.get(answerField(question.id));
    if (typeof value !== "string") continue;
    if (question.kind === "short_answer") {
      const text = value.trim().slice(0, MAX_ANSWER_CHARS);
      if (text) answers.push({ question_id: question.id, text });
    } else if (OPTION_ID.test(value)) {
      answers.push({ question_id: question.id, option_id: value });
    }
  }
  return answers;
}
