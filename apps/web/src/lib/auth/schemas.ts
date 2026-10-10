import { z } from "zod";

const email = z
  .string()
  .trim()
  .pipe(z.email({ error: "Enter a valid email address." }));

export const MIN_PASSWORD_LENGTH = 10;
// Supabase hashes passwords with bcrypt, which only uses the first 72 bytes.
export const MAX_PASSWORD_LENGTH = 72;

export const signInSchema = z.object({
  email,
  password: z.string().min(1, "Enter your password."),
});

export const signUpSchema = z.object({
  displayName: z.string().trim().max(80, "Use 80 characters or fewer."),
  email,
  password: z
    .string()
    .min(MIN_PASSWORD_LENGTH, `Use at least ${MIN_PASSWORD_LENGTH} characters.`)
    .max(MAX_PASSWORD_LENGTH, `Use at most ${MAX_PASSWORD_LENGTH} characters.`),
});

export type SignInField = "email" | "password";
export type SignUpField = "displayName" | "email" | "password";
