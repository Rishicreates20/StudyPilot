import { studyPath } from "@/lib/lessons/paths";

/** Taking a quiz that was written for a topic. */
export function quizPath(goalId: string, itemId: string, quizId: string): string {
  return `${studyPath(goalId, itemId)}/quiz/${quizId}`;
}

/** The results of a submitted quiz: the score, the explanations, what to do next. */
export function resultsPath(goalId: string, itemId: string, attemptId: string): string {
  return `${studyPath(goalId, itemId)}/results/${attemptId}`;
}
