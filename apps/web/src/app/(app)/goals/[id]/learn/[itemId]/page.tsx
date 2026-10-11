import {
  ArrowLeftIcon,
  BookOpenIcon,
  CircleAlertIcon,
  InfoIcon,
  RotateCcwIcon,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { NoticeBanner } from "@/components/feedback/notice-banner";
import { SubmitButton } from "@/components/forms/submit-button";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { LessonGenerationStatus } from "@/components/lesson/lesson-generation-status";
import { LessonReader } from "@/components/lesson/lesson-reader";
import { LessonVersions } from "@/components/lesson/lesson-versions";
import { NewVersionDialog } from "@/components/lesson/new-version-dialog";
import { TopicNavigation } from "@/components/lesson/topic-navigation";
import { TopicAssessment } from "@/components/quiz/topic-assessment";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { ApiError, fetchAssessment, fetchMe, fetchStudy } from "@/lib/api/server";
import { requireApiSession } from "@/lib/auth/session";
import { isGoalId } from "@/lib/goals/ids";
import { generateLessonAction, retryLessonAction } from "@/lib/lessons/actions";
import { studyPath } from "@/lib/lessons/paths";
import { studyPanelState } from "@/lib/lessons/state";
import { formatMinutes } from "@/lib/roadmaps/labels";
import { roadmapPath } from "@/lib/roadmaps/paths";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Study" };

type StudyPageProps = {
  params: Promise<{ id: string; itemId: string }>;
  searchParams: SearchParams;
};

export default function StudyPage(props: StudyPageProps) {
  return (
    <PageContainer className="py-8">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading the lesson">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-96 w-full" />
          </div>
        }
      >
        <StudyContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

async function StudyContent({ params, searchParams }: StudyPageProps) {
  await connection();
  const { id, itemId } = await params;
  if (!isGoalId(id) || !isGoalId(itemId)) notFound();
  const query = await searchParams;
  const requested = firstParam(query.lesson);
  if (requested !== undefined && !isGoalId(requested)) notFound();

  // A missing topic and someone else's topic are the same 404.
  const { view, me } = await callApi(studyPath(id, itemId, requested), async (accessToken) => {
    const [view, me] = await Promise.all([
      fetchStudy(accessToken, itemId, requested),
      fetchMe(accessToken),
    ]);
    return { view, me };
  });
  // The URL names the goal as well as the topic; they must belong together.
  if (view.topic.goal_id !== id) notFound();

  const { topic, roadmap } = view;
  // Revision sessions have no lesson and so no quiz; for the rest the card is secondary to the
  // lesson, so a failure to load it hides the card instead of the page.
  const assessment =
    topic.kind === "revision" ? null : await loadAssessment(itemId, studyPath(id, itemId));
  const state = studyPanelState(view);
  const archived = view.goal_archived;
  const roadmapLink = roadmapPath(id, roadmap.status === "current" ? undefined : roadmap.version);

  return (
    <div className="space-y-8">
      <Link
        href={roadmapLink}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        Back to the roadmap
      </Link>

      <PageHeader
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            {topic.module_title ? <Badge variant="secondary">{topic.module_title}</Badge> : null}
            {topic.day_number !== null ? (
              <Badge variant="outline">Day {topic.day_number}</Badge>
            ) : null}
            <Badge variant="outline">{formatMinutes(topic.estimated_minutes)}</Badge>
            {topic.kind === "enrichment" ? <Badge variant="outline">Optional</Badge> : null}
          </span>
        }
        title={topic.title}
        description={topic.description}
      />

      {topic.practice_task ? (
        <p className="max-w-2xl rounded-lg border bg-card p-4 text-sm">
          <span className="font-medium">Practice: </span>
          {topic.practice_task}
        </p>
      ) : null}

      <NoticeBanner code={firstParam(query.notice)} />

      {archived ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived, so its lessons are read-only. Restore the goal to write new
            versions or save your progress.
          </AlertDescription>
        </Alert>
      ) : null}

      {!archived && roadmap.status !== "current" ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This topic belongs to an earlier roadmap version. You can read what was written for it,
            but new lessons are only written for the current roadmap.{" "}
            <Link href={roadmapLink} className="underline underline-offset-4">
              Go to that version.
            </Link>
          </AlertDescription>
        </Alert>
      ) : null}

      {state.kind === "generating" ? (
        <LessonGenerationStatus goalId={id} itemId={itemId} job={state.job} />
      ) : null}

      {state.kind === "failed" ? (
        <div className="space-y-3">
          <Alert variant="destructive">
            <CircleAlertIcon aria-hidden="true" />
            <AlertTitle>We couldn&rsquo;t write this lesson</AlertTitle>
            <AlertDescription>
              <p>{state.job.error_message ?? "Something went wrong. Please try again."}</p>
            </AlertDescription>
          </Alert>
          {view.can_generate ? (
            <form action={retryLessonAction.bind(null, id, itemId, state.job.id)}>
              <SubmitButton>
                <RotateCcwIcon aria-hidden="true" />
                Try again
              </SubmitButton>
            </form>
          ) : null}
        </div>
      ) : null}

      {state.kind === "empty" ? (
        <EmptyState
          icon={BookOpenIcon}
          headingLevel="h2"
          title="This topic doesn't have a lesson yet"
          description={
            view.can_generate
              ? "StudyPilot writes the lesson for you from your roadmap, at your level. It is made in the background, and you can ask for a simpler or deeper version afterwards."
              : "Lessons can only be written for the current roadmap of a goal that isn't archived."
          }
          action={
            view.can_generate ? (
              <form action={generateLessonAction.bind(null, id, itemId)}>
                <SubmitButton>
                  <BookOpenIcon aria-hidden="true" />
                  Write this lesson
                </SubmitButton>
              </form>
            ) : undefined
          }
        />
      ) : null}

      {state.kind === "ready" ? (
        <>
          {state.writing ? (
            <LessonGenerationStatus goalId={id} itemId={itemId} job={state.writing} newVersion />
          ) : null}
          {state.failedNewer ? (
            <Alert variant="destructive">
              <CircleAlertIcon aria-hidden="true" />
              <AlertTitle>We couldn&rsquo;t write the new version</AlertTitle>
              <AlertDescription>
                <p>
                  {state.failedNewer.error_message ?? "Something went wrong."} The lesson below is
                  unchanged.
                </p>
                {view.can_generate ? (
                  <form
                    action={retryLessonAction.bind(null, id, itemId, state.failedNewer.id)}
                    className="mt-3"
                  >
                    <SubmitButton size="sm" variant="outline">
                      <RotateCcwIcon aria-hidden="true" />
                      Try again
                    </SubmitButton>
                  </form>
                ) : null}
              </AlertDescription>
            </Alert>
          ) : null}
          <LessonReader
            key={state.lesson.id}
            goalId={id}
            itemId={itemId}
            lesson={state.lesson}
            progress={view.progress}
            outline={view.outline}
            previous={view.previous}
            next={view.next}
            readOnly={archived}
            versionActions={
              view.can_generate && !state.writing ? (
                <NewVersionDialog goalId={id} itemId={itemId} />
              ) : null
            }
          />
          {assessment ? (
            <TopicAssessment
              goalId={id}
              itemId={itemId}
              assessment={assessment}
              timeZone={me.timezone}
            />
          ) : null}
          <LessonVersions
            goalId={id}
            itemId={itemId}
            versions={view.versions}
            viewingId={state.lesson.id}
            timeZone={me.timezone}
          />
        </>
      ) : (
        <TopicNavigation goalId={id} previous={view.previous} next={view.next} />
      )}
    </div>
  );
}

async function loadAssessment(itemId: string, returnTo: string) {
  const { accessToken } = await requireApiSession(returnTo);
  try {
    return await fetchAssessment(accessToken, itemId);
  } catch (error) {
    if (error instanceof ApiError) return null;
    throw error;
  }
}
