/** Choices offered when creating a goal. Values must match the API contract. */

export const GOAL_TYPE_OPTIONS = [
  { value: "professional_skill", label: "A professional skill" },
  { value: "interview", label: "Interview preparation" },
  { value: "certification", label: "A certification" },
  { value: "exam", label: "An exam" },
  { value: "academic_subject", label: "An academic subject" },
  { value: "general", label: "Something else" },
] as const;

export const GOAL_LEVEL_OPTIONS = [
  { value: "unknown", label: "I'm not sure" },
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
] as const;

export const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi (हिन्दी)" },
  { value: "or", label: "Odia (ଓଡ଼ିଆ)" },
] as const;

/** What a learner wants alongside the lessons themselves. */
export const LEARNING_PREFERENCE_OPTIONS = [
  { value: "examples", label: "Worked examples", hint: "See each idea applied step by step." },
  { value: "quizzes", label: "Practice quizzes", hint: "Check what you have learned." },
  {
    value: "revision",
    label: "Spaced revision",
    hint: "Come back to topics just before you would forget them.",
  },
] as const;

export const GOAL_STATUS_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "archived", label: "Archived" },
] as const;

export const MIN_DAILY_MINUTES = 10;
export const MAX_DAILY_MINUTES = 480;
export const DEFAULT_DAILY_MINUTES = 60;
export const DEFAULT_LANGUAGES: readonly string[] = ["en"];
export const DEFAULT_LEARNING_PREFERENCES: readonly string[] = ["examples", "quizzes", "revision"];

const labelOf = (options: readonly { value: string; label: string }[], value: string) =>
  options.find((option) => option.value === value)?.label ?? value;

export const goalTypeLabel = (value: string) => labelOf(GOAL_TYPE_OPTIONS, value);
export const goalLevelLabel = (value: string) => labelOf(GOAL_LEVEL_OPTIONS, value);
export const languageLabel = (value: string) => labelOf(LANGUAGE_OPTIONS, value);
export const learningPreferenceLabel = (value: string) =>
  labelOf(LEARNING_PREFERENCE_OPTIONS, value);
export const goalStatusLabel = (value: string) => labelOf(GOAL_STATUS_OPTIONS, value);
