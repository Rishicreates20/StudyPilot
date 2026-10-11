import Link from "next/link";

import { SignOutButton } from "@/components/auth/sign-out-button";
import { Button } from "@/components/ui/button";
import { SheetClose } from "@/components/ui/sheet";
import { getSessionUser } from "@/lib/auth/session";

/**
 * The account links inside the phone menu. On a narrow screen the header has no room for them, so
 * they live here; from the `sm` breakpoint up the header shows them itself (see `AuthNav`).
 * Each link closes the menu, because a menu left open over the page you navigated to is confusing.
 */
export async function AuthMobileMenu() {
  const user = await getSessionUser();

  return (
    <div className="mt-6 space-y-1 border-t px-4 pt-6 sm:hidden">
      {user ? (
        <>
          <SheetClose asChild>
            <Button asChild variant="ghost" className="w-full justify-start">
              <Link href="/dashboard">Dashboard</Link>
            </Button>
          </SheetClose>
          <SheetClose asChild>
            <Button asChild variant="ghost" className="w-full justify-start">
              <Link href="/settings">Settings</Link>
            </Button>
          </SheetClose>
          {user.email ? (
            <p className="truncate px-3 pt-3 text-xs text-muted-foreground">{user.email}</p>
          ) : null}
          <SignOutButton />
        </>
      ) : (
        <SheetClose asChild>
          <Button asChild className="w-full">
            <Link href="/sign-up">Create account</Link>
          </Button>
        </SheetClose>
      )}
    </div>
  );
}
