/**
 * The little inline formatting a lesson's text may contain: `code` and **bold**.
 *
 * Lesson text is plain text written by a model, so nothing in it is ever treated as HTML or as a
 * link: it is split into parts here and each part is rendered as an ordinary React node. Anything
 * that does not match exactly (an unclosed backtick, a lone asterisk) stays as plain text.
 */
export type InlinePart = { readonly kind: "text" | "code" | "strong"; readonly text: string };

const MARKUP = /(`[^`\n]+`|\*\*[^*\n]+\*\*)/;

export function parseInline(input: string): InlinePart[] {
  const parts: InlinePart[] = [];
  for (const piece of input.split(MARKUP)) {
    if (piece === "") continue;
    if (piece.length > 2 && piece.startsWith("`") && piece.endsWith("`")) {
      parts.push({ kind: "code", text: piece.slice(1, -1) });
    } else if (piece.length > 4 && piece.startsWith("**") && piece.endsWith("**")) {
      parts.push({ kind: "strong", text: piece.slice(2, -2) });
    } else {
      parts.push({ kind: "text", text: piece });
    }
  }
  return parts;
}
