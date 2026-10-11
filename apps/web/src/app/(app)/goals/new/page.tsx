import type { Metadata } from "next";
import { Suspense } from "react";

import { GoalForm } from "@/components/goals/goal-form";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchMe } from "@/lib/api/server";
import { DASHBOARD_PATH } from "@/lib/auth/paths";
import { createGoalAction } from "@/lib/goals/actions";
import { newGoalDefaults } from "@/lib/goals/schema";

export const metadata: Metadata = { title: "New goal" };

export default function NewGoalPage() {
  return (
    <PageContainer className="max-w-2xl py-10">
      <PageHeader
        title="Create a learning goal"
        description="The more precisely you describe your situation, the better your plan will fit it. You can change your mind later."
      />
      <Card className="mt-8">
        <CardContent>
          <Suspense
            fallback={
              <Skeleton className="h-96 w-full" role="status" aria-label="Loading the form" />
            }
          >
            <NewGoalForm />
          </Suspense>
        </CardContent>
      </Card>
    </PageContainer>
  );
}

/** The form starts from the learner's saved preferences (study time, languages, practice). */
async function NewGoalForm() {
  const me = await callApi("/goals/new", fetchMe);
  return (
    <GoalForm
      action={createGoalAction}
      defaults={newGoalDefaults(me.preferences)}
      submitLabel="Create goal"
      cancelHref={DASHBOARD_PATH}
    />
  );
}
