import { InfoIcon } from "lucide-react";

import { AuthCard } from "@/components/auth/auth-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/** Shown in development when the Supabase variables are not set, instead of a broken form. */
export function AuthNotConfigured() {
  return (
    <AuthCard
      title="Sign-in isn't set up yet"
      description="This environment is not connected to a Supabase project."
    >
      <Alert variant="info">
        <InfoIcon aria-hidden="true" />
        <AlertTitle>One-time setup</AlertTitle>
        <AlertDescription>
          <p>
            Add <code className="font-mono text-xs">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
            <code className="font-mono text-xs">NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY</code> to{" "}
            <code className="font-mono text-xs">apps/web/.env.local</code>, then restart the web
            server. The steps are in{" "}
            <code className="font-mono text-xs">docs/SUPABASE_SETUP.md</code>.
          </p>
        </AlertDescription>
      </Alert>
    </AuthCard>
  );
}
