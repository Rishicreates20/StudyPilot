export const ONBOARDING_PATH = "/onboarding";
export const ONBOARDING_STEP_COUNT = 3;

export type OnboardingStep = 1 | 2 | 3;

/** The step named by `?step=`. Anything missing or unrecognised starts from the beginning. */
export function parseOnboardingStep(value: string | undefined): OnboardingStep {
  return value === "2" ? 2 : value === "3" ? 3 : 1;
}

export const onboardingStepPath = (step: OnboardingStep) => `${ONBOARDING_PATH}?step=${step}`;
