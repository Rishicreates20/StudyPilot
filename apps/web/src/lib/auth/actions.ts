"use server";

import { redirect } from "next/navigation";

import {
  AUTH_NOT_CONFIGURED_MESSAGE,
  signInErrorMessage,
  signUpErrorMessage,
} from "@/lib/auth/messages";
import { DASHBOARD_PATH, safeRedirectPath } from "@/lib/auth/paths";
import { signInSchema, signUpSchema, type SignInField, type SignUpField } from "@/lib/auth/schemas";
import { formString, zodFieldErrors, type FormState } from "@/lib/forms";
import { createClient } from "@/lib/supabase/server";

export type SignInState = FormState<SignInField>;
export type SignUpState =
  | FormState<SignUpField>
  /** Confirmation is required: the account exists but cannot sign in until the link is used. */
  | { readonly status: "check-email"; readonly email: string };

/**
 * Credentials are exchanged with Supabase Auth directly from the server. They are never logged,
 * never placed in a URL, and never echoed back to the page (only the email address is).
 */
export async function signInAction(
  _previous: SignInState,
  formData: FormData,
): Promise<SignInState> {
  const email = formString(formData, "email");
  const parsed = signInSchema.safeParse({ email, password: formString(formData, "password") });
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values: { email } };
  }

  const supabase = await createClient();
  if (!supabase) {
    return {
      status: "error",
      formError: AUTH_NOT_CONFIGURED_MESSAGE,
      fieldErrors: {},
      values: { email },
    };
  }

  const { error } = await supabase.auth.signInWithPassword(parsed.data);
  if (error) {
    return {
      status: "error",
      formError: signInErrorMessage(error),
      fieldErrors: {},
      values: { email },
    };
  }

  // Only a same-site path is honoured; anything else falls back to the dashboard.
  redirect(safeRedirectPath(formString(formData, "next")));
}

export async function signUpAction(
  _previous: SignUpState,
  formData: FormData,
): Promise<SignUpState> {
  const values = {
    displayName: formString(formData, "displayName"),
    email: formString(formData, "email"),
  };
  const parsed = signUpSchema.safeParse({ ...values, password: formString(formData, "password") });
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }

  const supabase = await createClient();
  if (!supabase) {
    return { status: "error", formError: AUTH_NOT_CONFIGURED_MESSAGE, fieldErrors: {}, values };
  }

  const { data, error } = await supabase.auth.signUp({
    email: parsed.data.email,
    password: parsed.data.password,
    options: { data: parsed.data.displayName ? { display_name: parsed.data.displayName } : {} },
  });
  if (error) {
    return { status: "error", formError: signUpErrorMessage(error), fieldErrors: {}, values };
  }

  // With email confirmation off (local development) Supabase returns a session straight away.
  if (data.session) redirect(DASHBOARD_PATH);

  // With confirmation on, the answer is the same whether or not the address already had an
  // account, so this screen cannot be used to discover who is registered.
  return { status: "check-email", email: parsed.data.email };
}

/** Ends this device's session (other devices stay signed in) and returns to the landing page. */
export async function signOutAction(): Promise<void> {
  const supabase = await createClient();
  await supabase?.auth.signOut({ scope: "local" });
  redirect("/");
}
