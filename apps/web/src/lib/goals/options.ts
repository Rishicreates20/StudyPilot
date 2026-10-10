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

export const MIN_DAILY_MINUTES = 10;
export const MAX_DAILY_MINUTES = 480;
export const DEFAULT_DAILY_MINUTES = 60;

const labelOf = (options: readonly { value: string; label: string }[], value: string) =>
  options.find((option) => option.value === value)?.label ?? value;

export const goalTypeLabel = (value: string) => labelOf(GOAL_TYPE_OPTIONS, value);
export const goalLevelLabel = (value: string) => labelOf(GOAL_LEVEL_OPTIONS, value);
export const languageLabel = (value: string) => labelOf(LANGUAGE_OPTIONS, value);
