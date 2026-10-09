import { getPublicEnv } from "@/lib/env";

export type NavItem = {
  readonly href: string;
  readonly label: string;
};

/** Primary navigation. Product areas (dashboard, goals, ...) are added as they are built. */
export const primaryNav: readonly NavItem[] = [
  { href: "/", label: "Home" },
  { href: "/status", label: "System status" },
  { href: "/design", label: "Design system" },
];

export const siteName = getPublicEnv().NEXT_PUBLIC_APP_NAME;

export const siteDescription =
  "An AI learning coach that turns your goal into a plan, teaches each topic, tests your understanding and adapts what you study next.";
