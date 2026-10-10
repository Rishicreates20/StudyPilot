import { SubmitButton } from "@/components/forms/submit-button";
import { signOutAction } from "@/lib/auth/actions";

/** A form (not a link), so signing out is a POST protected by Next.js' Server Action origin check. */
export function SignOutButton() {
  return (
    <form action={signOutAction}>
      <SubmitButton variant="ghost" size="sm">
        Sign out
      </SubmitButton>
    </form>
  );
}
