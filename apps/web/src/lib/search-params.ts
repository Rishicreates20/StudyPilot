/** The shape of `searchParams` in Next.js pages (a promise in v16). */
export type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** The first value of a query parameter, or undefined. */
export function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
