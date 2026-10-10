import type { EmailOtpType } from "@supabase/supabase-js";
import { redirect } from "next/navigation";
import type { NextRequest } from "next/server";

import { safeRedirectPath, SIGN_IN_PATH } from "@/lib/auth/paths";
import { createClient } from "@/lib/supabase/server";

// The only link types this app sends. Anything else is refused rather than passed to Supabase.
const ACCEPTED_TYPES: ReadonlySet<string> = new Set<EmailOtpType>(["email", "signup"]);

/**
 * Email confirmation landing point (PKCE flow): the link in the sign-up email carries a one-time
 * token hash, which is exchanged for a session on the server. The destination is restricted to
 * same-site paths, unlike the sample in the Supabase docs, which redirects to any `next` value.
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type");
  const next = safeRedirectPath(searchParams.get("next"));

  if (tokenHash && type && ACCEPTED_TYPES.has(type)) {
    const supabase = await createClient();
    if (supabase) {
      const { error } = await supabase.auth.verifyOtp({
        type: type as EmailOtpType,
        token_hash: tokenHash,
      });
      if (!error) redirect(next);
    }
  }

  redirect(`${SIGN_IN_PATH}?error=confirmation_failed`);
}
