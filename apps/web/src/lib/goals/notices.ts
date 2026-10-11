/**
 * Short confirmations shown after an action redirects back to a page (`?notice=paused`).
 *
 * The code comes from the URL, so it is only ever used as a key into this table: an unknown or
 * made-up code shows nothing, and no text from the URL is rendered.
 */
export type NoticeVariant = "success" | "info" | "warning";

export type Notice = {
  readonly variant: NoticeVariant;
  readonly title: string;
  readonly message?: string;
};

const NOTICES: Readonly<Record<string, Notice>> = {
  created: {
    variant: "success",
    title: "Goal created",
    message: "It is saved to your account and shown below.",
  },
  updated: { variant: "success", title: "Changes saved" },
  paused: {
    variant: "info",
    title: "Goal paused",
    message: "Resume it whenever you are ready.",
  },
  active: { variant: "success", title: "This goal is active again" },
  completed: { variant: "success", title: "Goal completed", message: "Well done." },
  archived: {
    variant: "info",
    title: "Goal archived",
    message: "It is out of your way but not lost. You can restore it from the archive.",
  },
  deleted: { variant: "info", title: "Goal deleted permanently" },
  onboarded: {
    variant: "success",
    title: "You're all set",
    message: "Your first goal is below. Change your study preferences any time in Settings.",
  },
  skipped: {
    variant: "info",
    title: "Onboarding skipped",
    message: "You can set your preferences in Settings and create a goal whenever you like.",
  },
  "status-conflict": {
    variant: "warning",
    title: "That change isn't possible right now",
    message: "The goal's status may have changed in another window. Check it and try again.",
  },
  "limit-reached": {
    variant: "warning",
    title: "You have too many goals open",
    message: "Archive or complete one before restoring another.",
  },
  "not-archived": {
    variant: "warning",
    title: "Archive the goal first",
    message: "Only archived goals can be deleted permanently.",
  },
  unavailable: {
    variant: "warning",
    title: "We couldn't do that just now",
    message: "The learning service is unavailable. Nothing was changed. Please try again.",
  },
};

export function noticeFor(code: string | undefined): Notice | null {
  if (code === undefined || !Object.hasOwn(NOTICES, code)) return null;
  return NOTICES[code] ?? null;
}
