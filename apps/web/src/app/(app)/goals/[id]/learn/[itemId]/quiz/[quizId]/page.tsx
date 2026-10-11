import { ArrowLeftIcon, InfoIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { NoticeBanner } from "@/components/feedback/notice-banner";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { QuizForm } from "@/components/quiz/quiz-form";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchGoal, fetchQuiz } from "@/lib/api/server";
import { isGoalId } from "@/lib/goals/ids";
import { studyPath } from "@/lib/lessons/paths";
import { quizPath, resultsPath } from "@/lib/quizzes/paths";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Quiz" };

type QuizPageProps = {
  params: Promise<{ id: string; itemId: string; quizId: string }>;
  searchParams: SearchParams;
};

export default function QuizPage(props: QuizPageProps) {
  return (
    <PageContainer className="max-w-3xl py-8">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading the quiz">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        }
      >
        <QuizContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

async function QuizContent({ params, searchParams }: QuizPageProps) {
  await connection();
  const { id, itemId, quizId } = await params;
  if (!isGoalId(id) || !isGoalId(itemId) || !isGoalId(quizId)) notFound();
  const query = await searchParams;

  // A missing quiz and someone else's quiz are the same 404.
  const { quiz, goal } = await callApi(quizPath(id, itemId, quizId), async (accessToken) => {
    const [quiz, goal] = await Promise.all([
      fetchQuiz(accessToken, quizId),
      fetchGoal(accessToken, id),
    ]);
    return { quiz, goal };
  });
  // The URL names the goal and the topic as well as the quiz; they must belong together.
  if (quiz.goal_id !== id || quiz.item_id !== itemId) notFound();

  const archived = goal.status === "archived";
  const submitted = quiz.attempt;

  return (
    <div className="space-y-8">
      <Link
        href={studyPath(id, itemId)}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        Back to the lesson
      </Link>

      <PageHeader
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{quiz.item_title}</Badge>
            {quiz.purpose === "practice" ? <Badge variant="info">Practice quiz</Badge> : null}
            {quiz.is_synthetic ? <Badge variant="warning">Sample quiz</Badge> : null}
          </span>
        }
        title={quiz.title}
        description={
          quiz.purpose === "practice"
            ? "New questions, aimed at the parts of this topic that scored lowest. The right answers and explanations appear after you submit."
            : "Answer what you can. The right answers and explanations appear after you submit, and you can only submit once."
        }
      />

      <NoticeBanner code={firstParam(query.notice)} />

      {quiz.is_synthetic ? (
        <Alert variant="warning">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This server uses a built-in test provider instead of an AI model, so these are generic
            sample questions, not questions about your topic.
          </AlertDescription>
        </Alert>
      ) : null}

      {submitted ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            <p>You have already submitted this quiz, so it can&rsquo;t be taken again.</p>
            <Button asChild size="sm" className="mt-3">
              <Link href={resultsPath(id, itemId, submitted.id)}>See your results</Link>
            </Button>
          </AlertDescription>
        </Alert>
      ) : archived ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived, so its quizzes are read-only. Restore the goal to take this quiz.
          </AlertDescription>
        </Alert>
      ) : (
        <QuizForm goalId={id} itemId={itemId} quiz={quiz} />
      )}
    </div>
  );
}
