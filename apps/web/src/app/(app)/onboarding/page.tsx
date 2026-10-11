import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { NoticeBanner } from "@/components/feedback/notice-banner";
import { PageContainer, PageHeader } from "@/components/layout/page";
import {
  AboutYouForm,
  FirstGoalForm,
  SkipOnboardingButton,
  StudyStyleForm,
} from "@/components/onboarding/onboarding-forms";
import { ProgressBar } from "@/components/progress/progress-bar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchMe } from "@/lib/api/server";
import { DASHBOARD_PATH } from "@/lib/auth/paths";
import { newGoalDefaults } from "@/lib/goals/schema";
import {
  ONBOARDING_STEP_COUNT,
  onboardingStepPath,
  parseOnboardingStep,
  type OnboardingStep,
} from "@/lib/onboarding/paths";
import { meToSettingsValues } from "@/lib/profile/schema";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Welcome" };

const STEP_COPY: Record<OnboardingStep, { title: string; description: string }> = {
  1: {
    title: "Welcome to StudyPilot",
    description: "Two quick questions, then your first goal. Everything can be changed later.",
  },
  2: {
    title: "How do you like to study?",
    description: "This sets the starting point for every goal you create.",
  },
  3: {
    title: "What do you want to learn first?",
    description: "Just the essentials. You can add the details later.",
  },
};

export default function OnboardingPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <PageContainer className="max-w-2xl py-10">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-80 w-full" />
          </div>
        }
      >
        <OnboardingContent searchParams={searchParams} />
      </Suspense>
    </PageContainer>
  );
}

async function OnboardingContent({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const step = parseOnboardingStep(firstParam(params.step));

  const me = await callApi(onboardingStepPath(step), fetchMe);
  // Done (or skipped) already: nothing to ask. This page deliberately does not redirect. After an
  // onboarding action finishes, Next re-renders the page the learner was on, and a redirect from
  // here would override the action's own redirect (and drop its confirmation). The dashboard only
  // sends people here while onboarding is still due, so this cannot loop.
  if (me.onboarding_completed) {
    return (
      <PageHeader
        title="You're all set"
        description="Your preferences are saved. You can change them any time in Settings."
        actions={
          <>
            <Button asChild size="lg">
              <Link href={DASHBOARD_PATH}>Go to your goals</Link>
            </Button>
            <Button asChild variant="outline" size="lg">
              <Link href="/settings">Settings</Link>
            </Button>
          </>
        }
      />
    );
  }

  const { title, description } = STEP_COPY[step];
  // What the learner already saved in an earlier visit or step, so coming back loses nothing.
  const saved = meToSettingsValues(me);

  return (
    <div className="space-y-6">
      <ProgressBar
        label={`Step ${step} of ${ONBOARDING_STEP_COUNT}`}
        value={step}
        max={ONBOARDING_STEP_COUNT}
        showValue={false}
      />
      <PageHeader title={title} description={description} />
      <NoticeBanner code={firstParam(params.notice)} />
      <Card>
        <CardContent>
          {step === 1 ? <AboutYouForm defaults={saved} /> : null}
          {step === 2 ? <StudyStyleForm defaults={saved} /> : null}
          {step === 3 ? <FirstGoalForm defaults={newGoalDefaults(me.preferences)} /> : null}
        </CardContent>
      </Card>
      <div className="flex justify-center">
        <SkipOnboardingButton />
      </div>
    </div>
  );
}
