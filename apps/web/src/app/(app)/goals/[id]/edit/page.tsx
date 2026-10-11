import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";

import { GoalForm } from "@/components/goals/goal-form";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchGoal } from "@/lib/api/server";
import { updateGoalAction } from "@/lib/goals/actions";
import { editGoalPath, goalPath, isGoalId } from "@/lib/goals/ids";
import { goalToFormValues } from "@/lib/goals/schema";

export const metadata: Metadata = { title: "Edit goal" };

type EditGoalPageProps = { params: Promise<{ id: string }> };

export default function EditGoalPage(props: EditGoalPageProps) {
  return (
    <PageContainer className="max-w-2xl py-10">
      <PageHeader
        title="Edit your goal"
        description="Change anything that is no longer true. Your progress stays with the goal."
      />
      <Card className="mt-8">
        <CardContent>
          <Suspense
            fallback={
              <Skeleton className="h-96 w-full" role="status" aria-label="Loading the form" />
            }
          >
            <EditGoalForm {...props} />
          </Suspense>
        </CardContent>
      </Card>
    </PageContainer>
  );
}

async function EditGoalForm({ params }: EditGoalPageProps) {
  const { id } = await params;
  if (!isGoalId(id)) notFound();

  const goal = await callApi(editGoalPath(id), (accessToken) => fetchGoal(accessToken, id));
  // An archived goal is read-only: send the learner to where they can restore it.
  if (goal.status === "archived") redirect(goalPath(id));

  return (
    <GoalForm
      action={updateGoalAction.bind(null, id)}
      defaults={goalToFormValues(goal)}
      submitLabel="Save changes"
      cancelHref={goalPath(id)}
    />
  );
}
