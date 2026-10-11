/**
 * Dates for display. Date-only values ("2027-01-31", a target date) are formatted in UTC so no
 * timezone can shift them to a neighbouring day; moments (when a goal was completed) are shown
 * in the learner's own timezone.
 */

const MS_PER_DAY = 86_400_000;

/** "2027-01-31" -> "31 Jan 2027". */
export function formatDate(isoDate: string): string {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(`${isoDate}T00:00:00Z`),
  );
}

/** A timestamp as a date in the given IANA timezone: "2026-10-10T20:00:00Z" -> "11 Oct 2026". */
export function formatMoment(isoTimestamp: string, timeZone: string): string {
  const date = new Date(isoTimestamp);
  try {
    return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone }).format(date);
  } catch {
    // A timezone name this runtime doesn't know: fall back to UTC rather than failing the page.
    return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" }).format(date);
  }
}

/**
 * Today's date ("2026-10-10") in the given IANA timezone. Call it only where a request is being
 * served (after the session has been read), never while a page is prerendered.
 */
export function todayIn(timeZone: string): string {
  try {
    // The Canadian English locale formats dates as YYYY-MM-DD.
    return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

/**
 * Whole days from `today` (a date-only string) to `isoDate`: positive in the future, negative
 * once the date has passed, 0 on the day itself.
 */
export function daysBetween(today: string, isoDate: string): number {
  return Math.round(
    (Date.parse(`${isoDate}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / MS_PER_DAY,
  );
}

/** "in 12 days", "tomorrow", "today", "3 days ago". */
export function describeDaysAway(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${-days} days ago`;
}
