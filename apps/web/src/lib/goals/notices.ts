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
  "already-generating": {
    variant: "info",
    title: "A roadmap is already being made for this goal",
    message: "Its progress is shown below.",
  },
  "generation-cancelled": {
    variant: "info",
    title: "Generation cancelled",
    message: "Nothing was saved. You can start again whenever you like.",
  },
  "version-switched": {
    variant: "success",
    title: "Version switched",
    message: "This is now your current roadmap. Nothing was deleted: every version is kept.",
  },
  "needs-detail": {
    variant: "warning",
    title: "This goal needs a little more before it can be planned",
    message:
      "Give it a more descriptive title, or allow more study time before the target date, then try again.",
  },
  "ai-unavailable": {
    variant: "warning",
    title: "Roadmap generation isn't set up yet",
    message: "This server has no AI provider configured, so nothing was started.",
  },
  "generation-limit": {
    variant: "warning",
    title: "Daily roadmap limit reached",
    message: "You have used today's roadmap generations. Please try again tomorrow.",
  },
  "goal-archived": {
    variant: "warning",
    title: "Restore the goal first",
    message: "An archived goal is read-only, so its roadmap can't be changed.",
  },
  "lesson-exists": {
    variant: "info",
    title: "This topic already has a lesson",
    message: "It is shown below. You can ask for a new version of it at any time.",
  },
  "lesson-cancelled": {
    variant: "info",
    title: "Lesson cancelled",
    message: "Nothing was saved. You can start again whenever you like.",
  },
  "lesson-queue-full": {
    variant: "warning",
    title: "Other lessons are still being written",
    message: "Wait for one to finish, then try again.",
  },
  "lesson-limit": {
    variant: "warning",
    title: "Daily lesson limit reached",
    message: "You have used today's lesson writing. Please try again tomorrow.",
  },
  "roadmap-not-current": {
    variant: "warning",
    title: "This topic belongs to an earlier roadmap version",
    message:
      "Make that version current from the roadmap page to write new lessons for it. Lessons that were already written can still be read.",
  },
  "not-lessonable": {
    variant: "info",
    title: "Revision sessions don't have lessons",
    message: "They are a time to recall what you have studied.",
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
