/**
 * User-facing messages for Supabase Auth errors.
 *
 * Sign-in failures are deliberately uniform ("email or password is incorrect") so the form cannot
 * be used to discover which email addresses have accounts. Raw error text from the provider is
 * never shown, and never logged with user input.
 */

type AuthErrorLike = { readonly code?: string | undefined };

const GENERIC = "Something went wrong on our side. Please try again in a moment.";

export function signInErrorMessage(error: AuthErrorLike): string {
  switch (error.code) {
    case "invalid_credentials":
      return "The email or password is incorrect.";
    case "email_not_confirmed":
      return "Confirm your email address first. We sent you a link when you signed up.";
    case "over_request_rate_limit":
      return "Too many attempts. Wait a minute and try again.";
    case "user_banned":
      return "This account has been suspended. Contact support if you think that is a mistake.";
    default:
      return GENERIC;
  }
}

export function signUpErrorMessage(error: AuthErrorLike): string {
  switch (error.code) {
    case "user_already_exists":
    case "email_exists":
      return "An account with that email may already exist. Try signing in instead.";
    case "weak_password":
      return "That password is too easy to guess. Choose a longer or less common one.";
    case "over_email_send_rate_limit":
    case "over_request_rate_limit":
      return "Too many attempts. Wait a few minutes and try again.";
    case "signup_disabled":
      return "New sign-ups are currently closed.";
    case "email_address_invalid":
      return "Enter a valid email address.";
    default:
      return GENERIC;
  }
}

export const AUTH_NOT_CONFIGURED_MESSAGE =
  "Sign-in is not configured for this environment yet. See docs/SUPABASE_SETUP.md.";
