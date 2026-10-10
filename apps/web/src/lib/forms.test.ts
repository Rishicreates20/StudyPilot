import { describe, expect, it } from "vitest";
import { z } from "zod";

import { formString, zodFieldErrors } from "@/lib/forms";

describe("zodFieldErrors", () => {
  it("keeps the first message for each top-level field", () => {
    const schema = z.object({
      name: z
        .string()
        .min(3, "too short")
        .regex(/^[a-z]+$/, "letters only"),
      age: z.number({ error: "must be a number" }),
    });

    const result = schema.safeParse({ name: "A1", age: "x" });

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(zodFieldErrors(result.error)).toEqual({ name: "too short", age: "must be a number" });
    }
  });
});

describe("formString", () => {
  it("reads strings, and returns an empty string for missing fields and for files", () => {
    const data = new FormData();
    data.set("title", "Learn");
    data.set("upload", new File(["x"], "x.txt"));

    expect(formString(data, "title")).toBe("Learn");
    expect(formString(data, "missing")).toBe("");
    expect(formString(data, "upload")).toBe("");
  });
});
