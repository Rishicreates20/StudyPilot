import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { AuthNotConfigured } from "@/components/auth/auth-not-configured";
import { SignInForm } from "@/components/auth/sign-in-form";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { safeRedirectPath, SESSION_ENDED_ERROR, SIGN_UP_PATH } from "@/lib/auth/paths";
import { getSessionUser } from "@/lib/auth/session";
import { getSupabaseConfig } from "@/lib/env";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Sign in" };

export default function SignInPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <SignInContent searchParams={searchParams} />
    </Suspense>
  );
}

async function SignInContent({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const next = safeRedirectPath(firstParam(params.next));

  if (!getSupabaseConfig()) return <AuthNotConfigured />;
  const error = firstParam(params.error);
  // After the API refused the session, show the form even though a session cookie still exists.
  if (error !== SESSION_ENDED_ERROR && (await getSessionUser())) redirect(next);

  return (
    <AuthCard
      title="Welcome back"
      description="Sign in to pick up where you left off."
      footer={
        <p className="text-muted-foreground">
          New here?{" "}
          <Link
            href={SIGN_UP_PATH}
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            Create an account
          </Link>
        </p>
      }
    >
      <div className="space-y-5">
        {error === SESSION_ENDED_ERROR ? (
          <Alert variant="warning">
            <AlertDescription>Your session has ended. Sign in again to continue.</AlertDescription>
          </Alert>
        ) : null}
        {error === "confirmation_failed" ? (
          <Alert variant="warning">
            <AlertDescription>
              That confirmation link is invalid or has expired. Sign in, or create your account
              again to get a new link.
            </AlertDescription>
          </Alert>
        ) : null}
        <SignInForm next={next} />
      </div>
    </AuthCard>
  );
}
