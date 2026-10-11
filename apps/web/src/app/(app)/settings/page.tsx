import type { Metadata } from "next";
import { Suspense } from "react";

import { PageContainer, PageHeader } from "@/components/layout/page";
import { SettingsForm } from "@/components/settings/settings-form";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchMe } from "@/lib/api/server";
import { meToSettingsValues } from "@/lib/profile/schema";

export const metadata: Metadata = { title: "Settings" };

const SETTINGS_PATH = "/settings";

/** Timezone names the runtime knows, always including UTC. */
function timeZones(): string[] {
  const zones = Intl.supportedValuesOf("timeZone");
  return zones.includes("UTC") ? zones : ["UTC", ...zones];
}

export default function SettingsPage() {
  return (
    <PageContainer className="max-w-2xl py-10">
      <PageHeader
        title="Settings"
        description="Your details and the study preferences new goals start from."
      />
      <Card className="mt-8">
        <CardContent>
          <Suspense
            fallback={
              <Skeleton className="h-96 w-full" role="status" aria-label="Loading your settings" />
            }
          >
            <SettingsContent />
          </Suspense>
        </CardContent>
      </Card>
    </PageContainer>
  );
}

async function SettingsContent() {
  const me = await callApi(SETTINGS_PATH, fetchMe);
  return <SettingsForm defaults={meToSettingsValues(me)} timeZones={timeZones()} />;
}
