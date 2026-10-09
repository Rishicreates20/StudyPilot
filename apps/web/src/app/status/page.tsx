import { GlobeIcon, ServerIcon } from "lucide-react";
import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import { CardGridSkeleton } from "@/components/feedback/loading-state";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { RefreshButton } from "@/components/status/refresh-button";
import { ServiceStatusCard } from "@/components/status/service-status-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { fetchApiStatus, type ApiStatus } from "@/lib/api/health";
import { siteName } from "@/lib/site";
import pkg from "../../../package.json";

export const metadata: Metadata = { title: "System status" };

const unreachableCopy: Record<Extract<ApiStatus, { state: "unreachable" }>["reason"], string> = {
  timeout: "The API did not answer in time.",
  network: "The API could not be reached. Is it running?",
  "bad-response": "The API answered, but not with a recognisable health response.",
};

async function ServiceStatuses() {
  // Health is only meaningful at request time. Declaring that up front also keeps the
  // timeout and timing calls inside fetchApiStatus out of build-time prerendering.
  await connection();
  const api = await fetchApiStatus();

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Rendering this page is itself proof that the web server is up. */}
      <ServiceStatusCard
        name="Web app"
        description={`${siteName} interface`}
        state="operational"
        icon={GlobeIcon}
        details={[{ label: "Version", value: pkg.version }]}
      />
      {api.state === "up" ? (
        <ServiceStatusCard
          name="API"
          description="FastAPI service"
          state={api.ready ? "operational" : "degraded"}
          icon={ServerIcon}
          details={[
            { label: "Version", value: api.version },
            { label: "Response time", value: `${api.latencyMs} ms` },
            {
              label: "Dependency checks",
              value: Object.keys(api.checks).length === 0 ? "None registered yet" : "See below",
            },
          ]}
        >
          {Object.keys(api.checks).length > 0 ? (
            <ul className="space-y-1 text-sm">
              {Object.entries(api.checks).map(([name, result]) => (
                <li key={name} className="flex justify-between gap-4">
                  <span className="text-muted-foreground">{name}</span>
                  <span className="font-medium">{result === "ok" ? "OK" : "Failing"}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </ServiceStatusCard>
      ) : (
        <ServiceStatusCard
          name="API"
          description="FastAPI service"
          state="unreachable"
          icon={ServerIcon}
        >
          <Alert variant="destructive">
            <AlertTitle>Can&apos;t reach the API</AlertTitle>
            <AlertDescription>{unreachableCopy[api.reason]}</AlertDescription>
          </Alert>
        </ServiceStatusCard>
      )}
    </div>
  );
}

export default function StatusPage() {
  return (
    <PageContainer className="py-12">
      <PageHeader
        title="System status"
        description="Live checks of the services that make up the app. These results come from the running services, not from sample data."
        actions={<RefreshButton />}
      />
      <div className="mt-10">
        <Suspense fallback={<CardGridSkeleton count={2} label="Checking services" />}>
          <ServiceStatuses />
        </Suspense>
      </div>
    </PageContainer>
  );
}
