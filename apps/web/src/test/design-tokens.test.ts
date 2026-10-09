// @vitest-environment node
/**
 * Guards the accessibility of the design tokens in src/app/globals.css.
 *
 * The CSS file is parsed directly, so editing a colour there re-runs these checks against the
 * real values. Thresholds follow WCAG 2.2: 4.5:1 for normal text (1.4.3) and 3:1 for the
 * boundaries of form controls and focus indicators (1.4.11).
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { contrastRatio, parseOklch } from "@/test/oklch";

const css = readFileSync(fileURLToPath(new URL("../app/globals.css", import.meta.url)), "utf8");

function tokensIn(selectorPattern: RegExp): Record<string, string> {
  const match = selectorPattern.exec(css);
  if (!match) throw new Error(`Block not found: ${selectorPattern}`);
  const tokens: Record<string, string> = {};
  for (const [, name, value] of match[1].matchAll(/--([a-z-]+):\s*(oklch\([^)]+\))\s*;/g)) {
    tokens[name] = value;
  }
  return tokens;
}

const themes = {
  light: tokensIn(/^:root\s*\{([^}]*)\}/m),
  dark: tokensIn(/^\.dark\s*\{([^}]*)\}/m),
} as const;

const ratio = (theme: keyof typeof themes, foreground: string, background: string) => {
  const tokens = themes[theme];
  const fg = tokens[foreground];
  const bg = tokens[background];
  if (!fg || !bg) throw new Error(`Missing token in ${theme}: ${foreground} or ${background}`);
  return contrastRatio(parseOklch(fg), parseOklch(bg));
};

// [foreground token, background token]
const textPairs: ReadonlyArray<readonly [string, string]> = [
  ["foreground", "background"],
  ["foreground", "card"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["primary-foreground", "primary"],
  ["secondary-foreground", "secondary"],
  ["accent-foreground", "accent"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["muted-foreground", "muted"],
  ["primary", "background"], // links and accent text
  ["primary", "card"],
  ["destructive-foreground", "background"], // inline field errors
  ["destructive-foreground", "destructive-soft"],
  ["success-foreground", "success-soft"],
  ["warning-foreground", "warning-soft"],
  ["info-foreground", "info-soft"],
];

const nonTextPairs: ReadonlyArray<readonly [string, string]> = [
  ["input", "background"], // form-control outline
  ["input", "card"],
  ["ring", "background"], // keyboard focus indicator
  ["ring", "card"],
];

describe.each(Object.keys(themes) as (keyof typeof themes)[])("%s theme", (theme) => {
  it("defines every token it is checked against", () => {
    for (const [fg, bg] of [...textPairs, ...nonTextPairs]) {
      expect(themes[theme][fg], `${fg} missing`).toBeDefined();
      expect(themes[theme][bg], `${bg} missing`).toBeDefined();
    }
  });

  it.each(textPairs)("text %s on %s has at least 4.5:1 contrast", (fg, bg) => {
    expect(ratio(theme, fg, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(nonTextPairs)("UI boundary %s against %s has at least 3:1 contrast", (fg, bg) => {
    expect(ratio(theme, fg, bg)).toBeGreaterThanOrEqual(3);
  });
});

describe("token parity", () => {
  it("defines the same token names in light and dark themes", () => {
    expect(Object.keys(themes.dark).sort()).toEqual(Object.keys(themes.light).sort());
  });
});

describe("colour maths", () => {
  it("computes the known extremes", () => {
    const white = parseOklch("oklch(1 0 0)");
    const black = parseOklch("oklch(0 0 0)");

    expect(contrastRatio(white, black)).toBeCloseTo(21, 0);
    expect(contrastRatio(white, white)).toBeCloseTo(1, 5);
  });
});
