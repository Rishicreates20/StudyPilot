import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { AuthNotConfigured } from "@/components/auth/auth-not-configured";
import { SignUpForm } from "@/components/auth/sign-up-form";
import { Skeleton } from "@/components/ui/skeleton";
import { DASHBOARD_PATH, SIGN_IN_PATH } from "@/lib/auth/paths";
import { getSessionUser } from "@/lib/auth/session";
import { getSupabaseConfig } from "@/lib/env";

export const metadata: Metadata = { title: "Create your account" };

export default function SignUpPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[34rem] w-full rounded-xl" />}>
      <SignUpContent />
    </Suspense>
  );
}

async function SignUpContent() {
  if (!getSupabaseConfig()) return <AuthNotConfigured />;
  if (await getSessionUser()) redirect(DASHBOARD_PATH);

  return (
    <AuthCard
      title="Create your account"
      description="Your goals, lessons and progress are saved to your account and private to you."
      footer={
        <p className="text-muted-foreground">
          Already have an account?{" "}
          <Link
            href={SIGN_IN_PATH}
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            Sign in
          </Link>
        </p>
      }
    >
      <SignUpForm />
    </AuthCard>
  );
}
