import type { Metadata } from "next";

import { GoalForm } from "@/components/goals/goal-form";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Card, CardContent } from "@/components/ui/card";

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
          <GoalForm />
        </CardContent>
      </Card>
    </PageContainer>
  );
}
