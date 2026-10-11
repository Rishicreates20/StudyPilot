import type { EmailOtpType } from "@supabase/supabase-js";
import { redirect } from "next/navigation";
import type { NextRequest } from "next/server";

import {
  CONFIRM_SIGN_IN_ERROR,
  isAuthCode,
  safeRedirectPath,
  SIGN_IN_PATH,
} from "@/lib/auth/paths";
import { createClient } from "@/lib/supabase/server";

// The only link types this app sends. Anything else is refused rather than passed to Supabase.
const ACCEPTED_TYPES: ReadonlySet<string> = new Set<EmailOtpType>(["email", "signup"]);

/**
 * Email confirmation landing point. Two kinds of link arrive here:
 *
 * - `?token_hash=…&type=…`: the link of the custom template in `supabase/templates`, exchanged for
 *   a session on the server (works on any device);
 * - `?code=…`: what Supabase's built-in template produces. Supabase has already confirmed the
 *   address when it redirects here; the code finishes the sign-in, and only works in the browser
 *   that started the sign-up (it is bound to a verifier cookie set there, so a code in a link
 *   someone else sends cannot sign you in as them).
 *
 * The destination is restricted to same-site paths, unlike the sample in the Supabase docs, which
 * redirects to any `next` value.
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type");
  const next = safeRedirectPath(searchParams.get("next"));
  const code = searchParams.get("code");

  if (isAuthCode(code)) {
    const supabase = await createClient();
    if (supabase) {
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (!error) redirect(next);
    }
    // Most often the link was opened in another browser or device: the address is confirmed
    // all the same, so say that and let the person sign in.
    redirect(`${SIGN_IN_PATH}?error=${CONFIRM_SIGN_IN_ERROR}`);
  }

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
