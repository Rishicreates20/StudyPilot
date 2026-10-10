import Link from "next/link";

import { SignOutButton } from "@/components/auth/sign-out-button";
import { Button } from "@/components/ui/button";
import { getSessionUser } from "@/lib/auth/session";

/**
 * Account links in the header. It reads the session, so it is rendered per request (inside a
 * Suspense boundary) while the rest of the header stays static.
 */
export async function AuthNav() {
  const user = await getSessionUser();

  if (!user) {
    return (
      <div className="flex items-center gap-1">
        <Button asChild variant="ghost" size="sm">
          <Link href="/sign-in">Sign in</Link>
        </Button>
        <Button asChild size="sm" className="hidden sm:inline-flex">
          <Link href="/sign-up">Create account</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <Button asChild variant="ghost" size="sm">
        <Link href="/dashboard">Dashboard</Link>
      </Button>
      {user.email ? (
        <span className="hidden max-w-44 truncate text-sm text-muted-foreground lg:inline">
          {user.email}
        </span>
      ) : null}
      <SignOutButton />
    </div>
  );
}
