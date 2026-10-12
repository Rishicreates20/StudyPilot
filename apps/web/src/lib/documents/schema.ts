import { z } from "zod";

import type { SearchResult } from "@/lib/api/server";
import type { FormState } from "@/lib/forms";

/** Limits that mirror the API's (it checks them again; these only give fast, friendly feedback). */
export const MAX_TITLE_CHARS = 200;
export const MAX_PASTED_CHARS = 1_000_000;
export const MAX_PAGE_CHARS = 400_000;
export const MAX_QUERY_CHARS = 500;

const optionalTitle = z.string().trim().max(MAX_TITLE_CHARS, "Use 200 characters or fewer.");

export const uploadFormSchema = z.object({ title: optionalTitle });

export const pasteFormSchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, "Give this material a title.")
    .max(MAX_TITLE_CHARS, "Use 200 characters or fewer."),
  text: z
    .string()
    .trim()
    .min(1, "Paste some text.")
    .max(MAX_PASTED_CHARS, "That is too long. Split it into several documents."),
});

export const renameFormSchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, "The title can't be empty.")
    .max(MAX_TITLE_CHARS, "Use 200 characters or fewer."),
});

export const pageFormSchema = z.object({
  text: z.string().max(MAX_PAGE_CHARS, "That page is too long."),
});

export const searchFormSchema = z.object({
  query: z
    .string()
    .trim()
    .min(2, "Type a question or a few words.")
    .max(MAX_QUERY_CHARS, "Use 500 characters or fewer."),
});

export type UploadFormState = FormState<"file" | "title">;
export type PasteFormState = FormState<"title" | "text">;
export type RenameFormState = FormState<"title">;
export type PageFormState = FormState<"text">;

/** The result of a search: the real passages found, or the honest "nothing in your material". */
export type SearchState =
  | { readonly status: "idle" }
  | { readonly status: "error"; readonly message: string; readonly query: string }
  | { readonly status: "results"; readonly query: string; readonly result: SearchResult };
