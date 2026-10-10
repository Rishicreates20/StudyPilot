import { redirect } from "next/navigation";
import { Suspense, type ReactNode } from "react";

import { CardGridSkeleton } from "@/components/feedback/loading-state";
import { PageContainer } from "@/components/layout/page";
import { SIGN_IN_PATH } from "@/lib/auth/paths";
import { getSessionUser } from "@/lib/auth/session";

/**
 * Everything under (app) needs a signed-in user. This server-side gate is the second layer behind
 * the proxy's redirect, and each page's data calls are the third: the API itself rejects any
 * request without a valid access token. Hiding links or redirecting in the browser alone would
 * protect nothing.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <PageContainer className="py-10">
          <CardGridSkeleton count={3} label="Loading your account" />
        </PageContainer>
      }
    >
      <SessionGate>{children}</SessionGate>
    </Suspense>
  );
}

async function SessionGate({ children }: { children: ReactNode }) {
  if (!(await getSessionUser())) redirect(SIGN_IN_PATH);
  return <>{children}</>;
}
