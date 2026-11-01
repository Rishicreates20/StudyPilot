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
  "card-deleted": {
    variant: "success",
    title: "Card deleted",
    message: "Its history went with it.",
  },
  "card-failed": {
    variant: "warning",
    title: "We couldn't change that card",
    message: "Nothing was changed. Please try again.",
  },
  "review-failed": {
    variant: "warning",
    title: "That review wasn't saved",
    message: "The card is still due. Please try again.",
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
  "quiz-pending": {
    variant: "info",
    title: "This topic already has a quiz waiting",
    message: "Take it first: a topic keeps one untaken quiz at a time.",
  },
  "lesson-required": {
    variant: "info",
    title: "Study this topic first",
    message: "A quiz is written from the topic's lesson, so the lesson has to exist first.",
  },
  "quiz-limit": {
    variant: "warning",
    title: "Daily quiz limit reached",
    message: "You have used today's quiz writing. Please try again tomorrow.",
  },
  "quiz-cancelled": {
    variant: "info",
    title: "Quiz cancelled",
    message: "Nothing was saved. You can start again whenever you like.",
  },
  "marking-cancelled": {
    variant: "info",
    title: "Marking stopped",
    message:
      "Your short answers are still waiting. Ask for them to be marked again, or mark them yourself against the model answer.",
  },
  "answers-invalid": {
    variant: "warning",
    title: "We couldn't read those answers",
    message: "Nothing was submitted. Please check your answers and try again.",
  },
  "already-submitted": {
    variant: "info",
    title: "This quiz was already submitted",
    message: "A quiz can be taken once. Ask for a practice quiz to try again with new questions.",
  },
  reviewed: {
    variant: "success",
    title: "Your review is saved",
    message: "Your score and your topic progress now follow your own marking.",
  },
  "not-reviewable": {
    variant: "warning",
    title: "That answer can't be reviewed",
    message: "Only answers you wrote in your own words can be reviewed.",
  },
  "marking-exhausted": {
    variant: "warning",
    title: "Marking didn't work after several tries",
    message: "Compare your answer with the model answer and mark it yourself instead.",
  },
  "document-deleted": {
    variant: "info",
    title: "Document deleted",
    message: "Its file, its text and its indexed passages were removed.",
  },
  "document-cancelled": {
    variant: "info",
    title: "Processing stopped",
    message: "Nothing was indexed. You can process the document again whenever you like.",
  },
  "document-busy": {
    variant: "warning",
    title: "This document is being processed",
    message: "Wait for it to finish, or stop the job first.",
  },
  "nothing-to-confirm": {
    variant: "info",
    title: "There is no text waiting to be used",
    message: "Process the document again to read it from the start.",
  },
  "document-limit-today": {
    variant: "warning",
    title: "Daily document limit reached",
    message: "You have used today's document processing. Please try again tomorrow.",
  },
  "storage-unavailable": {
    variant: "warning",
    title: "File storage isn't available",
    message: "Nothing was changed. Please try again in a moment.",
  },
  "documents-ai-unavailable": {
    variant: "warning",
    title: "Reading documents isn't set up yet",
    message: "This server has no AI provider configured, so the document was not processed.",
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
  "export-requested": {
    variant: "success",
    title: "Your file is being made",
    message: "It usually takes a few seconds. It will appear below, ready to download.",
  },
  "export-ready": {
    variant: "info",
    title: "That file is already made",
    message: "It is shown below, ready to download.",
  },
  "export-busy": {
    variant: "info",
    title: "That file is still being made",
    message: "Wait for it to finish, then try again.",
  },
  "export-deleted": { variant: "info", title: "File deleted" },
  "export-limit-today": {
    variant: "warning",
    title: "Daily export limit reached",
    message: "You have made today's exports. Please try again tomorrow.",
  },
  "export-goal-archived": {
    variant: "warning",
    title: "Restore the goal first",
    message: "An archived goal is read-only, so its lessons and roadmaps can't be exported.",
  },
  "export-not-ready": {
    variant: "info",
    title: "That file isn't ready yet",
    message: "It will appear below as soon as it is made.",
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
